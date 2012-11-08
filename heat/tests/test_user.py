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

from heat.common import exception
from heat.common import config
from heat.engine import parser
from heat.engine.resources import user
from heat.tests.v1_1 import fakes
from keystoneclient.v2_0 import users
from keystoneclient.v2_0 import roles
from keystoneclient.v2_0 import ec2
from heat.openstack.common import cfg


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class UserTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()
        self.fc.users = users.UserManager(None)
        self.fc.roles = roles.RoleManager(None)
        self.fc.ec2 = ec2.CredentialsManager(None)
        self.m.StubOutWithMock(user.User, 'keystone')
        self.m.StubOutWithMock(user.AccessKey, 'keystone')
        self.m.StubOutWithMock(self.fc.users, 'create')
        self.m.StubOutWithMock(self.fc.users, 'get')
        self.m.StubOutWithMock(self.fc.users, 'delete')
        self.m.StubOutWithMock(self.fc.users, 'list')
        self.m.StubOutWithMock(self.fc.roles, 'list')
        self.m.StubOutWithMock(self.fc.roles, 'add_user_role')
        self.m.StubOutWithMock(self.fc.ec2, 'create')
        self.m.StubOutWithMock(self.fc.ec2, 'get')
        self.m.StubOutWithMock(self.fc.ec2, 'delete')
        self.m.StubOutWithMock(eventlet, 'sleep')
        config.register_engine_opts()
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    def tearDown(self):
        self.m.UnsetStubs()
        print "UserTest teardown complete"

    def load_template(self):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/Rails_Single_Instance.template" % self.path)
        t = json.loads(f.read())
        f.close()
        return t

    def parse_stack(self, t):
        class DummyContext():
            tenant_id = 'test_tenant'
            username = 'test_username'
            password = 'password'
            auth_url = 'http://localhost:5000/v2.0'
        template = parser.Template(t)
        params = parser.Parameters('test_stack',
                                   template,
                                   {'KeyName': 'test',
                                    'DBRootPassword': 'test',
                                    'DBUsername': 'test',
                                    'DBPassword': 'test'})
        stack = parser.Stack(DummyContext(), 'test_stack', template,
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

    def create_access_key(self, t, stack, resource_name):
        resource = user.AccessKey(resource_name,
                                      t['Resources'][resource_name],
                                      stack)
        self.assertEqual(None, resource.validate())
        self.assertEqual(None, resource.create())
        self.assertEqual(user.AccessKey.CREATE_COMPLETE,
                         resource.state)
        return resource

    def test_user(self):

        fake_user = users.User(self.fc.users, {'id': '1'})
        user.User.keystone().AndReturn(self.fc)
        self.fc.users.create('test_stack.CfnUser',
                             '',
                             'test_stack.CfnUser@heat-api.org',
                             enabled=True,
                             tenant_id='test_tenant').AndReturn(fake_user)

        fake_role = roles.Role(self.fc.roles, {'id': '123',
                                               'name': 'stack_user_role'})
        user.User.keystone().AndReturn(self.fc)
        self.fc.roles.list().AndReturn([fake_role])

        user.User.keystone().AndReturn(self.fc)
        self.fc.roles.add_user_role('1', '123', 'test_tenant').AndReturn(None)

        # delete script
        user.User.keystone().AndReturn(self.fc)
        self.fc.users.get(user.DummyId('1')).AndRaise(Exception('not found'))
        eventlet.sleep(1).AndReturn(None)

        user.User.keystone().AndReturn(self.fc)
        self.fc.users.get(user.DummyId('1')).AndReturn(fake_user)
        self.fc.users.delete(fake_user).AndRaise(Exception('delete failed'))

        self.fc.users.delete(fake_user).AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t)

        resource = self.create_user(t, stack, 'CfnUser')
        self.assertEqual('1', resource.resource_id)
        self.assertEqual('test_stack.CfnUser', resource.FnGetRefId())

        self.assertEqual('CREATE_COMPLETE', resource.state)
        self.assertEqual(user.User.UPDATE_REPLACE,
                  resource.handle_update())

        resource.resource_id = None
        self.assertEqual(None, resource.delete())
        self.assertEqual('DELETE_COMPLETE', resource.state)

        resource.resource_id = '1'
        resource.state_set('CREATE_COMPLETE')
        self.assertEqual('CREATE_COMPLETE', resource.state)

        self.assertEqual(None, resource.delete())
        self.assertEqual('DELETE_COMPLETE', resource.state)

        resource.state_set('CREATE_COMPLETE')
        self.assertEqual('CREATE_COMPLETE', resource.state)

        self.assertEqual(None, resource.delete())
        self.assertEqual('DELETE_COMPLETE', resource.state)
        self.m.VerifyAll()

    def test_access_key(self):

        fake_user = users.User(self.fc.users, {'id': '1',
                                               'name': 'test_stack.CfnUser'})
        fake_cred = ec2.EC2(self.fc.ec2, {
                        'access': '03a4967889d94a9c8f707d267c127a3d',
                        'secret': 'd5fd0c08f8cc417ead0355c67c529438'})

        user.AccessKey.keystone().AndReturn(self.fc)
        self.fc.users.list(tenant_id='test_tenant').AndReturn([fake_user])

        user.AccessKey.keystone().AndReturn(self.fc)
        self.fc.ec2.create('1', 'test_tenant').AndReturn(fake_cred)

        # fetch secret key
        user.AccessKey.keystone().AndReturn(self.fc)
        self.fc.auth_user_id = '1'
        user.AccessKey.keystone().AndReturn(self.fc)
        self.fc.ec2.get('1',
                '03a4967889d94a9c8f707d267c127a3d').AndReturn(fake_cred)

        # delete script
        user.AccessKey.keystone().AndReturn(self.fc)
        self.fc.users.list(tenant_id='test_tenant').AndReturn([fake_user])
        user.AccessKey.keystone().AndReturn(self.fc)
        self.fc.ec2.delete('1',
                           '03a4967889d94a9c8f707d267c127a3d').AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t)

        resource = self.create_access_key(t, stack, 'HostKeys')

        self.assertEqual(user.AccessKey.UPDATE_REPLACE,
                  resource.handle_update())
        self.assertEqual('03a4967889d94a9c8f707d267c127a3d',
                         resource.resource_id)

        self.assertEqual('d5fd0c08f8cc417ead0355c67c529438',
                         resource._secret)

        self.assertEqual(resource.FnGetAtt('UserName'), 'test_stack.CfnUser')
        resource._secret = None
        self.assertEqual(resource.FnGetAtt('SecretAccessKey'),
                         'd5fd0c08f8cc417ead0355c67c529438')
        try:
            resource.FnGetAtt('Foo')
        except exception.InvalidTemplateAttribute:
            pass
        else:
            raise Exception('Expected InvalidTemplateAttribute')

        self.assertEqual(None, resource.delete())
        self.m.VerifyAll()

    def test_access_key_no_user(self):

        user.AccessKey.keystone().AndReturn(self.fc)
        self.fc.users.list(tenant_id='test_tenant').AndReturn([])

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t)

        resource = user.AccessKey('HostKeys',
                                      t['Resources']['HostKeys'],
                                      stack)
        self.assertEqual('could not find user test_stack.CfnUser',
                         resource.create())
        self.assertEqual(user.AccessKey.CREATE_FAILED,
                         resource.state)

        self.m.VerifyAll()

    # allows testing of the test directly, shown below
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
