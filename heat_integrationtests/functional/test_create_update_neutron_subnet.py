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
      allocation_pools: [{start: 11.11.11.10, end: 11.11.11.250}]
outputs:
  alloc_pools:
    value: {get_attr: [subnet, allocation_pools]}
'''


class UpdateSubnetTest(test.HeatIntegrationTest):

    def setUp(self):
        super(UpdateSubnetTest, self).setUp()
        self.client = self.orchestration_client

    def get_alloc_pools(self, stack_identifier):
        stack = self.client.stacks.get(stack_identifier)
        alloc_pools = self._stack_output(stack, 'alloc_pools')
        return alloc_pools

    def test_update_allocation_pools(self):
        stack_identifier = self.stack_create(template=test_template)
        alloc_pools = self.get_alloc_pools(stack_identifier)
        self.assertEqual([{'start': '11.11.11.10', 'end': '11.11.11.250'}],
                         alloc_pools)

        # Update allocation_pools with a new range
        templ_other_pool = test_template.replace(
            'allocation_pools: [{start: 11.11.11.10, end: 11.11.11.250}]',
            'allocation_pools: [{start: 11.11.11.10, end: 11.11.11.100}]')
        self.update_stack(stack_identifier, templ_other_pool)
        new_alloc_pools = self.get_alloc_pools(stack_identifier)
        # the new pools should be the new range
        self.assertEqual([{'start': '11.11.11.10', 'end': '11.11.11.100'}],
                         new_alloc_pools)

    def test_update_allocation_pools_to_empty(self):
        stack_identifier = self.stack_create(template=test_template)
        alloc_pools = self.get_alloc_pools(stack_identifier)
        self.assertEqual([{'start': '11.11.11.10', 'end': '11.11.11.250'}],
                         alloc_pools)

        # Update allocation_pools with []
        templ_empty_pools = test_template.replace(
            'allocation_pools: [{start: 11.11.11.10, end: 11.11.11.250}]',
            'allocation_pools: []')
        self.update_stack(stack_identifier, templ_empty_pools)
        new_alloc_pools = self.get_alloc_pools(stack_identifier)
        # new_alloc_pools should be []
        self.assertEqual([], new_alloc_pools)

    def test_update_to_no_allocation_pools(self):
        stack_identifier = self.stack_create(template=test_template)
        alloc_pools = self.get_alloc_pools(stack_identifier)
        self.assertEqual([{'start': '11.11.11.10', 'end': '11.11.11.250'}],
                         alloc_pools)

        # Remove the allocation_pools from template
        templ_no_pools = test_template.replace(
            'allocation_pools: [{start: 11.11.11.10, end: 11.11.11.250}]',
            '')
        self.update_stack(stack_identifier, templ_no_pools)
        last_alloc_pools = self.get_alloc_pools(stack_identifier)
        # last_alloc_pools should be []
        self.assertEqual([], last_alloc_pools)
