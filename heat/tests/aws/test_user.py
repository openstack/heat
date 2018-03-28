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

import mock
from oslo_config import cfg

from heat.common import exception
from heat.common import short_id
from heat.common import template_format
from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine import node_data
from heat.engine.resources.aws.iam import user
from heat.engine.resources.openstack.heat import access_policy as ap
from heat.engine import scheduler
from heat.engine import stk_defn
from heat.objects import resource_data as resource_data_object
from heat.tests import common
from heat.tests import utils


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

user_template_password = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a User",
  "Parameters" : {},
  "Resources" : {
    "CfnUser" : {
      "Type" : "AWS::IAM::User",
      "Properties": {
        "LoginProfile": { "Password": "myP@ssW0rd" }
      }
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


class UserTest(common.HeatTestCase):
    def setUp(self):
        super(UserTest, self).setUp()
        self.stack_name = 'test_user_stack_%s' % utils.random_name()
        self.username = '%s-CfnUser-aabbcc' % self.stack_name
        self.fc = fake_ks.FakeKeystoneClient(username=self.username)
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    def create_user(self, t, stack, resource_name,
                    project_id, user_id='dummy_user',
                    password=None):
        self.patchobject(user.User, 'keystone', return_value=self.fc)

        self.mock_create_project = self.patchobject(
            fake_ks.FakeKeystoneClient, 'create_stack_domain_project',
            return_value=project_id)

        resource_defns = stack.t.resource_definitions(stack)
        rsrc = user.User(resource_name,
                         resource_defns[resource_name],
                         stack)
        rsrc.store()

        self.patchobject(short_id, 'get_id', return_value='aabbcc')

        self.mock_create_user = self.patchobject(
            fake_ks.FakeKeystoneClient, 'create_stack_domain_user',
            return_value=user_id)

        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_user(self):
        t = template_format.parse(user_template)
        stack = utils.parse_stack(t, stack_name=self.stack_name)
        project_id = 'stackproject'

        rsrc = self.create_user(t, stack, 'CfnUser', project_id)
        self.assertEqual('dummy_user', rsrc.resource_id)
        self.assertEqual(self.username, rsrc.FnGetRefId())

        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.FnGetAtt, 'Foo')

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

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
        self.mock_create_project.assert_called_once_with(stack.id)
        self.mock_create_user.assert_called_once_with(
            password=None, project_id=project_id,
            username=self.username)

    def test_user_password(self):
        t = template_format.parse(user_template_password)
        stack = utils.parse_stack(t, stack_name=self.stack_name)
        project_id = 'stackproject'
        password = u'myP@ssW0rd'
        rsrc = self.create_user(t, stack, 'CfnUser',
                                project_id=project_id,
                                password=password)
        self.assertEqual('dummy_user', rsrc.resource_id)
        self.assertEqual(self.username, rsrc.FnGetRefId())

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.mock_create_project.assert_called_once_with(stack.id)
        self.mock_create_user.assert_called_once_with(
            password=password, project_id=project_id,
            username=self.username)

    def test_user_validate_policies(self):
        t = template_format.parse(user_policy_template)
        stack = utils.parse_stack(t, stack_name=self.stack_name)
        project_id = 'stackproject'

        rsrc = self.create_user(t, stack, 'CfnUser', project_id)
        self.assertEqual('dummy_user', rsrc.resource_id)
        self.assertEqual(self.username, rsrc.FnGetRefId())
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertEqual([u'WebServerAccessPolicy'],
                         rsrc.properties['Policies'])

        # OK
        self.assertTrue(rsrc._validate_policies([u'WebServerAccessPolicy']))

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
        self.mock_create_project.assert_called_once_with(stack.id)
        self.mock_create_user.assert_called_once_with(
            password=None, project_id=project_id,
            username=self.username)

    def test_user_create_bad_policies(self):
        t = template_format.parse(user_policy_template)
        t['Resources']['CfnUser']['Properties']['Policies'] = ['NoExistBad']
        stack = utils.parse_stack(t, stack_name=self.stack_name)
        resource_name = 'CfnUser'
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = user.User(resource_name,
                         resource_defns[resource_name],
                         stack)
        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.handle_create)

    def test_user_access_allowed(self):

        def mock_access_allowed(resource):
            return True if resource == 'a_resource' else False

        self.patchobject(ap.AccessPolicy, 'access_allowed',
                         side_effect=mock_access_allowed)

        t = template_format.parse(user_policy_template)
        stack = utils.parse_stack(t, stack_name=self.stack_name)
        project_id = 'stackproject'

        rsrc = self.create_user(t, stack, 'CfnUser', project_id)
        self.assertEqual('dummy_user', rsrc.resource_id)
        self.assertEqual(self.username, rsrc.FnGetRefId())
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertTrue(rsrc.access_allowed('a_resource'))
        self.assertFalse(rsrc.access_allowed('b_resource'))
        self.mock_create_project.assert_called_once_with(stack.id)
        self.mock_create_user.assert_called_once_with(
            password=None, project_id=project_id,
            username=self.username)

    def test_user_access_allowed_ignorepolicy(self):

        def mock_access_allowed(resource):
            return True if resource == 'a_resource' else False

        self.patchobject(ap.AccessPolicy, 'access_allowed',
                         side_effect=mock_access_allowed)

        t = template_format.parse(user_policy_template)
        t['Resources']['CfnUser']['Properties']['Policies'] = [
            'WebServerAccessPolicy', {'an_ignored': 'policy'}]
        stack = utils.parse_stack(t, stack_name=self.stack_name)
        project_id = 'stackproject'

        rsrc = self.create_user(t, stack, 'CfnUser', project_id)
        self.assertEqual('dummy_user', rsrc.resource_id)
        self.assertEqual(self.username, rsrc.FnGetRefId())
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertTrue(rsrc.access_allowed('a_resource'))
        self.assertFalse(rsrc.access_allowed('b_resource'))
        self.mock_create_project.assert_called_once_with(stack.id)
        self.mock_create_user.assert_called_once_with(
            password=None, project_id=project_id,
            username=self.username)

    def test_user_refid_rsrc_id(self):
        t = template_format.parse(user_template)
        stack = utils.parse_stack(t)
        rsrc = stack['CfnUser']
        rsrc.resource_id = 'phy-rsrc-id'
        self.assertEqual('phy-rsrc-id', rsrc.FnGetRefId())

    def test_user_refid_convg_cache_data(self):
        t = template_format.parse(user_template)
        cache_data = {'CfnUser': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        })}
        stack = utils.parse_stack(t, cache_data=cache_data)
        rsrc = stack.defn['CfnUser']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())


class AccessKeyTest(common.HeatTestCase):
    def setUp(self):
        super(AccessKeyTest, self).setUp()
        self.username = utils.PhysName('test_stack', 'CfnUser')
        self.credential_id = 'acredential123'
        self.fc = fake_ks.FakeKeystoneClient(username=self.username,
                                             user_id='dummy_user',
                                             credential_id=self.credential_id)
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    def create_user(self, t, stack, resource_name,
                    project_id='stackproject', user_id='dummy_user',
                    password=None):
        self.patchobject(user.User, 'keystone', return_value=self.fc)
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        stk_defn.update_resource_data(stack.defn, resource_name,
                                      rsrc.node_data())
        return rsrc

    def create_access_key(self, t, stack, resource_name):
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_access_key(self):
        t = template_format.parse(user_accesskey_template)
        stack = utils.parse_stack(t)

        self.create_user(t, stack, 'CfnUser')
        rsrc = self.create_access_key(t, stack, 'HostKeys')
        self.assertEqual(self.fc.access,
                         rsrc.resource_id)

        self.assertEqual(self.fc.secret,
                         rsrc._secret)

        # Ensure the resource data has been stored correctly
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
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

    def test_access_key_get_from_keystone(self):
        self.patchobject(user.AccessKey, 'keystone', return_value=self.fc)
        t = template_format.parse(user_accesskey_template)

        stack = utils.parse_stack(t)

        self.create_user(t, stack, 'CfnUser')
        rsrc = self.create_access_key(t, stack, 'HostKeys')

        # Delete the resource data for secret_key, to test that existing
        # stacks which don't have the resource_data stored will continue
        # working via retrieving the keypair from keystone
        resource_data_object.ResourceData.delete(rsrc, 'credential_id')
        resource_data_object.ResourceData.delete(rsrc, 'secret_key')
        self.assertRaises(exception.NotFound,
                          resource_data_object.ResourceData.get_all,
                          rsrc)

        rsrc._secret = None
        rsrc._data = None
        self.assertEqual(self.fc.secret,
                         rsrc.FnGetAtt('SecretAccessKey'))

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

    def test_access_key_no_user(self):
        t = template_format.parse(user_accesskey_template)
        # Set the resource properties UserName to an unknown user
        t['Resources']['HostKeys']['Properties']['UserName'] = 'NonExistent'
        stack = utils.parse_stack(t)
        stack['CfnUser'].resource_id = self.fc.user_id

        resource_defns = stack.t.resource_definitions(stack)
        rsrc = user.AccessKey('HostKeys',
                              resource_defns['HostKeys'],
                              stack)
        create = scheduler.TaskRunner(rsrc.create)
        self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)


class AccessPolicyTest(common.HeatTestCase):

    def test_accesspolicy_create_ok(self):
        t = template_format.parse(user_policy_template)
        stack = utils.parse_stack(t)

        resource_name = 'WebServerAccessPolicy'
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = ap.AccessPolicy(resource_name,
                               resource_defns[resource_name],
                               stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    def test_accesspolicy_create_ok_empty(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        t['Resources'][resource_name]['Properties']['AllowedResources'] = []
        stack = utils.parse_stack(t)

        resource_defns = stack.t.resource_definitions(stack)
        rsrc = ap.AccessPolicy(resource_name,
                               resource_defns[resource_name],
                               stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    def test_accesspolicy_create_err_notfound(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        t['Resources'][resource_name]['Properties']['AllowedResources'] = [
            'NoExistResource']
        stack = utils.parse_stack(t)

        self.assertRaises(exception.StackValidationFailed, stack.validate)

    def test_accesspolicy_access_allowed(self):
        t = template_format.parse(user_policy_template)
        resource_name = 'WebServerAccessPolicy'
        stack = utils.parse_stack(t)

        resource_defns = stack.t.resource_definitions(stack)
        rsrc = ap.AccessPolicy(resource_name,
                               resource_defns[resource_name],
                               stack)
        self.assertTrue(rsrc.access_allowed('WikiDatabase'))
        self.assertFalse(rsrc.access_allowed('NotWikiDatabase'))
        self.assertFalse(rsrc.access_allowed(None))
