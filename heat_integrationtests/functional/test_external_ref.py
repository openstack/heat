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


class ExternalReferencesTest(functional_base.FunctionalTestsBase):

    TEMPLATE = '''
heat_template_version: 2016-10-14
resources:
  test1:
    type: OS::Heat::TestResource
'''
    TEMPLATE_WITH_EX_REF = '''
heat_template_version: 2016-10-14
resources:
  test1:
    type: OS::Heat::TestResource
    external_id: foobar
outputs:
  str:
    value: {get_resource: test1}
'''

    def test_create_with_external_ref(self):
        stack_name = self._stack_rand_name()
        stack_identifier = self.stack_create(
            stack_name=stack_name,
            template=self.TEMPLATE_WITH_EX_REF,
            files={},
            disable_rollback=True,
            parameters={},
            environment={}
        )

        stack = self.client.stacks.get(stack_identifier)

        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')
        expected_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(expected_resources,
                         self.list_resources(stack_identifier))
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual(
            [{'description': 'No description given',
              'output_key': 'str',
              'output_value': 'foobar'}], stack.outputs)

    def test_update_with_external_ref(self):
        stack_name = self._stack_rand_name()
        stack_identifier = self.stack_create(
            stack_name=stack_name,
            template=self.TEMPLATE,
            files={},
            disable_rollback=True,
            parameters={},
            environment={}
        )
        stack = self.client.stacks.get(stack_identifier)

        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')
        expected_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(expected_resources,
                         self.list_resources(stack_identifier))
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual([], stack.outputs)

        stack_name = stack_identifier.split('/')[0]
        kwargs = {'stack_id': stack_identifier, 'stack_name': stack_name,
                  'template': self.TEMPLATE_WITH_EX_REF, 'files': {},
                  'disable_rollback': True, 'parameters': {}, 'environment': {}
                  }
        self.client.stacks.update(**kwargs)
        self._wait_for_stack_status(stack_identifier, 'UPDATE_FAILED')
