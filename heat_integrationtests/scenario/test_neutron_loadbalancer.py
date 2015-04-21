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

from six.moves import urllib

from heat_integrationtests.scenario import scenario_base


class NeutronLoadBalancerTest(scenario_base.ScenarioTestsBase):
    """
    The class is responsible for testing of neutron resources balancer.
    """

    def setUp(self):
        super(NeutronLoadBalancerTest, self).setUp()
        self.public_net = self._get_network(self.conf.floating_network_name)
        self.template_name = 'test_neutron_loadbalancer.yaml'

    def collect_responses(self, ip, expected_resp):
        resp = set()
        for count in range(10):
            time.sleep(1)
            resp.add(urllib.request.urlopen('http://%s/' % ip).read())

        self.assertEqual(expected_resp, resp)

    def test_neutron_loadbalancer(self):
        """
        Check work of Neutron LBaaS resource in Heat.

        The alternative scenario is the following:
            1. Launch a stack with a load balancer, two servers,
               but use only one as a LB member.
            2. Check connection to the servers and LB.
            3. Collect info about responces, which were received by LB from
               its members (responces have to be received only from 'server1').
            4. Update stack definition: include 'server2' into LBaaS.
            5. Check that number of members in LB was increased and
               responces were received from 'server1' and 'server2'.
        """

        parameters = {
            'key_name': self.keypair_name,
            'flavor': self.conf.minimal_instance_type,
            'image': self.conf.image_ref,
            'private_subnet_id': self.net['subnets'][0],
            'external_network_id': self.public_net['id'],
            'timeout': self.conf.build_timeout
        }

        # Launch stack
        sid = self.launch_stack(
            template_name=self.template_name,
            parameters=parameters
        )

        stack = self.client.stacks.get(sid)
        floating_ip = self._stack_output(stack, 'fip')
        vip = self._stack_output(stack, 'vip')
        server1_ip = self._stack_output(stack, 'serv1_ip')
        server2_ip = self._stack_output(stack, 'serv2_ip')

        # Check connection and info about received responses
        self.check_connectivity(server1_ip)
        self.collect_responses(server1_ip, {'server1\n'})

        self.check_connectivity(server2_ip)
        self.collect_responses(server2_ip, {'server2\n'})

        self.check_connectivity(vip)
        self.collect_responses(vip, {'server1\n'})

        self.check_connectivity(floating_ip)
        self.collect_responses(floating_ip, {'server1\n'})

        # Include 'server2' to LB and update the stack
        template = self._load_template(
            __file__, self.template_name, self.sub_dir
        )

        template = template.replace(
            '- { get_resource: server1 }',
            '- { get_resource: server1 }\n      - { get_resource: server2 }\n'
        )

        self.update_stack(
            sid,
            template=template,
            parameters=parameters
        )

        self.check_connectivity(vip)
        self.collect_responses(vip, {'server1\n', 'server2\n'})

        self.check_connectivity(floating_ip)
        self.collect_responses(floating_ip, {'server1\n', 'server2\n'})
