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

template_subnet_old_network = """
heat_template_version: 2016-10-14
parameters:
  net_cidr:
    type: string
resources:
  net:
    type: OS::Neutron::Net
  subnet:
    type: OS::Neutron::Subnet
    properties:
      cidr: { get_param: net_cidr }
      network_id: { get_resource: net }
"""

template_with_get_attr = """
heat_template_version: 2016-10-14
description: Test template to create/update subnet with translation
parameters:
  net_cidr:
    type: string
resources:
  net:
    type: OS::Neutron::Net
  net_value:
    type: OS::Heat::Value
    properties:
      value: { get_resource: net }
  subnet:
    type: OS::Neutron::Subnet
    properties:
      network: { get_attr: [net_value, value] }
      cidr: { get_param: net_cidr }
"""

template_value_from_nested_stack_main = """
heat_template_version: 2016-10-14
parameters:
  flavor:
    type: string
  image:
    type: string
  public_net:
    type: string
resources:
  network_settings:
    type: network.yaml
    properties:
      public_net: { get_param: public_net }
  server:
    type: OS::Nova::Server
    properties:
      flavor: { get_param: flavor }
      image: { get_param: image }
      networks: { get_attr: [network_settings, networks] }
"""

template_value_from_nested_stack_network = """
heat_template_version: 2016-10-14
parameters:
  public_net:
    type: string
outputs:
  networks:
    value:
      - uuid: { get_param: public_net }
"""


class TestTranslation(functional_base.FunctionalTestsBase):

    def test_create_update_subnet_old_network(self):
        # Just create and update where network is translated properly.
        env = {'parameters': {'net_cidr': '11.11.11.0/24'}}
        stack_identifier = self.stack_create(
            template=template_subnet_old_network,
            environment=env)
        env = {'parameters': {'net_cidr': '11.11.12.0/24'}}
        self.update_stack(stack_identifier,
                          template=template_subnet_old_network,
                          environment=env)

    def test_create_update_translation_with_get_attr(self):
        # Check create and update successful for translation function value.
        env = {'parameters': {'net_cidr': '11.11.11.0/24'}}
        stack_identifier = self.stack_create(
            template=template_with_get_attr,
            environment=env)
        env = {'parameters': {'net_cidr': '11.11.12.0/24'}}
        self.update_stack(stack_identifier,
                          template=template_with_get_attr,
                          environment=env)

    def test_value_from_nested_stack(self):
        env = {'parameters': {
            'flavor': self.conf.minimal_instance_type,
            'image': self.conf.minimal_image_ref,
            'public_net': self.conf.fixed_network_name
        }}
        self.stack_create(
            template=template_value_from_nested_stack_main,
            environment=env,
            files={'network.yaml': template_value_from_nested_stack_network})
