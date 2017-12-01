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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.keystone import group
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

keystone_group_template = {
    'heat_template_version': '2013-05-23',
    'resources': {
        'test_group': {
            'type': 'OS::Keystone::Group',
            'properties': {
                'name': 'test_group_1',
                'description': 'Test group',
                'domain': 'default'
            }
        }
    }
}


class KeystoneGroupTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneGroupTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone',
            template.Template(keystone_group_template)
        )

        self.test_group = self.stack['test_group']

        # Mock client
        self.keystoneclient = mock.Mock()
        self.patchobject(resource.Resource, 'client',
                         return_value=fake_ks.FakeKeystoneClient(
                             client=self.keystoneclient))
        self.groups = self.keystoneclient.groups
        self.role_assignments = self.keystoneclient.role_assignments

        # Mock client plugin
        def _side_effect(value):
            return value

        self.keystone_client_plugin = mock.MagicMock()
        (self.keystone_client_plugin.get_domain_id.
         side_effect) = _side_effect
        self.test_group.client_plugin = mock.MagicMock()
        (self.test_group.client_plugin.
         return_value) = self.keystone_client_plugin

    def _get_mock_group(self):
        value = mock.MagicMock()
        group_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        value.id = group_id

        return value

    def test_properties_title(self):
        property_title_map = {
            group.KeystoneGroup.NAME: 'name',
            group.KeystoneGroup.DESCRIPTION: 'description',
            group.KeystoneGroup.DOMAIN: 'domain'
        }

        for actual_title, expected_title in property_title_map.items():
            self.assertEqual(
                expected_title,
                actual_title,
                'KeystoneGroup PROPERTIES(%s) title modified.' %
                actual_title)

    def test_property_name_validate_schema(self):
        schema = group.KeystoneGroup.properties_schema[
            group.KeystoneGroup.NAME]
        self.assertEqual(
            True,
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            group.KeystoneGroup.NAME)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         group.KeystoneGroup.NAME)

        self.assertEqual('Name of keystone group.',
                         schema.description,
                         'description for property %s is modified' %
                         group.KeystoneGroup.NAME)

    def test_property_description_validate_schema(self):
        schema = group.KeystoneGroup.properties_schema[
            group.KeystoneGroup.DESCRIPTION]
        self.assertEqual(
            True,
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            group.KeystoneGroup.DESCRIPTION)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         group.KeystoneGroup.DESCRIPTION)

        self.assertEqual('Description of keystone group.',
                         schema.description,
                         'description for property %s is modified' %
                         group.KeystoneGroup.DESCRIPTION)

        self.assertEqual(
            '',
            schema.default,
            'default for property %s is modified' %
            group.KeystoneGroup.DESCRIPTION)

    def test_property_domain_validate_schema(self):
        schema = group.KeystoneGroup.properties_schema[
            group.KeystoneGroup.DOMAIN]
        self.assertEqual(
            True,
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            group.KeystoneGroup.DOMAIN)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         group.KeystoneGroup.DOMAIN)

        self.assertEqual('Name or id of keystone domain.',
                         schema.description,
                         'description for property %s is modified' %
                         group.KeystoneGroup.DOMAIN)

        self.assertEqual([constraints.CustomConstraint('keystone.domain')],
                         schema.constraints,
                         'constrains for property %s is modified' %
                         group.KeystoneGroup.DOMAIN)

        self.assertEqual(
            'default',
            schema.default,
            'default for property %s is modified' %
            group.KeystoneGroup.DOMAIN)

    def _get_property_schema_value_default(self, name):
        schema = group.KeystoneGroup.properties_schema[name]
        return schema.default

    def test_group_handle_create(self):
        mock_group = self._get_mock_group()
        self.groups.create.return_value = mock_group

        # validate the properties
        self.assertEqual(
            'test_group_1',
            self.test_group.properties.get(group.KeystoneGroup.NAME))
        self.assertEqual(
            'Test group',
            self.test_group.properties.get(group.KeystoneGroup.DESCRIPTION))
        self.assertEqual(
            'default',
            self.test_group.properties.get(group.KeystoneGroup.DOMAIN))

        self.test_group.handle_create()

        # validate group creation
        self.groups.create.assert_called_once_with(
            name='test_group_1',
            description='Test group',
            domain='default')

        # validate physical resource id
        self.assertEqual(mock_group.id, self.test_group.resource_id)

    def test_group_handle_create_default(self):
        values = {
            group.KeystoneGroup.NAME: None,
            group.KeystoneGroup.DESCRIPTION:
            (self._get_property_schema_value_default(
             group.KeystoneGroup.DESCRIPTION)),
            group.KeystoneGroup.DOMAIN:
            (self._get_property_schema_value_default(
             group.KeystoneGroup.DOMAIN)),
            group.KeystoneGroup.ROLES: None
        }

        def _side_effect(key):
            return values[key]

        mock_group = self._get_mock_group()
        self.groups.create.return_value = mock_group
        self.test_group.properties = mock.MagicMock()
        self.test_group.properties.get.side_effect = _side_effect
        self.test_group.properties.__getitem__.side_effect = _side_effect

        self.test_group.physical_resource_name = mock.MagicMock()
        self.test_group.physical_resource_name.return_value = 'foo'

        # validate the properties
        self.assertEqual(
            None,
            self.test_group.properties.get(group.KeystoneGroup.NAME))
        self.assertEqual(
            '',
            self.test_group.properties.get(group.KeystoneGroup.DESCRIPTION))
        self.assertEqual(
            'default',
            self.test_group.properties.get(group.KeystoneGroup.DOMAIN))

        self.test_group.handle_create()

        # validate group creation
        self.groups.create.assert_called_once_with(
            name='foo',
            description='',
            domain='default')

    def test_group_handle_update(self):
        self.test_group.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {group.KeystoneGroup.NAME: 'test_group_1_updated',
                     group.KeystoneGroup.DESCRIPTION: 'Test Group updated',
                     group.KeystoneGroup.DOMAIN: 'test_domain'}

        self.test_group.handle_update(json_snippet=None,
                                      tmpl_diff=None,
                                      prop_diff=prop_diff)

        self.groups.update.assert_called_once_with(
            group=self.test_group.resource_id,
            name=prop_diff[group.KeystoneGroup.NAME],
            description=prop_diff[group.KeystoneGroup.DESCRIPTION],
            domain_id='test_domain'
        )

        # validate the role assignment isn't updated
        self.roles = self.keystoneclient.roles
        self.assertEqual(0, self.roles.revoke.call_count)
        self.assertEqual(0, self.roles.grant.call_count)

    def test_group_handle_update_default(self):
        self.test_group.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {group.KeystoneGroup.DESCRIPTION: 'Test Project updated'}

        self.test_group.handle_update(json_snippet=None,
                                      tmpl_diff=None,
                                      prop_diff=prop_diff)

        # validate default name to physical resource name and
        # domain is set from stored properties used during creation.
        self.groups.update.assert_called_once_with(
            group=self.test_group.resource_id,
            name=None,
            description=prop_diff[group.KeystoneGroup.DESCRIPTION],
            domain_id='default'
        )

    def test_group_handle_delete(self):
        self.test_group.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.groups.delete.return_value = None

        self.test_group.handle_delete()
        self.groups.delete.assert_called_once_with(
            self.test_group.resource_id
        )

    def test_group_handle_delete_resource_id_is_none(self):
        self.resource_id = None
        self.assertIsNone(self.test_group.handle_delete())

    def test_group_handle_delete_not_found(self):
        exc = self.keystoneclient.NotFound
        self.groups.delete.side_effect = exc

        self.assertIsNone(self.test_group.handle_delete())

    def test_show_resource(self):
        group = mock.Mock()
        group.to_dict.return_value = {'attr': 'val'}
        self.groups.get.return_value = group
        res = self.test_group._show_resource()
        self.assertEqual({'attr': 'val'}, res)

    def test_get_live_state(self):
        group = mock.Mock()
        group.to_dict.return_value = {
            'id': '48ee1f94b77047e592de55a4934c198c',
            'domain_id': 'default',
            'name': 'fake',
            'links': {'self': 'some_link'},
            'description': ''}
        roles = mock.MagicMock()
        roles.to_dict.return_value = {
            'scope': {
                'project': {'id': 'fc0fe982401643368ff2eb11d9ca70f1'}},
            'role': {'id': '3b8b253648f44256a457a5073b78021d'},
            'group': {'id': '4147558a763046cfb68fb870d58ef4cf'}}
        self.role_assignments.list.return_value = [roles]
        self.groups.get.return_value = group
        self.test_group.resource_id = '1234'

        reality = self.test_group.get_live_state(self.test_group.properties)
        expected = {
            'domain': 'default',
            'name': 'fake',
            'description': '',
            'roles': [{
                'role': '3b8b253648f44256a457a5073b78021d',
                'project': 'fc0fe982401643368ff2eb11d9ca70f1',
                'domain': None
            }]
        }
        self.assertEqual(set(expected.keys()), set(reality.keys()))
        for key in expected:
            self.assertEqual(expected[key], reality[key])
