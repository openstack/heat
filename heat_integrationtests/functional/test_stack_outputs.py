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


class StackOutputsTest(functional_base.FunctionalTestsBase):

    template = '''
heat_template_version: 2015-10-15
resources:
  test_resource_a:
    type: OS::Heat::TestResource
    properties:
      value: 'a'
  test_resource_b:
    type: OS::Heat::TestResource
    properties:
      value: 'b'
outputs:
  resource_output_a:
    description: 'Output of resource a'
    value: { get_attr: [test_resource_a, output] }
  resource_output_b:
    description: 'Output of resource b'
    value: { get_attr: [test_resource_b, output] }
'''

    def test_outputs(self):
        stack_identifier = self.stack_create(
            template=self.template
        )
        expected_list = [{u'output_key': u'resource_output_a',
                          u'description': u'Output of resource a'},
                         {u'output_key': u'resource_output_b',
                          u'description': u'Output of resource b'}]

        actual_list = self.client.stacks.output_list(
            stack_identifier)['outputs']
        sorted_actual_list = sorted(actual_list, key=lambda x: x['output_key'])
        self.assertEqual(expected_list, sorted_actual_list)

        expected_output_a = {
            u'output_value': u'a', u'output_key': u'resource_output_a',
            u'description': u'Output of resource a'}
        expected_output_b = {
            u'output_value': u'b', u'output_key': u'resource_output_b',
            u'description': u'Output of resource b'}
        actual_output_a = self.client.stacks.output_show(
            stack_identifier, 'resource_output_a')['output']
        actual_output_b = self.client.stacks.output_show(
            stack_identifier, 'resource_output_b')['output']
        self.assertEqual(expected_output_a, actual_output_a)
        self.assertEqual(expected_output_b, actual_output_b)

    before_template = '''
heat_template_version: 2015-10-15
resources:
  test_resource_a:
    type: OS::Heat::TestResource
    properties:
      value: 'foo'
outputs:
'''

    after_template = '''
heat_template_version: 2015-10-15
resources:
  test_resource_a:
    type: OS::Heat::TestResource
    properties:
      value: 'foo'
  test_resource_b:
    type: OS::Heat::TestResource
    properties:
      value: {get_attr: [test_resource_a, output]}
outputs:
  output_value:
    description: 'Output of resource b'
    value: {get_attr: [test_resource_b, output]}
'''

    def test_outputs_update_new_resource(self):
        stack_identifier = self.stack_create(template=self.before_template)
        self.update_stack(stack_identifier, template=self.after_template)

        expected_output_value = {
            u'output_value': u'foo', u'output_key': u'output_value',
            u'description': u'Output of resource b'}
        actual_output_value = self.client.stacks.output_show(
            stack_identifier, 'output_value')['output']
        self.assertEqual(expected_output_value, actual_output_value)

    nested_template = '''
heat_template_version: 2015-10-15
resources:
  parent:
    type: 1.yaml
outputs:
  resource_output_a:
    value: { get_attr: [parent, resource_output_a] }
    description: 'parent a'
  resource_output_b:
    value: { get_attr: [parent, resource_output_b] }
    description: 'parent b'
    '''
    error_template = '''
heat_template_version: 2015-10-15
resources:
  test_resource_a:
    type: OS::Heat::TestResource
    properties:
      value: 'a'
  test_resource_b:
    type: OS::Heat::TestResource
    properties:
      value: 'b'
outputs:
  resource_output_a:
    description: 'Output of resource a'
    value: { get_attr: [test_resource_a, output] }
  resource_output_b:
    description: 'Output of resource b'
    value: { get_param: foo }
'''

    def test_output_error_nested(self):
        stack_identifier = self.stack_create(
            template=self.nested_template,
            files={'1.yaml': self.error_template}
        )
        self.update_stack(stack_identifier, template=self.nested_template,
                          files={'1.yaml': self.error_template})
        expected_list = [{u'output_key': u'resource_output_a',
                          u'output_value': u'a',
                          u'description': u'parent a'},
                         {u'output_key': u'resource_output_b',
                          u'output_value': None,
                          u'output_error': u'Error in parent output '
                                           u'resource_output_b: The Parameter'
                                           u' (foo) was not provided.',
                          u'description': u'parent b'}]

        actual_list = self.client.stacks.get(stack_identifier).outputs
        sorted_actual_list = sorted(actual_list, key=lambda x: x['output_key'])
        self.assertEqual(expected_list, sorted_actual_list)
