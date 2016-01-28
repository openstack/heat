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
        self.assertEqual(expected_list, actual_list)

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
