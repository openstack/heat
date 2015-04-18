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

from heat_integrationtests.scenario import scenario_base


class NeutronAutoscalingTest(scenario_base.ScenarioTestsBase):
    """
    The class is responsible for testing of neutron resources autoscaling.
    """

    def setUp(self):
        super(NeutronAutoscalingTest, self).setUp()
        if not self.conf.fixed_subnet_name:
            raise self.skipException("No sub-network configured to test")
        self.template_name = 'test_neutron_autoscaling.yaml'

    def test_neutron_autoscaling(self):
        """
        Check autoscaling of load balancer members in Heat.

        The alternative scenario is the following:
            1. Launch a stack with a load balancer.
            2. Check that the load balancer created
            one load balancer member for stack.
            3. Update stack definition: increase desired capacity of stack.
            4. Check that number of members in load balancer was increased.
        """

        parameters = {
            "image_id": self.conf.minimal_image_ref,
            "capacity": "1",
            "instance_type": self.conf.minimal_instance_type,
            "fixed_subnet_name": self.conf.fixed_subnet_name,
        }

        # Launch stack
        stack_id = self.launch_stack(
            template_name=self.template_name,
            parameters=parameters
        )

        # Check number of members
        pool_resource = self.client.resources.get(stack_id, 'test_pool')
        pool_members = self.network_client.list_members(
            pool_id=pool_resource.physical_resource_id)['members']
        self.assertEqual(1, len(pool_members))

        # Increase desired capacity and update the stack
        template = self._load_template(
            __file__, self.template_name, self.sub_dir
        )
        parameters["capacity"] = "2"
        self.update_stack(
            stack_id,
            template=template,
            parameters=parameters
        )

        # Check number of members
        pool_members = self.network_client.list_members(
            pool_id=pool_resource.physical_resource_id)['members']
        self.assertEqual(2, len(pool_members))
