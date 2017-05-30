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
  security_group:
    type: OS::Neutron::SecurityGroup
    properties:
      name: the_sg
      description: Ping and SSH
      rules:
      - protocol: icmp
      - protocol: tcp
        port_range_min: 22
        port_range_max: 22
  server:
    type: OS::Nova::Server
    properties:
      image: {get_param: image}
      flavor: {get_param: flavor}
      networks:
        - subnet: {get_resource: subnet}
          fixed_ip: 11.11.11.11
      security_groups:
        - {get_resource: security_group}
outputs:
  networks:
    value: {get_attr: [server, networks]}
'''

server_with_port_template = '''
heat_template_version: 2016-04-08
description: Test template to test nova server with port.
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
  port:
    type: OS::Neutron::Port
    properties:
      network: {get_resource: net}
      fixed_ips:
        - subnet: {get_resource: subnet}
          ip_address: 11.11.11.11
  server:
    type: OS::Nova::Server
    properties:
      image: {get_param: image}
      flavor: {get_param: flavor}
      networks:
        - port: {get_resource: port}
'''


class CreateServerTest(functional_base.FunctionalTestsBase):

    def get_outputs(self, stack_identifier, output_key):
        stack = self.client.stacks.get(stack_identifier)
        return self._stack_output(stack, output_key)

    def test_create_server_with_subnet_fixed_ip_sec_group(self):
        parms = {'flavor': self.conf.minimal_instance_type,
                 'image': self.conf.minimal_image_ref}
        stack_identifier = self.stack_create(
            template=server_with_sub_fixed_ip_template,
            stack_name='server_with_sub_ip',
            parameters=parms)

        networks = self.get_outputs(stack_identifier, 'networks')
        self.assertEqual(['11.11.11.11'], networks['my_net'])

        server_resource = self.client.resources.get(
            stack_identifier, 'server')
        server_id = server_resource.physical_resource_id
        server = self.compute_client.servers.get(server_id)
        self.assertEqual([{"name": "the_sg"}], server.security_groups)

    def test_create_update_server_with_subnet(self):
        parms = {'flavor': self.conf.minimal_instance_type,
                 'image': self.conf.minimal_image_ref}
        template = server_with_sub_fixed_ip_template.replace(
            'fixed_ip: 11.11.11.11',
            'fixed_ip: 11.11.11.22').replace(
            'name: my_net', 'name: your_net')
        stack_identifier = self.stack_create(
            template=template,
            stack_name='create_server_with_sub_ip',
            parameters=parms)
        networks = self.get_outputs(stack_identifier, 'networks')
        self.assertEqual(['11.11.11.22'], networks['your_net'])

        # update the server only with subnet, we won't pass
        # both port_id and net_id to attach interface, then update success
        template_only_subnet = template.replace(
            'fixed_ip: 11.11.11.22', '')
        self.update_stack(stack_identifier,
                          template_only_subnet,
                          parameters=parms)
        new_networks = self.get_outputs(stack_identifier, 'networks')
        self.assertNotEqual(['11.11.11.22'], new_networks['your_net'])

    def test_create_server_with_port(self):
        parms = {'flavor': self.conf.minimal_instance_type,
                 'image': self.conf.minimal_image_ref}
        # We just want to make sure we can create the server, no need to assert
        # anything
        self.stack_create(
            template=server_with_port_template,
            stack_name='server_with_port',
            parameters=parms)
