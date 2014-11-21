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

import logging

from heat_integrationtests.common import test


LOG = logging.getLogger(__name__)


class UpdateStackTest(test.HeatIntegrationTest):

    template = '''
heat_template_version: 2013-05-23
resources:
  random1:
    type: OS::Heat::RandomString
'''
    update_template = '''
heat_template_version: 2013-05-23
resources:
  random1:
    type: OS::Heat::RandomString
  random2:
    type: OS::Heat::RandomString
'''

    provider_template = '''
heat_template_version: 2013-05-23
resources:
  random1:
    type: My::RandomString
'''

    provider_group_template = '''
heat_template_version: 2013-05-23
resources:
  random_group:
    type: OS::Heat::ResourceGroup
    properties:
      count: 2
      resource_def:
        type: My::RandomString
'''

    def setUp(self):
        super(UpdateStackTest, self).setUp()
        self.client = self.orchestration_client

    def update_stack(self, stack_identifier, template, environment=None,
                     files=None):
        env = environment or {}
        env_files = files or {}
        stack_name = stack_identifier.split('/')[0]
        self.client.stacks.update(
            stack_id=stack_identifier,
            stack_name=stack_name,
            template=template,
            files=env_files,
            disable_rollback=True,
            parameters={},
            environment=env
        )
        self._wait_for_stack_status(stack_identifier, 'UPDATE_COMPLETE')

    def list_resources(self, stack_identifier):
        resources = self.client.resources.list(stack_identifier)
        return dict((r.resource_name, r.resource_type) for r in resources)

    def test_stack_update_nochange(self):
        stack_name = self._stack_rand_name()
        self.client.stacks.create(
            stack_name=stack_name,
            template=self.template,
            files={},
            disable_rollback=True,
            parameters={},
            environment={}
        )
        self.addCleanup(self.client.stacks.delete, stack_name)

        stack = self.client.stacks.get(stack_name)
        stack_identifier = '%s/%s' % (stack_name, stack.id)

        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')
        expected_resources = {'random1': 'OS::Heat::RandomString'}
        self.assertEqual(expected_resources,
                         self.list_resources(stack_identifier))

        # Update with no changes, resources should be unchanged
        self.update_stack(stack_identifier, self.template)
        self.assertEqual(expected_resources,
                         self.list_resources(stack_identifier))

    def test_stack_update_add_remove(self):
        stack_name = self._stack_rand_name()

        self.client.stacks.create(
            stack_name=stack_name,
            template=self.template,
            files={},
            disable_rollback=True,
            parameters={},
            environment={}
        )
        self.addCleanup(self.client.stacks.delete, stack_name)

        stack = self.client.stacks.get(stack_name)
        stack_identifier = '%s/%s' % (stack_name, stack.id)

        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')
        initial_resources = {'random1': 'OS::Heat::RandomString'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Add one resource via a stack update
        self.update_stack(stack_identifier, self.update_template)
        stack = self.client.stacks.get(stack_identifier)
        updated_resources = {'random1': 'OS::Heat::RandomString',
                             'random2': 'OS::Heat::RandomString'}
        self.assertEqual(updated_resources,
                         self.list_resources(stack_identifier))

        # Then remove it by updating with the original template
        self.update_stack(stack_identifier, self.template)
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

    def test_stack_update_provider(self):
        stack_name = self._stack_rand_name()
        files = {'provider.yaml': self.template}
        env = {'resource_registry':
               {'My::RandomString': 'provider.yaml'}}

        self.client.stacks.create(
            stack_name=stack_name,
            template=self.provider_template,
            files=files,
            disable_rollback=True,
            parameters={},
            environment=env
        )
        self.addCleanup(self.client.stacks.delete, stack_name)

        stack = self.client.stacks.get(stack_name)
        stack_identifier = '%s/%s' % (stack_name, stack.id)

        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')
        initial_resources = {'random1': 'My::RandomString'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Prove the resource is backed by a nested stack, save the ID
        rsrc = self.client.resources.get(stack_identifier, 'random1')
        nested_link = [l for l in rsrc.links if l['rel'] == 'nested']
        nested_href = nested_link[0]['href']
        nested_id = nested_href.split('/')[-1]
        nested_identifier = '/'.join(nested_href.split('/')[-2:])
        physical_resource_id = rsrc.physical_resource_id
        self.assertEqual(physical_resource_id, nested_id)

        # Then check the expected resources are in the nested stack
        nested_resources = {'random1': 'OS::Heat::RandomString'}
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))

        # Add one resource via a stack update by changing the nested stack
        files['provider.yaml'] = self.update_template
        self.update_stack(stack_identifier, self.provider_template,
                          environment=env, files=files)
        stack = self.client.stacks.get(stack_identifier)

        # Parent resources should be unchanged and the nested stack
        # should have been updated in-place without replacement
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))
        rsrc = self.client.resources.get(stack_identifier, 'random1')
        self.assertEqual(rsrc.physical_resource_id, nested_id)

        # Then check the expected resources are in the nested stack
        nested_resources = {'random1': 'OS::Heat::RandomString',
                            'random2': 'OS::Heat::RandomString'}
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))

    def test_stack_update_provider_group(self):
        '''Test two-level nested update.'''
        # Create a ResourceGroup (which creates a nested stack),
        # containing provider resources (which create a nested
        # stack), thus excercising an update which traverses
        # two levels of nesting.
        stack_name = self._stack_rand_name()
        files = {'provider.yaml': self.template}
        env = {'resource_registry':
               {'My::RandomString': 'provider.yaml'}}

        self.client.stacks.create(
            stack_name=stack_name,
            template=self.provider_group_template,
            files=files,
            disable_rollback=True,
            parameters={},
            environment=env
        )
        self.addCleanup(self.client.stacks.delete, stack_name)

        stack = self.client.stacks.get(stack_name)
        stack_identifier = '%s/%s' % (stack_name, stack.id)

        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')
        initial_resources = {'random_group': 'OS::Heat::ResourceGroup'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Prove the resource is backed by a nested stack, save the ID
        rsrc = self.client.resources.get(stack_identifier, 'random_group')
        physical_resource_id = rsrc.physical_resource_id

        nested_stack = self.client.stacks.get(physical_resource_id)
        nested_identifier = '%s/%s' % (nested_stack.stack_name,
                                       nested_stack.id)
        self.assertEqual(stack.id, nested_stack.parent)

        # Then check the expected resources are in the nested stack
        nested_resources = {'0': 'My::RandomString',
                            '1': 'My::RandomString'}
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))

        for n_rsrc in nested_resources:
            rsrc = self.client.resources.get(nested_identifier, n_rsrc)
            provider_stack = self.client.stacks.get(rsrc.physical_resource_id)
            provider_identifier = '%s/%s' % (provider_stack.stack_name,
                                             provider_stack.id)
            provider_resources = {u'random1': u'OS::Heat::RandomString'}
            self.assertEqual(provider_resources,
                             self.list_resources(provider_identifier))

        # Add one resource via a stack update by changing the nested stack
        files['provider.yaml'] = self.update_template
        self.update_stack(stack_identifier, self.provider_group_template,
                          environment=env, files=files)
        stack = self.client.stacks.get(stack_identifier)

        # Parent resources should be unchanged and the nested stack
        # should have been updated in-place without replacement
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Resource group stack should also be unchanged (but updated)
        nested_stack = self.client.stacks.get(nested_identifier)
        self.assertEqual('UPDATE_COMPLETE', nested_stack.stack_status)
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))

        for n_rsrc in nested_resources:
            rsrc = self.client.resources.get(nested_identifier, n_rsrc)
            provider_stack = self.client.stacks.get(rsrc.physical_resource_id)
            provider_identifier = '%s/%s' % (provider_stack.stack_name,
                                             provider_stack.id)
            provider_resources = {'random1': 'OS::Heat::RandomString',
                                  'random2': 'OS::Heat::RandomString'}
            self.assertEqual(provider_resources,
                             self.list_resources(provider_identifier))
