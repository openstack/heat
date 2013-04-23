# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import os
import datetime
import copy

import eventlet
import unittest
import mox

from nose.plugins.attrib import attr

from heat.common import context
from heat.common import template_format
from heat.engine.resources import autoscaling as asc
from heat.engine.resources import loadbalancer
from heat.engine.resources import instance
from heat.engine import parser
from heat.engine.resource import Metadata
from heat.openstack.common import timeutils


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class AutoScalingTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()

    def tearDown(self):
        self.m.UnsetStubs()
        print "AutoScalingTest teardown complete"

    def load_template(self):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/AutoScalingMultiAZSample.template" % self.path)
        t = template_format.parse(f.read())
        f.close()
        return t

    def parse_stack(self, t):
        ctx = context.RequestContext.from_dict({
            'tenant': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'auth_url': 'http://localhost:5000/v2.0'})
        template = parser.Template(t)
        params = parser.Parameters('test_stack', template, {'KeyName': 'test'})
        stack = parser.Stack(ctx, 'test_stack', template, params)

        return stack

    def create_scaling_group(self, t, stack, resource_name):
        resource = asc.AutoScalingGroup(resource_name,
                                        t['Resources'][resource_name],
                                        stack)
        self.assertEqual(None, resource.validate())
        self.assertEqual(None, resource.create())
        self.assertEqual(asc.AutoScalingGroup.CREATE_COMPLETE, resource.state)
        return resource

    def create_scaling_policy(self, t, stack, resource_name):
        resource = asc.ScalingPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)

        self.assertEqual(None, resource.validate())
        self.assertEqual(None, resource.create())
        self.assertEqual(asc.ScalingPolicy.CREATE_COMPLETE,
                         resource.state)
        return resource

    def _stub_create(self, num):
        self.m.StubOutWithMock(eventlet, 'sleep')

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_active')
        cookie = object()
        for x in range(num):
            instance.Instance.handle_create().AndReturn(cookie)
        instance.Instance.check_active(cookie).AndReturn(False)
        eventlet.sleep(mox.IsA(int)).AndReturn(None)
        instance.Instance.check_active(cookie).MultipleTimes().AndReturn(True)

    def _stub_lb_reload(self, expected_list, unset=True):
        if unset:
            self.m.VerifyAll()
            self.m.UnsetStubs()
        self.m.StubOutWithMock(loadbalancer.LoadBalancer, 'reload')
        loadbalancer.LoadBalancer.reload(expected_list).AndReturn(None)

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

    def test_scaling_group_update(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')

        self.assertEqual('WebServerGroup', resource.FnGetRefId())
        self.assertEqual('WebServerGroup-0', resource.resource_id)
        self.assertEqual(asc.AutoScalingGroup.UPDATE_REPLACE,
                         resource.handle_update({}))

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_maxsize(self):
        t = self.load_template()
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        stack = self.parse_stack(t)

        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # Reduce the max size to 2, should complete without adjusting
        update_snippet = copy.deepcopy(resource.parsed_template())
        update_snippet['Properties']['MaxSize'] = '2'
        self.assertEqual(asc.AutoScalingGroup.UPDATE_COMPLETE,
                         resource.handle_update(update_snippet))
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_minsize(self):
        t = self.load_template()
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        stack = self.parse_stack(t)

        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # Increase min size to 2, should trigger an ExactCapacity adjust
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(1)
        self.m.ReplayAll()

        update_snippet = copy.deepcopy(resource.parsed_template())
        update_snippet['Properties']['MinSize'] = '2'
        self.assertEqual(asc.AutoScalingGroup.UPDATE_COMPLETE,
                         resource.handle_update(update_snippet))
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_desired(self):
        t = self.load_template()
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['MinSize'] = '1'
        properties['MaxSize'] = '3'
        stack = self.parse_stack(t)

        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # Increase min size to 2 via DesiredCapacity, should adjust
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(1)
        self.m.ReplayAll()

        update_snippet = copy.deepcopy(resource.parsed_template())
        update_snippet['Properties']['DesiredCapacity'] = '2'
        self.assertEqual(asc.AutoScalingGroup.UPDATE_COMPLETE,
                         resource.handle_update(update_snippet))
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_desired_remove(self):
        t = self.load_template()
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        stack = self.parse_stack(t)

        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # Remove DesiredCapacity from the updated template, which should
        # have no effect, it's an optional parameter
        update_snippet = copy.deepcopy(resource.parsed_template())
        del(update_snippet['Properties']['DesiredCapacity'])
        self.assertEqual(asc.AutoScalingGroup.UPDATE_COMPLETE,
                         resource.handle_update(update_snippet))
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_group_update_ok_cooldown(self):
        t = self.load_template()
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['Cooldown'] = '60'
        stack = self.parse_stack(t)

        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')

        self.assertEqual('WebServerGroup', resource.FnGetRefId())
        self.assertEqual('WebServerGroup-0', resource.resource_id)
        update_snippet = copy.deepcopy(resource.parsed_template())
        old_cd = update_snippet['Properties']['Cooldown']
        update_snippet['Properties']['Cooldown'] = '61'
        self.assertEqual(asc.AutoScalingGroup.UPDATE_COMPLETE,
                         resource.handle_update(update_snippet))

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_group_adjust(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # start with 3
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '3'
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 3')
        self._stub_create(3)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        # reduce to 1
        self._stub_lb_reload(['WebServerGroup-0'])
        self._stub_meta_expected(now, 'ChangeInCapacity : -2')
        self.m.ReplayAll()
        resource.adjust(-2)
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # raise to 3
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'])
        self._stub_meta_expected(now, 'ChangeInCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        resource.adjust(2)
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        # set to 2
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self.m.ReplayAll()
        resource.adjust(2, 'ExactCapacity')
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)
        self.m.VerifyAll()

    def test_scaling_group_nochange(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group, 2 instances
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # raise above the max
        resource.adjust(2)
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # lower below the min
        resource.adjust(-2)
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # no change
        resource.adjust(0)
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)
        resource.delete()
        self.m.VerifyAll()

    def test_scaling_group_percent(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group, 2 instances
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        self._stub_create(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # reduce by 50%
        self._stub_lb_reload(['WebServerGroup-0'])
        self._stub_meta_expected(now, 'PercentChangeInCapacity : -50')
        self.m.ReplayAll()
        resource.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual('WebServerGroup-0',
                         resource.resource_id)

        # raise by 200%
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'])
        self._stub_meta_expected(now, 'PercentChangeInCapacity : 200')
        self._stub_create(2)
        self.m.ReplayAll()
        resource.adjust(200, 'PercentChangeInCapacity')
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        resource.delete()

    def test_scaling_group_cooldown_toosoon(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group, 2 instances, Cooldown 60s
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        properties['Cooldown'] = '60'
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # reduce by 50%
        self._stub_lb_reload(['WebServerGroup-0'])
        self._stub_meta_expected(now, 'PercentChangeInCapacity : -50')
        self.m.ReplayAll()
        resource.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual('WebServerGroup-0',
                         resource.resource_id)

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
        timeutils.utcnow().AndReturn(now)

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), resource, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        self.m.ReplayAll()

        # raise by 200%, too soon for Cooldown so there should be no change
        resource.adjust(200, 'PercentChangeInCapacity')
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        resource.delete()

    def test_scaling_group_cooldown_ok(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group, 2 instances, Cooldown 60s
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        properties['Cooldown'] = '60'
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        self._stub_create(2)
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # reduce by 50%
        self._stub_lb_reload(['WebServerGroup-0'])
        self._stub_meta_expected(now, 'PercentChangeInCapacity : -50')
        self.m.ReplayAll()
        resource.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual('WebServerGroup-0',
                         resource.resource_id)

        # Now move time on 61 seconds - Cooldown in template is 60
        # so this should update the policy metadata, and the
        # scaling group instances updated
        previous_meta = {timeutils.strtime(now):
                         'PercentChangeInCapacity : -50'}

        self.m.VerifyAll()
        self.m.UnsetStubs()

        now = now + datetime.timedelta(seconds=61)

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), resource, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        # raise by 200%, should work
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'], unset=False)
        self._stub_create(2)
        self._stub_meta_expected(now, 'PercentChangeInCapacity : 200')
        self.m.ReplayAll()
        resource.adjust(200, 'PercentChangeInCapacity')
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        resource.delete()

    def test_scaling_group_cooldown_zero(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group, 2 instances, Cooldown 0
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        properties['Cooldown'] = '0'
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # reduce by 50%
        self._stub_lb_reload(['WebServerGroup-0'])
        self._stub_meta_expected(now, 'PercentChangeInCapacity : -50')
        self.m.ReplayAll()
        resource.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual('WebServerGroup-0',
                         resource.resource_id)

        # Don't move time, since cooldown is zero, it should work
        previous_meta = {timeutils.strtime(now):
                         'PercentChangeInCapacity : -50'}

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), resource, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        # raise by 200%, should work
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'], unset=False)
        self._stub_meta_expected(now, 'PercentChangeInCapacity : 200')
        self._stub_create(2)
        self.m.ReplayAll()
        resource.adjust(200, 'PercentChangeInCapacity')
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_policy_up(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group
        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # Scale up one
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)
        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.alarm()
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_policy_down(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group, 2 instances
        properties = t['Resources']['WebServerGroup']['Properties']
        properties['DesiredCapacity'] = '2'
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 2')
        self._stub_create(2)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # Scale down one
        self._stub_lb_reload(['WebServerGroup-0'])
        self._stub_meta_expected(now, 'ChangeInCapacity : -1', 2)
        self.m.ReplayAll()
        down_policy = self.create_scaling_policy(t, stack,
                                                 'WebServerScaleDownPolicy')
        down_policy.alarm()
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_policy_cooldown_toosoon(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group
        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # Scale up one
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)
        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.alarm()
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

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
        timeutils.utcnow().AndReturn(now)

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), up_policy, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        self.m.ReplayAll()
        up_policy.alarm()
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_policy_cooldown_ok(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group
        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # Scale up one
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)
        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.alarm()
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # Now move time on 61 seconds - Cooldown in template is 60
        # so this should trigger a scale-up
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), up_policy, mox.IgnoreArg()
                         ).AndReturn(previous_meta)
        Metadata.__get__(mox.IgnoreArg(), resource, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        now = now + datetime.timedelta(seconds=61)
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'], unset=False)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy.alarm()
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_policy_cooldown_zero(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group
        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # Create the scaling policy (with Cooldown=0) and scale up one
        properties = t['Resources']['WebServerScaleUpPolicy']['Properties']
        properties['Cooldown'] = '0'
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)
        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.alarm()
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # Now trigger another scale-up without changing time, should work
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), up_policy, mox.IgnoreArg()
                         ).AndReturn(previous_meta)
        Metadata.__get__(mox.IgnoreArg(), resource, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'], unset=False)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy.alarm()
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        resource.delete()
        self.m.VerifyAll()

    def test_scaling_policy_cooldown_none(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        # Create initial group
        self._stub_lb_reload(['WebServerGroup-0'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ExactCapacity : 1')
        self._stub_create(1)
        self.m.ReplayAll()
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # Create the scaling policy no Cooldown property, should behave the
        # same as when Cooldown==0
        properties = t['Resources']['WebServerScaleUpPolicy']['Properties']
        del(properties['Cooldown'])
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
        now = timeutils.utcnow()
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)
        self.m.ReplayAll()
        up_policy = self.create_scaling_policy(t, stack,
                                               'WebServerScaleUpPolicy')
        up_policy.alarm()
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # Now trigger another scale-up without changing time, should work
        previous_meta = {timeutils.strtime(now): 'ChangeInCapacity : 1'}
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(Metadata, '__get__')
        Metadata.__get__(mox.IgnoreArg(), up_policy, mox.IgnoreArg()
                         ).AndReturn(previous_meta)
        Metadata.__get__(mox.IgnoreArg(), resource, mox.IgnoreArg()
                         ).AndReturn(previous_meta)

        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'], unset=False)
        self._stub_meta_expected(now, 'ChangeInCapacity : 1', 2)
        self._stub_create(1)

        self.m.ReplayAll()
        up_policy.alarm()
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        resource.delete()
        self.m.VerifyAll()
