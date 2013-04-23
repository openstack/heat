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

import copy
import os

import eventlet
import unittest
import mox

from nose.plugins.attrib import attr

from heat.tests.v1_1 import fakes
from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.engine.resources import autoscaling as asc
from heat.engine.resources import instance
from heat.engine.resources import loadbalancer
from heat.engine import parser


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class InstanceGroupTest(unittest.TestCase):
    def setUp(self):
        self.fc = fakes.FakeClient()
        self.m = mox.Mox()
        self.m.StubOutWithMock(loadbalancer.LoadBalancer, 'reload')

    def tearDown(self):
        self.m.UnsetStubs()
        print "InstanceGroupTest teardown complete"

    def load_template(self):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/InstanceGroup.template" % self.path)
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

    def create_instance_group(self, t, stack, resource_name):
        resource = asc.InstanceGroup(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        self.assertEqual(None, resource.validate())
        self.assertEqual(None, resource.create())
        self.assertEqual(asc.InstanceGroup.CREATE_COMPLETE, resource.state)
        return resource

    def test_instance_group(self):

        t = self.load_template()
        stack = self.parse_stack(t)

        # start with min then delete
        self._stub_create(1)
        self.m.StubOutWithMock(instance.Instance, 'FnGetAtt')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('1.2.3.4')

        self.m.ReplayAll()
        resource = self.create_instance_group(t, stack, 'JobServerGroup')

        self.assertEqual('JobServerGroup', resource.FnGetRefId())
        self.assertEqual('1.2.3.4', resource.FnGetAtt('InstanceList'))
        self.assertEqual('JobServerGroup-0', resource.resource_id)
        self.assertEqual(asc.InstanceGroup.UPDATE_REPLACE,
                         resource.handle_update({}))

        resource.delete()
        self.m.VerifyAll()

    def test_missing_image(self):

        t = self.load_template()
        stack = self.parse_stack(t)

        resource = asc.InstanceGroup('JobServerGroup',
                                     t['Resources']['JobServerGroup'],
                                     stack)

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        not_found = exception.ImageNotFound(image_name='bla')
        instance.Instance.handle_create().AndRaise(not_found)

        self.m.ReplayAll()

        self.assertRaises(exception.ResourceFailure, resource.create)
        self.assertEqual(asc.InstanceGroup.CREATE_FAILED, resource.state)

        self.m.VerifyAll()

    def test_update_size(self):
        t = self.load_template()
        properties = t['Resources']['JobServerGroup']['Properties']
        properties['Size'] = '2'
        stack = self.parse_stack(t)

        self._stub_create(2)
        self.m.ReplayAll()
        resource = self.create_instance_group(t, stack, 'JobServerGroup')
        self.assertEqual('JobServerGroup-0,JobServerGroup-1',
                         resource.resource_id)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        # Increase min size to 5
        self._stub_create(3)
        self.m.StubOutWithMock(instance.Instance, 'FnGetAtt')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.2')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.3')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.4')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.5')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.6')

        self.m.ReplayAll()

        update_snippet = copy.deepcopy(resource.parsed_template())
        update_snippet['Properties']['Size'] = '5'
        self.assertEqual(asc.AutoScalingGroup.UPDATE_COMPLETE,
                         resource.handle_update(update_snippet))
        assert_str = ','.join(['JobServerGroup-%s' % x for x in range(5)])
        self.assertEqual(assert_str,
                         resource.resource_id)
        self.assertEqual('10.0.0.2,10.0.0.3,10.0.0.4,10.0.0.5,10.0.0.6',
                         resource.FnGetAtt('InstanceList'))

        resource.delete()
        self.m.VerifyAll()
