
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

from heat.common import exception
from heat.common import template_format
from heat.db import api as db_api
from heat.engine import resource
from heat.engine import scheduler
from heat.engine.resources import user
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils

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
        username = utils.PhysName('test_stack', 'CfnUser')
        self.fc = fakes.FakeKeystoneClient(username=username)
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')
        utils.setup_dummy_db()


class UserTest(UserPolicyTestCase):

    def create_user(self, t, stack, resource_name):
        rsrc = user.User(resource_name,
                         t['Resources'][resource_name],
                         stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_user(self):

        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        t = template_format.parse(user_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_user(t, stack, 'CfnUser')
        self.assertEqual(self.fc.user_id, rsrc.resource_id)
        self.assertEqual(utils.PhysName('test_stack', 'CfnUser'),
                         rsrc.FnGetRefId())

        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.FnGetAtt, 'Foo')

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})

        self.assertIsNone(rsrc.handle_suspend())
        self.assertIsNone(rsrc.handle_resume())

        rsrc.resource_id = None
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        rsrc.resource_id = self.fc.access
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE)
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE)
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_user_validate_policies(self):

        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        t = template_format.parse(user_policy_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_user(t, stack, 'CfnUser')
        self.assertEqual(self.fc.user_id, rsrc.resource_id)
        self.assertEqual(utils.PhysName('test_stack', 'CfnUser'),
                         rsrc.FnGetRefId())
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertEqual([u'WebServerAccessPolicy'],
                         rsrc.properties['Policies'])

        # OK
        self.assertTrue(
            rsrc._validate_policies([u'WebServerAccessPolicy']))

        # Resource name doesn't exist in the stack
        self.assertFalse(rsrc._validate_policies([u'NoExistAccessPolicy']))

        # Resource name is wrong Resource type
        self.assertFalse(rsrc._validate_policies([u'NoExistAccessPolicy',
                                                  u'WikiDatabase']))

        # Wrong type (AWS embedded policy format, not yet supported)
        dict_policy = {"PolicyName": "AccessForCFNInit",
                       "PolicyDocument":
                       {"Statement": [{"Effect": "Allow",
                                       "Action":
                                       "cloudformation:DescribeStackResource",
                                       "Resource": "*"}]}}

        # However we should just ignore it to avoid breaking existing templates
        self.assertTrue(rsrc._validate_policies([dict_policy]))

        self.m.VerifyAll()

    def test_user_create_bad_policies(self):
        self.m.ReplayAll()

        t = template_format.parse(user_policy_template)
        t['Resources']['CfnUser']['Properties']['Policies'] = ['NoExistBad']
        stack = utils.parse_stack(t)
        resource_name = 'CfnUser'
        rsrc = user.User(resource_name,
                         t['Resources'][resource_name],
                         stack)
        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.handle_create)
        self.m.VerifyAll()

    def test_user_access_allowed(self):

        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.StubOutWithMock(user.AccessPolicy, 'access_allowed')
        user.AccessPolicy.access_allowed('a_resource').AndReturn(True)
        user.AccessPolicy.access_allowed('b_resource').AndReturn(False)

        self.m.ReplayAll()

        t = template_format.parse(user_policy_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_user(t, stack, 'CfnUser')
        self.assertEqual(self.fc.user_id, rsrc.resource_id)
        self.assertEqual(utils.PhysName('test_stack', 'CfnUser'),
                         rsrc.FnGetRefId())
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertTrue(rsrc.access_allowed('a_resource'))
        self.assertFalse(rsrc.access_allowed('b_resource'))
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
        stack = utils.parse_stack(t)

        rsrc = self.create_user(t, stack, 'CfnUser')
        self.assertEqual(self.fc.user_id, rsrc.resource_id)
        self.assertEqual(utils.PhysName('test_stack', 'CfnUser'),
                         rsrc.FnGetRefId())
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertTrue(rsrc.access_allowed('a_resource'))
        self.assertFalse(rsrc.access_allowed('b_resource'))
        self.m.VerifyAll()


class AccessKeyTest(UserPolicyTestCase):

    def create_access_key(self, t, stack, resource_name):
        rsrc = user.AccessKey(resource_name,
                              t['Resources'][resource_name],
                              stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_user(self, t, stack, resource_name):
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_access_key(self):
        self.m.StubOutWithMock(user.AccessKey, 'keystone')
        self.m.StubOutWithMock(user.User, 'keystone')
        user.AccessKey.keystone().MultipleTimes().AndReturn(self.fc)
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        t = template_format.parse(user_accesskey_template)

        stack = utils.parse_stack(t)

        self.create_user(t, stack, 'CfnUser')
        rsrc = self.create_access_key(t, stack, 'HostKeys')

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})
        self.assertEqual(self.fc.access,
                         rsrc.resource_id)

        self.assertEqual(self.fc.secret,
                         rsrc._secret)

        # Ensure the resource data has been stored correctly
        rs_data = db_api.resource_data_get_all(rsrc)
        self.assertEqual(self.fc.secret, rs_data.get('secret_key'))
        self.assertEqual(self.fc.credential_id, rs_data.get('credential_id'))
        self.assertEqual(2, len(rs_data.keys()))

        self.assertEqual(utils.PhysName(stack.name, 'CfnUser'),
                         rsrc.FnGetAtt('UserName'))
        rsrc._secret = None
        self.assertEqual(self.fc.secret,
                         rsrc.FnGetAtt('SecretAccessKey'))

        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.FnGetAtt, 'Foo')

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_access_key_get_from_keystone(self):
        self.m.StubOutWithMock(user.AccessKey, 'keystone')
        self.m.StubOutWithMock(user.User, 'keystone')
        user.AccessKey.keystone().MultipleTimes().AndReturn(self.fc)
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        t = template_format.parse(user_accesskey_template)

        stack = utils.parse_stack(t)

        self.create_user(t, stack, 'CfnUser')
        rsrc = self.create_access_key(t, stack, 'HostKeys')

        # Delete the resource data for secret_key, to test that existing
        # stacks which don't have the resource_data stored will continue
        # working via retrieving the keypair from keystone
        db_api.resource_data_delete(rsrc, 'credential_id')
        db_api.resource_data_delete(rsrc, 'secret_key')
        rs_data = db_api.resource_data_get_all(rsrc)
        self.assertEqual(0, len(rs_data.keys()))

        rsrc._secret = None
        self.assertEqual(self.fc.secret,
                         rsrc.FnGetAtt('SecretAccessKey'))

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_access_key_deleted(self):
        self.m.StubOutWithMock(user.AccessKey, 'keystone')
        self.m.StubOutWithMock(user.User, 'keystone')
        user.AccessKey.keystone().MultipleTimes().AndReturn(self.fc)
        user.User.keystone().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        t = template_format.parse(user_accesskey_template)
        stack = utils.parse_stack(t)

        self.create_user(t, stack, 'CfnUser')
        rsrc = self.create_access_key(t, stack, 'HostKeys')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.StubOutWithMock(self.fc, 'delete_ec2_keypair')
        NotFound = keystoneclient.exceptions.NotFound
        self.fc.delete_ec2_keypair(self.fc.user_id,
                                   rsrc.resource_id).AndRaise(NotFound('Gone'))
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_access_key_no_user(self):
        self.m.ReplayAll()

        t = template_format.parse(user_accesskey_template)
        # Set the resource properties UserName to an unknown user
        t['Resources']['HostKeys']['Properties']['UserName'] = 'NonExistent'
        stack = utils.parse_stack(t)
        stack['CfnUser'].resource_id = self.fc.user_id

        rsrc = user.AccessKey('HostKeys',
                              t['Resources']['HostKeys'],
                              stack)
        create = scheduler.TaskRunner(rsrc.create)
        self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()


class AccessPolicyTest(UserPolicyTestCase):

    def test_accesspolicy_create_ok(self):
        t = template_format.parse(user_policy_template)
        stack = utils.parse_stack(t)

        resource_name = 'WebServerAccessPolicy'
        rsrc = user.AccessPolicy(resource_name,
                                 t['Resources'][resource_name],
                                 stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    def test_accesspolicy_create_ok_empty(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        t['Resources'][resource_name]['Properties']['AllowedResources'] = []
        stack = utils.parse_stack(t)

        rsrc = user.AccessPolicy(resource_name,
                                 t['Resources'][resource_name],
                                 stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    def test_accesspolicy_create_err_notfound(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        t['Resources'][resource_name]['Properties']['AllowedResources'] = [
            'NoExistResource']
        stack = utils.parse_stack(t)

        rsrc = user.AccessPolicy(resource_name,
                                 t['Resources'][resource_name],
                                 stack)
        self.assertRaises(exception.ResourceNotFound, rsrc.handle_create)

    def test_accesspolicy_update(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        stack = utils.parse_stack(t)

        rsrc = user.AccessPolicy(resource_name,
                                 t['Resources'][resource_name],
                                 stack)
        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})

    def test_accesspolicy_access_allowed(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        stack = utils.parse_stack(t)

        rsrc = user.AccessPolicy(resource_name,
                                 t['Resources'][resource_name],
                                 stack)
        self.assertTrue(rsrc.access_allowed('WikiDatabase'))
        self.assertFalse(rsrc.access_allowed('NotWikiDatabase'))
        self.assertFalse(rsrc.access_allowed(None))
