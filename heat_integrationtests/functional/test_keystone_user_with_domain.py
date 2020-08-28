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

from heat_integrationtests.common import test
from heat_integrationtests.functional import functional_base

create_user = '''
heat_template_version: 2014-10-16
description: test template to test user role assignment with user{domain}
parameters:
  user_name:
    type: string
    label: User Name
    description: Test user name
  project_name:
    type: string
    label: Project Name
    description: Test project name
  domain_name:
    type: string
    label: Domain Name
    description: Test domain name
resources:
  Domain:
    properties:
      description: "Test Domain"
      enabled: true
      name: {get_param: domain_name}
    type: OS::Keystone::Domain
  Project:
    properties:
      description: "Test Project"
      enabled: true
      name: {get_param: project_name}
    type: OS::Keystone::Project
  User:
    type: OS::Keystone::User
    properties:
      name: {get_param: user_name}
      domain: {get_resource: Domain}
      description: Test user
      enabled: true
      email: xyz@abc.com
      password: passWORD
outputs:
  project_name:
    value: {get_attr: [Project, name]}
  user_name:
    value: {get_attr: [User, name]}
'''
assign_user_roles = '''
heat_template_version: 2014-10-16
description: test template to test user role assignment with user{domain}
parameters:
  user_name:
    type: string
    label: User Name
    description: Test user name
  project_name:
    type: string
    label: Project Name
    description: Test project name
  domain_name:
    type: string
    label: Domain Name
    description: Test domain name
resources:
  UserRoleAssignemnt:
    properties:
      roles:
      - role: admin
        project: {get_param: project_name}
      user:
        list_join: ['',
                      [
                        {get_param: user_name},
                        '{',
                        {get_param: domain_name},
                        '}'
                      ]
                   ]
    type: OS::Keystone::UserRoleAssignment
'''
disable_domain = '''
heat_template_version: 2014-10-16
description: test template to test user role assignment with user{domain}
parameters:
  user_name:
    type: string
    label: User Name
    description: Test user name
  project_name:
    type: string
    label: Project Name
    description: Test project name
  domain_name:
    type: string
    label: Domain Name
    description: Test domain name
resources:
  Domain:
    properties:
      description: "Test Domain"
      enabled: false
      name: {get_param: domain_name}
    type: OS::Keystone::Domain
  Project:
    properties:
      description: "Test Project"
      enabled: true
      name: {get_param: project_name}
    type: OS::Keystone::Project
  User:
    type: OS::Keystone::User
    properties:
      name: {get_param: user_name}
      domain: {get_resource: Domain}
      description: Test user
      enabled: true
      email: xyz@abc.com
      password: passWORD
outputs:
  project_name:
    value: {get_attr: [Project, name]}
  user_name:
    value: {get_attr: [User, name]}
'''


class CreateUserTest(functional_base.FunctionalTestsBase):

    def get_user_and_project_outputs(self, stack_identifier):
        stack = self.client.stacks.get(stack_identifier)
        project_name = self._stack_output(stack, 'project_name')
        user_name = self._stack_output(stack, 'user_name')
        return project_name, user_name

    def get_outputs(self, stack_identifier, output_key):
        stack = self.client.stacks.get(stack_identifier)
        return self._stack_output(stack, output_key)

    def test_assign_user_role_with_domain(self):
        # Setup admin clients
        self.setup_clients_for_admin()
        parms = {
            'user_name': test.rand_name('test-user-domain-user-name'),
            'project_name': test.rand_name('test-user-domain-project'),
            'domain_name': test.rand_name('test-user-domain-domain-name')
        }
        stack_identifier_create_user = self.stack_create(
            template=create_user,
            parameters=parms)

        self.stack_create(
            template=assign_user_roles,
            parameters=parms)

        project_name, user_name = self.get_user_and_project_outputs(
            stack_identifier_create_user)
        self.assertEqual(project_name, project_name)
        self.assertEqual(user_name, user_name)
        users = self.keystone_client.users.list()
        projects = self.keystone_client.projects.list()
        user_id = [x for x in users if x.name == user_name][0].id
        project_id = [x for x in projects if x.name == project_name][0].id
        self.assertIsNotNone(
            self.keystone_client.role_assignments.list(
                user=user_id, project=project_id))

        # Disable domain so stack can be deleted
        self.update_stack(
            stack_identifier=stack_identifier_create_user,
            template=disable_domain,
            parameters=parms)
