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

import json

from heat_integrationtests.common import exceptions
from heat_integrationtests.scenario import scenario_base


class CfnInitIntegrationTest(scenario_base.ScenarioTestsBase):
    """Testing cfn-init and cfn-signal workability."""

    def setUp(self):
        super(CfnInitIntegrationTest, self).setUp()
        if not self.conf.image_ref:
            raise self.skipException("No image configured to test")
        if not self.conf.instance_type:
            raise self.skipException("No flavor configured to test")

    def check_stack(self, sid):
        # Check status of all resources
        for res in ('WaitHandle', 'SmokeSecurityGroup', 'SmokeKeys',
                    'CfnUser', 'SmokeServer', 'SmokeServerElasticIp'):
            self._wait_for_resource_status(
                sid, res, 'CREATE_COMPLETE')

        server_resource = self.client.resources.get(sid, 'SmokeServer')
        server_id = server_resource.physical_resource_id
        server = self.compute_client.servers.get(server_id)

        try:
            self._wait_for_resource_status(
                sid, 'WaitCondition', 'CREATE_COMPLETE')
        finally:
            # attempt to log the server console regardless of WaitCondition
            # going to complete. This allows successful and failed cloud-init
            # logs to be compared
            self._log_console_output(servers=[server])

        stack = self.client.stacks.get(sid)

        # This is an assert of great significance, as it means the following
        # has happened:
        # - cfn-init read the provided metadata and wrote out a file
        # - a user was created and credentials written to the server
        # - a cfn-signal was built which was signed with provided credentials
        # - the wait condition was fulfilled and the stack has changed state
        wait_status = json.loads(
            self._stack_output(stack, 'WaitConditionStatus'))
        self.assertEqual('smoke test complete', wait_status['smoke_status'])

        # Check EIP attributes.
        server_floatingip_id = self._stack_output(stack,
                                                  'ElasticIp_Id')
        self.assertIsNotNone(server_floatingip_id)

        # Fetch EIP details.
        net_show = self.network_client.show_floatingip(
            floatingip=server_floatingip_id)
        floating_ip = net_show['floatingip']['floating_ip_address']
        port_id = net_show['floatingip']['port_id']

        # Ensure that EIP was assigned to server.
        port_show = self.network_client.show_port(port=port_id)
        self.assertEqual(server.id, port_show['port']['device_id'])
        server_ip = self._stack_output(stack, 'SmokeServerElasticIp')
        self.assertEqual(server_ip, floating_ip)

        # Check that created server is reachable
        if not self._ping_ip_address(server_ip):
            self._log_console_output(servers=[server])
            self.fail(
                "Timed out waiting for %s to become reachable" % server_ip)

        # Check that the user can authenticate with the generated keypair
        if self.keypair:
            try:
                linux_client = self.get_remote_client(
                    server_ip, username='ec2-user')
                linux_client.validate_authentication()
            except (exceptions.ServerUnreachable,
                    exceptions.SSHTimeout):
                self._log_console_output(servers=[server])
                raise

    def test_server_cfn_init(self):
        """Check cfn-init and cfn-signal availability on the created server.

        The alternative scenario is the following:
            1. Create a stack with a server and configured security group.
            2. Check that all stack resources were created.
            3. Check that created server is reachable.
            4. Check that stack was created successfully.
            5. Check that is it possible to connect to server
               via generated keypair.
        """
        parameters = {
            'key_name': self.keypair_name,
            'flavor': self.conf.instance_type,
            'image': self.conf.image_ref,
            'timeout': self.conf.build_timeout,
            'subnet': self.net['subnets'][0],
        }

        # Launch stack
        stack_id = self.launch_stack(
            template_name="test_server_cfn_init.yaml",
            parameters=parameters,
            expected_status=None
        )

        # Check stack
        self.check_stack(stack_id)
