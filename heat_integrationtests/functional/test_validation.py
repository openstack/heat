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


class StackValidationTest(functional_base.FunctionalTestsBase):

    def setUp(self):
        super(StackValidationTest, self).setUp()
        if not self.conf.minimal_image_ref:
            raise self.skipException("No image configured to test")

        if not self.conf.minimal_instance_type:
            raise self.skipException(
                "No minimal_instance_type configured to test")

        self.assign_keypair()

    def test_stack_validate_provider_references_parent_resource(self):
        template = '''
heat_template_version: 2014-10-16
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
  config:
    type: My::Config
    properties:
        server: {get_resource: server}

  server:
    type: OS::Nova::Server
    properties:
      image: {get_param: image}
      flavor: {get_param: flavor}
      key_name: {get_param: keyname}
      networks: [{network: {get_param: network} }]
      user_data_format: SOFTWARE_CONFIG

'''
        config_template = '''
heat_template_version: 2014-10-16
parameters:
  server:
    type: string
resources:
  config:
    type: OS::Heat::SoftwareConfig

  deployment:
    type: OS::Heat::SoftwareDeployment
    properties:
      config:
        get_resource: config
      server:
        get_param: server
'''
        files = {'provider.yaml': config_template}
        env = {'resource_registry':
               {'My::Config': 'provider.yaml'}}
        parameters = {'keyname': self.keypair_name,
                      'flavor': self.conf.minimal_instance_type,
                      'image': self.conf.minimal_image_ref,
                      'network': self.conf.fixed_network_name}
        # Note we don't wait for CREATE_COMPLETE, because we're using a
        # minimal image without the tools to apply the config.
        # The point of the test is just to prove that validation won't
        # falsely prevent stack creation starting, ref bug #1407100
        # Note that we can be sure My::Config will stay IN_PROGRESS as
        # there's no signal sent to the deployment
        self.stack_create(template=template,
                          files=files,
                          environment=env,
                          parameters=parameters,
                          expected_status='CREATE_IN_PROGRESS')
