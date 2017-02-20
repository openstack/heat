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
heat_template_version: 2015-04-30
description: Test template to create port wit ip_address.
parameters:
  mac:
    type: string
    default: 00-00-00-00-BB-BB
resources:
  net:
    type: OS::Neutron::Net
  subnet:
    type: OS::Neutron::Subnet
    properties:
      enable_dhcp: false
      network: { get_resource: net }
      cidr: 11.11.11.0/24
  port:
    type: OS::Neutron::Port
    properties:
      network: {get_resource: net}
      mac_address: {get_param: mac}
      fixed_ips:
        - subnet: {get_resource: subnet}
          ip_address: 11.11.11.11
  test:
    depends_on: port
    type: OS::Heat::TestResource
    properties:
      value: Test1
      fail: False
outputs:
  port_ip:
    value: {get_attr: [port, fixed_ips, 0, ip_address]}
  mac_address:
    value: {get_attr: [port, mac_address]}
'''


class UpdatePortTest(functional_base.FunctionalTestsBase):

    def get_port_id_and_outputs(self, stack_identifier):
        resources = self.client.resources.list(stack_identifier)
        port_id = [res.physical_resource_id for res in resources
                   if res.resource_name == 'port']
        stack = self.client.stacks.get(stack_identifier)
        port_ip = self._stack_output(stack, 'port_ip')
        port_mac = self._stack_output(stack, 'mac_address')
        return port_id[0], port_ip, port_mac

    def test_update_remove_ip(self):
        # create with defined ip_address
        stack_identifier = self.stack_create(template=test_template)
        _id, _ip, _mac = self.get_port_id_and_outputs(stack_identifier)

        # remove ip_address property and update stack
        templ_no_ip = test_template.replace('ip_address: 11.11.11.11', '')
        self.update_stack(stack_identifier, templ_no_ip)

        new_id, new_ip, new_mac = self.get_port_id_and_outputs(
            stack_identifier)
        # port should be updated with the same id
        self.assertEqual(_id, new_id)
        self.assertEqual(_mac, new_mac)

    def test_update_with_mac_address(self):
        if not self.conf.admin_username or not self.conf.admin_password:
            self.skipTest('No admin creds found, skipping')

        # Setup admin clients for updating mac_address
        self.setup_clients_for_admin()

        # Create with default mac_address and defined ip_address
        stack_identifier = self.stack_create(template=test_template)
        _id, _ip, _mac = self.get_port_id_and_outputs(stack_identifier)

        # Update with another 'mac' parameter
        parameters = {'mac': '00-00-00-00-AA-AA'}
        self.update_stack(stack_identifier, test_template,
                          parameters=parameters)

        new_id, new_ip, new_mac = self.get_port_id_and_outputs(
            stack_identifier)
        # mac_address should be different
        self.assertEqual(_id, new_id)
        self.assertEqual(_ip, new_ip)
        self.assertNotEqual(_mac, new_mac)
