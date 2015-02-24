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
import logging

from heat_integrationtests.common import exceptions
from heat_integrationtests.common import test

LOG = logging.getLogger(__name__)


class CfnInitIntegrationTest(test.HeatIntegrationTest):

    def setUp(self):
        super(CfnInitIntegrationTest, self).setUp()
        if not self.conf.image_ref:
            raise self.skipException("No image configured to test")
        self.assign_keypair()
        self.client = self.orchestration_client
        self.template_name = 'test_server_cfn_init.yaml'
        self.sub_dir = 'templates'

    def launch_stack(self):
        net = self._get_default_network()
        parameters = {
            'key_name': self.keypair_name,
            'flavor': self.conf.instance_type,
            'image': self.conf.image_ref,
            'timeout': self.conf.build_timeout,
            'subnet': net['subnets'][0],
        }

        # create the stack
        template = self._load_template(__file__, self.template_name,
                                       self.sub_dir)
        return self.stack_create(template=template,
                                 parameters=parameters)

    def check_stack(self, sid):
        self._wait_for_resource_status(
            sid, 'WaitHandle', 'CREATE_COMPLETE')
        self._wait_for_resource_status(
            sid, 'SmokeSecurityGroup', 'CREATE_COMPLETE')
        self._wait_for_resource_status(
            sid, 'SmokeKeys', 'CREATE_COMPLETE')
        self._wait_for_resource_status(
            sid, 'CfnUser', 'CREATE_COMPLETE')
        self._wait_for_resource_status(
            sid, 'SmokeServer', 'CREATE_COMPLETE')

        server_resource = self.client.resources.get(sid, 'SmokeServer')
        server_id = server_resource.physical_resource_id
        server = self.compute_client.servers.get(server_id)
        server_ip = server.networks[self.conf.network_for_ssh][0]

        if not self._ping_ip_address(server_ip):
            self._log_console_output(servers=[server])
            self.fail(
                "Timed out waiting for %s to become reachable" % server_ip)

        try:
            self._wait_for_resource_status(
                sid, 'WaitCondition', 'CREATE_COMPLETE')
        except (exceptions.StackResourceBuildErrorException,
                exceptions.TimeoutException) as e:
            raise e
        finally:
            # attempt to log the server console regardless of WaitCondition
            # going to complete. This allows successful and failed cloud-init
            # logs to be compared
            self._log_console_output(servers=[server])

        self._wait_for_stack_status(sid, 'CREATE_COMPLETE')

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

        if self.keypair:
            # Check that the user can authenticate with the generated
            # keypair
            try:
                linux_client = self.get_remote_client(
                    server_ip, username='ec2-user')
                linux_client.validate_authentication()
            except (exceptions.ServerUnreachable,
                    exceptions.SSHTimeout) as e:
                self._log_console_output(servers=[server])
                raise e

    def test_server_cfn_init(self):
        sid = self.launch_stack()
        self.check_stack(sid)
