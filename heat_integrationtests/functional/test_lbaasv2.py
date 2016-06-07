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

from oslo_log import log as logging

from heat_integrationtests.functional import functional_base

LOG = logging.getLogger(__name__)


class LoadBalancerv2Test(functional_base.FunctionalTestsBase):

    create_template = '''
heat_template_version: 2016-04-08
parameters:
    subnet:
        type: string
resources:
  loadbalancer:
    type: OS::Neutron::LBaaS::LoadBalancer
    properties:
      description: aLoadBalancer
      vip_subnet: { get_param: subnet }
  listener:
    type: OS::Neutron::LBaaS::Listener
    properties:
      description: aListener
      loadbalancer: { get_resource: loadbalancer }
      protocol: HTTP
      protocol_port: 80
      connection_limit: 5555
  pool:
    type: OS::Neutron::LBaaS::Pool
    properties:
      description: aPool
      lb_algorithm: ROUND_ROBIN
      protocol: HTTP
      listener: { get_resource: listener }
  poolmember:
    type: OS::Neutron::LBaaS::PoolMember
    properties:
      address: 1.1.1.1
      pool: { get_resource: pool }
      protocol_port: 1111
      subnet: { get_param: subnet }
      weight: 255
  # pm2
  healthmonitor:
    type: OS::Neutron::LBaaS::HealthMonitor
    properties:
      delay: 3
      type: HTTP
      timeout: 3
      max_retries: 3
      pool: { get_resource: pool }
outputs:
  loadbalancer:
    value: { get_attr: [ loadbalancer, show ] }
  pool:
    value: { get_attr: [ pool, show ] }
  poolmember:
    value: { get_attr: [ poolmember, show ] }
  listener:
    value: { get_attr: [ listener, show ] }
  healthmonitor:
    value: { get_attr: [ healthmonitor, show ] }
'''

    add_member = '''
  poolmember2:
    type: OS::Neutron::LBaaS::PoolMember
    properties:
      address: 2.2.2.2
      pool: { get_resource: pool }
      protocol_port: 2222
      subnet: { get_param: subnet }
      weight: 222
'''

    def setUp(self):
        super(LoadBalancerv2Test, self).setUp()
        if not self.is_network_extension_supported('lbaasv2'):
            self.skipTest('LBaasv2 extension not available, skipping')

    def test_create_update_loadbalancer(self):
        parameters = {
            'subnet': self.conf.fixed_subnet_name,
        }
        stack_identifier = self.stack_create(template=self.create_template,
                                             parameters=parameters)
        stack = self.client.stacks.get(stack_identifier)
        output = self._stack_output(stack, 'loadbalancer')
        self.assertEqual('ONLINE', output['operating_status'])

        template = self.create_template.replace('ROUND_ROBIN', 'SOURCE_IP')
        template = template.replace('3', '6')
        template = template.replace('255', '256')
        template = template.replace('5555', '7777')
        template = template.replace('aLoadBalancer', 'updatedLoadBalancer')
        template = template.replace('aPool', 'updatedPool')
        template = template.replace('aListener', 'updatedListener')
        self.update_stack(stack_identifier, template=template,
                          parameters=parameters)
        stack = self.client.stacks.get(stack_identifier)

        output = self._stack_output(stack, 'loadbalancer')
        self.assertEqual('ONLINE', output['operating_status'])
        self.assertEqual('updatedLoadBalancer', output['description'])
        output = self._stack_output(stack, 'pool')
        self.assertEqual('SOURCE_IP', output['lb_algorithm'])
        self.assertEqual('updatedPool', output['description'])
        output = self._stack_output(stack, 'poolmember')
        self.assertEqual(256, output['weight'])
        output = self._stack_output(stack, 'healthmonitor')
        self.assertEqual(6, output['delay'])
        self.assertEqual(6, output['timeout'])
        self.assertEqual(6, output['max_retries'])
        output = self._stack_output(stack, 'listener')
        self.assertEqual(7777, output['connection_limit'])
        self.assertEqual('updatedListener', output['description'])

    def test_add_delete_poolmember(self):
        parameters = {
            'subnet': self.conf.fixed_subnet_name,
        }
        stack_identifier = self.stack_create(template=self.create_template,
                                             parameters=parameters)
        stack = self.client.stacks.get(stack_identifier)
        output = self._stack_output(stack, 'loadbalancer')
        self.assertEqual('ONLINE', output['operating_status'])
        output = self._stack_output(stack, 'pool')
        self.assertEqual(1, len(output['members']))
        # add pool member
        template = self.create_template.replace('# pm2', self.add_member)
        self.update_stack(stack_identifier, template=template,
                          parameters=parameters)
        stack = self.client.stacks.get(stack_identifier)
        output = self._stack_output(stack, 'loadbalancer')
        self.assertEqual('ONLINE', output['operating_status'])
        output = self._stack_output(stack, 'pool')
        self.assertEqual(2, len(output['members']))
        # delete pool member
        self.update_stack(stack_identifier, template=self.create_template,
                          parameters=parameters)
        stack = self.client.stacks.get(stack_identifier)
        output = self._stack_output(stack, 'loadbalancer')
        self.assertEqual('ONLINE', output['operating_status'])
        output = self._stack_output(stack, 'pool')
        self.assertEqual(1, len(output['members']))
