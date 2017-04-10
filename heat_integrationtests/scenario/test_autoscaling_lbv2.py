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

import time

import requests

from heat_integrationtests.common import test
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

    def check_num_responses(self, url, expected_num, retries=20):
        resp = set()
        for count in range(retries):
            time.sleep(2)
            try:
                r = requests.get(url, verify=self.verify_cert)
            except requests.exceptions.ConnectionError:
                # The LB may not be up yet, let's retry
                continue
            # skip unsuccessful requests
            if r.status_code == 200:
                resp.add(r.text)
                if len(resp) == expected_num:
                    break
        self.assertEqual(expected_num, len(resp))

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

        parameters = {
            'flavor': self.conf.minimal_instance_type,
            'image': self.conf.minimal_image_ref,
            'net': self.conf.fixed_network_name,
            'subnet': self.conf.fixed_subnet_name,
            'public_net': self.conf.floating_network_name
        }

        app_server_template = self._load_template(
            __file__, self.app_server_template_name, self.sub_dir
        )
        webapp_template = self._load_template(
            __file__, self.webapp_template_name, self.sub_dir
        )
        files = {'appserver.yaml': app_server_template,
                 'webapp.yaml': webapp_template}
        env = {'resource_registry':
               {'OS::Test::NeutronAppServer': 'appserver.yaml',
                'OS::Test::WebAppConfig': 'webapp.yaml'}}

        # Launch stack
        sid = self.launch_stack(
            template_name=self.template_name,
            parameters=parameters,
            files=files,
            environment=env
        )
        stack = self.client.stacks.get(sid)
        lb_url = self._stack_output(stack, 'lburl')
        # Check number of distinctive responces, must be 1
        self.check_num_responses(lb_url, 1)

        # Signal the scaling hook
        self.client.resources.signal(sid, 'scale_up')

        # Wait for AutoScalingGroup update to finish
        asg = self.client.resources.get(sid, 'asg')
        test.call_until_true(self.conf.build_timeout,
                             self.conf.build_interval,
                             self.check_autoscale_complete,
                             asg.physical_resource_id, 2, sid, 'scale_up')

        # Check number of distinctive responses, must now be 2
        self.check_num_responses(lb_url, 2)
