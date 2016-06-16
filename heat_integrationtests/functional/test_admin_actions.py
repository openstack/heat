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

from heat_integrationtests.functional import functional_base

# Simple stack
test_template = {
    'heat_template_version': '2013-05-23',
    'resources': {
        'test1': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'Test1'
            }
        }
    }
}

# Nested stack
rsg_template = {
    'heat_template_version': '2013-05-23',
    'resources': {
        'random_group': {
            'type': 'OS::Heat::ResourceGroup',
            'properties': {
                'count': 2,
                'resource_def': {
                    'type': 'OS::Heat::RandomString',
                    'properties': {
                        'length': 30,
                        'salt': 'initial'
                    }
                }
            }
        }
    }
}


class AdminActionsTest(functional_base.FunctionalTestsBase):

    def setUp(self):
        super(AdminActionsTest, self).setUp()
        if not self.conf.admin_username or not self.conf.admin_password:
            self.skipTest('No admin creds found, skipping')

    def create_stack_setup_admin_client(self, template=test_template):
        # Create the stack with the default user
        self.stack_identifier = self.stack_create(template=template)

        # Setup admin clients
        self.setup_clients_for_admin()

    def test_admin_simple_stack_actions(self):
        self.create_stack_setup_admin_client()

        updated_template = test_template.copy()
        props = updated_template['resources']['test1']['properties']
        props['value'] = 'new_value'

        # Update, suspend and resume stack
        self.update_stack(self.stack_identifier,
                          template=updated_template)
        self.stack_suspend(self.stack_identifier)
        self.stack_resume(self.stack_identifier)

        # List stack resources
        initial_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(initial_resources,
                         self.list_resources(self.stack_identifier))
        # Delete stack
        self._stack_delete(self.stack_identifier)

    def test_admin_complex_stack_actions(self):
        self.create_stack_setup_admin_client(template=rsg_template)

        updated_template = rsg_template.copy()
        props = updated_template['resources']['random_group']['properties']
        props['count'] = 3

        # Update, suspend and resume stack
        self.update_stack(self.stack_identifier,
                          template=updated_template)
        self.stack_suspend(self.stack_identifier)
        self.stack_resume(self.stack_identifier)

        # List stack resources
        resources = {'random_group': 'OS::Heat::ResourceGroup'}
        self.assertEqual(resources,
                         self.list_resources(self.stack_identifier))
        # Delete stack
        self._stack_delete(self.stack_identifier)
