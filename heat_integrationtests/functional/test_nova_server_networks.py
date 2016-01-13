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


server_with_sub_fixed_ip_template = '''
heat_template_version: 2016-04-08
description: Test template to test nova server with subnet and fixed_ip.
parameters:
  flavor:
    type: string
  image:
    type: string
resources:
  net:
    type: OS::Neutron::Net
    properties:
      name: my_net
  subnet:
    type: OS::Neutron::Subnet
    properties:
      network: {get_resource: net}
      cidr: 11.11.11.0/24
  server:
    type: OS::Nova::Server
    properties:
      image: {get_param: image}
      flavor: {get_param: flavor}
      networks:
        - subnet: {get_resource: subnet}
          fixed_ip: 11.11.11.11
outputs:
  networks:
    value: {get_attr: [server, networks]}
'''


class CreateServerTest(functional_base.FunctionalTestsBase):

    def setUp(self):
        super(CreateServerTest, self).setUp()

    def get_outputs(self, stack_identifier, output_key):
        stack = self.client.stacks.get(stack_identifier)
        output = self._stack_output(stack, output_key)
        return output

    def test_create_server_with_subnet_fixed_ip(self):
        parms = {'flavor': self.conf.minimal_instance_type,
                 'image': self.conf.minimal_image_ref}
        stack_identifier = self.stack_create(
            template=server_with_sub_fixed_ip_template,
            stack_name='server_with_sub_ip',
            parameters=parms)
        networks = self.get_outputs(stack_identifier, 'networks')
        self.assertEqual(['11.11.11.11'], networks['my_net'])
