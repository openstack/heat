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


class HeatAutoscalingTest(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: 2014-10-16

resources:
  random_group:
    type: OS::Heat::AutoScalingGroup
    properties:
      cooldown: 0
      desired_capacity: 3
      max_size: 5
      min_size: 2
      resource:
        type: OS::Heat::RandomString

  scale_up_policy:
    type: OS::Heat::ScalingPolicy
    properties:
      adjustment_type: change_in_capacity
      auto_scaling_group_id: { get_resource: random_group }
      scaling_adjustment: 1

  scale_down_policy:
    type: OS::Heat::ScalingPolicy
    properties:
      adjustment_type: change_in_capacity
      auto_scaling_group_id: { get_resource: random_group }
      scaling_adjustment: -1

outputs:
  all_values:
    value: {get_attr: [random_group, outputs_list, value]}
  value_0:
    value: {get_attr: [random_group, resource.0.value]}
  value_1:
    value: {get_attr: [random_group, resource.1.value]}
  value_2:
    value: {get_attr: [random_group, resource.2.value]}
  asg_size:
    value: {get_attr: [random_group, current_size]}
'''

    template_nested = '''
heat_template_version: 2014-10-16

resources:
  random_group:
    type: OS::Heat::AutoScalingGroup
    properties:
      desired_capacity: 3
      max_size: 5
      min_size: 2
      resource:
        type: randomstr.yaml

outputs:
  all_values:
    value: {get_attr: [random_group, outputs_list, random_str]}
  value_0:
    value: {get_attr: [random_group, resource.0.random_str]}
  value_1:
    value: {get_attr: [random_group, resource.1.random_str]}
  value_2:
    value: {get_attr: [random_group, resource.2.random_str]}
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
        self.assertEqual(3, len(all_values))
        self.assertEqual(all_values[0], self._stack_output(stack, 'value_0'))
        self.assertEqual(all_values[1], self._stack_output(stack, 'value_1'))
        self.assertEqual(all_values[2], self._stack_output(stack, 'value_2'))

    def test_asg_scale_up_max_size(self):
        stack_id = self.stack_create(template=self.template,
                                     expected_status='CREATE_COMPLETE')
        stack = self.client.stacks.get(stack_id)
        asg_size = self._stack_output(stack, 'asg_size')
        # Ensure that initial desired capacity is met
        self.assertEqual(3, asg_size)

        # send scale up signals and ensure that asg honors max_size
        asg = self.client.resources.get(stack_id, 'random_group')
        max_size = 5
        for num in range(asg_size+1, max_size+2):
            expected_resources = num if num <= max_size else max_size
            self.client.resources.signal(stack_id, 'scale_up_policy')
            self.assertTrue(
                test.call_until_true(self.conf.build_timeout,
                                     self.conf.build_interval,
                                     self.check_autoscale_complete,
                                     asg.physical_resource_id,
                                     expected_resources, stack_id,
                                     'random_group'))

    def test_asg_scale_down_min_size(self):
        stack_id = self.stack_create(template=self.template,
                                     expected_status='CREATE_COMPLETE')
        stack = self.client.stacks.get(stack_id)
        asg_size = self._stack_output(stack, 'asg_size')
        # Ensure that initial desired capacity is met
        self.assertEqual(3, asg_size)

        # send scale down signals and ensure that asg honors min_size
        asg = self.client.resources.get(stack_id, 'random_group')
        min_size = 2
        for num in range(asg_size-1, 0, -1):
            expected_resources = num if num >= min_size else min_size
            self.client.resources.signal(stack_id, 'scale_down_policy')
            self.assertTrue(
                test.call_until_true(self.conf.build_timeout,
                                     self.conf.build_interval,
                                     self.check_autoscale_complete,
                                     asg.physical_resource_id,
                                     expected_resources, stack_id,
                                     'random_group'))

    def test_asg_cooldown(self):
        cooldown_tmpl = self.template.replace('cooldown: 0',
                                              'cooldown: 60')
        stack_id = self.stack_create(template=cooldown_tmpl,
                                     expected_status='CREATE_COMPLETE')
        stack = self.client.stacks.get(stack_id)
        asg_size = self._stack_output(stack, 'asg_size')
        # Ensure that initial desired capacity is met
        self.assertEqual(3, asg_size)

        # send scale up signal.
        # Since cooldown is in effect, number of resources should not change
        asg = self.client.resources.get(stack_id, 'random_group')
        expected_resources = 3
        self.client.resources.signal(stack_id, 'scale_up_policy')
        self.assertTrue(
            test.call_until_true(self.conf.build_timeout,
                                 self.conf.build_interval,
                                 self.check_autoscale_complete,
                                 asg.physical_resource_id,
                                 expected_resources, stack_id,
                                 'random_group'))

    def test_path_attrs(self):
        stack_id = self.stack_create(template=self.template)
        expected_resources = {'random_group': 'OS::Heat::AutoScalingGroup',
                              'scale_up_policy': 'OS::Heat::ScalingPolicy',
                              'scale_down_policy': 'OS::Heat::ScalingPolicy'}
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
