# Copyright (c) 2017 Ericsson.
#
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

import copy
import yaml

from heat_integrationtests.functional import functional_base


test_template = '''
heat_template_version: pike
description: Test template to create, update, delete trunk.
resources:
  parent_net:
    type: OS::Neutron::Net
  trunk_net_one:
    type: OS::Neutron::Net
  trunk_net_two:
    type: OS::Neutron::Net
  parent_subnet:
    type: OS::Neutron::Subnet
    properties:
      network: { get_resource: parent_net }
      cidr: 10.0.0.0/16
  trunk_subnet_one:
    type: OS::Neutron::Subnet
    properties:
      network: { get_resource: trunk_net_one }
      cidr: 10.10.0.0/16
  trunk_subnet_two:
    type: OS::Neutron::Subnet
    properties:
      network: { get_resource: trunk_net_two }
      cidr: 10.20.0.0/16
  parent_port:
    type: OS::Neutron::Port
    properties:
      network: { get_resource: parent_net }
      name: trunk_parent_port
  sub_port_one:
    type: OS::Neutron::Port
    properties:
      network: { get_resource: trunk_net_one }
      name: trunk_sub_port_one
  sub_port_two:
    type: OS::Neutron::Port
    properties:
      network: { get_resource: trunk_net_two }
      name: trunk_sub_port_two
  trunk:
    type: OS::Neutron::Trunk
    properties:
      name: test_trunk
      port: { get_resource: parent_port }
      sub_ports:
outputs:
  trunk_parent_port:
    value: { get_attr: [trunk, port_id] }
'''


class UpdateTrunkTest(functional_base.FunctionalTestsBase):

    @staticmethod
    def _sub_ports_dict_to_set(sub_ports):
        new_sub_ports = copy.deepcopy(sub_ports)

        # NOTE(lajos katona): In the template we have to give the sub port as
        # port, but from trunk_details we receive back them with port_id.
        # As an extra trunk_details contains the mac_address as well which is
        # useless here.
        # So here we have to make sure that the dictionary (input from
        # template or output from trunk_details) have the same keys:
        if any('mac_address' in d for d in new_sub_ports):
            for sp in new_sub_ports:
                sp['port'] = sp['port_id']
                del sp['port_id']
                del sp['mac_address']

        # NOTE(lajos katona): We receive lists (trunk_details['sub_ports'] and
        # the input to the template) and we can't be sure that the order is the
        # same, so by using sets we can compare them.
        sub_ports_set = {frozenset(d.items()) for d in new_sub_ports}
        return sub_ports_set

    def test_add_first_sub_port(self):
        stack_identifier = self.stack_create(template=test_template)

        parsed_template = yaml.safe_load(test_template)
        new_sub_port = [{'port': {'get_resource': 'sub_port_one'},
                         'segmentation_id': 10,
                         'segmentation_type': 'vlan'}]
        parsed_template['resources']['trunk']['properties'][
            'sub_ports'] = new_sub_port
        updated_template = yaml.safe_dump(parsed_template)
        self.update_stack(stack_identifier, updated_template)

        # Fix the port_id in the template for assertion
        new_sub_port[0]['port'] = self.get_physical_resource_id(
            stack_identifier, 'sub_port_one')
        parent_id = self.get_stack_output(
            stack_identifier, 'trunk_parent_port')
        parent_port = self.network_client.show_port(parent_id)['port']
        trunk_sub_port = parent_port['trunk_details']['sub_ports']

        self.assertEqual(self._sub_ports_dict_to_set(new_sub_port),
                         self._sub_ports_dict_to_set(trunk_sub_port))

    def test_add_a_second_sub_port(self):
        parsed_template = yaml.safe_load(test_template)
        sub_ports = [{'port': {'get_resource': 'sub_port_one'},
                      'segmentation_type': 'vlan',
                      'segmentation_id': 10}, ]
        parsed_template['resources']['trunk']['properties'][
            'sub_ports'] = sub_ports
        template_with_sub_ports = yaml.safe_dump(parsed_template)

        stack_identifier = self.stack_create(template=template_with_sub_ports)

        new_sub_port = {'port': {'get_resource': 'sub_port_two'},
                        'segmentation_id': 20,
                        'segmentation_type': 'vlan'}
        parsed_template['resources']['trunk']['properties'][
            'sub_ports'].append(new_sub_port)

        updated_template = yaml.safe_dump(parsed_template)

        self.update_stack(stack_identifier, updated_template)

        # Fix the port_ids in the templates for assertion
        sub_ports[0]['port'] = self.get_physical_resource_id(
            stack_identifier, 'sub_port_one')
        new_sub_port['port'] = self.get_physical_resource_id(
            stack_identifier, 'sub_port_two')
        expected_sub_ports = [sub_ports[0], new_sub_port]

        parent_id = self.get_stack_output(
            stack_identifier, 'trunk_parent_port')
        parent_port = self.network_client.show_port(parent_id)['port']
        trunk_sub_ports = parent_port['trunk_details']['sub_ports']

        self.assertEqual(self._sub_ports_dict_to_set(expected_sub_ports),
                         self._sub_ports_dict_to_set(trunk_sub_ports))

    def test_remove_sub_port_from_trunk(self):
        sub_ports = [{'port': {'get_resource': 'sub_port_one'},
                      'segmentation_type': 'vlan',
                      'segmentation_id': 10},
                     {'port': {'get_resource': 'sub_port_two'},
                      'segmentation_type': 'vlan',
                      'segmentation_id': 20}]
        parsed_template = yaml.safe_load(test_template)
        parsed_template['resources']['trunk']['properties'][
            'sub_ports'] = sub_ports
        template_with_sub_ports = yaml.safe_dump(parsed_template)

        stack_identifier = self.stack_create(template=template_with_sub_ports)

        sub_port_to_be_removed = {'port': {'get_resource': 'sub_port_two'},
                                  'segmentation_type': 'vlan',
                                  'segmentation_id': 20}
        parsed_template['resources']['trunk'][
            'properties']['sub_ports'].remove(sub_port_to_be_removed)
        updated_template = yaml.safe_dump(parsed_template)

        self.update_stack(stack_identifier, updated_template)

        # Fix the port_ids in the templates for assertion
        sub_ports[0]['port'] = self.get_physical_resource_id(
            stack_identifier, 'sub_port_one')
        expected_sub_ports = [sub_ports[0]]

        parent_id = self.get_stack_output(
            stack_identifier, 'trunk_parent_port')
        parent_port = self.network_client.show_port(parent_id)['port']
        trunk_sub_ports = parent_port['trunk_details']['sub_ports']

        self.assertEqual(self._sub_ports_dict_to_set(expected_sub_ports),
                         self._sub_ports_dict_to_set(trunk_sub_ports))

    def test_remove_last_sub_port_from_trunk(self):
        sub_ports = [{'port': {'get_resource': 'sub_port_one'},
                      'segmentation_type': 'vlan',
                      'segmentation_id': 10}]
        parsed_template = yaml.safe_load(test_template)
        parsed_template['resources']['trunk']['properties'][
            'sub_ports'] = sub_ports

        template_with_sub_ports = yaml.safe_dump(parsed_template)
        stack_identifier = self.stack_create(template=template_with_sub_ports)

        sub_port_to_be_removed = {'port': {'get_resource': 'sub_port_one'},
                                  'segmentation_type': 'vlan',
                                  'segmentation_id': 10}

        parsed_template['resources']['trunk'][
            'properties']['sub_ports'] = []
        updated_template = yaml.safe_dump(parsed_template)

        self.update_stack(stack_identifier, updated_template)

        sub_port_to_be_removed['port'] = self.get_physical_resource_id(
            stack_identifier, 'sub_port_one')
        parent_id = self.get_stack_output(
            stack_identifier, 'trunk_parent_port')
        parent_port = self.network_client.show_port(parent_id)['port']
        trunk_sub_ports = parent_port['trunk_details']['sub_ports']

        self.assertNotEqual(
            self._sub_ports_dict_to_set([sub_port_to_be_removed]),
            self._sub_ports_dict_to_set(trunk_sub_ports))
        self.assertFalse(trunk_sub_ports,
                         'The returned sub ports (%s) in trunk_details is '
                         'not empty!' % trunk_sub_ports)

    def test_update_existing_sub_port_on_trunk(self):
        sub_ports = [{'port': {'get_resource': 'sub_port_one'},
                      'segmentation_type': 'vlan',
                      'segmentation_id': 10}]
        parsed_template = yaml.safe_load(test_template)
        parsed_template['resources']['trunk']['properties'][
            'sub_ports'] = sub_ports

        template_with_sub_ports = yaml.safe_dump(parsed_template)
        stack_identifier = self.stack_create(template=template_with_sub_ports)

        sub_port_id = self.get_physical_resource_id(
            stack_identifier, 'sub_port_one')
        parsed_template['resources']['trunk']['properties']['sub_ports'][0][
            'segmentation_id'] = 99
        updated_template = yaml.safe_dump(parsed_template)

        self.update_stack(stack_identifier, updated_template)
        updated_sub_port = {'port': sub_port_id,
                            'segmentation_type': 'vlan',
                            'segmentation_id': 99}
        parent_id = self.get_stack_output(
            stack_identifier, 'trunk_parent_port')
        parent_port = self.network_client.show_port(parent_id)['port']
        trunk_sub_ports = parent_port['trunk_details']['sub_ports']

        self.assertEqual(self._sub_ports_dict_to_set([updated_sub_port]),
                         self._sub_ports_dict_to_set(trunk_sub_ports))

    def test_update_trunk_name_and_description(self):
        new_name = 'pineapple'
        new_description = 'This is a test trunk'

        stack_identifier = self.stack_create(template=test_template)
        parsed_template = yaml.safe_load(test_template)
        parsed_template['resources']['trunk']['properties']['name'] = new_name
        parsed_template['resources']['trunk']['properties'][
            'description'] = new_description
        updated_template = yaml.safe_dump(parsed_template)
        self.update_stack(stack_identifier, template=updated_template)

        parent_id = self.get_stack_output(
            stack_identifier, 'trunk_parent_port')
        parent_port = self.network_client.show_port(parent_id)['port']
        trunk_id = parent_port['trunk_details']['trunk_id']

        trunk = self.network_client.show_trunk(trunk_id)['trunk']
        self.assertEqual(new_name, trunk['name'])
        self.assertEqual(new_description, trunk['description'])
