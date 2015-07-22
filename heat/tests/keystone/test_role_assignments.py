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

from heat.common import exception
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.keystone import role_assignments
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

RESOURCE_TYPE = 'OS::Keystone::DummyRoleAssignment'

keystone_role_assignment_template = {
    'heat_template_version': '2013-05-23',
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


class KeystoneRoleAssignmentTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneRoleAssignmentTest, self).setUp()

        self.ctx = utils.dummy_context()

        # For unit testing purpose. Register resource provider explicitly.
        resource._register_class(RESOURCE_TYPE,
                                 role_assignments.KeystoneRoleAssignment)

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone',
            template.Template(keystone_role_assignment_template)
        )
        self.test_role_assignment = self.stack['test_role_assignment']

        # Mock client
        self.keystoneclient = mock.MagicMock()
        self.test_role_assignment.client = mock.MagicMock()
        self.test_role_assignment.client.return_value = self.keystoneclient
        self.roles = self.keystoneclient.client.roles

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

    def test_resource_mapping_not_defined(self):
        # this resource is not planned to support in heat, so resource_mapping
        # is not to be defined in KeystoneRoleAssignment
        try:
            from ..resources.role_assignments import resource_mapping  # noqa
            self.fail("KeystoneRoleAssignment is designed to be exposed as"
                      "Heat resource")
        except Exception:
            pass

    def test_properties_title(self):
        property_title_map = {
            role_assignments.KeystoneRoleAssignment.ROLES: 'roles'
        }

        for actual_title, expected_title in property_title_map.items():
            self.assertEqual(
                expected_title,
                actual_title,
                'KeystoneRoleAssignment PROPERTIES(%s) title modified.' %
                actual_title)

    def test_property_roles_validate_schema(self):
        schema = (role_assignments.KeystoneRoleAssignment.
                  properties_schema[
                      role_assignments.KeystoneRoleAssignment.ROLES])
        self.assertEqual(
            True,
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            role_assignments.KeystoneRoleAssignment.ROLES)

        self.assertEqual(properties.Schema.LIST,
                         schema.type,
                         'type for property %s is modified' %
                         role_assignments.KeystoneRoleAssignment.ROLES)

        self.assertEqual('List of role assignments.',
                         schema.description,
                         'description for property %s is modified' %
                         role_assignments.KeystoneRoleAssignment.ROLES)

    def test_role_assignment_handle_create_user(self):
        # validate the properties
        self.assertEqual([
            {
                'role': 'role_1',
                'project': 'project_1',
                'domain': None
            },
            {
                'role': 'role_1',
                'project': None,
                'domain': 'domain_1'
            }],
            (self.test_role_assignment.properties.
             get(role_assignments.KeystoneRoleAssignment.ROLES)))

        self.test_role_assignment.handle_create(user_id='user_1',
                                                group_id=None)

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

    def test_role_assignment_handle_create_group(self):
        # validate the properties
        self.assertEqual([
            {
                'role': 'role_1',
                'project': 'project_1',
                'domain': None
            },
            {
                'role': 'role_1',
                'project': None,
                'domain': 'domain_1'
            }],
            (self.test_role_assignment.properties.
             get(role_assignments.KeystoneRoleAssignment.ROLES)))

        self.test_role_assignment.handle_create(user_id=None,
                                                group_id='group_1')

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

    def test_role_assignment_handle_update_user(self):
        self.test_role_assignment._stored_properties_data = {
            'roles': [
                {
                    'role': 'role_1',
                    'project': 'project_1'
                },
                {
                    'role': 'role_1',
                    'domain': 'domain_1'
                }
            ]
        }

        prop_diff = {
            role_assignments.KeystoneRoleAssignment.ROLES: [
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

        self.test_role_assignment.handle_update(
            user_id='user_1',
            group_id=None,
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

    def test_role_assignment_handle_update_group(self):
        self.test_role_assignment._stored_properties_data = {
            'roles': [
                {
                    'role': 'role_1',
                    'project': 'project_1'
                },
                {
                    'role': 'role_1',
                    'domain': 'domain_1'
                }
            ]
        }

        prop_diff = {
            role_assignments.KeystoneRoleAssignment.ROLES: [
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

        self.test_role_assignment.handle_update(
            user_id=None,
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

    def test_role_assignment_handle_delete_user(self):
        self.test_role_assignment._stored_properties_data = {
            'roles': [
                {
                    'role': 'role_1',
                    'project': 'project_1'
                },
                {
                    'role': 'role_1',
                    'domain': 'domain_1'
                }
            ]
        }
        self.assertIsNone(self.test_role_assignment.handle_delete(
            user_id='user_1',
            group_id=None
        ))

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

    def test_role_assignment_handle_delete_group(self):
        self.test_role_assignment._stored_properties_data = {
            'roles': [
                {
                    'role': 'role_1',
                    'project': 'project_1'
                },
                {
                    'role': 'role_1',
                    'domain': 'domain_1'
                }
            ]
        }
        self.assertIsNone(self.test_role_assignment.handle_delete(
            user_id=None,
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
