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

import mock
import mox
from oslo.config import cfg
from oslo.utils import timeutils
import six

from heat.common import exception
from heat.common import short_id
from heat.common import template_format
from heat.engine.notification import autoscaling as notification
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources import autoscaling as asc
from heat.engine.resources import instance
from heat.engine.resources import loadbalancer
from heat.engine.resources.neutron import loadbalancer as neutron_lb
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils


as_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "AutoScaling Test",
  "Parameters" : {
  "ImageId": {"Type": "String"},
  "KeyName": {"Type": "String"}
  },
  "Resources" : {
    "WebServerGroup" : {
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "LaunchConfigurationName" : { "Ref" : "LaunchConfig" },
        "MinSize" : "1",
        "MaxSize" : "5",
        "LoadBalancerNames" : [ { "Ref" : "ElasticLoadBalancer" } ]
      }
    },
    "WebServerScaleUpPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : { "Ref" : "WebServerGroup" },
        "Cooldown" : "60",
        "ScalingAdjustment" : "1"
      }
    },
    "WebServerScaleDownPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : { "Ref" : "WebServerGroup" },
        "Cooldown" : "60",
        "ScalingAdjustment" : "-1"
      }
    },
    "ElasticLoadBalancer" : {
        "Type" : "AWS::ElasticLoadBalancing::LoadBalancer",
        "Properties" : {
            "AvailabilityZones" : ["nova"],
            "Listeners" : [ {
                "LoadBalancerPort" : "80",
                "InstancePort" : "80",
                "Protocol" : "HTTP"
            }]
        }
    },
    "LaunchConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId" : {"Ref": "ImageId"},
        "InstanceType"   : "bar",
        "BlockDeviceMappings": [
            {
                "DeviceName": "vdb",
                "Ebs": {"SnapshotId": "9ef5496e-7426-446a-bbc8-01f84d9c9972",
                        "DeleteOnTermination": "True"}
            }]
      }
    }
  }
}
'''

as_template_bad_group = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Parameters" : {
  "ImageId": {"Type": "String"},
  "KeyName": {"Type": "String"}
  },
  "Resources" : {
    "WebServerScaleUpPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : "not a real group",
        "Cooldown" : "60",
        "ScalingAdjustment" : "1"
      }
    }
  }
}
'''


class AutoScalingTest(HeatTestCase):
    dummy_instance_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    params = {'KeyName': 'test', 'ImageId': 'foo'}

    def setUp(self):
        super(AutoScalingTest, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()

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

    def _stub_create(self, num, with_error=None):
        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        self.stub_ImageConstraint_validate()
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

    def _stub_suspend(self, cookies=None, with_error=None):
        cookies = cookies or []
        self.m.StubOutWithMock(instance.Instance, 'handle_suspend')
        self.m.StubOutWithMock(instance.Instance, 'check_suspend_complete')
        if with_error:
            instance.Instance.handle_suspend().AndRaise(
                exception.Error(with_error))
            return
        inst_cookies = cookies or [(object(), object(), object())]
        for cookie in inst_cookies:
            instance.Instance.handle_suspend().InAnyOrder().AndReturn(cookie)
            instance.Instance.check_suspend_complete(
                cookie).InAnyOrder().AndReturn(False)
            instance.Instance.check_suspend_complete(
                cookie).InAnyOrder().AndReturn(True)

    def _stub_resume(self, cookies=None, with_error=None):
        cookies = cookies or []
        self.m.StubOutWithMock(instance.Instance, 'handle_resume')
        self.m.StubOutWithMock(instance.Instance, 'check_resume_complete')
        if with_error:
            instance.Instance.handle_resume().AndRaise(
                exception.Error(with_error))
            return
        inst_cookies = cookies or [(object(), object(), object())]
        for cookie in inst_cookies:
            instance.Instance.handle_resume().InAnyOrder().AndReturn(cookie)
            instance.Instance.check_resume_complete(
                cookie).InAnyOrder().AndReturn(False)
            instance.Instance.check_resume_complete(
                cookie).InAnyOrder().AndReturn(True)

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
        self.m.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().MultipleTimes().AndReturn(now)

        # Then set a stub to ensure the metadata update is as
        # expected based on the timestamp and data
        self.m.StubOutWithMock(resource.Resource, 'metadata_set')
        expected = {timeutils.strtime(now): data}
        # Note for ScalingPolicy, we expect to get a metadata
        # update for the policy and autoscaling group, so pass nmeta=2
        for x in range(nmeta):
            resource.Resource.metadata_set(expected).AndReturn(None)

    def test_scaling_delete_empty(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '0'
        properties['MaxSize'] = '0'
        properties['DesiredCapacity'] = '0'
        stack = utils.parse_stack(t, params=self.params)
        self._stub_lb_reload(0)
        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertIsNone(rsrc.FnGetAtt("InstanceList"))

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_adjust_down_empty(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '1'
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()

        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        instance_names = rsrc.get_instance_names()
        self.assertEqual(1, len(instance_names))

        # Reduce the min size to 0, should complete without adjusting
        props = copy.copy(rsrc.properties.data)
        props['MinSize'] = '0'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(instance_names, rsrc.get_instance_names())

        # trigger adjustment to reduce to 0, there should be no more instances
        self._stub_lb_reload(0)
        self._stub_scale_notification(adjust=-1, groupname=rsrc.FnGetRefId(),
                                      start_capacity=1, end_capacity=0)
        self._stub_meta_expected(now, 'ChangeInCapacity : -1')
        self._stub_delete(1)
        self.m.ReplayAll()
        rsrc.adjust(-1)
        self.assertEqual([], rsrc.get_instance_names())

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_replace(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual(1, len(rsrc.get_instance_names()))
        props = copy.copy(rsrc.properties.data)
        props['AvailabilityZones'] = ['foo']
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        updater = scheduler.TaskRunner(rsrc.update, update_snippet)
        self.assertRaises(resource.UpdateReplace, updater)

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_suspend(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual(1, len(rsrc.get_instance_names()))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self._stub_suspend()
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_resume(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual(1, len(rsrc.get_instance_names()))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self._stub_resume()
        self.m.ReplayAll()

        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        for i in rsrc.nested().values():
            i.state_set(rsrc.SUSPEND, rsrc.COMPLETE)

        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_suspend_multiple(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual(2, len(rsrc.get_instance_names()))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self._stub_suspend(cookies=[('foo1', 'foo2', 'foo3'),
                                    ('bar1', 'bar2', 'bar3')])
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_resume_multiple(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual(2, len(rsrc.get_instance_names()))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self._stub_resume(cookies=[('foo1', 'foo2', 'foo3'),
                                   ('bar1', 'bar2', 'bar3')])
        self.m.ReplayAll()

        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        for i in rsrc.nested().values():
            i.state_set(rsrc.SUSPEND, rsrc.COMPLETE)

        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_suspend_fail(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual(1, len(rsrc.get_instance_names()))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self._stub_suspend(with_error='oops')
        self.m.ReplayAll()

        sus_task = scheduler.TaskRunner(rsrc.suspend)
        self.assertRaises(exception.ResourceFailure, sus_task, ())
        self.assertEqual((rsrc.SUSPEND, rsrc.FAILED), rsrc.state)
        self.assertEqual('Error: Resource SUSPEND failed: Error: oops',
                         rsrc.status_reason)

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_resume_fail(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual(1, len(rsrc.get_instance_names()))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self._stub_resume(with_error='oops')
        self.m.ReplayAll()

        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        for i in rsrc.nested().values():
            i.state_set(rsrc.SUSPEND, rsrc.COMPLETE)

        sus_task = scheduler.TaskRunner(rsrc.resume)
        self.assertRaises(exception.ResourceFailure, sus_task, ())
        self.assertEqual((rsrc.RESUME, rsrc.FAILED), rsrc.state)
        self.assertEqual('Error: Resource RESUME failed: Error: oops',
                         rsrc.status_reason)

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_create_error(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        instance.Instance.handle_create().AndRaise(Exception)
        self.stub_ImageConstraint_validate()

        self.m.ReplayAll()

        conf = stack['LaunchConfig']
        self.assertIsNone(conf.validate())
        scheduler.TaskRunner(conf.create)()
        self.assertEqual((conf.CREATE, conf.COMPLETE), conf.state)

        rsrc = stack['WebServerGroup']
        self.assertIsNone(rsrc.validate())
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.assertEqual([], rsrc.get_instance_names())

        self.m.VerifyAll()

    def test_scaling_group_update_ok_maxsize(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(1, len(rsrc.get_instance_names()))
        instance_names = rsrc.get_instance_names()

        # Reduce the max size to 2, should complete without adjusting
        props = copy.copy(rsrc.properties.data)
        props['MaxSize'] = '2'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(instance_names, rsrc.get_instance_names())
        self.assertEqual(2, rsrc.properties['MaxSize'])

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_minsize(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Increase min size to 2, should trigger an ExactCapacity adjust
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()

        props = copy.copy(rsrc.properties.data)
        props['MinSize'] = '2'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(2, len(rsrc.get_instance_names()))
        self.assertEqual(2, rsrc.properties['MinSize'])

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_desired(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Increase min size to 2 via DesiredCapacity, should adjust
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(1)
        self.m.ReplayAll()

        props = copy.copy(rsrc.properties.data)
        props['DesiredCapacity'] = '2'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(2, len(rsrc.get_instance_names()))
        self.assertEqual(2, rsrc.properties['DesiredCapacity'])

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_desired_zero(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Increase min size to 2 via DesiredCapacity, should adjust
        self._stub_lb_reload(0)
        self._stub_meta_expected(now, 'ExactCapacity : 0')
        self._stub_delete(1)
        self.m.ReplayAll()

        props = copy.copy(rsrc.properties.data)
        props['MinSize'] = '0'
        props['DesiredCapacity'] = '0'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(0, len(rsrc.get_instance_names()))
        self.assertEqual(0, rsrc.properties['DesiredCapacity'])

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_desired_remove(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(2, len(rsrc.get_instance_names()))
        instance_names = rsrc.get_instance_names()

        # Remove DesiredCapacity from the updated template, which should
        # have no effect, it's an optional parameter
        props = copy.copy(rsrc.properties.data)
        del props['DesiredCapacity']
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(instance_names, rsrc.get_instance_names())
        self.assertIsNone(rsrc.properties['DesiredCapacity'])

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_cooldown(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['Cooldown'] = '60'
        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')

        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual(1, len(rsrc.get_instance_names()))

        props = copy.copy(rsrc.properties.data)
        props['Cooldown'] = '61'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(61, rsrc.properties['Cooldown'])

        rsrc.delete()
        self.m.VerifyAll()

    def test_lb_reload_static_resolve(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['ElasticLoadBalancer']['Properties']
        properties['AvailabilityZones'] = {'Fn::GetAZs': ''}

        self.m.StubOutWithMock(parser.Stack, 'get_availability_zones')
        parser.Stack.get_availability_zones().MultipleTimes().AndReturn(
            ['abc', 'xyz'])

        # Check that the Fn::GetAZs is correctly resolved
        expected = {u'Type': u'AWS::ElasticLoadBalancing::LoadBalancer',
                    u'Properties': {'Instances': ['aaaabbbbcccc'],
                                    u'Listeners': [{u'InstancePort': u'80',
                                                    u'LoadBalancerPort': u'80',
                                                    u'Protocol': u'HTTP'}],
                                    u'AvailabilityZones': ['abc', 'xyz']}}

        self.m.StubOutWithMock(short_id, 'generate_id')
        short_id.generate_id().AndReturn('aaaabbbbcccc')

        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        stack = utils.parse_stack(t, params=self.params)

        lb = stack['ElasticLoadBalancer']
        self.m.StubOutWithMock(lb, 'handle_update')
        lb.handle_update(expected,
                         mox.IgnoreArg(),
                         mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()

        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual(1, len(rsrc.get_instance_names()))
        props = copy.copy(rsrc.properties.data)
        props['Cooldown'] = '61'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()

        rsrc.delete()
        self.m.VerifyAll()

    def test_lb_reload_members(self):
        t = template_format.parse(as_template)
        t['Resources']['ElasticLoadBalancer'] = {
            'Type': 'OS::Neutron::LoadBalancer',
            'Properties': {
                'protocol_port': 8080,
                'pool_id': 'pool123'
            }
        }

        expected = {
            'Type': 'OS::Neutron::LoadBalancer',
            'Properties': {
                'protocol_port': 8080,
                'pool_id': 'pool123',
                'members': [u'aaaabbbbcccc']}
        }

        self.m.StubOutWithMock(short_id, 'generate_id')
        short_id.generate_id().AndReturn('aaaabbbbcccc')

        self.m.StubOutWithMock(neutron_lb.LoadBalancer, 'handle_update')
        neutron_lb.LoadBalancer.handle_update(expected,
                                              mox.IgnoreArg(),
                                              mox.IgnoreArg()).AndReturn(None)

        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        stack = utils.parse_stack(t, params=self.params)
        self.create_scaling_group(t, stack, 'WebServerGroup')

        self.m.VerifyAll()

    def test_lb_reload_invalid_resource(self):
        t = template_format.parse(as_template)
        t['Resources']['ElasticLoadBalancer'] = {
            'Type': 'AWS::EC2::Volume',
            'Properties': {
                'AvailabilityZone': 'nova'
            }
        }

        self._stub_create(1)
        self.m.ReplayAll()
        stack = utils.parse_stack(t, params=self.params)
        error = self.assertRaises(
            exception.ResourceFailure,
            self.create_scaling_group, t, stack, 'WebServerGroup')
        self.assertEqual(
            "Error: Unsupported resource 'ElasticLoadBalancer' in "
            "LoadBalancerNames",
            six.text_type(error))

        self.m.VerifyAll()

    def test_scaling_group_adjust(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        # start with 3
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '3'
        self._stub_lb_reload(3)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 3')
        self._stub_create(3)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(3, len(rsrc.get_instance_names()))

        # reduce to 1
        self._stub_lb_reload(1)
        self._stub_delete(2)
        self.stub_ImageConstraint_validate(num=1)
        self._stub_meta_expected(now, 'ChangeInCapacity : -2')
        self._stub_scale_notification(adjust=-2, groupname=rsrc.FnGetRefId(),
                                      start_capacity=3, end_capacity=1)
        self.m.ReplayAll()
        rsrc.adjust(-2)
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # raise to 3
        self._stub_lb_reload(3)
        self._stub_meta_expected(now, 'ChangeInCapacity : 2')
        self._stub_create(2)
        self._stub_scale_notification(adjust=2, groupname=rsrc.FnGetRefId(),
                                      start_capacity=1, end_capacity=3)
        self.m.ReplayAll()
        rsrc.adjust(2)
        self.assertEqual(3, len(rsrc.get_instance_names()))

        # set to 2
        self._stub_lb_reload(2)
        self._stub_delete(1)
        self.stub_ImageConstraint_validate(num=2)
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_scale_notification(adjust=2, groupname=rsrc.FnGetRefId(),
                                      adjust_type='ExactCapacity',
                                      start_capacity=3, end_capacity=2)
        self.m.ReplayAll()
        rsrc.adjust(2, 'ExactCapacity')
        self.assertEqual(2, len(rsrc.get_instance_names()))
        self.m.VerifyAll()

    def test_scaling_group_scale_up_failure(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group
        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual(1, len(rsrc.get_instance_names()))
        self.m.VerifyAll()
        self.m.UnsetStubs()

        # Scale up one 1 instance with resource failure
        self._stub_create(1, with_error='Bang')
        self._stub_lb_reload(1, unset=False, nochange=True)
        self._stub_scale_notification(adjust=1,
                                      groupname=rsrc.FnGetRefId(),
                                      start_capacity=1,
                                      with_error='Bang')
        self.m.ReplayAll()

        self.assertRaises(exception.Error, rsrc.adjust, 1)
        self.assertEqual(1, len(rsrc.get_instance_names()))

        self.m.VerifyAll()

    def test_scaling_group_truncate_adjustment(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group, 2 instances
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        self._stub_lb_reload(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # raise above the max
        self._stub_lb_reload(5)
        self._stub_meta_expected(now, 'ChangeInCapacity : 4')
        self._stub_create(3)
        self.m.ReplayAll()
        rsrc.adjust(4)
        self.assertEqual(5, len(rsrc.get_instance_names()))

        # lower below the min
        self._stub_lb_reload(1)
        self._stub_delete(4)
        self.stub_ImageConstraint_validate(num=1)
        self._stub_meta_expected(now, 'ChangeInCapacity : -5')
        self.m.ReplayAll()
        rsrc.adjust(-5)
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # no change
        rsrc.adjust(0)
        self.assertEqual(1, len(rsrc.get_instance_names()))

        rsrc.delete()
        self.m.VerifyAll()

    def _do_test_scaling_group_percent(self, decrease, lowest,
                                       increase, create, highest):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group, 2 instances
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        self._stub_lb_reload(2)
        self._stub_create(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # reduce by decrease %
        self._stub_lb_reload(lowest)
        adjust = 'PercentChangeInCapacity : %d' % decrease
        self._stub_meta_expected(now, adjust)
        self._stub_delete(2 - lowest)
        self.stub_ImageConstraint_validate(num=1)
        self.m.ReplayAll()
        rsrc.adjust(decrease, 'PercentChangeInCapacity')
        self.assertEqual(lowest, len(rsrc.get_instance_names()))

        # raise by increase %
        self._stub_lb_reload(highest)
        adjust = 'PercentChangeInCapacity : %d' % increase
        self._stub_meta_expected(now, adjust)
        self._stub_create(create)
        self.m.ReplayAll()
        rsrc.adjust(increase, 'PercentChangeInCapacity')
        self.assertEqual(highest, len(rsrc.get_instance_names()))

        rsrc.delete()

    def test_scaling_group_percent(self):
        self._do_test_scaling_group_percent(-50, 1, 200, 2, 3)

    def test_scaling_group_percent_round_up(self):
        self._do_test_scaling_group_percent(-33, 1, 33, 1, 2)

    def test_scaling_group_percent_round_down(self):
        self._do_test_scaling_group_percent(-66, 1, 225, 2, 3)

    def test_scaling_group_cooldown_toosoon(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group, 2 instances, Cooldown 60s
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        properties['Cooldown'] = '60'
        self._stub_lb_reload(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # reduce by 50%
        self._stub_lb_reload(1)
        self._stub_delete(1)
        self.stub_ImageConstraint_validate(num=1)
        self._stub_meta_expected(now, 'PercentChangeInCapacity : -50')
        self.m.ReplayAll()
        rsrc.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Now move time on 10 seconds - Cooldown in template is 60
        # so this should not update the policy metadata, and the
        # scaling group instances should be unchanged
        # Note we have to stub Resource.metadata_get since up_policy isn't
        # stored in the DB (because the stack hasn't really been created)
        previous_meta = {timeutils.strtime(now):
                         'PercentChangeInCapacity : -50'}

        self.m.VerifyAll()
        self.m.UnsetStubs()

        now = now + datetime.timedelta(seconds=10)
        self.m.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().MultipleTimes().AndReturn(now)

        self.m.StubOutWithMock(resource.Resource, 'metadata_get')
        rsrc.metadata_get().AndReturn(previous_meta)

        self.m.ReplayAll()

        # raise by 200%, too soon for Cooldown so there should be no change
        rsrc.adjust(200, 'PercentChangeInCapacity')
        self.assertEqual(1, len(rsrc.get_instance_names()))

        rsrc.delete()

    def test_scaling_group_cooldown_ok(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group, 2 instances, Cooldown 60s
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        properties['Cooldown'] = '60'
        self._stub_lb_reload(2)
        self._stub_create(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # reduce by 50%
        self._stub_lb_reload(1)
        self._stub_delete(1)
        self.stub_ImageConstraint_validate(num=1)
        self._stub_meta_expected(now, 'PercentChangeInCapacity : -50')
        self.m.ReplayAll()
        rsrc.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Now move time on 61 seconds - Cooldown in template is 60
        # so this should update the policy metadata, and the
        # scaling group instances updated
        previous_meta = {timeutils.strtime(now):
                         'PercentChangeInCapacity : -50'}

        self.m.VerifyAll()
        self.m.UnsetStubs()

        now = now + datetime.timedelta(seconds=61)

        self.m.StubOutWithMock(resource.Resource, 'metadata_get')
        rsrc.metadata_get().AndReturn(previous_meta)

        #stub for the metadata accesses while creating the two instances
        resource.Resource.metadata_get()
        resource.Resource.metadata_get()

        # raise by 200%, should work
        self._stub_lb_reload(3, unset=False)
        self._stub_create(2)
        self._stub_meta_expected(now, 'PercentChangeInCapacity : 200')
        self.m.ReplayAll()
        rsrc.adjust(200, 'PercentChangeInCapacity')
        self.assertEqual(3, len(rsrc.get_instance_names()))

        rsrc.delete()

    def test_scaling_group_cooldown_zero(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group, 2 instances, Cooldown 0
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        properties['Cooldown'] = '0'
        self._stub_lb_reload(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # reduce by 50%
        self._stub_lb_reload(1)
        self._stub_meta_expected(now, 'PercentChangeInCapacity : -50')
        self._stub_delete(1)
        self.stub_ImageConstraint_validate(num=1)
        self.m.ReplayAll()
        rsrc.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Don't move time, since cooldown is zero, it should work
        previous_meta = {timeutils.strtime(now):
                         'PercentChangeInCapacity : -50'}

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(resource.Resource, 'metadata_get')
        rsrc.metadata_get().AndReturn(previous_meta)

        #stub for the metadata accesses while creating the two instances
        resource.Resource.metadata_get()
        resource.Resource.metadata_get()
        # raise by 200%, should work

        self._stub_lb_reload(3, unset=False)
        self._stub_meta_expected(now, 'PercentChangeInCapacity : 200')
        self._stub_create(2)
        self.m.ReplayAll()
        rsrc.adjust(200, 'PercentChangeInCapacity')
        self.assertEqual(3, len(rsrc.get_instance_names()))

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_policy_bad_group(self):
        t = template_format.parse(as_template_bad_group)
        stack = utils.parse_stack(t, params=self.params)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')

        alarm_url = up_policy.FnGetAtt('AlarmUrl')
        self.assertIsNotNone(alarm_url)
        ex = self.assertRaises(exception.ResourceFailure, up_policy.signal)
        self.assertIn('Alarm WebServerScaleUpPolicy could '
                      'not find scaling group', six.text_type(ex))

        self.m.VerifyAll()

    def test_scaling_policy_up(self):
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
        self.assertEqual(1, len(rsrc.get_instance_names()))

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
        self.assertEqual(2, len(rsrc.get_instance_names()))

        rsrc.delete()
        self.m.VerifyAll()

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
        self.assertEqual(1, len(rsrc.get_instance_names()))

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
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Check CustomLB metadata was updated
        self.m.StubOutWithMock(instance.Instance, '_ipaddress')
        instance.Instance._ipaddress().MultipleTimes().AndReturn(
            '127.0.0.1')
        self.m.ReplayAll()

        expected_meta = {'IPs': u'127.0.0.1,127.0.0.1'}
        self.assertEqual(expected_meta, stack['MyCustomLB'].metadata_get())

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_policy_down(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group, 2 instances
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        self._stub_lb_reload(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Scale down one
        self._stub_lb_reload(1)
        self._stub_delete(1)
        self.stub_ImageConstraint_validate(num=1)
        self._stub_meta_expected(now, 'ChangeInCapacity : -1', 2)

        self.m.ReplayAll()
        down_policy = self.create_scaling_policy(t, stack,
                                                 'WebServerScaleDownPolicy')
        down_policy.signal()
        self.assertEqual(1, len(rsrc.get_instance_names()))

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_policy_cooldown_toosoon(self):
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
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Scale up one
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.signal()
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Now move time on 10 seconds - Cooldown in template is 60
        # so this should not update the policy metadata, and the
        # scaling group instances should be unchanged
        # Note we have to stub Resource.metadata_get since up_policy isn't
        # stored in the DB (because the stack hasn't really been created)
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}

        self.m.VerifyAll()
        self.m.UnsetStubs()

        now = now + datetime.timedelta(seconds=10)
        self.m.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().MultipleTimes().AndReturn(now)

        self.m.StubOutWithMock(resource.Resource, 'metadata_get')
        up_policy.metadata_get().AndReturn(previous_meta)

        self.m.ReplayAll()
        up_policy.signal()
        self.assertEqual(2, len(rsrc.get_instance_names()))

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_policy_cooldown_ok(self):
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
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Scale up one
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.signal()
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Now move time on 61 seconds - Cooldown in template is 60
        # so this should trigger a scale-up
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(resource.Resource, 'metadata_get')
        up_policy.metadata_get().AndReturn(previous_meta)
        rsrc.metadata_get().AndReturn(previous_meta)

        #stub for the metadata accesses while creating the additional instance
        resource.Resource.metadata_get()

        now = now + datetime.timedelta(seconds=61)
        self._stub_lb_reload(3, unset=False)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy.signal()
        self.assertEqual(3, len(rsrc.get_instance_names()))

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_policy_cooldown_zero(self):
        t = template_format.parse(as_template)

        # Create the scaling policy (with Cooldown=0) and scale up one
        properties = t['Resources']['WebServerScaleUpPolicy']['Properties']
        properties['Cooldown'] = '0'

        stack = utils.parse_stack(t, params=self.params)

        # Create initial group
        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(1, len(rsrc.get_instance_names()))

        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.signal()
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Now trigger another scale-up without changing time, should work
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(resource.Resource, 'metadata_get')
        up_policy.metadata_get().AndReturn(previous_meta)
        rsrc.metadata_get().AndReturn(previous_meta)

        #stub for the metadata accesses while creating the additional instance
        resource.Resource.metadata_get()

        self._stub_lb_reload(3, unset=False)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy.signal()
        self.assertEqual(3, len(rsrc.get_instance_names()))

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_policy_cooldown_none(self):
        t = template_format.parse(as_template)

        # Create the scaling policy no Cooldown property, should behave the
        # same as when Cooldown==0
        properties = t['Resources']['WebServerScaleUpPolicy']['Properties']
        del properties['Cooldown']

        stack = utils.parse_stack(t, params=self.params)

        # Create initial group
        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = rsrc
        self.assertEqual(1, len(rsrc.get_instance_names()))

        self._stub_lb_reload(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.signal()
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Now trigger another scale-up without changing time, should work
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(resource.Resource, 'metadata_get')
        up_policy.metadata_get().AndReturn(previous_meta)
        rsrc.metadata_get().AndReturn(previous_meta)

        #stub for the metadata accesses while creating the additional instance
        resource.Resource.metadata_get()

        self._stub_lb_reload(3, unset=False)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy.signal()
        self.assertEqual(3, len(rsrc.get_instance_names()))

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
        self.assertEqual(1, len(rsrc.get_instance_names()))

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
        self.assertEqual(2, len(rsrc.get_instance_names()))

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

        #stub for the metadata accesses while creating the two instances
        resource.Resource.metadata_get()
        resource.Resource.metadata_get()

        now = now + datetime.timedelta(seconds=61)

        self._stub_lb_reload(4, unset=False)
        self._stub_meta_expected(now, 'ChangeInCapacity : 2', 2)
        self._stub_create(2)
        self.m.ReplayAll()

        # Trigger alarm
        up_policy.signal()
        self.assertEqual(4, len(rsrc.get_instance_names()))

        rsrc.delete()
        self.m.VerifyAll()

    def test_vpc_zone_identifier(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['VPCZoneIdentifier'] = ['xxxx']

        stack = utils.parse_stack(t, params=self.params)

        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()

        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        instances = rsrc.get_instances()
        self.assertEqual(1, len(instances))
        self.assertEqual('xxxx', instances[0].properties['SubnetId'])

        rsrc.delete()
        self.m.VerifyAll()

    def test_toomany_vpc_zone_identifier(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['VPCZoneIdentifier'] = ['xxxx', 'yyyy']

        stack = utils.parse_stack(t, params=self.params)
        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()
        self.assertRaises(exception.NotSupported,
                          self.create_scaling_group, t,
                          stack, 'WebServerGroup')

        self.m.VerifyAll()

    def test_invalid_min_size(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '-1'
        properties['MaxSize'] = '2'

        stack = utils.parse_stack(t, params=self.params)

        self.stub_ImageConstraint_validate()

        self.m.ReplayAll()
        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "The size of AutoScalingGroup can not be less than zero"
        self.assertEqual(expected_msg, six.text_type(e))
        self.m.VerifyAll()

    def test_invalid_max_size(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '3'
        properties['MaxSize'] = '1'

        stack = utils.parse_stack(t, params=self.params)

        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "MinSize can not be greater than MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))
        self.m.VerifyAll()

    def test_invalid_desiredcapacity(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        properties['DesiredCapacity'] = '4'

        stack = utils.parse_stack(t, params=self.params)
        self.stub_ImageConstraint_validate()

        self.m.ReplayAll()
        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "DesiredCapacity must be between MinSize and MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))
        self.m.VerifyAll()

    def test_invalid_desiredcapacity_zero(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        properties['DesiredCapacity'] = '0'

        stack = utils.parse_stack(t, params=self.params)
        self.stub_ImageConstraint_validate()

        self.m.ReplayAll()
        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "DesiredCapacity must be between MinSize and MaxSize"
        self.assertEqual(expected_msg, six.text_type(e))
        self.m.VerifyAll()

    def test_child_template_uses_min_size(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)
        defn = rsrc_defn.ResourceDefinition(
            'asg', 'AWS::AutoScaling::AutoScalingGroup',
            {'MinSize': 2, 'MaxSize': 5, 'LaunchConfigurationName': 'foo'})
        rsrc = asc.AutoScalingGroup('asg', defn, stack)

        rsrc._create_template = mock.Mock(return_value='tpl')

        self.assertEqual('tpl', rsrc.child_template())
        rsrc._create_template.assert_called_once_with(2)

    def test_child_template_uses_desired_capacity(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)
        defn = rsrc_defn.ResourceDefinition(
            'asg', 'AWS::AutoScaling::AutoScalingGroup',
            {'MinSize': 2, 'MaxSize': 5, 'DesiredCapacity': 3,
             'LaunchConfigurationName': 'foo'})
        rsrc = asc.AutoScalingGroup('asg', defn, stack)

        rsrc._create_template = mock.Mock(return_value='tpl')

        self.assertEqual('tpl', rsrc.child_template())
        rsrc._create_template.assert_called_once_with(3)

    def test_launch_config_get_ref_by_id(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)
        rsrc = stack['LaunchConfig']
        self.stub_ImageConstraint_validate()
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # use physical_resource_name when rsrc.id is not None
        self.assertIsNotNone(rsrc.id)
        expected = '%s-%s-%s' % (rsrc.stack.name,
                                 rsrc.name,
                                 short_id.get_id(rsrc.id))
        self.assertEqual(expected, rsrc.FnGetRefId())

        # otherwise use parent method
        rsrc.id = None
        self.assertIsNone(rsrc.resource_id)
        self.assertEqual('LaunchConfig', rsrc.FnGetRefId())

    def test_validate_BlockDeviceMappings_VolumeSize_invalid_str(self):
        t = template_format.parse(as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'DeviceName': 'vdb',
                'Ebs': {'SnapshotId': '1234',
                        'VolumeSize': 10}}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=self.params)
        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'LaunchConfig')

        expected_msg = "Value must be a string"
        self.assertIn(expected_msg, six.text_type(e))

        self.m.VerifyAll()

    def test_validate_BlockDeviceMappings_without_Ebs_property(self):
        t = template_format.parse(as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'DeviceName': 'vdb'}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=self.params)

        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'LaunchConfig')

        self.assertIn("Ebs is missing, this is required",
                      six.text_type(e))

        self.m.VerifyAll()

    def test_validate_BlockDeviceMappings_without_SnapshotId_property(self):
        t = template_format.parse(as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'DeviceName': 'vdb',
                'Ebs': {'VolumeSize': '1'}}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=self.params)

        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'LaunchConfig')

        self.assertIn("SnapshotId is missing, this is required",
                      six.text_type(e))
        self.m.VerifyAll()

    def test_validate_BlockDeviceMappings_without_DeviceName_property(self):
        t = template_format.parse(as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'Ebs': {'SnapshotId': '1234',
                        'VolumeSize': '1'}}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=self.params)
        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'LaunchConfig')

        excepted_error = ('Property error : LaunchConfig: BlockDeviceMappings '
                          'Property error : BlockDeviceMappings: 0 Property '
                          'error : 0: Property DeviceName not assigned')
        self.assertIn(excepted_error, six.text_type(e))

        self.m.VerifyAll()


class TestInstanceGroup(HeatTestCase):
    params = {'KeyName': 'test', 'ImageId': 'foo'}

    def setUp(self):
        super(TestInstanceGroup, self).setUp()

        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        defn = rsrc_defn.ResourceDefinition('ig', 'OS::Heat::InstanceGroup',
                                            {'Size': 2,
                                             'LaunchConfigurationName': 'foo'})
        self.instance_group = asc.InstanceGroup('ig', defn, stack)

    def test_child_template(self):
        self.instance_group._create_template = mock.Mock(return_value='tpl')

        self.assertEqual('tpl', self.instance_group.child_template())
        self.instance_group._create_template.assert_called_once_with(2)

    def test_child_params(self):
        self.instance_group._environment = mock.Mock(return_value='env')
        self.assertEqual('env', self.instance_group.child_params())
