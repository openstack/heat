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


from oslo.config import cfg

from heat.common import config
from heat.common import exception
from heat.common import template_format
from heat.engine import scheduler
from heat.engine.resources import user
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests.utils import setup_dummy_db
from heat.tests.utils import parse_stack

import keystoneclient.exceptions

user_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a User",
  "Parameters" : {},
  "Resources" : {
    "CfnUser" : {
      "Type" : "AWS::IAM::User"
    }
  }
}
'''

user_accesskey_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a User",
  "Parameters" : {},
  "Resources" : {
    "CfnUser" : {
      "Type" : "AWS::IAM::User"
    },

    "HostKeys" : {
      "Type" : "AWS::IAM::AccessKey",
      "Properties" : {
        "UserName" : {"Ref": "CfnUser"}
      }
    }
  }
}
'''


user_policy_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a User",
  "Parameters" : {},
  "Resources" : {
    "CfnUser" : {
      "Type" : "AWS::IAM::User",
      "Properties" : {
        "Policies" : [ { "Ref": "WebServerAccessPolicy"} ]
      }
    },
    "WebServerAccessPolicy" : {
      "Type" : "OS::Heat::AccessPolicy",
      "Properties" : {
        "AllowedResources" : [ "WikiDatabase" ]
      }
    },
    "WikiDatabase" : {
      "Type" : "AWS::EC2::Instance",
    }
  }
}
'''


class UserPolicyTestCase(HeatTestCase):
    def setUp(self):
        super(UserPolicyTestCase, self).setUp()
        config.register_engine_opts()
        self.fc = fakes.FakeKeystoneClient(username='test_stack.CfnUser')
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')
        setup_dummy_db()


class UserTest(UserPolicyTestCase):

    def create_user(self, t, stack, resource_name):
        resource = user.User(resource_name,
                             t['Resources'][resource_name],
                             stack)
        self.assertEqual(None, resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(user.User.CREATE_COMPLETE, resource.state)
        return resource

    def test_user(self):

        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        t = template_format.parse(user_template)
        stack = parse_stack(t)

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

        t = template_format.parse(user_policy_template)
        stack = parse_stack(t)

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

        t = template_format.parse(user_policy_template)
        t['Resources']['CfnUser']['Properties']['Policies'] = ['NoExistBad']
        stack = parse_stack(t)
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

        t = template_format.parse(user_policy_template)
        stack = parse_stack(t)

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

        t = template_format.parse(user_policy_template)
        t['Resources']['CfnUser']['Properties']['Policies'] = [
            'WebServerAccessPolicy', {'an_ignored': 'policy'}]
        stack = parse_stack(t)

        resource = self.create_user(t, stack, 'CfnUser')
        self.assertEqual(self.fc.user_id, resource.resource_id)
        self.assertEqual('test_stack.CfnUser', resource.FnGetRefId())
        self.assertEqual('CREATE_COMPLETE', resource.state)

        self.assertTrue(resource.access_allowed('a_resource'))
        self.assertFalse(resource.access_allowed('b_resource'))
        self.m.VerifyAll()


class AccessKeyTest(UserPolicyTestCase):

    def create_access_key(self, t, stack, resource_name):
        resource = user.AccessKey(resource_name,
                                  t['Resources'][resource_name],
                                  stack)
        self.assertEqual(None, resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(user.AccessKey.CREATE_COMPLETE,
                         resource.state)
        return resource

    def test_access_key(self):
        self.m.StubOutWithMock(user.AccessKey, 'keystone')
        user.AccessKey.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        t = template_format.parse(user_accesskey_template)
        # Override the Ref for UserName with a hard-coded name,
        # so we don't need to create the User resource
        t['Resources']['HostKeys']['Properties']['UserName'] =\
            'test_stack.CfnUser'
        stack = parse_stack(t)
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

        t = template_format.parse(user_accesskey_template)
        # Set the resource properties UserName to an unknown user
        t['Resources']['HostKeys']['Properties']['UserName'] =\
            'test_stack.NoExist'
        stack = parse_stack(t)
        stack.resources['CfnUser'].resource_id = self.fc.user_id

        resource = user.AccessKey('HostKeys',
                                  t['Resources']['HostKeys'],
                                  stack)
        create = scheduler.TaskRunner(resource.create)
        self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual(user.AccessKey.CREATE_FAILED,
                         resource.state)

        self.assertEqual(None, resource.delete())
        self.assertEqual(user.AccessKey.DELETE_COMPLETE, resource.state)

        self.m.VerifyAll()


class AccessPolicyTest(UserPolicyTestCase):

    def test_accesspolicy_create_ok(self):
        t = template_format.parse(user_policy_template)
        stack = parse_stack(t)

        resource_name = 'WebServerAccessPolicy'
        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(user.User.CREATE_COMPLETE, resource.state)

    def test_accesspolicy_create_ok_empty(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        t['Resources'][resource_name]['Properties']['AllowedResources'] = []
        stack = parse_stack(t)

        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(user.User.CREATE_COMPLETE, resource.state)

    def test_accesspolicy_create_err_notfound(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        t['Resources'][resource_name]['Properties']['AllowedResources'] = [
            'NoExistResource']
        stack = parse_stack(t)

        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        self.assertRaises(exception.ResourceNotFound, resource.handle_create)

    def test_accesspolicy_update(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        stack = parse_stack(t)

        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        self.assertEqual(user.AccessPolicy.UPDATE_REPLACE,
                         resource.handle_update({}))

    def test_accesspolicy_access_allowed(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        stack = parse_stack(t)

        resource = user.AccessPolicy(resource_name,
                                     t['Resources'][resource_name],
                                     stack)
        self.assertTrue(resource.access_allowed('WikiDatabase'))
        self.assertFalse(resource.access_allowed('NotWikiDatabase'))
        self.assertFalse(resource.access_allowed(None))
