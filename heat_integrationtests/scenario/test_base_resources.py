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
from heat_integrationtests.scenario import scenario_base
from heatclient.common import template_utils


class BasicResourcesTest(scenario_base.ScenarioTestsBase):

    def setUp(self):
        super(BasicResourcesTest, self).setUp()
        if not self.conf.image_ref:
            raise self.skipException("No image configured to test")
        if not self.conf.instance_type:
            raise self.skipException("No flavor configured to test")

    def check_stack(self):
        sid = self.stack_identifier
        # Check that stack were created
        self._wait_for_stack_status(sid, 'CREATE_COMPLETE')
        server_resource = self.client.resources.get(sid, 'server')
        server_id = server_resource.physical_resource_id
        server = self.compute_client.servers.get(server_id)
        self.assertEqual(server.id, server_id)

        stack = self.client.stacks.get(sid)

        server_networks = self._stack_output(stack, 'server_networks')
        self.assertIn(self.private_net_name, server_networks)

    def test_base_resources_integration(self):
        """Define test for base resources interation from core porjects

        The alternative scenario is the following:
            1. Create a stack with basic resources from core projects.
            2. Check that all stack resources are created successfully.
            3. Wait for deployment.
            4. Check that stack was created.
            5. Check stack outputs.
        """

        self.private_net_name = test.rand_name('heat-net')
        parameters = {
            'key_name': test.rand_name('heat-key'),
            'flavor': self.conf.instance_type,
            'image': self.conf.image_ref,
            'vol_size': self.conf.volume_size,
            'private_net_name': self.private_net_name
        }

        env_files, env = template_utils.process_environment_and_files(
            self.conf.boot_config_env)

        # Launch stack
        self.stack_identifier = self.launch_stack(
            template_name='test_base_resources.yaml',
            parameters=parameters,
            expected_status=None,
            environment=env
        )

        # Check stack
        self.check_stack()
