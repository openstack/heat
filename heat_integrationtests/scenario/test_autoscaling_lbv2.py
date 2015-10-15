#
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


class AutoscalingLoadBalancerv2Test(scenario_base.ScenarioTestsBase):
    """The class is responsible for testing ASG + LBv2 scenario.

    The very common use case tested is an autoscaling group
    of some web application servers behind a loadbalancer.
    """

    def setUp(self):
        super(AutoscalingLoadBalancerv2Test, self).setUp()
        self.template_name = 'test_autoscaling_lbv2_neutron.yaml'
        self.app_server_template_name = 'app_server_lbv2_neutron.yaml'
        self.webapp_template_name = 'netcat-webapp.yaml'
        if not self.is_network_extension_supported('lbaasv2'):
            self.skipTest('LBaasv2 extension not available, skipping')

    def test_autoscaling_loadbalancer_neutron(self):
        """Check work of AutoScaing and Neutron LBaaS v2 resource in Heat.

        The scenario is the following:
            1. Launch a stack with a load balancer and autoscaling group
               of one server, wait until stack create is complete.
            2. Check that there is only one distinctive response from
               loadbalanced IP.
            3. Signal the scale_up policy, wait until all resources in
               autoscaling group are complete.
            4. Check that now there are two distinctive responses from
               loadbalanced IP.
        """

        # TODO(MRV): Place holder for AutoScaing and Neutron LBaaS v2 test
        pass
