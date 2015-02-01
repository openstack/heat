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

test_template = '''
heat_template_version: 2014-10-16

description: Auto-scaling Test

parameters:
  image_id:
    type: string
    label: Image ID
    description: Image ID from configurations
  capacity:
    type: string
    label: Capacity
    description: Auto-scaling group desired capacity
  fixed_subnet_name:
    type: string
    label: fixed subnetwork ID
    description: subnetwork ID used for autoscaling
  instance_type:
    type: string
    label: instance_type
    description: type of instance to launch

resources:
  test_pool:
    type: OS::Neutron::Pool
    properties:
      description: Test Pool
      lb_method: ROUND_ROBIN
      name: test_pool
      protocol: HTTP
      subnet: { get_param: fixed_subnet_name }
      vip: {
        "description": "Test VIP",
        "protocol_port": 80,
        "name": "test_vip"
      }
  load_balancer:
    type: OS::Neutron::LoadBalancer
    properties:
      protocol_port: 80
      pool_id: { get_resource: test_pool }
  launch_config:
    type: AWS::AutoScaling::LaunchConfiguration
    properties:
      ImageId: { get_param: image_id }
      InstanceType: { get_param: instance_type }
  server_group:
    type: AWS::AutoScaling::AutoScalingGroup
    properties:
      AvailabilityZones : ["nova"]
      LaunchConfigurationName : { get_resource : launch_config }
      MinSize : 1
      MaxSize : 5
      DesiredCapacity: { get_param: capacity }
      LoadBalancerNames : [ { get_resource : load_balancer } ]
'''


class NeutronAutoscalingTest(test.HeatIntegrationTest):
    """"
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
                              "fixed_subnet_name":
                                  self.conf.fixed_subnet_name,
                              }}

        # Create stack
        stack_id = self.stack_create(template=test_template,
                                     environment=env)

        members = self.network_client.list_members()
        self.assertEqual(1, len(members["members"]))

        # Increase desired capacity and update the stack
        env["parameters"]["capacity"] = "2"
        self.update_stack(stack_id,
                          template=test_template,
                          environment=env)

        upd_members = self.network_client.list_members()
        self.assertEqual(2, len(upd_members["members"]))