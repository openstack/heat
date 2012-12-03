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


import sys
import os

import eventlet
import json
import nose
import mox
import unittest

from nose.plugins.attrib import attr

from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine.resources import user
from heat.tests import fakes
from heat.openstack.common import cfg


@attr(tag=['unit', 'resource', 'Unit'])
@attr(speed='fast')
class UserTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeKeystoneClient(username='test_stack.CfnUser')
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    def tearDown(self):
        self.m.UnsetStubs()
        print "UserTest teardown complete"

    def load_template(self):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/Rails_Single_Instance.template" % self.path)
        t = template_format.parse(f.read())
        f.close()
        return t

    def parse_stack(self, t):
        ctx = context.RequestContext.from_dict({
            'tenant_id': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'auth_url': 'http://localhost:5000/v2.0'})
        template = parser.Template(t)
        params = parser.Parameters('test_stack',
                                   template,
                                   {'KeyName': 'test',
                                    'DBRootPassword': 'test',
                                    'DBUsername': 'test',
                                    'DBPassword': 'test'})
        stack = parser.Stack(ctx, 'test_stack', template,
                             params, stack_id=-1)

        return stack

    def create_user(self, t, stack, resource_name):
        resource = user.User(resource_name,
                                      t['Resources'][resource_name],
                                      stack)
        self.assertEqual(None, resource.validate())
        self.assertEqual(None, resource.create())
        self.assertEqual(user.User.CREATE_COMPLETE, resource.state)
        return resource

    def test_user(self):

        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t)

        resource = self.create_user(t, stack, 'CfnUser')
        self.assertEqual(self.fc.user_id, resource.resource_id)
        self.assertEqual('test_stack.CfnUser', resource.FnGetRefId())

        self.assertEqual('CREATE_COMPLETE', resource.state)
        self.assertEqual(user.User.UPDATE_REPLACE,
                  resource.handle_update())

        resource.resource_id = None
        self.assertEqual(None, resource.delete())
        self.assertEqual('DELETE_COMPLETE', resource.state)

        resource.resource_id = self.fc.access
        resource.state_set('CREATE_COMPLETE')
        self.assertEqual('CREATE_COMPLETE', resource.state)

        self.assertEqual(None, resource.delete())
        self.assertEqual('DELETE_COMPLETE', resource.state)

        resource.state_set('CREATE_COMPLETE')
        self.assertEqual('CREATE_COMPLETE', resource.state)

        self.assertEqual(None, resource.delete())
        self.assertEqual('DELETE_COMPLETE', resource.state)
        self.m.VerifyAll()

    def create_access_key(self, t, stack, resource_name):
        resource = user.AccessKey(resource_name,
                                      t['Resources'][resource_name],
                                      stack)
        self.assertEqual(None, resource.validate())
        self.assertEqual(None, resource.create())
        self.assertEqual(user.AccessKey.CREATE_COMPLETE,
                         resource.state)
        return resource

    def test_access_key(self):
        self.m.StubOutWithMock(user.AccessKey, 'keystone')
        user.AccessKey.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        t = self.load_template()
        # Override the Ref for UserName with a hard-coded name,
        # so we don't need to create the User resource
        t['Resources']['HostKeys']['Properties']['UserName'] =\
            'test_stack.CfnUser'
        stack = self.parse_stack(t)
        stack.resources['CfnUser'].resource_id = self.fc.user_id

        resource = self.create_access_key(t, stack, 'HostKeys')

        self.assertEqual(user.AccessKey.UPDATE_REPLACE,
                  resource.handle_update())
        self.assertEqual(self.fc.access,
                         resource.resource_id)

        self.assertEqual(self.fc.secret,
                         resource._secret)

        self.assertEqual(resource.FnGetAtt('UserName'), 'test_stack.CfnUser')
        resource._secret = None
        self.assertEqual(resource.FnGetAtt('SecretAccessKey'),
                         self.fc.secret)
        try:
            resource.FnGetAtt('Foo')
        except exception.InvalidTemplateAttribute:
            pass
        else:
            raise Exception('Expected InvalidTemplateAttribute')

        self.assertEqual(None, resource.delete())
        self.m.VerifyAll()

    def test_access_key_no_user(self):
        self.m.ReplayAll()

        t = self.load_template()
        # Set the resource properties UserName to an unknown user
        t['Resources']['HostKeys']['Properties']['UserName'] =\
            'test_stack.NoExist'
        stack = self.parse_stack(t)
        stack.resources['CfnUser'].resource_id = self.fc.user_id

        resource = user.AccessKey('HostKeys',
                                  t['Resources']['HostKeys'],
                                  stack)
        self.assertEqual('could not find user test_stack.NoExist',
                         resource.create())
        self.assertEqual(user.AccessKey.CREATE_FAILED,
                         resource.state)

        self.m.VerifyAll()

# allows testing of the test directly, shown below
if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
