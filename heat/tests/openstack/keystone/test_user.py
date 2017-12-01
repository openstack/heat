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

from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine import resource
from heat.engine.resources.openstack.keystone import user
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

keystone_user_template = {
    'heat_template_version': '2013-05-23',
    'resources': {
        'test_user': {
            'type': 'OS::Keystone::User',
            'properties': {
                'name': 'test_user_1',
                'description': 'Test user',
                'domain': 'default',
                'email': 'abc@xyz.com',
                'password': 'password',
                'default_project': 'project_1',
                'groups': ['group1', 'group2'],
                'enabled': True

            }
        }
    }
}


class KeystoneUserTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneUserTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone',
            template.Template(keystone_user_template)
        )

        self.test_user = self.stack['test_user']

        # Mock client
        self.keystoneclient = mock.Mock()
        self.patchobject(resource.Resource, 'client',
                         return_value=fake_ks.FakeKeystoneClient(
                             client=self.keystoneclient))
        self.users = self.keystoneclient.users

        # Mock client plugin
        def _side_effect(value):
            return value

        self.keystone_client_plugin = mock.MagicMock()
        (self.keystone_client_plugin.get_domain_id.
         side_effect) = _side_effect
        (self.keystone_client_plugin.get_group_id.
         side_effect) = _side_effect
        (self.keystone_client_plugin.get_project_id.
         side_effect) = _side_effect
        self.test_user.client_plugin = mock.MagicMock()
        (self.test_user.client_plugin.
         return_value) = self.keystone_client_plugin

    def _get_mock_user(self):
        value = mock.MagicMock()
        user_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        value.id = user_id
        value.name = 'test_user_1'
        value.default_project_id = 'project_1'
        value.domain_id = 'default'
        value.enabled = True
        value.password_expires_at = '2016-12-10T17:28:49.000000'
        return value

    def test_user_handle_create(self):
        mock_user = self._get_mock_user()
        self.users.create.return_value = mock_user
        self.users.get.return_value = mock_user
        self.users.add_to_group = mock.MagicMock()

        # validate the properties
        self.assertEqual(
            'test_user_1',
            self.test_user.properties.get(user.KeystoneUser.NAME))
        self.assertEqual(
            'Test user',
            self.test_user.properties.get(user.KeystoneUser.DESCRIPTION))
        self.assertEqual(
            'default',
            self.test_user.properties.get(user.KeystoneUser.DOMAIN))
        self.assertEqual(
            True,
            self.test_user.properties.get(user.KeystoneUser.ENABLED))
        self.assertEqual(
            'abc@xyz.com',
            self.test_user.properties.get(user.KeystoneUser.EMAIL))
        self.assertEqual(
            'password',
            self.test_user.properties.get(user.KeystoneUser.PASSWORD))
        self.assertEqual(
            'project_1',
            self.test_user.properties.get(user.KeystoneUser.DEFAULT_PROJECT))
        self.assertEqual(
            ['group1', 'group2'],
            self.test_user.properties.get(user.KeystoneUser.GROUPS))

        self.test_user.handle_create()

        # validate user creation
        self.users.create.assert_called_once_with(
            name='test_user_1',
            description='Test user',
            domain='default',
            enabled=True,
            email='abc@xyz.com',
            password='password',
            default_project='project_1')

        # validate physical resource id
        self.assertEqual(mock_user.id, self.test_user.resource_id)

        # validate groups
        for group in ['group1', 'group2']:
            self.users.add_to_group.assert_any_call(
                self.test_user.resource_id,
                group)

    def _get_property_schema_value_default(self, name):
        schema = user.KeystoneUser.properties_schema[name]
        return schema.default

    def test_user_handle_create_default(self):
        values = {
            user.KeystoneUser.NAME: None,
            user.KeystoneUser.DESCRIPTION:
            (self._get_property_schema_value_default(
             user.KeystoneUser.DESCRIPTION)),
            user.KeystoneUser.DOMAIN:
            (self._get_property_schema_value_default(
             user.KeystoneUser.DOMAIN)),
            user.KeystoneUser.ENABLED:
            (self._get_property_schema_value_default(
             user.KeystoneUser.ENABLED)),
            user.KeystoneUser.ROLES: None,
            user.KeystoneUser.GROUPS: None,
            user.KeystoneUser.PASSWORD: 'password',
            user.KeystoneUser.EMAIL: 'abc@xyz.com',
            user.KeystoneUser.DEFAULT_PROJECT: 'default_project'
        }

        def _side_effect(key):
            return values[key]

        mock_user = self._get_mock_user()
        self.users.create.return_value = mock_user
        self.test_user.properties = mock.MagicMock()
        self.test_user.properties.get.side_effect = _side_effect
        self.test_user.properties.__getitem__.side_effect = _side_effect

        self.test_user.physical_resource_name = mock.MagicMock()
        self.test_user.physical_resource_name.return_value = 'foo'

        self.test_user.handle_create()

        # validate user creation
        self.users.create.assert_called_once_with(
            name='foo',
            description='',
            domain='default',
            enabled=True,
            email='abc@xyz.com',
            password='password',
            default_project='default_project')

    def test_user_handle_update(self):
        self.test_user.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        # add new group group3 and remove group group2
        prop_diff = {user.KeystoneUser.NAME: 'test_user_1_updated',
                     user.KeystoneUser.DESCRIPTION: 'Test User updated',
                     user.KeystoneUser.ENABLED: False,
                     user.KeystoneUser.EMAIL: 'xyz@abc.com',
                     user.KeystoneUser.PASSWORD: 'passWORD',
                     user.KeystoneUser.DEFAULT_PROJECT: 'project_2',
                     user.KeystoneUser.GROUPS: ['group1', 'group3']}

        self.test_user.handle_update(json_snippet=None,
                                     tmpl_diff=None,
                                     prop_diff=prop_diff)

        # validate user update
        self.users.update.assert_called_once_with(
            user=self.test_user.resource_id,
            domain=self.test_user.properties[user.KeystoneUser.DOMAIN],
            name=prop_diff[user.KeystoneUser.NAME],
            description=prop_diff[user.KeystoneUser.DESCRIPTION],
            email=prop_diff[user.KeystoneUser.EMAIL],
            password=prop_diff[user.KeystoneUser.PASSWORD],
            default_project=prop_diff[user.KeystoneUser.DEFAULT_PROJECT],
            enabled=prop_diff[user.KeystoneUser.ENABLED]
        )

        # validate the new groups added
        for group in ['group3']:
            self.users.add_to_group.assert_any_call(
                self.test_user.resource_id,
                group)

        # validate the removed groups are deleted
        for group in ['group2']:
            self.users.remove_from_group.assert_any_call(
                self.test_user.resource_id,
                group)

        # validate the role assignment isn't updated
        self.roles = self.keystoneclient.roles
        self.roles.revoke.assert_not_called()
        self.roles.grant.assert_not_called()

    def test_user_handle_update_password_only(self):
        self.test_user.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        # Update the password only
        prop_diff = {user.KeystoneUser.PASSWORD: 'passWORD'}

        self.test_user.handle_update(json_snippet=None,
                                     tmpl_diff=None,
                                     prop_diff=prop_diff)

        # Validate user update
        self.users.update.assert_called_once_with(
            user=self.test_user.resource_id,
            domain=self.test_user.properties[user.KeystoneUser.DOMAIN],
            password=prop_diff[user.KeystoneUser.PASSWORD]
        )

        # Validate that there is no change in groups
        self.users.add_to_group.assert_not_called()
        self.users.remove_from_group.assert_not_called()

    def test_user_handle_delete(self):
        self.test_user.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.users.delete.return_value = None

        self.assertIsNone(self.test_user.handle_delete())
        self.users.delete.assert_called_once_with(
            self.test_user.resource_id
        )

        # validate the groups are deleted
        for group in ['group1', 'group2']:
            self.users.remove_from_group.assert_any_call(
                self.test_user.resource_id,
                group)

    def test_user_handle_delete_resource_id_is_none(self):
        self.resource_id = None
        self.assertIsNone(self.test_user.handle_delete())

    def test_user_handle_delete_not_found(self):
        exc = self.keystoneclient.NotFound
        self.users.delete.side_effect = exc

        self.assertIsNone(self.test_user.handle_delete())

    def test_show_resource(self):
        user = mock.Mock()
        user.to_dict.return_value = {'attr': 'val'}
        self.users.get.return_value = user
        res = self.test_user._show_resource()
        self.assertEqual({'attr': 'val'}, res)

    def test_get_live_state(self):
        user = mock.MagicMock()
        user.to_dict.return_value = {
            'description': '',
            'enabled': True,
            'domain_id': 'default',
            'email': 'fake@312.com',
            'default_project_id': '859aee961e30408e813853e1cffad089',
            'id': '4060e773e26842a88b7490528d78de4f',
            'name': 'user1-user-275g3vdmwuo5'}
        self.users.get.return_value = user
        role = mock.MagicMock()
        role.to_dict.return_value = {
            'scope': {'domain': {'id': '1234'}}, 'role': {'id': '4321'}
        }
        self.keystoneclient.role_assignments.list.return_value = [role]
        group = mock.MagicMock()
        group.id = '39393'
        self.keystoneclient.groups.list.return_value = [group]
        self.test_user.resource_id = '1111'

        reality = self.test_user.get_live_state(self.test_user.properties)
        expected = {
            'description': '',
            'enabled': True,
            'domain': 'default',
            'email': 'fake@312.com',
            'default_project': '859aee961e30408e813853e1cffad089',
            'name': 'user1-user-275g3vdmwuo5',
            'groups': ['39393'],
            'roles': [{'role': '4321', 'domain': '1234', 'project': None}]
        }
        self.assertEqual(set(expected.keys()), set(reality.keys()))
        for key in expected:
            self.assertEqual(expected[key], reality[key])

    def test_resolve_attributes(self):
        mock_user = self._get_mock_user()
        self.test_user.resource_id = mock_user['id']
        self.users.get.return_value = mock_user
        self.assertEqual(
            mock_user.name,
            self.test_user._resolve_attribute('name'))
        self.assertEqual(
            mock_user.default_project_id,
            self.test_user._resolve_attribute('default_project_id'))
        self.assertEqual(
            mock_user.domain_id,
            self.test_user._resolve_attribute('domain_id'))
        self.assertEqual(
            mock_user.enabled,
            self.test_user._resolve_attribute('enabled'))
        self.assertEqual(
            mock_user.password_expires_at,
            self.test_user._resolve_attribute('password_expires_at'))
