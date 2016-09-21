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


class EncryptedParametersTest(functional_base.FunctionalTestsBase):

    template = '''
heat_template_version: 2014-10-16
parameters:
  image:
    type: string
  flavor:
    type: string
  network:
    type: string
  foo:
    type: string
    description: 'parameter with encryption turned on'
    hidden: true
    default: secret
resources:
  server_with_encrypted_property:
    type: OS::Nova::Server
    properties:
      name: { get_param: foo }
      image: { get_param: image }
      flavor: { get_param: flavor }
      networks: [{network: {get_param: network} }]
outputs:
  encrypted_foo_param:
    description: 'encrypted param'
    value: { get_param: foo }
'''

    def test_db_encryption(self):
        # Create a stack with the value of 'foo' to be encrypted
        foo_param = 'my_encrypted_foo'
        parameters = {
            "image": self.conf.minimal_image_ref,
            "flavor": self.conf.minimal_instance_type,
            'network': self.conf.fixed_network_name,
            "foo": foo_param
        }

        stack_identifier = self.stack_create(
            template=self.template,
            parameters=parameters
        )
        stack = self.client.stacks.get(stack_identifier)

        # Verify the output value for 'foo' parameter
        for out in stack.outputs:
            if out['output_key'] == 'encrypted_foo_param':
                self.assertEqual(foo_param, out['output_value'])
