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
from heatclient import exc as heat_exceptions


class ImmutableParametersTest(functional_base.FunctionalTestsBase):

    template_param_has_no_immutable_field = '''
heat_template_version: 2014-10-16
parameters:
  param1:
    type: string
    default: default_value
outputs:
  param1_output:
    description: 'parameter 1 details'
    value: { get_param: param1 }
'''

    template_param_has_immutable_field = '''
heat_template_version: 2014-10-16
parameters:
  param1:
    type: string
    default: default_value
    immutable: false
outputs:
  param1_output:
    description: 'parameter 1 details'
    value: { get_param: param1 }
'''

    def test_no_immutable_param_field(self):
        param1_create_value = 'value1'
        create_parameters = {"param1": param1_create_value}

        stack_identifier = self.stack_create(
            template=self.template_param_has_no_immutable_field,
            parameters=create_parameters
        )
        stack = self.client.stacks.get(stack_identifier)

        # Verify the value of the parameter
        self.assertEqual(param1_create_value,
                         self._stack_output(stack, 'param1_output'))

        param1_update_value = 'value2'
        update_parameters = {"param1": param1_update_value}

        self.update_stack(
            stack_identifier,
            template=self.template_param_has_no_immutable_field,
            parameters=update_parameters)

        stack = self.client.stacks.get(stack_identifier)

        # Verify the value of the updated parameter
        self.assertEqual(param1_update_value,
                         self._stack_output(stack, 'param1_output'))

    def test_immutable_param_field_allowed(self):
        param1_create_value = 'value1'
        create_parameters = {"param1": param1_create_value}

        stack_identifier = self.stack_create(
            template=self.template_param_has_immutable_field,
            parameters=create_parameters
        )
        stack = self.client.stacks.get(stack_identifier)

        # Verify the value of the parameter
        self.assertEqual(param1_create_value,
                         self._stack_output(stack, 'param1_output'))

        param1_update_value = 'value2'
        update_parameters = {"param1": param1_update_value}

        self.update_stack(
            stack_identifier,
            template=self.template_param_has_immutable_field,
            parameters=update_parameters)
        stack = self.client.stacks.get(stack_identifier)

        # Verify the value of the updated parameter
        self.assertEqual(param1_update_value,
                         self._stack_output(stack, 'param1_output'))

        # Ensure stack is not in a failed state
        self.assertEqual('UPDATE_COMPLETE', stack.stack_status)

    def test_immutable_param_field_error(self):
        param1_create_value = 'value1'
        create_parameters = {"param1": param1_create_value}

        # Toggle the immutable field to preclude updating
        immutable_true = self.template_param_has_immutable_field.replace(
            'immutable: false', 'immutable: true')

        stack_identifier = self.stack_create(
            template=immutable_true,
            parameters=create_parameters
        )
        stack = self.client.stacks.get(stack_identifier)

        param1_update_value = 'value2'
        update_parameters = {"param1": param1_update_value}

        # Verify the value of the parameter
        self.assertEqual(param1_create_value,
                         self._stack_output(stack, 'param1_output'))

        # Attempt to update the stack with a new parameter value
        try:
            self.update_stack(
                stack_identifier,
                template=immutable_true,
                parameters=update_parameters)
        except heat_exceptions.HTTPBadRequest as exc:
            exp = ('The following parameters are immutable and may not be '
                   'updated: param1')
            self.assertIn(exp, str(exc))

        stack = self.client.stacks.get(stack_identifier)

        # Ensure stack is not in a failed state
        self.assertEqual('CREATE_COMPLETE', stack.stack_status)

        # Ensure immutable parameter has not changed
        self.assertEqual(param1_create_value,
                         self._stack_output(stack, 'param1_output'))
