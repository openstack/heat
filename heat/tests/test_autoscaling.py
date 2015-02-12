#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import copy
import datetime

import mox
from oslo.config import cfg
from oslo.utils import timeutils

from heat.common import exception
from heat.common import grouputils
from heat.common import template_format
from heat.engine.notification import autoscaling as notification
from heat.engine import resource
from heat.engine.resources.aws import autoscaling_group as asg
from heat.engine.resources.aws import instance
from heat.engine.resources import loadbalancer
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


as_template = inline_templates.as_template


class AutoScalingTest(common.HeatTestCase):
    dummy_instance_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    params = {'KeyName': 'test', 'ImageId': 'foo'}
    params_HoT = {'flavor': 'test', 'image': 'foo'}

    def setUp(self):
        super(AutoScalingTest, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)
        self.defn = rsrc_defn.ResourceDefinition(
            'asg', 'AWS::AutoScaling::AutoScalingGroup',
            {'AvailabilityZones': ['nova'],
             'LaunchConfigurationName': 'config',
             'MaxSize': 5,
             'MinSize': 1,
             'DesiredCapacity': 2})
        self.asg = asg.AutoScalingGroup('asg', self.defn, stack)

    def create_scaling_group(self, t, stack, resource_name):
        # create the launch configuration resource
        conf = stack['LaunchConfig']
        self.assertIsNone(conf.validate())
        scheduler.TaskRunner(conf.create)()
        self.assertEqual((conf.CREATE, conf.COMPLETE), conf.state)
        # check bdm in configuration
        self.assertIsNotNone(conf.properties['BlockDeviceMappings'])

        # create the group resource
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        # check bdm in instance_definition
        instance_definition = rsrc._get_instance_definition()
        self.assertIn('BlockDeviceMappings',
                      instance_definition['Properties'])

        return rsrc

    def create_scaling_policy(self, t, stack, resource_name):
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def _stub_create(self, num, with_error=None, with_lcn=True):
        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        # create with launch config name, need to stub snapshot constraint
        if with_lcn:
            self.stub_SnapshotConstraint_validate()
        if with_error:
            instance.Instance.handle_create().AndRaise(
                exception.Error(with_error))
            return
        cookie = object()
        for x in range(num):
            instance.Instance.handle_create().AndReturn(cookie)
        instance.Instance.check_create_complete(cookie).AndReturn(False)
        instance.Instance.check_create_complete(
            cookie).MultipleTimes().AndReturn(True)

    def _stub_delete(self, num):
        self.m.StubOutWithMock(instance.Instance, 'handle_delete')
        self.m.StubOutWithMock(instance.Instance, 'check_delete_complete')
        task = object()
        for x in range(num):
            instance.Instance.handle_delete().AndReturn(task)
        instance.Instance.check_delete_complete(task).AndReturn(False)
        instance.Instance.check_delete_complete(
            task).MultipleTimes().AndReturn(True)

    def _stub_lb_reload(self, num, unset=True, nochange=False):
        expected_list = [self.dummy_instance_id] * num
        if unset:
            self.m.VerifyAll()
            self.m.UnsetStubs()
        if num > 0:
            self.m.StubOutWithMock(instance.Instance, 'FnGetRefId')
            instance.Instance.FnGetRefId().MultipleTimes().AndReturn(
                self.dummy_instance_id)

        if not nochange:
            self.m.StubOutWithMock(loadbalancer.LoadBalancer, 'handle_update')
            loadbalancer.LoadBalancer.handle_update(
                mox.IgnoreArg(), mox.IgnoreArg(),
                {'Instances': expected_list}).AndReturn(None)

    def _stub_scale_notification(self,
                                 adjust,
                                 groupname,
                                 start_capacity,
                                 adjust_type='ChangeInCapacity',
                                 end_capacity=None,
                                 with_error=None):

        self.m.StubOutWithMock(notification, 'send')
        notification.send(stack=mox.IgnoreArg(),
                          adjustment=adjust,
                          adjustment_type=adjust_type,
                          capacity=start_capacity,
                          groupname=mox.IgnoreArg(),
                          suffix='start',
                          message="Start resizing the group %s"
                          % groupname,
                          ).AndReturn(False)
        if with_error:
            notification.send(stack=mox.IgnoreArg(),
                              adjustment=adjust,
                              capacity=start_capacity,
                              adjustment_type=adjust_type,
                              groupname=mox.IgnoreArg(),
                              message='Nested stack update failed:'
                                      ' Error: %s' % with_error,
                              suffix='error',
                              ).AndReturn(False)
        else:
            notification.send(stack=mox.IgnoreArg(),
                              adjustment=adjust,
                              adjustment_type=adjust_type,
                              capacity=end_capacity,
                              groupname=mox.IgnoreArg(),
                              message="End resizing the group %s"
                              % groupname,
                              suffix='end',
                              ).AndReturn(False)

    def _stub_meta_expected(self, now, data, nmeta=1):
        # Stop time at now
        timeutils.set_time_override(now)
        self.addCleanup(timeutils.clear_time_override)

        # Then set a stub to ensure the metadata update is as
        # expected based on the timestamp and data
        self.m.StubOutWithMock(resource.Resource, 'metadata_set')
        expected = {timeutils.strtime(now): data}
        # Note for ScalingPolicy, we expect to get a metadata
        # update for the policy and autoscaling group, so pass nmeta=2
        for x in range(nmeta):
            resource.Resource.metadata_set(expected).AndReturn(None)

    def test_scaling_up_meta_update(self):
        t = template_format.parse(as_template)

        # Add CustomLB (just AWS::EC2::Instance) to template
        t['Resources']['MyCustomLB'] = {
            'Type': 'AWS::EC2::Instance',
            'ImageId': {'Ref': 'ImageId'},
            'InstanceType': 'bar',
            'Metadata': {
                'IPs': {'Fn::GetAtt': ['WebServerGroup', 'InstanceList']}
            }
        }
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group
        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)

        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(1, len(grouputils.get_member_names(rsrc)))

        # Scale up one
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')

        alarm_url = up_policy.FnGetAtt('AlarmUrl')
        self.assertIsNotNone(alarm_url)
        up_policy.signal()
        self.assertEqual(2, len(grouputils.get_member_names(rsrc)))

        # Check CustomLB metadata was updated
        self.m.StubOutWithMock(instance.Instance, '_ipaddress')
        instance.Instance._ipaddress().MultipleTimes().AndReturn(
            '127.0.0.1')
        self.m.ReplayAll()

        expected_meta = {'IPs': u'127.0.0.1,127.0.0.1'}
        self.assertEqual(expected_meta, stack['MyCustomLB'].metadata_get())

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_policy_update(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group
        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)

        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(1, len(grouputils.get_member_names(rsrc)))

        # Create initial scaling policy
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')

        # Scale up one
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()

        # Trigger alarm
        up_policy.signal()
        self.assertEqual(2, len(grouputils.get_member_names(rsrc)))

        # Update scaling policy
        props = copy.copy(up_policy.properties.data)
        props['ScalingAdjustment'] = '2'
        update_snippet = rsrc_defn.ResourceDefinition(up_policy.name,
                                                      up_policy.type(),
                                                      props)
        scheduler.TaskRunner(up_policy.update, update_snippet)()
        self.assertEqual(2, up_policy.properties['ScalingAdjustment'])

        # Now move time on 61 seconds - Cooldown in template is 60
        # so this should trigger a scale-up
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(resource.Resource, 'metadata_get')
        up_policy.metadata_get().AndReturn(previous_meta)
        rsrc.metadata_get().AndReturn(previous_meta)

        # stub for the metadata accesses while creating the two instances
        resource.Resource.metadata_get()
        resource.Resource.metadata_get()

        now = now + datetime.timedelta(seconds=61)

        self._stub_lb_reload(4, unset=False)
        self._stub_meta_expected(now, 'ChangeInCapacity : 2', 2)
        self._stub_create(2)
        self.m.ReplayAll()

        # Trigger alarm
        up_policy.signal()
        self.assertEqual(4, len(grouputils.get_member_names(rsrc)))

        rsrc.delete()
        self.m.VerifyAll()
