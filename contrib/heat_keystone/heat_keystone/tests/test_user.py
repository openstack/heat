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

from heat.engine import resource
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

from ..resources.user import KeystoneUser  # noqa
from ..resources.user import resource_mapping  # noqa

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

RESOURCE_TYPE = 'OS::Keystone::User'


class KeystoneUserTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneUserTest, self).setUp()

        self.ctx = utils.dummy_context()

        # For unit testing purpose. Register resource provider explicitly.
        resource._register_class(RESOURCE_TYPE, KeystoneUser)

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone',
            template.Template(keystone_user_template)
        )

        self.test_user = self.stack['test_user']

        # Mock client
        self.keystoneclient = mock.MagicMock()
        self.test_user.keystone = mock.MagicMock()
        self.test_user.keystone.return_value = self.keystoneclient
        self.users = self.keystoneclient.client.users

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

        return value

    def test_resource_mapping(self):
        mapping = resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(KeystoneUser, mapping[RESOURCE_TYPE])
        self.assertIsInstance(self.test_user, KeystoneUser)

    def test_user_handle_create(self):
        mock_user = self._get_mock_user()
        self.users.create.return_value = mock_user
        self.users.add_to_group = mock.MagicMock()

        # validate the properties
        self.assertEqual(
            'test_user_1',
            self.test_user.properties.get(KeystoneUser.NAME))
        self.assertEqual(
            'Test user',
            self.test_user.properties.get(KeystoneUser.DESCRIPTION))
        self.assertEqual(
            'default',
            self.test_user.properties.get(KeystoneUser.DOMAIN))
        self.assertEqual(
            True,
            self.test_user.properties.get(KeystoneUser.ENABLED))
        self.assertEqual(
            'abc@xyz.com',
            self.test_user.properties.get(KeystoneUser.EMAIL))
        self.assertEqual(
            'password',
            self.test_user.properties.get(KeystoneUser.PASSWORD))
        self.assertEqual(
            'project_1',
            self.test_user.properties.get(KeystoneUser.DEFAULT_PROJECT))
        self.assertEqual(
            ['group1', 'group2'],
            self.test_user.properties.get(KeystoneUser.GROUPS))

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
        schema = KeystoneUser.properties_schema[name]
        return schema.default

    def test_user_handle_create_default(self):
        values = {
            KeystoneUser.NAME: None,
            KeystoneUser.DESCRIPTION:
            (self._get_property_schema_value_default(
             KeystoneUser.DESCRIPTION)),
            KeystoneUser.DOMAIN:
            (self._get_property_schema_value_default(
             KeystoneUser.DOMAIN)),
            KeystoneUser.ENABLED:
            (self._get_property_schema_value_default(
             KeystoneUser.ENABLED)),
            KeystoneUser.ROLES: None,
            KeystoneUser.GROUPS: None,
            KeystoneUser.PASSWORD: 'password',
            KeystoneUser.EMAIL: 'abc@xyz.com',
            KeystoneUser.DEFAULT_PROJECT: 'default_project'
        }

        def _side_effect(key):
            return values[key]

        mock_user = self._get_mock_user()
        self.users.create.return_value = mock_user
        self.test_user.properties = mock.MagicMock()
        self.test_user.properties.get.side_effect = _side_effect

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

        # Make the existing groups as group1 and group2
        self.test_user._stored_properties_data = {
            'groups': ['group1', 'group2'],
            'domain': 'default'
        }

        # add new group group3 and remove group group2
        prop_diff = {KeystoneUser.NAME: 'test_user_1_updated',
                     KeystoneUser.DESCRIPTION: 'Test User updated',
                     KeystoneUser.ENABLED: False,
                     KeystoneUser.EMAIL: 'xyz@abc.com',
                     KeystoneUser.PASSWORD: 'passWORD',
                     KeystoneUser.DEFAULT_PROJECT: 'project_2',
                     KeystoneUser.GROUPS: ['group1', 'group3']}

        self.test_user.handle_update(json_snippet=None,
                                     tmpl_diff=None,
                                     prop_diff=prop_diff)

        # validate user update
        self.users.update.assert_called_once_with(
            user=self.test_user.resource_id,
            domain=self.test_user._stored_properties_data[KeystoneUser.DOMAIN],
            name=prop_diff[KeystoneUser.NAME],
            description=prop_diff[KeystoneUser.DESCRIPTION],
            email=prop_diff[KeystoneUser.EMAIL],
            password=prop_diff[KeystoneUser.PASSWORD],
            default_project=prop_diff[KeystoneUser.DEFAULT_PROJECT],
            enabled=prop_diff[KeystoneUser.ENABLED]
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

    def test_user_handle_delete(self):
        self.test_user.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.test_user._stored_properties_data = {
            'groups': ['group1', 'group2'],
            'roles': None
        }
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
        self.test_user._stored_properties_data = dict(groups=None, roles=None)
        exc = self.keystoneclient.NotFound
        self.users.delete.side_effect = exc

        self.assertIsNone(self.test_user.handle_delete())
