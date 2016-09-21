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
description: Test template to create/update subnet with allocation_pools.
resources:
  net:
    type: OS::Neutron::Net
  subnet:
    type: OS::Neutron::Subnet
    properties:
      network: { get_resource: net }
      cidr: 11.11.11.0/24
      gateway_ip: 11.11.11.5
      allocation_pools: [{start: 11.11.11.10, end: 11.11.11.250}]
outputs:
  alloc_pools:
    value: {get_attr: [subnet, allocation_pools]}
  gateway_ip:
    value: {get_attr: [subnet, gateway_ip]}
'''


class UpdateSubnetTest(functional_base.FunctionalTestsBase):

    def get_outputs(self, stack_identifier, output_key):
        stack = self.client.stacks.get(stack_identifier)
        output = self._stack_output(stack, output_key)
        return output

    def test_update_allocation_pools(self):
        stack_identifier = self.stack_create(template=test_template)
        alloc_pools = self.get_outputs(stack_identifier, 'alloc_pools')
        self.assertEqual([{'start': '11.11.11.10', 'end': '11.11.11.250'}],
                         alloc_pools)

        # Update allocation_pools with a new range
        templ_other_pool = test_template.replace(
            'allocation_pools: [{start: 11.11.11.10, end: 11.11.11.250}]',
            'allocation_pools: [{start: 11.11.11.10, end: 11.11.11.100}]')
        self.update_stack(stack_identifier, templ_other_pool)
        new_alloc_pools = self.get_outputs(stack_identifier, 'alloc_pools')
        # the new pools should be the new range
        self.assertEqual([{'start': '11.11.11.10', 'end': '11.11.11.100'}],
                         new_alloc_pools)

    def test_update_allocation_pools_to_empty(self):
        stack_identifier = self.stack_create(template=test_template)
        alloc_pools = self.get_outputs(stack_identifier, 'alloc_pools')
        self.assertEqual([{'start': '11.11.11.10', 'end': '11.11.11.250'}],
                         alloc_pools)

        # Update allocation_pools with []
        templ_empty_pools = test_template.replace(
            'allocation_pools: [{start: 11.11.11.10, end: 11.11.11.250}]',
            'allocation_pools: []')
        self.update_stack(stack_identifier, templ_empty_pools)
        new_alloc_pools = self.get_outputs(stack_identifier, 'alloc_pools')
        # new_alloc_pools should be []
        self.assertEqual([], new_alloc_pools)

    def test_update_to_no_allocation_pools(self):
        stack_identifier = self.stack_create(template=test_template)
        alloc_pools = self.get_outputs(stack_identifier, 'alloc_pools')
        self.assertEqual([{'start': '11.11.11.10', 'end': '11.11.11.250'}],
                         alloc_pools)

        # Remove the allocation_pools from template
        templ_no_pools = test_template.replace(
            'allocation_pools: [{start: 11.11.11.10, end: 11.11.11.250}]',
            '')
        self.update_stack(stack_identifier, templ_no_pools)
        last_alloc_pools = self.get_outputs(stack_identifier, 'alloc_pools')
        # last_alloc_pools should be []
        self.assertEqual([], last_alloc_pools)

    def test_update_gateway_ip(self):
        stack_identifier = self.stack_create(template=test_template)
        gw_ip = self.get_outputs(stack_identifier, 'gateway_ip')
        self.assertEqual('11.11.11.5', gw_ip)

        # Update gateway_ip
        templ_other_gw_ip = test_template.replace(
            'gateway_ip: 11.11.11.5', 'gateway_ip: 11.11.11.9')
        self.update_stack(stack_identifier, templ_other_gw_ip)
        new_gw_ip = self.get_outputs(stack_identifier, 'gateway_ip')
        # the gateway_ip should be the new one
        self.assertEqual('11.11.11.9', new_gw_ip)

    def test_update_gateway_ip_to_empty(self):
        stack_identifier = self.stack_create(template=test_template)
        gw_ip = self.get_outputs(stack_identifier, 'gateway_ip')
        self.assertEqual('11.11.11.5', gw_ip)

        # Update gateway_ip to null(resolve to '')
        templ_empty_gw_ip = test_template.replace(
            'gateway_ip: 11.11.11.5', 'gateway_ip: null')
        self.update_stack(stack_identifier, templ_empty_gw_ip)
        new_gw_ip = self.get_outputs(stack_identifier, 'gateway_ip')
        # new gateway_ip should be None
        self.assertIsNone(new_gw_ip)

    def test_update_to_no_gateway_ip(self):
        stack_identifier = self.stack_create(template=test_template)
        gw_ip = self.get_outputs(stack_identifier, 'gateway_ip')
        self.assertEqual('11.11.11.5', gw_ip)

        # Remove the gateway from template
        templ_no_gw_ip = test_template.replace(
            'gateway_ip: 11.11.11.5', '')
        self.update_stack(stack_identifier, templ_no_gw_ip)
        new_gw_ip = self.get_outputs(stack_identifier, 'gateway_ip')
        # new gateway_ip should be None
        self.assertIsNone(new_gw_ip)
