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

test_template = '''
heat_template_version: 2014-10-16

resources:
  signal_handle:
    type: "OS::Heat::SwiftSignalHandle"

outputs:
  signal_curl:
    value: { get_attr: ['signal_handle', 'curl_cli'] }
    description: Swift signal cURL

  signal_url:
    value: { get_attr: ['signal_handle', 'endpoint'] }
    description: Swift signal URL
'''


class SwiftSignalHandleUpdateTest(functional_base.FunctionalTestsBase):

    def test_stack_update_same_template_replace_no_url(self):
        if not self.is_service_available('object-store'):
            self.skipTest('object-store service not available, skipping')
        stack_identifier = self.stack_create(template=test_template)
        stack = self.client.stacks.get(stack_identifier)
        orig_url = self._stack_output(stack, 'signal_url')
        orig_curl = self._stack_output(stack, 'signal_curl')
        self.update_stack(stack_identifier, test_template)
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual(orig_url, self._stack_output(stack, 'signal_url'))
        self.assertEqual(orig_curl, self._stack_output(stack, 'signal_curl'))
