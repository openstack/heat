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
'''


class UpdatePortTest(functional_base.FunctionalTestsBase):

    def get_port_id_and_ip(self, stack_identifier):
        resources = self.client.resources.list(stack_identifier)
        port_id = [res.physical_resource_id for res in resources
                   if res.resource_name == 'port']
        stack = self.client.stacks.get(stack_identifier)
        port_ip = self._stack_output(stack, 'port_ip')
        return port_id[0], port_ip

    def test_stack_update_replace_no_ip(self):
        templ_no_ip = test_template.replace('ip_address: 11.11.11.11', '')
        # create with default 'mac' parameter
        stack_identifier = self.stack_create(template=templ_no_ip)
        _id, _ip = self.get_port_id_and_ip(stack_identifier)

        # Update with another 'mac' parameter
        parameters = {'mac': '00-00-00-00-AA-AA'}
        self.update_stack(stack_identifier, templ_no_ip,
                          parameters=parameters)

        new_id, _ = self.get_port_id_and_ip(stack_identifier)
        # port id should be different
        self.assertNotEqual(_id, new_id)

    def test_stack_update_replace_with_ip(self):
        # create with default 'mac' parameter
        stack_identifier = self.stack_create(template=test_template)

        _id, _ip = self.get_port_id_and_ip(stack_identifier)

        # Update with another 'mac' parameter
        parameters = {'mac': '00-00-00-00-AA-AA'}

        # port should be replaced with same ip
        self.update_stack(stack_identifier, test_template,
                          parameters=parameters)

        new_id, new_ip = self.get_port_id_and_ip(stack_identifier)
        # port id should be different, ip should be the same
        self.assertEqual(_ip, new_ip)
        self.assertNotEqual(_id, new_id)

    def test_stack_update_replace_with_ip_rollback(self):
        # create with default 'mac' parameter
        stack_identifier = self.stack_create(template=test_template)

        _id, _ip = self.get_port_id_and_ip(stack_identifier)

        # Update with another 'mac' parameter
        parameters = {'mac': '00-00-00-00-AA-AA'}

        # make test resource failing during update
        fail_template = test_template.replace('fail: False',
                                              'fail: True')
        fail_template = fail_template.replace('value: Test1',
                                              'value: Rollback')

        # port should be replaced with same ip
        self.update_stack(stack_identifier, fail_template,
                          parameters=parameters,
                          expected_status='ROLLBACK_COMPLETE',
                          disable_rollback=False)

        new_id, new_ip = self.get_port_id_and_ip(stack_identifier)
        # port id and ip should be the same after rollback
        self.assertEqual(_ip, new_ip)
        self.assertEqual(_id, new_id)

    def test_stack_update_replace_with_ip_after_failed_update(self):
        # create with default 'mac' parameter
        stack_identifier = self.stack_create(template=test_template)

        _id, _ip = self.get_port_id_and_ip(stack_identifier)

        # Update with another 'mac' parameter
        parameters = {'mac': '00-00-00-00-AA-AA'}

        # make test resource failing during update
        fail_template = test_template.replace('fail: False',
                                              'fail: True')
        fail_template = fail_template.replace('value: Test1',
                                              'value: Rollback')

        # port should be replaced with same ip
        self.update_stack(stack_identifier, fail_template,
                          parameters=parameters,
                          expected_status='UPDATE_FAILED')

        # port should be replaced with same ip
        self.update_stack(stack_identifier, test_template,
                          parameters=parameters)

        new_id, new_ip = self.get_port_id_and_ip(stack_identifier)
        # ip should be the same, but port id should be different, because it's
        # restore replace
        self.assertEqual(_ip, new_ip)
        self.assertNotEqual(_id, new_id)

    def test_stack_update_in_place_remove_ip(self):
        # create with default 'mac' parameter and defined ip_address
        stack_identifier = self.stack_create(template=test_template)
        _id, _ip = self.get_port_id_and_ip(stack_identifier)

        # remove ip_address property and update stack
        templ_no_ip = test_template.replace('ip_address: 11.11.11.11', '')
        self.update_stack(stack_identifier, templ_no_ip)

        new_id, new_ip = self.get_port_id_and_ip(stack_identifier)
        # port should be updated with the same id
        self.assertEqual(_id, new_id)
