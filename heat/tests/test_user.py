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
from oslo.config import cfg

from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine.resources import user
from heat.tests import fakes

import keystoneclient.exceptions


@attr(tag=['unit', 'resource', 'User'])
@attr(speed='fast')
class UserTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeKeystoneClient(username='test_stack.CfnUser')
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    def tearDown(self):
        self.m.UnsetStubs()
        print "UserTest teardown complete"

    def load_template(self, template_name='Rails_Single_Instance.template'):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/%s" % (self.path, template_name))
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
        stack = parser.Stack(ctx, 'test_stack', template, params)

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
                         resource.handle_update({}))

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

    def test_user_validate_policies(self):

        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        tmpl = 'WordPress_Single_Instance_With_HA_AccessPolicy.template'
        t = self.load_template(template_name=tmpl)
        stack = self.parse_stack(t)

        resource = self.create_user(t, stack, 'CfnUser')
        self.assertEqual(self.fc.user_id, resource.resource_id)
        self.assertEqual('test_stack.CfnUser', resource.FnGetRefId())
        self.assertEqual('CREATE_COMPLETE', resource.state)

        self.assertEqual([u'WebServerAccessPolicy'],
                         resource.properties['Policies'])

        # OK
        self.assertTrue(
            resource._validate_policies([u'WebServerAccessPolicy']))

        # Resource name doesn't exist in the stack
        self.assertFalse(resource._validate_policies([u'NoExistAccessPolicy']))

        # Resource name is wrong Resource type
        self.assertFalse(resource._validate_policies([u'NoExistAccessPolicy',
                                                      u'WikiDatabase']))

        # Wrong type (AWS embedded policy format, not yet supported)
        dict_policy = {"PolicyName": "AccessForCFNInit",
                       "PolicyDocument":
                       {"Statement": [{"Effect": "Allow",
                                       "Action":
                                       "cloudformation:DescribeStackResource",
                                       "Resource": "*"}]}}

        # However we should just ignore it to avoid breaking existing templates
        self.assertTrue(resource._validate_policies([dict_policy]))

        self.m.VerifyAll()

    def test_user_create_bad_policies(self):
        self.m.ReplayAll()

        tmpl = 'WordPress_Single_Instance_With_HA_AccessPolicy.template'
        t = self.load_template(template_name=tmpl)
        t['Resources']['CfnUser']['Properties']['Policies'] = ['NoExistBad']
        stack = self.parse_stack(t)
        resource_name = 'CfnUser'
        resource = user.User(resource_name,
                             t['Resources'][resource_name],
                             stack)
        self.assertRaises(exception.InvalidTemplateAttribute,
                          resource.handle_create)
        self.m.VerifyAll()

    def test_user_access_allowed(self):

        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.StubOutWithMock(user.AccessPolicy, 'access_allowed')
        user.AccessPolicy.access_allowed('a_resource').AndReturn(True)
        user.AccessPolicy.access_allowed('b_resource').AndReturn(False)

        self.m.ReplayAll()

        tmpl = 'WordPress_Single_Instance_With_HA_AccessPolicy.template'
        t = self.load_template(template_name=tmpl)
        stack = self.parse_stack(t)

        resource = self.create_user(t, stack, 'CfnUser')
        self.assertEqual(self.fc.user_id, resource.resource_id)
        self.assertEqual('test_stack.CfnUser', resource.FnGetRefId())
        self.assertEqual('CREATE_COMPLETE', resource.state)

        self.assertTrue(resource.access_allowed('a_resource'))
        self.assertFalse(resource.access_allowed('b_resource'))
        self.m.VerifyAll()

    def test_user_access_allowed_ignorepolicy(self):

        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.StubOutWithMock(user.AccessPolicy, 'access_allowed')
        user.AccessPolicy.access_allowed('a_resource').AndReturn(True)
        user.AccessPolicy.access_allowed('b_resource').AndReturn(False)

        self.m.ReplayAll()

        tmpl = 'WordPress_Single_Instance_With_HA_AccessPolicy.template'
        t = self.load_template(template_name=tmpl)
        t['Resources']['CfnUser']['Properties']['Policies'] = [
            'WebServerAccessPolicy', {'an_ignored': 'policy'}]
        stack = self.parse_stack(t)

        resource = self.create_user(t, stack, 'CfnUser')
        self.assertEqual(self.fc.user_id, resource.resource_id)
        self.assertEqual('test_stack.CfnUser', resource.FnGetRefId())
        self.assertEqual('CREATE_COMPLETE', resource.state)

        self.assertTrue(resource.access_allowed('a_resource'))
        self.assertFalse(resource.access_allowed('b_resource'))
        self.m.VerifyAll()


@attr(tag=['unit', 'resource', 'AccessKey'])
@attr(speed='fast')
class AccessKeyTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeKeystoneClient(username='test_stack.CfnUser')
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    def tearDown(self):
        self.m.UnsetStubs()
        print "AccessKey teardown complete"

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
        stack = parser.Stack(ctx, 'test_stack', template, params)

        return stack

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
        stack.resources['CfnUser'].state = 'CREATE_COMPLETE'

        resource = self.create_access_key(t, stack, 'HostKeys')

        self.assertEqual(user.AccessKey.UPDATE_REPLACE,
                         resource.handle_update({}))
        self.assertEqual(self.fc.access,
                         resource.resource_id)

        self.assertEqual(self.fc.secret,
                         resource._secret)

        self.assertEqual(resource.FnGetAtt('UserName'), 'test_stack.CfnUser')
        resource._secret = None
        self.assertEqual(resource.FnGetAtt('SecretAccessKey'),
                         self.fc.secret)

        self.assertRaises(exception.InvalidTemplateAttribute,
                          resource.FnGetAtt, 'Foo')
        self.assertEqual(None, resource.delete())
        self.m.VerifyAll()

        # Check for double delete
        test_key = object()
        self.m.StubOutWithMock(self.fc, 'delete_ec2_keypair')
        NotFound = keystoneclient.exceptions.NotFound
        self.fc.delete_ec2_keypair(self.fc.user_id,
                                   test_key).AndRaise(NotFound('Gone'))

        self.m.ReplayAll()
        resource.state = resource.CREATE_COMPLETE
        resource.resource_id = test_key
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
        self.assertRaises(exception.ResourceFailure, resource.create)
        self.assertEqual(user.AccessKey.CREATE_FAILED,
                         resource.state)

        self.assertEqual(None, resource.delete())

        self.m.VerifyAll()


@attr(tag=['unit', 'resource', 'AccessPolicy'])
@attr(speed='fast')
class AccessPolicyTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeKeystoneClient(username='test_stack.CfnUser')
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    def tearDown(self):
        self.m.UnsetStubs()
        print "UserTest teardown complete"

    def load_template(self):
        template_name =\
            'WordPress_Single_Instance_With_HA_AccessPolicy.template'
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/%s" % (self.path, template_name))
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
        stack = parser.Stack(ctx, 'test_stack', template, params)

        return stack

    def test_accesspolicy_create_ok(self):
        t = self.load_template()
        stack = self.parse_stack(t)

        resource_name = 'WebServerAccessPolicy'
        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        self.assertEqual(None, resource.create())
        self.assertEqual(user.User.CREATE_COMPLETE, resource.state)

    def test_accesspolicy_create_ok_empty(self):
        t = self.load_template()
        resource_name = 'WebServerAccessPolicy'
        t['Resources'][resource_name]['Properties']['AllowedResources'] = []
        stack = self.parse_stack(t)

        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        self.assertEqual(None, resource.create())
        self.assertEqual(user.User.CREATE_COMPLETE, resource.state)

    def test_accesspolicy_create_err_notfound(self):
        t = self.load_template()
        resource_name = 'WebServerAccessPolicy'
        t['Resources'][resource_name]['Properties']['AllowedResources'] = [
            'NoExistResource']
        stack = self.parse_stack(t)

        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        self.assertRaises(exception.ResourceNotFound, resource.handle_create)

    def test_accesspolicy_update(self):
        t = self.load_template()
        resource_name = 'WebServerAccessPolicy'
        stack = self.parse_stack(t)

        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        self.assertEqual(user.AccessPolicy.UPDATE_REPLACE,
                         resource.handle_update({}))

    def test_accesspolicy_access_allowed(self):
        t = self.load_template()
        resource_name = 'WebServerAccessPolicy'
        stack = self.parse_stack(t)

        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        self.assertTrue(resource.access_allowed('WikiDatabase'))
        self.assertFalse(resource.access_allowed('NotWikiDatabase'))
        self.assertFalse(resource.access_allowed(None))
