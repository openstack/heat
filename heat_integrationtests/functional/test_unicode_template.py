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


class StackUnicodeTemplateTest(functional_base.FunctionalTestsBase):

    random_template = u'''
heat_template_version: 2014-10-16
description: \u8fd9\u662f\u4e00\u4e2a\u63cf\u8ff0
parameters:
  \u53c2\u6570:
    type: number
    default: 10
    label: \u6807\u7b7e
    description: \u8fd9\u662f\u4e00\u4e2a\u63cf\u8ff0
resources:
  \u8d44\u6e90:
    type: OS::Heat::RandomString
    properties:
      length: {get_param: \u53c2\u6570}
outputs:
  \u8f93\u51fa:
    description: \u8fd9\u662f\u4e00\u4e2a\u63cf\u8ff0
    value: {get_attr: [\u8d44\u6e90, value]}
'''

    def setUp(self):
        super(StackUnicodeTemplateTest, self).setUp()

    def _assert_results(self, result):
        self.assertTrue(result['disable_rollback'])
        self.assertIsNone(result['parent'])
        self.assertEqual(u'\u8fd9\u662f\u4e00\u4e2a\u63cf\u8ff0',
                         result['template_description'])
        self.assertEqual(u'10', result['parameters'][u'\u53c2\u6570'])

    def _assert_preview_results(self, result):
        self._assert_results(result)
        res = result['resources'][0]
        self.assertEqual('/resources/%s' % res['resource_name'],
                         res['resource_identity']['path'])

    def _assert_create_results(self, result):
        self._assert_results(result)
        output = result['outputs'][0]
        self.assertEqual(u'\u8fd9\u662f\u4e00\u4e2a\u63cf\u8ff0',
                         output['description'])
        self.assertEqual(u'\u8f93\u51fa', output['output_key'])
        self.assertIsNotNone(output['output_value'])

    def _assert_resource_results(self, result):
        self.assertEqual(u'\u8d44\u6e90', result['resource_name'])
        self.assertEqual('OS::Heat::RandomString',
                         result['resource_type'])

    def test_template_validate_basic(self):
        ret = self.client.stacks.validate(template=self.random_template)
        expected = {
            'Description': u'\u8fd9\u662f\u4e00\u4e2a\u63cf\u8ff0',
            'Parameters': {
                u'\u53c2\u6570': {
                    'Default': 10,
                    'Description': u'\u8fd9\u662f\u4e00\u4e2a\u63cf\u8ff0',
                    'Label': u'\u6807\u7b7e',
                    'NoEcho': 'false',
                    'Type': 'Number'}
            }
        }
        self.assertEqual(expected, ret)

    def test_template_validate_override_default(self):
        env = {'parameters': {u'\u53c2\u6570': 5}}
        ret = self.client.stacks.validate(template=self.random_template,
                                          environment=env)
        expected = {
            'Description': u'\u8fd9\u662f\u4e00\u4e2a\u63cf\u8ff0',
            'Parameters': {
                u'\u53c2\u6570': {
                    'Default': 10,
                    'Value': 5,
                    'Description': u'\u8fd9\u662f\u4e00\u4e2a\u63cf\u8ff0',
                    'Label': u'\u6807\u7b7e',
                    'NoEcho': 'false',
                    'Type': 'Number'}
            }
        }
        self.assertEqual(expected, ret)

    def test_stack_preview(self):
        result = self.client.stacks.preview(
            template=self.random_template,
            stack_name=self._stack_rand_name(),
            disable_rollback=True).to_dict()
        self._assert_preview_results(result)

    def test_create_stack(self):
        stack_identifier = self.stack_create(template=self.random_template)
        stack = self.client.stacks.get(stack_identifier)
        self._assert_create_results(stack.to_dict())
        rl = self.client.resources.list(stack_identifier)
        self.assertEqual(1, len(rl))
        self._assert_resource_results(rl[0].to_dict())
