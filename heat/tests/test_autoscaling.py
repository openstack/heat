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

import unittest
import mox

from nose.plugins.attrib import attr

from heat.common import context
from heat.common import template_format
from heat.engine.resources import autoscaling as asc
from heat.engine.resources import loadbalancer
from heat.engine import parser


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class AutoScalingTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.m.StubOutWithMock(loadbalancer.LoadBalancer, 'reload')

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

    def _stub_lb_reload(self, expected_list):
        self.m.VerifyAll()
        self.m.UnsetStubs()
        self.m.StubOutWithMock(loadbalancer.LoadBalancer, 'reload')
        loadbalancer.LoadBalancer.reload(expected_list).AndReturn(None)
        self.m.ReplayAll()

    def test_scaling_group_update(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        self._stub_lb_reload(['WebServerGroup-0'])
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')

        self.assertEqual('WebServerGroup', resource.FnGetRefId())
        self.assertEqual('WebServerGroup-0', resource.resource_id)
        self.assertEqual(asc.AutoScalingGroup.UPDATE_REPLACE,
                         resource.handle_update())

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
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        # reduce to 1
        self._stub_lb_reload(['WebServerGroup-0'])
        resource.adjust(-2)
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # raise to 3
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'])
        resource.adjust(2)
        self.assertEqual('WebServerGroup-0,WebServerGroup-1,WebServerGroup-2',
                         resource.resource_id)

        # set to 2
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
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
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # reduce by 50%
        self._stub_lb_reload(['WebServerGroup-0'])
        resource.adjust(-50, 'PercentChangeInCapacity')
        self.assertEqual('WebServerGroup-0',
                         resource.resource_id)

        # raise by 200%
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1',
                              'WebServerGroup-2'])
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
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        # Scale up one
        self._stub_lb_reload(['WebServerGroup-0', 'WebServerGroup-1'])
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
        resource = self.create_scaling_group(t, stack, 'WebServerGroup')
        stack.resources['WebServerGroup'] = resource
        self.assertEqual('WebServerGroup-0,WebServerGroup-1',
                         resource.resource_id)

        # Scale down one
        self._stub_lb_reload(['WebServerGroup-0'])
        down_policy = self.create_scaling_policy(t, stack,
                                                 'WebServerScaleDownPolicy')
        down_policy.alarm()
        self.assertEqual('WebServerGroup-0', resource.resource_id)

        resource.delete()
        self.m.VerifyAll()
