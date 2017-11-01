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

import yaml

from heat_integrationtests.functional import functional_base


class ReplaceDeprecatedResourceTest(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: "2013-05-23"
parameters:
  flavor:
    type: string
  image:
    type: string
  network:
    type: string

resources:
  config:
    type: OS::Heat::SoftwareConfig
    properties:
      config: xxxx

  server:
    type: OS::Nova::Server
    properties:
      image: {get_param: image}
      flavor: {get_param: flavor}
      networks: [{network: {get_param: network} }]
      user_data_format: SOFTWARE_CONFIG
  dep:
    type: OS::Heat::SoftwareDeployments
    properties:
        config: {get_resource: config}
        servers: {'0': {get_resource: server}}
        signal_transport: NO_SIGNAL
outputs:
  server:
    value: {get_resource: server}
'''

    deployment_group_snippet = '''
type: OS::Heat::SoftwareDeploymentGroup
properties:
  config: {get_resource: config}
  servers: {'0': {get_resource: server}}
  signal_transport: NO_SIGNAL
'''
    enable_cleanup = True

    def test_replace_software_deployments(self):
        parms = {'flavor': self.conf.minimal_instance_type,
                 'network': self.conf.fixed_network_name,
                 'image': self.conf.minimal_image_ref
                 }
        deployments_template = yaml.safe_load(self.template)
        stack_identifier = self.stack_create(
            parameters=parms,
            template=deployments_template,
            enable_cleanup=self.enable_cleanup)

        expected_resources = {'config': 'OS::Heat::SoftwareConfig',
                              'dep': 'OS::Heat::SoftwareDeployments',
                              'server': 'OS::Nova::Server'}
        self.assertEqual(expected_resources,
                         self.list_resources(stack_identifier))

        resource = self.client.resources.get(stack_identifier, 'dep')
        initial_phy_id = resource.physical_resource_id

        resources = deployments_template['resources']
        resources['dep'] = yaml.safe_load(self.deployment_group_snippet)
        self.update_stack(
            stack_identifier,
            deployments_template,
            parameters=parms)

        expected_new_resources = {'config': 'OS::Heat::SoftwareConfig',
                                  'dep': 'OS::Heat::SoftwareDeploymentGroup',
                                  'server': 'OS::Nova::Server'}
        self.assertEqual(expected_new_resources,
                         self.list_resources(stack_identifier))

        resource = self.client.resources.get(stack_identifier, 'dep')
        self.assertEqual(initial_phy_id, resource.physical_resource_id)
