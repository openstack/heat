# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from heat_integrationtests.common import test


class NeutronAutoscalingTest(test.HeatIntegrationTest):
    """
    The class is responsible for testing of neutron resources autoscaling.
    """

    def setUp(self):
        super(NeutronAutoscalingTest, self).setUp()
        self.client = self.orchestration_client
        if not self.conf.minimal_image_ref:
            raise self.skipException("No minimal image configured to test")
        if not self.conf.instance_type:
            raise self.skipException("No flavor configured to test")
        if not self.conf.fixed_subnet_name:
            raise self.skipException("No sub-network configured to test")

    def test_neutron_autoscaling(self):
        """
        Check autoscaling of load balancer members  in heat.

        The alternative scenario is the following:
            1. Initialize environment variables.
            2. Create a stack with a load balancer.
            3. Check that the load balancer created
            one load balancer member for stack.
            4. Update stack definition: increase desired capacity of stack.
            5. Check that number of members in load balancer was increased.
        """

        # Init env variables
        env = {'parameters': {"image_id": self.conf.minimal_image_ref,
                              "capacity": "1",
                              "instance_type": self.conf.instance_type,
                              "fixed_subnet_name": self.conf.fixed_subnet_name,
                              }}

        template = self._load_template(__file__,
                                       'test_neutron_autoscaling.yaml',
                                       'templates')
        # Create stack
        stack_id = self.stack_create(template=template,
                                     environment=env)

        members = self.network_client.list_members()
        self.assertEqual(1, len(members["members"]))

        # Increase desired capacity and update the stack
        env["parameters"]["capacity"] = "2"
        self.update_stack(stack_id,
                          template=template,
                          environment=env)

        upd_members = self.network_client.list_members()
        self.assertEqual(2, len(upd_members["members"]))
