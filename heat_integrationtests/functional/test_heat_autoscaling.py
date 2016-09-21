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


class HeatAutoscalingTest(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: 2014-10-16

resources:
  random_group:
    type: OS::Heat::AutoScalingGroup
    properties:
      max_size: 10
      min_size: 10
      resource:
        type: OS::Heat::RandomString

outputs:
  all_values:
    value: {get_attr: [random_group, outputs_list, value]}
  value_0:
    value: {get_attr: [random_group, resource.0.value]}
  value_5:
    value: {get_attr: [random_group, resource.5.value]}
  value_9:
    value: {get_attr: [random_group, resource.9.value]}
'''

    template_nested = '''
heat_template_version: 2014-10-16

resources:
  random_group:
    type: OS::Heat::AutoScalingGroup
    properties:
      max_size: 10
      min_size: 10
      resource:
        type: randomstr.yaml

outputs:
  all_values:
    value: {get_attr: [random_group, outputs_list, random_str]}
  value_0:
    value: {get_attr: [random_group, resource.0.random_str]}
  value_5:
    value: {get_attr: [random_group, resource.5.random_str]}
  value_9:
    value: {get_attr: [random_group, resource.9.random_str]}
'''

    template_randomstr = '''
heat_template_version: 2013-05-23

resources:
  random_str:
    type: OS::Heat::RandomString

outputs:
  random_str:
    value: {get_attr: [random_str, value]}
'''

    def _assert_output_values(self, stack_id):
        stack = self.client.stacks.get(stack_id)
        all_values = self._stack_output(stack, 'all_values')
        self.assertEqual(10, len(all_values))
        self.assertEqual(all_values[0], self._stack_output(stack, 'value_0'))
        self.assertEqual(all_values[5], self._stack_output(stack, 'value_5'))
        self.assertEqual(all_values[9], self._stack_output(stack, 'value_9'))

    def test_path_attrs(self):
        stack_id = self.stack_create(template=self.template)
        expected_resources = {'random_group': 'OS::Heat::AutoScalingGroup'}
        self.assertEqual(expected_resources, self.list_resources(stack_id))
        self._assert_output_values(stack_id)

    def test_path_attrs_nested(self):
        files = {'randomstr.yaml': self.template_randomstr}
        stack_id = self.stack_create(template=self.template_nested,
                                     files=files)
        expected_resources = {'random_group': 'OS::Heat::AutoScalingGroup'}
        self.assertEqual(expected_resources, self.list_resources(stack_id))
        self._assert_output_values(stack_id)


class AutoScalingGroupUpdateWithNoChanges(functional_base.FunctionalTestsBase):

    template = '''
heat_template_version: 2013-05-23

resources:
  test_group:
    type: OS::Heat::AutoScalingGroup
    properties:
      desired_capacity: 0
      max_size: 0
      min_size: 0
      resource:
        type: OS::Heat::RandomString
  test_policy:
    type: OS::Heat::ScalingPolicy
    properties:
      adjustment_type: change_in_capacity
      auto_scaling_group_id: { get_resource: test_group }
      scaling_adjustment: 1
'''

    def test_as_group_update_without_resource_changes(self):
        stack_identifier = self.stack_create(template=self.template)
        new_template = self.template.replace(
            'scaling_adjustment: 1',
            'scaling_adjustment: 2')

        self.update_stack(stack_identifier, template=new_template)
