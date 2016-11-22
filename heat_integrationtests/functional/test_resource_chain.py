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

from heat_integrationtests.functional import functional_base


TEMPLATE_SIMPLE = '''
heat_template_version: 2016-04-08
parameters:
  string-length:
    type: number
resources:
  my-chain:
    type: OS::Heat::ResourceChain
    properties:
      resources: ['OS::Heat::RandomString', 'OS::Heat::RandomString']
      resource_properties:
        length: { get_param: string-length }
outputs:
  resource-ids:
    value: { get_attr: [my-chain, refs] }
  resource-0-value:
    value: { get_attr: [my-chain, resource.0, value] }
  all-resource-attrs:
    value: { get_attr: [my-chain, attributes, value] }
'''

TEMPLATE_PARAM_DRIVEN = '''
heat_template_version: 2016-04-08
parameters:
  chain-types:
    type: comma_delimited_list
resources:
  my-chain:
    type: OS::Heat::ResourceChain
    properties:
      resources: { get_param: chain-types }
'''


class ResourceChainTests(functional_base.FunctionalTestsBase):

    def test_create(self):
        # Test
        params = {'string-length': 8}
        stack_id = self.stack_create(template=TEMPLATE_SIMPLE,
                                     parameters=params)

        # Verify
        stack = self.client.stacks.get(stack_id)
        self.assertIsNotNone(stack)

        # Top-level resource for chain
        expected = {'my-chain': 'OS::Heat::ResourceChain'}
        found = self.list_resources(stack_id)
        self.assertEqual(expected, found)

        # Nested stack exists and has two resources
        nested_id = self.group_nested_identifier(stack_id, 'my-chain')
        expected = {'0': 'OS::Heat::RandomString',
                    '1': 'OS::Heat::RandomString'}
        found = self.list_resources(nested_id)
        self.assertEqual(expected, found)

        # Outputs
        resource_ids = self._stack_output(stack, 'resource-ids')
        self.assertIsNotNone(resource_ids)
        self.assertEqual(2, len(resource_ids))

        resource_value = self._stack_output(stack, 'resource-0-value')
        self.assertIsNotNone(resource_value)
        self.assertEqual(8, len(resource_value))  # from parameter

        resource_attrs = self._stack_output(stack, 'all-resource-attrs')
        self.assertIsNotNone(resource_attrs)
        self.assertIsInstance(resource_attrs, dict)
        self.assertEqual(2, len(resource_attrs))
        self.assertEqual(8, len(resource_attrs['0']))
        self.assertEqual(8, len(resource_attrs['1']))

    def test_update(self):
        # Setup
        params = {'string-length': 8}
        stack_id = self.stack_create(template=TEMPLATE_SIMPLE,
                                     parameters=params)

        update_tmpl = '''
        heat_template_version: 2016-04-08
        parameters:
          string-length:
            type: number
        resources:
          my-chain:
            type: OS::Heat::ResourceChain
            properties:
              resources: ['OS::Heat::None']
        '''

        # Test
        self.update_stack(stack_id, template=update_tmpl, parameters=params)

        # Verify
        # Nested stack only has the None resource
        nested_id = self.group_nested_identifier(stack_id, 'my-chain')
        expected = {'0': 'OS::Heat::None'}
        found = self.list_resources(nested_id)
        self.assertEqual(expected, found)

    def test_update_resources(self):
        params = {'chain-types': 'OS::Heat::None'}

        stack_id = self.stack_create(template=TEMPLATE_PARAM_DRIVEN,
                                     parameters=params)

        nested_id = self.group_nested_identifier(stack_id, 'my-chain')
        expected = {'0': 'OS::Heat::None'}
        found = self.list_resources(nested_id)
        self.assertEqual(expected, found)

        params = {'chain-types': 'OS::Heat::None,OS::Heat::None'}
        self.update_stack(stack_id, template=TEMPLATE_PARAM_DRIVEN,
                          parameters=params)

        expected = {'0': 'OS::Heat::None', '1': 'OS::Heat::None'}
        found = self.list_resources(nested_id)
        self.assertEqual(expected, found)

    def test_resources_param_driven(self):
        # Setup
        params = {'chain-types':
                  'OS::Heat::None,OS::Heat::RandomString,OS::Heat::None'}

        # Test
        stack_id = self.stack_create(template=TEMPLATE_PARAM_DRIVEN,
                                     parameters=params)

        # Verify
        nested_id = self.group_nested_identifier(stack_id, 'my-chain')
        expected = {'0': 'OS::Heat::None',
                    '1': 'OS::Heat::RandomString',
                    '2': 'OS::Heat::None'}
        found = self.list_resources(nested_id)
        self.assertEqual(expected, found)

    def test_resources_env_defined(self):
        # Setup
        env = {'parameters': {'chain-types': 'OS::Heat::None'}}

        # Test
        stack_id = self.stack_create(template=TEMPLATE_PARAM_DRIVEN,
                                     environment=env)

        # Verify
        nested_id = self.group_nested_identifier(stack_id, 'my-chain')
        expected = {'0': 'OS::Heat::None'}
        found = self.list_resources(nested_id)
        self.assertEqual(expected, found)
