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


class StackSnapshotRestoreTest(functional_base.FunctionalTestsBase):

    def setUp(self):
        super(StackSnapshotRestoreTest, self).setUp()
        if not self.conf.minimal_image_ref:
            raise self.skipException("No image configured to test")

        if not self.conf.minimal_instance_type:
            raise self.skipException(
                "No minimal_instance_type configured to test")

        self.assign_keypair()

    def test_stack_snapshot_restore(self):
        template = '''
heat_template_version: ocata
parameters:
  keyname:
    type: string
  flavor:
    type: string
  image:
    type: string
  network:
    type: string
resources:
  my_port:
    type: OS::Neutron::Port
    properties:
      network: {get_param: network}
  my_server:
    type: OS::Nova::Server
    properties:
      image: {get_param: image}
      flavor: {get_param: flavor}
      key_name: {get_param: keyname}
      networks: [{port: {get_resource: my_port} }]

'''

        def get_server_image(server_id):
            server = self.compute_client.servers.get(server_id)
            return server.image['id']

        parameters = {'keyname': self.keypair_name,
                      'flavor': self.conf.minimal_instance_type,
                      'image': self.conf.minimal_image_ref,
                      'network': self.conf.fixed_network_name}
        stack_identifier = self.stack_create(template=template,
                                             parameters=parameters)
        server_resource = self.client.resources.get(
            stack_identifier, 'my_server')
        server_id = server_resource.physical_resource_id
        prev_image_id = get_server_image(server_id)

        # Do snapshot and restore
        snapshot_id = self.stack_snapshot(stack_identifier)
        self.stack_restore(stack_identifier, snapshot_id)

        self.assertNotEqual(prev_image_id, get_server_image(server_id))
