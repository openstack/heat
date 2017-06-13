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


class SoftwareDeploymentGroupTest(functional_base.FunctionalTestsBase):
    sd_template = '''
heat_template_version: 2016-10-14

parameters:
  input:
    type: string
    default: foo_input

resources:
  config:
    type: OS::Heat::SoftwareConfig
    properties:
      group: script
      inputs:
      - name: foo

  deployment:
    type: OS::Heat::SoftwareDeploymentGroup
    properties:
      config: {get_resource: config}
      input_values:
        foo: {get_param: input}
      servers:
        '0': dummy0
        '1': dummy1
        '2': dummy2
        '3': dummy3
'''

    sd_template_with_upd_policy = '''
heat_template_version: 2016-10-14

parameters:
  input:
    type: string
    default: foo_input

resources:
  config:
    type: OS::Heat::SoftwareConfig
    properties:
      group: script
      inputs:
      - name: foo

  deployment:
    type: OS::Heat::SoftwareDeploymentGroup
    update_policy:
      rolling_update:
        max_batch_size: 2
        pause_time: 1
    properties:
      config: {get_resource: config}
      input_values:
        foo: {get_param: input}
      servers:
        '0': dummy0
        '1': dummy1
        '2': dummy2
        '3': dummy3
'''
    enable_cleanup = True

    def deployment_crud(self, template):
        stack_identifier = self.stack_create(
            template=template,
            enable_cleanup=self.enable_cleanup,
            expected_status='CREATE_IN_PROGRESS')
        self._wait_for_resource_status(
            stack_identifier, 'deployment', 'CREATE_IN_PROGRESS')

        # Wait for all deployment resources to become IN_PROGRESS, since only
        # IN_PROGRESS resources get signalled
        nested_identifier = self.assert_resource_is_a_stack(
            stack_identifier, 'deployment')
        self._wait_for_stack_status(nested_identifier, 'CREATE_IN_PROGRESS')
        self._wait_for_all_resource_status(nested_identifier,
                                           'CREATE_IN_PROGRESS')
        group_resources = self.list_group_resources(
            stack_identifier, 'deployment', minimal=False)

        self.assertEqual(4, len(group_resources))
        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE',
                                    signal_required=True,
                                    resources_to_signal=group_resources)

        created_group_resources = self.list_group_resources(
            stack_identifier, 'deployment', minimal=False)
        self.assertEqual(4, len(created_group_resources))
        self.check_input_values(created_group_resources, 'foo', 'foo_input')

        self.update_stack(stack_identifier,
                          template=template,
                          environment={'parameters': {'input': 'input2'}},
                          expected_status='UPDATE_IN_PROGRESS')
        nested_identifier = self.assert_resource_is_a_stack(
            stack_identifier, 'deployment')
        self._wait_for_stack_status(stack_identifier, 'UPDATE_COMPLETE',
                                    signal_required=True,
                                    resources_to_signal=group_resources)

        self.check_input_values(created_group_resources, 'foo', 'input2')

        # We explicitly test delete here, vs just via cleanup and check
        # the nested stack is gone
        self._stack_delete(stack_identifier)
        self._wait_for_stack_status(
            nested_identifier, 'DELETE_COMPLETE',
            success_on_not_found=True)

    def test_deployment_crud(self):
        self.deployment_crud(self.sd_template)

    def test_deployment_crud_with_rolling_update(self):
        self.deployment_crud(self.sd_template_with_upd_policy)

    def test_deployments_create_delete_in_progress(self):
        stack_identifier = self.stack_create(
            template=self.sd_template,
            enable_cleanup=self.enable_cleanup,
            expected_status='CREATE_IN_PROGRESS')
        self._wait_for_resource_status(
            stack_identifier, 'deployment', 'CREATE_IN_PROGRESS')
        nested_identifier = self.assert_resource_is_a_stack(
            stack_identifier, 'deployment')
        group_resources = self.list_group_resources(
            stack_identifier, 'deployment', minimal=False)

        self.assertEqual(4, len(group_resources))
        # Now test delete while the stacks are still IN_PROGRESS
        self._stack_delete(stack_identifier)
        self._wait_for_stack_status(
            nested_identifier, 'DELETE_COMPLETE',
            success_on_not_found=True)
