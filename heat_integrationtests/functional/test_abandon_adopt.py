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

import json

from heat_integrationtests.functional import functional_base


class AbandonAdoptTest(functional_base.FunctionalTestsBase):
    """Test abandoning a stack and adopting its resources into a new stack."""

    template = '''
heat_template_version: 2014-10-16
resources:
  test1:
    type: OS::Heat::TestResource
    properties:
      value: test_value_1
  test2:
    type: OS::Heat::TestResource
    properties:
      value: test_value_2
outputs:
  test1_output:
    value: {get_attr: [test1, output]}
  test2_output:
    value: {get_attr: [test2, output]}
'''

    def test_abandon_and_adopt(self):
        """Test abandoning Stack A and adopting its resources into Stack B."""
        stack_identifier_a = self.stack_create(
            template=self.template,
            enable_cleanup=False
        )

        stack_a = self.client.stacks.get(stack_identifier_a)
        test1_value_a = self._stack_output(stack_a, 'test1_output')
        test2_value_a = self._stack_output(stack_a, 'test2_output')
        test1_id_a = self.get_physical_resource_id(
            stack_identifier_a, 'test1')
        test2_id_a = self.get_physical_resource_id(stack_identifier_a, 'test2')

        abandon_data = self.stack_abandon(stack_id=stack_identifier_a)

        stack_identifier_b = self.stack_adopt(
            adopt_data=json.dumps(abandon_data),
        )

        stack_b = self.client.stacks.get(stack_identifier_b)
        test1_value_b = self._stack_output(stack_b, 'test1_output')
        test2_value_b = self._stack_output(stack_b, 'test2_output')
        test1_id_b = self.get_physical_resource_id(stack_identifier_b, 'test1')
        test2_id_b = self.get_physical_resource_id(stack_identifier_b, 'test2')

        self.assertEqual(test1_value_a, test1_value_b)
        self.assertEqual(test2_value_a, test2_value_b)
        self.assertEqual(test1_id_a, test1_id_b)
        self.assertEqual(test2_id_a, test2_id_b)


class NestedStackAdoptTest(functional_base.FunctionalTestsBase):
    """Test adopting resources from an abandoned nested stack."""

    parent_template = '''
heat_template_version: 2014-10-16
resources:
  parent_resource:
    type: OS::Heat::TestResource
    properties:
      value: parent_value
  nested:
    type: nested.yaml
outputs:
  parent_output:
    value: {get_attr: [parent_resource, output]}
  nested_output1:
    value: {get_attr: [nested, nested_output1]}
  nested_output2:
    value: {get_attr: [nested, nested_output2]}
'''

    nested_template = '''
heat_template_version: 2014-10-16
resources:
  nested_resource1:
    type: OS::Heat::TestResource
    properties:
      value: nested_value_1
  nested_resource2:
    type: OS::Heat::TestResource
    properties:
      value: nested_value_2
outputs:
  nested_output1:
    value: {get_attr: [nested_resource1, output]}
  nested_output2:
    value: {get_attr: [nested_resource2, output]}
'''

    def test_adopt_nested_stack_resources(self):
        """Abandon parent stack and adopt only the nested stack's resources."""
        stack_identifier = self.stack_create(
            template=self.parent_template,
            files={'nested.yaml': self.nested_template},
            enable_cleanup=False
        )

        stack = self.client.stacks.get(stack_identifier)
        nested_output1 = self._stack_output(stack, 'nested_output1')
        nested_output2 = self._stack_output(stack, 'nested_output2')

        abandon_data = self.stack_abandon(stack_id=stack_identifier)
        nested_abandon = abandon_data['resources']['nested']
        nested_resources = nested_abandon['resources']
        orig_res1_id = nested_resources['nested_resource1']['resource_id']
        orig_res2_id = nested_resources['nested_resource2']['resource_id']

        adopt_data = {
            'template': nested_abandon['template'],
            'resources': nested_abandon['resources'],
            'environment': {'parameters': {}},
        }

        new_stack_identifier = self.stack_adopt(
            adopt_data=json.dumps(adopt_data),
        )

        new_stack = self.client.stacks.get(new_stack_identifier)
        new_output1 = self._stack_output(new_stack, 'nested_output1')
        new_output2 = self._stack_output(new_stack, 'nested_output2')
        new_res1_id = self.get_physical_resource_id(
            new_stack_identifier, 'nested_resource1')
        new_res2_id = self.get_physical_resource_id(
            new_stack_identifier, 'nested_resource2')

        self.assertEqual(nested_output1, new_output1)
        self.assertEqual(nested_output2, new_output2)
        self.assertEqual(orig_res1_id, new_res1_id)
        self.assertEqual(orig_res2_id, new_res2_id)
