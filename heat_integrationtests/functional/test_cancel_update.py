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


class CancelUpdateTest(functional_base.FunctionalTestsBase):

    template = '''
heat_template_version: '2013-05-23'
parameters:
 InstanceType:
   type: string
 ImageId:
   type: string
 network:
   type: string
resources:
 port:
   type: OS::Neutron::Port
   properties:
     network: {get_param: network}
 Server:
   type: OS::Nova::Server
   properties:
     flavor_update_policy: REPLACE
     image: {get_param: ImageId}
     flavor: {get_param: InstanceType}
     networks:
       - port: {get_resource: port}
'''

    def setUp(self):
        super(CancelUpdateTest, self).setUp()
        if not self.conf.minimal_image_ref:
            raise self.skipException("No minimal image configured to test")
        if not self.conf.minimal_instance_type:
            raise self.skipException("No minimal flavor configured to test.")

    def test_cancel_update_server_with_port(self):
        parameters = {'InstanceType': self.conf.minimal_instance_type,
                      'ImageId': self.conf.minimal_image_ref,
                      'network': self.conf.fixed_network_name}

        stack_identifier = self.stack_create(template=self.template,
                                             parameters=parameters)
        parameters['InstanceType'] = self.conf.instance_type
        self.update_stack(stack_identifier, self.template,
                          parameters=parameters,
                          expected_status='UPDATE_IN_PROGRESS')

        self.cancel_update_stack(stack_identifier)
