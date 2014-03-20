
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
from testtools import skipIf

from heat.common import exception
from heat.common import short_id
from heat.common import template_format
from heat.engine.notification import autoscaling as notification
from heat.engine import parser
from heat.engine import resource
from heat.engine.resource import Metadata
from heat.engine.resources import autoscaling as asc
from heat.engine.resources import image
from heat.engine.resources import instance
from heat.engine.resources import loadbalancer
from heat.engine.resources.neutron import loadbalancer as neutron_lb
from heat.engine import scheduler
from heat.openstack.common.importutils import try_import
from heat.openstack.common import timeutils
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils

neutronclient = try_import('neutronclient.v2_0.client')


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
        utils.setup_dummy_db()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.fc = fakes.FakeKeystoneClient()

    def create_scaling_group(self, t, stack, resource_name):
        # create the launch configuration resource
        conf = stack['LaunchConfig']
        self.assertIsNone(conf.validate())
        scheduler.TaskRunner(conf.create)()
        self.assertEqual((conf.CREATE, conf.COMPLETE), conf.state)

        # create the group resource
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_scaling_policy(self, t, stack, resource_name):
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def _stub_validate(self):
        self.m.StubOutWithMock(parser.Stack, 'validate')
        parser.Stack.validate().MultipleTimes()

    def _stub_create(self, num):
        self._stub_validate()
        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        self.m.StubOutWithMock(image.ImageConstraint, "validate")
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        cookie = object()
        for x in range(num):
            instance.Instance.handle_create().AndReturn(cookie)
        instance.Instance.check_create_complete(cookie).AndReturn(False)
        instance.Instance.check_create_complete(
            cookie).MultipleTimes().AndReturn(True)

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
        self.m.StubOutWithMock(Metadata, '__set__')
        expected = {timeutils.strtime(now): data}
        # Note for ScalingPolicy, we expect to get a metadata
        # update for the policy and autoscaling group, so pass nmeta=2
        for x in range(nmeta):
            Metadata.__set__(mox.IgnoreArg(), expected).AndReturn(None)

    def test_scaling_delete_empty(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '0'
        properties['MaxSize'] = '0'
        stack = utils.parse_stack(t, params=self.params)
        self._stub_lb_reload(0)
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
        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['MinSize'] = '0'
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(instance_names, rsrc.get_instance_names())

        # trigger adjustment to reduce to 0, there should be no more instances
        self._stub_lb_reload(0)
        self._stub_scale_notification(adjust=-1, groupname=rsrc.FnGetRefId(),
                                      start_capacity=1, end_capacity=0)
        self._stub_meta_expected(now, 'ChangeInCapacity : -1')
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
        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['AvailabilityZones'] = ['foo']
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

        self.m.StubOutWithMock(instance.Instance, 'handle_suspend')
        self.m.StubOutWithMock(instance.Instance, 'check_suspend_complete')
        inst_cookie = (object(), object(), object())
        instance.Instance.handle_suspend().AndReturn(inst_cookie)
        instance.Instance.check_suspend_complete(inst_cookie).AndReturn(False)
        instance.Instance.check_suspend_complete(inst_cookie).AndReturn(True)
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

        self.m.StubOutWithMock(instance.Instance, 'handle_resume')
        self.m.StubOutWithMock(instance.Instance, 'check_resume_complete')
        inst_cookie = (object(), object(), object())
        instance.Instance.handle_resume().AndReturn(inst_cookie)
        instance.Instance.check_resume_complete(inst_cookie).AndReturn(False)
        instance.Instance.check_resume_complete(inst_cookie).AndReturn(True)
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

        self.m.StubOutWithMock(instance.Instance, 'handle_suspend')
        self.m.StubOutWithMock(instance.Instance, 'check_suspend_complete')
        inst_cookie1 = ('foo1', 'foo2', 'foo3')
        inst_cookie2 = ('bar1', 'bar2', 'bar3')
        instance.Instance.handle_suspend().InAnyOrder().AndReturn(inst_cookie1)
        instance.Instance.handle_suspend().InAnyOrder().AndReturn(inst_cookie2)
        instance.Instance.check_suspend_complete(inst_cookie1).InAnyOrder(
        ).AndReturn(True)
        instance.Instance.check_suspend_complete(inst_cookie2).InAnyOrder(
        ).AndReturn(True)
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

        self.m.StubOutWithMock(instance.Instance, 'handle_resume')
        self.m.StubOutWithMock(instance.Instance, 'check_resume_complete')
        inst_cookie1 = ('foo1', 'foo2', 'foo3')
        inst_cookie2 = ('bar1', 'bar2', 'bar3')
        instance.Instance.handle_resume().InAnyOrder().AndReturn(inst_cookie1)
        instance.Instance.handle_resume().InAnyOrder().AndReturn(inst_cookie2)
        instance.Instance.check_resume_complete(inst_cookie1).InAnyOrder(
        ).AndReturn(True)
        instance.Instance.check_resume_complete(inst_cookie2).InAnyOrder(
        ).AndReturn(True)
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

        self.m.StubOutWithMock(instance.Instance, 'handle_suspend')
        self.m.StubOutWithMock(instance.Instance, 'check_suspend_complete')
        instance.Instance.handle_suspend().AndRaise(Exception('oops'))
        self.m.ReplayAll()

        sus_task = scheduler.TaskRunner(rsrc.suspend)
        self.assertRaises(exception.ResourceFailure, sus_task, ())
        self.assertEqual((rsrc.SUSPEND, rsrc.FAILED), rsrc.state)
        self.assertEqual('Error: Resource SUSPEND failed: Exception: oops',
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

        self.m.StubOutWithMock(instance.Instance, 'handle_resume')
        self.m.StubOutWithMock(instance.Instance, 'check_resume_complete')
        instance.Instance.handle_resume().AndRaise(Exception('oops'))
        self.m.ReplayAll()

        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        for i in rsrc.nested().values():
            i.state_set(rsrc.SUSPEND, rsrc.COMPLETE)

        sus_task = scheduler.TaskRunner(rsrc.resume)
        self.assertRaises(exception.ResourceFailure, sus_task, ())
        self.assertEqual((rsrc.RESUME, rsrc.FAILED), rsrc.state)
        self.assertEqual('Error: Resource RESUME failed: Exception: oops',
                         rsrc.status_reason)

        rsrc.delete()
        self.m.VerifyAll()

    def test_scaling_group_create_error(self):
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)

        self._stub_validate()
        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        instance.Instance.handle_create().AndRaise(Exception)
        self.m.StubOutWithMock(image.ImageConstraint, "validate")
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)

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
        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['MaxSize'] = '2'
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
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(1)
        self.m.ReplayAll()

        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['MinSize'] = '2'
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

        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['DesiredCapacity'] = '2'
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(2, len(rsrc.get_instance_names()))
        self.assertEqual(2, rsrc.properties['DesiredCapacity'])

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
        update_snippet = copy.deepcopy(rsrc.parsed_template())
        del(update_snippet['Properties']['DesiredCapacity'])
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
        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['Cooldown'] = '61'
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
        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['Cooldown'] = '61'
        scheduler.TaskRunner(rsrc.update, update_snippet)()

        rsrc.delete()
        self.m.VerifyAll()

    @skipIf(neutronclient is None, 'neutronclient unavailable')
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

    @skipIf(neutronclient is None, 'neutronclient unavailable')
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
            str(error))

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
        self._stub_validate()
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
        self._stub_validate()
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
        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        instance.Instance.handle_create().AndRaise(exception.Error('Bang'))
        self.m.StubOutWithMock(image.ImageConstraint, "validate")
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self._stub_lb_reload(1, unset=False, nochange=True)
        self._stub_validate()
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
        stack['WebServerGroup'] = rsrc
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
        self._stub_validate()
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
        stack['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # reduce by decrease %
        self._stub_lb_reload(lowest)
        adjust = 'PercentChangeInCapacity : %d' % decrease
        self._stub_meta_expected(now, adjust)
        self._stub_validate()
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
        stack['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # reduce by 50%
        self._stub_lb_reload(1)
        self._stub_validate()
        self._stub_meta_expected(now, 'PercentChangeInCapacity : -50')
        self.m.ReplayAll()
        rsrc.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Now move time on 10 seconds - Cooldown in template is 60
        # so this should not update the policy metadata, and the
        # scaling group instances should be unchanged
        # Note we have to stub Metadata.__get__ since up_policy isn't
        # stored in the DB (because the stack hasn't really been created)
        previous_meta = {timeutils.strtime(now):
                         'PercentChangeInCapacity : -50'}

        self.m.VerifyAll()
        self.m.UnsetStubs()

        now = now + datetime.timedelta(seconds=10)
        self.m.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().MultipleTimes().AndReturn(now)

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), rsrc, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

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
        stack['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # reduce by 50%
        self._stub_lb_reload(1)
        self._stub_validate()
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

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), rsrc, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        #stub for the metadata accesses while creating the two instances
        Metadata.__get__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        Metadata.__get__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

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
        stack['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # reduce by 50%
        self._stub_lb_reload(1)
        self._stub_meta_expected(now, 'PercentChangeInCapacity : -50')
        self._stub_validate()
        self.m.ReplayAll()
        rsrc.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Don't move time, since cooldown is zero, it should work
        previous_meta = {timeutils.strtime(now):
                         'PercentChangeInCapacity : -50'}

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), rsrc, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        #stub for the metadata accesses while creating the two instances
        Metadata.__get__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        Metadata.__get__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
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

        self.m.StubOutWithMock(asc.ScalingPolicy, 'keystone')
        asc.ScalingPolicy.keystone().MultipleTimes().AndReturn(
            self.fc)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')

        alarm_url = up_policy.FnGetAtt('AlarmUrl')
        self.assertIsNotNone(alarm_url)
        ex = self.assertRaises(exception.ResourceFailure, up_policy.signal)
        self.assertIn('Alarm WebServerScaleUpPolicy could '
                      'not find scaling group', str(ex))

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
        stack['WebServerGroup'] = rsrc
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Scale up one
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.StubOutWithMock(asc.ScalingPolicy, 'keystone')
        asc.ScalingPolicy.keystone().MultipleTimes().AndReturn(
            self.fc)

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
        stack['WebServerGroup'] = rsrc
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Scale up one
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.StubOutWithMock(asc.ScalingPolicy, 'keystone')
        asc.ScalingPolicy.keystone().MultipleTimes().AndReturn(
            self.fc)

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
        self.assertEqual(expected_meta, stack['MyCustomLB'].metadata)

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
        stack['WebServerGroup'] = rsrc
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Scale down one
        self._stub_lb_reload(1)
        self._stub_validate()
        self._stub_meta_expected(now, 'ChangeInCapacity : -1', 2)

        self.m.StubOutWithMock(asc.ScalingPolicy, 'keystone')
        asc.ScalingPolicy.keystone().MultipleTimes().AndReturn(
            self.fc)

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
        stack['WebServerGroup'] = rsrc
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Scale up one
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.StubOutWithMock(asc.ScalingPolicy, 'keystone')
        asc.ScalingPolicy.keystone().MultipleTimes().AndReturn(
            self.fc)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.signal()
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Now move time on 10 seconds - Cooldown in template is 60
        # so this should not update the policy metadata, and the
        # scaling group instances should be unchanged
        # Note we have to stub Metadata.__get__ since up_policy isn't
        # stored in the DB (because the stack hasn't really been created)
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}

        self.m.VerifyAll()
        self.m.UnsetStubs()

        now = now + datetime.timedelta(seconds=10)
        self.m.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().MultipleTimes().AndReturn(now)

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), up_policy, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

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
        stack['WebServerGroup'] = rsrc
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Scale up one
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.StubOutWithMock(asc.ScalingPolicy, 'keystone')
        asc.ScalingPolicy.keystone().MultipleTimes().AndReturn(
            self.fc)

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

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), up_policy, mox.IgnoreArg()
                         ).AndReturn(previous_meta)
        Metadata.__get__(mox.IgnoreArg(), rsrc, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        #stub for the metadata accesses while creating the additional instance
        Metadata.__get__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

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
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group
        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack['WebServerGroup'] = rsrc
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Create the scaling policy (with Cooldown=0) and scale up one
        properties = t['Resources']['WebServerScaleUpPolicy']['Properties']
        properties['Cooldown'] = '0'
        self._stub_lb_reload(2)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.StubOutWithMock(asc.ScalingPolicy, 'keystone')
        asc.ScalingPolicy.keystone().MultipleTimes().AndReturn(
            self.fc)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.signal()
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Now trigger another scale-up without changing time, should work
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), up_policy, mox.IgnoreArg()
                         ).AndReturn(previous_meta)
        Metadata.__get__(mox.IgnoreArg(), rsrc, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        #stub for the metadata accesses while creating the additional instance
        Metadata.__get__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

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
        stack = utils.parse_stack(t, params=self.params)

        # Create initial group
        self._stub_lb_reload(1)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack['WebServerGroup'] = rsrc
        self.assertEqual(1, len(rsrc.get_instance_names()))

        # Create the scaling policy no Cooldown property, should behave the
        # same as when Cooldown==0
        properties = t['Resources']['WebServerScaleUpPolicy']['Properties']
        del(properties['Cooldown'])
        self._stub_lb_reload(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.StubOutWithMock(asc.ScalingPolicy, 'keystone')
        asc.ScalingPolicy.keystone().MultipleTimes().AndReturn(
            self.fc)

        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.signal()
        self.assertEqual(2, len(rsrc.get_instance_names()))

        # Now trigger another scale-up without changing time, should work
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), up_policy, mox.IgnoreArg()
                         ).AndReturn(previous_meta)
        Metadata.__get__(mox.IgnoreArg(), rsrc, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        #stub for the metadata accesses while creating the additional instance
        Metadata.__get__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

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

        self.m.StubOutWithMock(asc.ScalingPolicy, 'keystone')
        asc.ScalingPolicy.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()
        rsrc = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack['WebServerGroup'] = rsrc
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
        update_snippet = copy.deepcopy(up_policy.parsed_template())
        update_snippet['Properties']['ScalingAdjustment'] = '2'
        scheduler.TaskRunner(up_policy.update, update_snippet)()
        self.assertEqual(2, up_policy.properties['ScalingAdjustment'])

        # Now move time on 61 seconds - Cooldown in template is 60
        # so this should trigger a scale-up
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(Metadata, '__get__')

        Metadata.__get__(mox.IgnoreArg(), up_policy, mox.IgnoreArg()
                         ).AndReturn(previous_meta)
        Metadata.__get__(mox.IgnoreArg(), rsrc, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        #stub for the metadata accesses while creating the two instances
        Metadata.__get__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        Metadata.__get__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

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

    def test_invalid_vpc_zone_identifier(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['VPCZoneIdentifier'] = ['xxxx', 'yyyy']

        stack = utils.parse_stack(t, params=self.params)

        self.assertRaises(exception.NotSupported, self.create_scaling_group, t,
                          stack, 'WebServerGroup')

    def test_invalid_min_size(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '-1'
        properties['MaxSize'] = '2'

        stack = utils.parse_stack(t, params=self.params)

        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "The size of AutoScalingGroup can not be less than zero"
        self.assertEqual(expected_msg, str(e))

    def test_invalid_max_size(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '3'
        properties['MaxSize'] = '1'

        stack = utils.parse_stack(t, params=self.params)

        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "MinSize can not be greater than MaxSize"
        self.assertEqual(expected_msg, str(e))

    def test_invalid_desiredcapacity(self):
        t = template_format.parse(as_template)
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        properties['DesiredCapacity'] = '4'

        stack = utils.parse_stack(t, params=self.params)

        e = self.assertRaises(exception.StackValidationFailed,
                              self.create_scaling_group, t,
                              stack, 'WebServerGroup')

        expected_msg = "DesiredCapacity must be between MinSize and MaxSize"
        self.assertEqual(expected_msg, str(e))


class TestInstanceGroup(HeatTestCase):
    params = {'KeyName': 'test', 'ImageId': 'foo'}

    def setUp(self):
        super(TestInstanceGroup, self).setUp()
        utils.setup_dummy_db()

        json_snippet = {'Properties':
                        {'Size': 2, 'LaunchConfigurationName': 'foo'}}
        t = template_format.parse(as_template)
        stack = utils.parse_stack(t, params=self.params)
        self.instance_group = asc.InstanceGroup('ig', json_snippet, stack)

    def test_child_template(self):
        self.instance_group._create_template = mock.Mock(return_value='tpl')

        self.assertEqual('tpl', self.instance_group.child_template())
        self.instance_group._create_template.assert_called_once_with(2)

    def test_child_params(self):
        self.instance_group._environment = mock.Mock(return_value='env')
        self.assertEqual('env', self.instance_group.child_params())
