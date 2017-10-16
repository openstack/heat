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

import copy
import mock

from heat.common import exception
from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.keystone import role_assignments
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import generic_resource
from heat.tests import utils

RESOURCE_TYPE = 'OS::Keystone::DummyRoleAssignment'

keystone_role_assignment_template = {
    'heat_template_version': '2015-10-15',
    'resources': {
        'test_role_assignment': {
            'type': RESOURCE_TYPE,
            'properties': {
                'roles': [
                    {
                        'role': 'role_1',
                        'project': 'project_1',
                    },
                    {
                        'role': 'role_1',
                        'domain': 'domain_1'
                    }
                ]
            }
        }
    }
}

MixinClass = role_assignments.KeystoneRoleAssignmentMixin


class DummyRoleAssignment(generic_resource.GenericResource, MixinClass):
    properties_schema = {}
    properties_schema.update(MixinClass.mixin_properties_schema)

    def validate(self):
        super(DummyRoleAssignment, self).validate()
        self.validate_assignment_properties()


class KeystoneRoleAssignmentMixinTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneRoleAssignmentMixinTest, self).setUp()

        self.ctx = utils.dummy_context()

        # For unit testing purpose. Register resource provider explicitly.
        resource._register_class(RESOURCE_TYPE, DummyRoleAssignment)

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone',
            template.Template(keystone_role_assignment_template)
        )
        self.test_role_assignment = self.stack['test_role_assignment']

        # Mock client
        self.keystoneclient = mock.MagicMock()
        self.test_role_assignment.client = mock.MagicMock()
        self.test_role_assignment.client.return_value = self.keystoneclient
        self.roles = self.keystoneclient.roles

        # Mock client plugin
        def _side_effect(value):
            return value

        self.keystone_client_plugin = mock.MagicMock()
        (self.keystone_client_plugin.get_domain_id.
         side_effect) = _side_effect
        (self.keystone_client_plugin.get_role_id.
         side_effect) = _side_effect
        (self.keystone_client_plugin.get_project_id.
         side_effect) = _side_effect
        self.test_role_assignment.client_plugin = mock.MagicMock()
        (self.test_role_assignment.client_plugin.
         return_value) = self.keystone_client_plugin

        self.parse_assgmnts = self.test_role_assignment.parse_list_assignments
        self.test_role_assignment.parse_list_assignments = mock.MagicMock()
        self.test_role_assignment.parse_list_assignments.return_value = [
            {'role': 'role_1',
             'domain': 'domain_1',
             'project': None},
            {'role': 'role_1',
             'project': 'project_1',
             'domain': None}]

    def test_properties_title(self):
        property_title_map = {MixinClass.ROLES: 'roles'}

        for actual_title, expected_title in property_title_map.items():
            self.assertEqual(
                expected_title,
                actual_title,
                'KeystoneRoleAssignmentMixin PROPERTIES(%s) title modified.' %
                actual_title)

    def test_property_roles_validate_schema(self):
        schema = MixinClass.mixin_properties_schema[MixinClass.ROLES]
        self.assertEqual(
            True,
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            MixinClass.ROLES)

        self.assertEqual(properties.Schema.LIST,
                         schema.type,
                         'type for property %s is modified' %
                         MixinClass.ROLES)

        self.assertEqual('List of role assignments.',
                         schema.description,
                         'description for property %s is modified' %
                         MixinClass.ROLES)

    def test_role_assignment_create_user(self):
        expected = [
            {
                'role': 'role_1',
                'project': 'project_1',
                'domain': None
            }, {
                'role': 'role_1',
                'project': None,
                'domain': 'domain_1'
            }
        ]
        # validate the properties
        self.assertEqual(
            expected,
            self.test_role_assignment.properties.get(MixinClass.ROLES))

        self.test_role_assignment.create_assignment(user_id='user_1')

        # validate role assignment creation
        # role-user-domain
        self.roles.grant.assert_any_call(
            role='role_1',
            user='user_1',
            domain='domain_1')

        # role-user-project
        self.roles.grant.assert_any_call(
            role='role_1',
            user='user_1',
            project='project_1')

    def test_role_assignment_create_group(self):
        expected = [
            {
                'role': 'role_1',
                'project': 'project_1',
                'domain': None
            }, {
                'role': 'role_1',
                'project': None,
                'domain': 'domain_1'
            }
        ]
        # validate the properties
        self.assertEqual(
            expected,
            self.test_role_assignment.properties.get(MixinClass.ROLES))

        self.test_role_assignment.create_assignment(group_id='group_1')

        # validate role assignment creation
        # role-group-domain
        self.roles.grant.assert_any_call(
            role='role_1',
            group='group_1',
            domain='domain_1')

        # role-group-project
        self.roles.grant.assert_any_call(
            role='role_1',
            group='group_1',
            project='project_1')

    def test_role_assignment_update_user(self):
        prop_diff = {
            MixinClass.ROLES: [
                {
                    'role': 'role_2',
                    'project': 'project_1'
                },
                {
                    'role': 'role_2',
                    'domain': 'domain_1'
                }
            ]
        }

        self.test_role_assignment.update_assignment(
            user_id='user_1',
            prop_diff=prop_diff)

        # Add role2-project1-domain1
        # role-user-domain
        self.roles.grant.assert_any_call(
            role='role_2',
            user='user_1',
            domain='domain_1')

        # role-user-project
        self.roles.grant.assert_any_call(
            role='role_2',
            user='user_1',
            project='project_1')

        # Remove role1-project1-domain1
        # role-user-domain
        self.roles.revoke.assert_any_call(
            role='role_1',
            user='user_1',
            domain='domain_1')

        # role-user-project
        self.roles.revoke.assert_any_call(
            role='role_1',
            user='user_1',
            project='project_1')

    def test_role_assignment_update_group(self):
        prop_diff = {
            MixinClass.ROLES: [
                {
                    'role': 'role_2',
                    'project': 'project_1'
                },
                {
                    'role': 'role_2',
                    'domain': 'domain_1'
                }
            ]
        }

        self.test_role_assignment.update_assignment(
            group_id='group_1',
            prop_diff=prop_diff)

        # Add role2-project1-domain1
        # role-group-domain
        self.roles.grant.assert_any_call(
            role='role_2',
            group='group_1',
            domain='domain_1')

        # role-group-project
        self.roles.grant.assert_any_call(
            role='role_2',
            group='group_1',
            project='project_1')

        # Remove role1-project1-domain1
        # role-group-domain
        self.roles.revoke.assert_any_call(
            role='role_1',
            group='group_1',
            domain='domain_1')

        # role-group-project
        self.roles.revoke.assert_any_call(
            role='role_1',
            group='group_1',
            project='project_1')

    def test_role_assignment_update_roles_no_change(self):
        prop_diff = {}
        self.test_role_assignment.update_assignment(
            group_id='group_1',
            prop_diff=prop_diff)
        self.assertEqual(0, self.roles.grant.call_count)
        self.assertEqual(0, self.roles.revoke.call_count)

        self.test_role_assignment.update_assignment(
            user_id='user_1',
            prop_diff=prop_diff)
        self.assertEqual(0, self.roles.grant.call_count)
        self.assertEqual(0, self.roles.revoke.call_count)

    def test_role_assignment_delete_user(self):
        self.assertIsNone(self.test_role_assignment.delete_assignment(
            user_id='user_1'))

        # Remove role1-project1-domain1
        # role-user-domain
        self.roles.revoke.assert_any_call(
            role='role_1',
            user='user_1',
            domain='domain_1')

        # role-user-project
        self.roles.revoke.assert_any_call(
            role='role_1',
            user='user_1',
            project='project_1')

    def test_role_assignment_delete_group(self):
        self.assertIsNone(self.test_role_assignment.delete_assignment(
            group_id='group_1'
        ))

        # Remove role1-project1-domain1
        # role-group-domain
        self.roles.revoke.assert_any_call(
            role='role_1',
            group='group_1',
            domain='domain_1')

        # role-group-project
        self.roles.revoke.assert_any_call(
            role='role_1',
            group='group_1',
            project='project_1')

    def test_role_assignment_delete_removed(self):
        self.test_role_assignment.parse_list_assignments.return_value = [
            {'role': 'role_1',
             'domain': 'domain_1',
             'project': None}]

        self.assertIsNone(self.test_role_assignment.delete_assignment(
            user_id='user_1'))

        expected = [
            ({'role': 'role_1', 'user': 'user_1', 'domain': 'domain_1'},)
        ]

        self.assertItemsEqual(expected, self.roles.revoke.call_args_list)

    def test_validate_1(self):
        self.test_role_assignment.properties = mock.MagicMock()

        # both project and domain are none
        self.test_role_assignment.properties.get.return_value = [
            dict(role='role1')]
        self.assertRaises(exception.StackValidationFailed,
                          self.test_role_assignment.validate)

    def test_validate_2(self):
        self.test_role_assignment.properties = mock.MagicMock()

        # both project and domain are not none
        self.test_role_assignment.properties.get.return_value = [
            dict(role='role1',
                 project='project1',
                 domain='domain1')
        ]
        self.assertRaises(exception.ResourcePropertyConflict,
                          self.test_role_assignment.validate)

    def test_empty_parse_list_assignments(self):
        self.test_role_assignment.parse_list_assignments = self.parse_assgmnts
        self.assertEqual([],
                         self.test_role_assignment.parse_list_assignments())

    def test_user_parse_list_assignments(self):
        self._test_parse_list_assignments('user')

    def test_group_parse_list_assignments(self):
        self._test_parse_list_assignments('group')

    def _test_parse_list_assignments(self, entity=None):
        self.test_role_assignment.parse_list_assignments = self.parse_assgmnts
        dict_obj = mock.MagicMock()
        dict_obj.to_dict.side_effect = [{'scope': {
            'project': {'id': 'fc0fe982401643368ff2eb11d9ca70f1'}},
            'role': {'id': '3b8b253648f44256a457a5073b78021d'},
            entity: {'id': '4147558a763046cfb68fb870d58ef4cf'}},
            {'role': {'id': '3b8b253648f44258021d6a457a5073b7'},
             entity: {'id': '4147558a763046cfb68fb870d58ef4cf'}}]
        self.keystoneclient.role_assignments.list.return_value = [dict_obj,
                                                                  dict_obj]

        kwargs = {'%s_id' % entity: '4147558a763046cfb68fb870d58ef4cf'}
        list_assignments = self.test_role_assignment.parse_list_assignments(
            **kwargs)
        expected = [
            {'role': '3b8b253648f44256a457a5073b78021d',
             'project': 'fc0fe982401643368ff2eb11d9ca70f1',
             'domain': None},
            {'role': '3b8b253648f44258021d6a457a5073b7',
             'project': None,
             'domain': None},
        ]
        self.assertEqual(expected, list_assignments)


class KeystoneUserRoleAssignmentTest(common.HeatTestCase):

    role_assignment_template = copy.deepcopy(keystone_role_assignment_template)
    role = role_assignment_template['resources']['test_role_assignment']
    role['properties']['user'] = 'user_1'
    role['type'] = 'OS::Keystone::UserRoleAssignment'

    def setUp(self):
        super(KeystoneUserRoleAssignmentTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone_user_role_add',
            template.Template(self.role_assignment_template)
        )
        self.test_role_assignment = self.stack['test_role_assignment']

        # Mock client
        self.keystoneclient = mock.Mock()
        self.patchobject(resource.Resource, 'client',
                         return_value=fake_ks.FakeKeystoneClient(
                             client=self.keystoneclient))
        self.roles = self.keystoneclient.roles

        # Mock client plugin
        def _side_effect(value):
            return value

        self.keystone_client_plugin = mock.MagicMock()
        self.keystone_client_plugin.get_user_id.side_effect = _side_effect
        self.keystone_client_plugin.get_domain_id.side_effect = _side_effect
        self.keystone_client_plugin.get_role_id.side_effect = _side_effect
        self.keystone_client_plugin.get_project_id.side_effect = _side_effect
        self.test_role_assignment.client_plugin = mock.MagicMock()
        (self.test_role_assignment.client_plugin.
         return_value) = self.keystone_client_plugin

        self.test_role_assignment.parse_list_assignments = mock.MagicMock()
        self.test_role_assignment.parse_list_assignments.return_value = [
            {'role': 'role_1',
             'domain': 'domain_1',
             'project': None},
            {'role': 'role_1',
             'project': 'project_1',
             'domain': None}]

    def test_user_role_assignment_handle_create(self):
        self.test_role_assignment.handle_create()

        # role-user-domain created
        self.roles.grant.assert_any_call(
            role='role_1',
            user='user_1',
            domain='domain_1')

        # role-user-project created
        self.roles.grant.assert_any_call(
            role='role_1',
            user='user_1',
            project='project_1')

    def test_user_role_assignment_handle_update(self):
        prop_diff = {
            MixinClass.ROLES: [
                {
                    'role': 'role_2',
                    'project': 'project_1'
                },
                {
                    'role': 'role_2',
                    'domain': 'domain_1'
                }
            ]
        }

        self.test_role_assignment.handle_update(json_snippet=None,
                                                tmpl_diff=None,
                                                prop_diff=prop_diff)

        # Add role2-project1-domain1
        # role-user-domain
        self.roles.grant.assert_any_call(
            role='role_2',
            user='user_1',
            domain='domain_1')

        # role-user-project
        self.roles.grant.assert_any_call(
            role='role_2',
            user='user_1',
            project='project_1')

        # Remove role1-project1-domain1
        # role-user-domain
        self.roles.revoke.assert_any_call(
            role='role_1',
            user='user_1',
            domain='domain_1')

        # role-user-project
        self.roles.revoke.assert_any_call(
            role='role_1',
            user='user_1',
            project='project_1')

    def test_user_role_assignment_handle_delete(self):
        self.assertIsNone(self.test_role_assignment.handle_delete())

        # Remove role1-project1-domain1
        # role-user-domain
        self.roles.revoke.assert_any_call(
            role='role_1',
            user='user_1',
            domain='domain_1')

        # role-user-project
        self.roles.revoke.assert_any_call(
            role='role_1',
            user='user_1',
            project='project_1')

    def test_user_role_assignment_delete_user_not_found(self):
        self.keystone_client_plugin.get_user_id.side_effect = [
            exception.EntityNotFound]
        self.assertIsNone(self.test_role_assignment.handle_delete())
        self.roles.revoke.assert_not_called()


class KeystoneGroupRoleAssignmentTest(common.HeatTestCase):

    role_assignment_template = copy.deepcopy(keystone_role_assignment_template)
    role = role_assignment_template['resources']['test_role_assignment']
    role['properties']['group'] = 'group_1'
    role['type'] = 'OS::Keystone::GroupRoleAssignment'

    def setUp(self):
        super(KeystoneGroupRoleAssignmentTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone_group_role_add',
            template.Template(self.role_assignment_template)
        )
        self.test_role_assignment = self.stack['test_role_assignment']

        # Mock client
        self.keystoneclient = mock.Mock()
        self.patchobject(resource.Resource, 'client',
                         return_value=fake_ks.FakeKeystoneClient(
                             client=self.keystoneclient))
        self.roles = self.keystoneclient.roles

        # Mock client plugin
        def _side_effect(value):
            return value

        self.keystone_client_plugin = mock.MagicMock()
        self.keystone_client_plugin.get_group_id.side_effect = _side_effect
        self.keystone_client_plugin.get_domain_id.side_effect = _side_effect
        self.keystone_client_plugin.get_role_id.side_effect = _side_effect
        self.keystone_client_plugin.get_project_id.side_effect = _side_effect
        self.test_role_assignment.client_plugin = mock.MagicMock()
        (self.test_role_assignment.client_plugin.
         return_value) = self.keystone_client_plugin

        self.test_role_assignment.parse_list_assignments = mock.MagicMock()
        self.test_role_assignment.parse_list_assignments.return_value = [
            {'role': 'role_1',
             'domain': 'domain_1',
             'project': None},
            {'role': 'role_1',
             'project': 'project_1',
             'domain': None}]

    def test_group_role_assignment_handle_create(self):
        self.test_role_assignment.handle_create()

        # role-group-domain created
        self.roles.grant.assert_any_call(
            role='role_1',
            group='group_1',
            domain='domain_1')

        # role-group-project created
        self.roles.grant.assert_any_call(
            role='role_1',
            group='group_1',
            project='project_1')

    def test_group_role_assignment_handle_update(self):
        prop_diff = {
            MixinClass.ROLES: [
                {
                    'role': 'role_2',
                    'project': 'project_1'
                },
                {
                    'role': 'role_2',
                    'domain': 'domain_1'
                }
            ]
        }

        self.test_role_assignment.handle_update(json_snippet=None,
                                                tmpl_diff=None,
                                                prop_diff=prop_diff)

        # Add role2-project1-domain1
        # role-group-domain
        self.roles.grant.assert_any_call(
            role='role_2',
            group='group_1',
            domain='domain_1')

        # role-group-project
        self.roles.grant.assert_any_call(
            role='role_2',
            group='group_1',
            project='project_1')

        # Remove role1-project1-domain1
        # role-group-domain
        self.roles.revoke.assert_any_call(
            role='role_1',
            group='group_1',
            domain='domain_1')

        # role-group-project
        self.roles.revoke.assert_any_call(
            role='role_1',
            group='group_1',
            project='project_1')

    def test_group_role_assignment_handle_delete(self):
        self.assertIsNone(self.test_role_assignment.handle_delete())

        # Remove role1-project1-domain1
        # role-group-domain
        self.roles.revoke.assert_any_call(
            role='role_1',
            group='group_1',
            domain='domain_1')

        # role-group-project
        self.roles.revoke.assert_any_call(
            role='role_1',
            group='group_1',
            project='project_1')

    def test_group_role_assignment_delete_group_not_found(self):
        self.keystone_client_plugin.get_group_id.side_effect = [
            exception.EntityNotFound]
        self.assertIsNone(self.test_role_assignment.handle_delete())
        self.roles.revoke.assert_not_called()
