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


class EncryptedParametersTest(test.HeatIntegrationTest):

    template = '''
heat_template_version: 2013-05-23
parameters:
  foo:
    type: string
    description: Parameter with encryption turned on
    hidden: true
    default: secret
outputs:
  encrypted_foo_param:
    description: ''
    value: {get_param: foo}
'''

    def setUp(self):
        super(EncryptedParametersTest, self).setUp()
        self.client = self.orchestration_client

    def test_db_encryption(self):
        # Create a stack with a non-default value for 'foo' to be encrypted
        foo_param = 'my_encrypted_foo'
        stack_identifier = self.stack_create(
            template=self.template,
            parameters={'foo': foo_param}
        )
        stack = self.client.stacks.get(stack_identifier)

        # Verify the output value for 'foo' parameter
        for out in stack.outputs:
            if out['output_key'] == 'encrypted_foo_param':
                self.assertEqual(foo_param, out['output_value'])
