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


class ParallelDeploymentsTest(test.HeatIntegrationTest):
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
  server:
    type: OS::Nova::Server
    properties:
      image: {get_param: image}
      flavor: {get_param: flavor}
      user_data_format: SOFTWARE_CONFIG
      networks: [{network: {get_param: network} }]
  config:
    type: OS::Heat::SoftwareConfig
    properties:
      config: hi!
  dep1:
    type: OS::Heat::SoftwareDeployment
    properties:
      config: {get_resource: config}
      server: {get_resource: server}
      signal_transport: NO_SIGNAL
  dep2:
    type: OS::Heat::SoftwareDeployment
    properties:
      config: {get_resource: config}
      server: {get_resource: server}
      signal_transport: NO_SIGNAL
  dep3:
    type: OS::Heat::SoftwareDeployment
    properties:
      config: {get_resource: config}
      server: {get_resource: server}
      signal_transport: NO_SIGNAL
  dep4:
    type: OS::Heat::SoftwareDeployment
    properties:
      config: {get_resource: config}
      server: {get_resource: server}
      signal_transport: NO_SIGNAL
'''

    def setUp(self):
        super(ParallelDeploymentsTest, self).setUp()
        self.client = self.orchestration_client

    def test_fail(self):
        parms = {'flavor': self.conf.minimal_instance_type,
                 'network': self.conf.fixed_network_name,
                 'image': self.conf.minimal_image_ref}
        stack_identifier = self.stack_create(
            parameters=parms,
            template=self.template)
        stack = self.client.stacks.get(stack_identifier)
        server_metadata = self.client.resources.metadata(stack.id, 'server')
        self.assertEqual(4, len(server_metadata['deployments']))
