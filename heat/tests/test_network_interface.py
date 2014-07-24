#
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

import copy

from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils

try:
    from neutronclient.v2_0 import client as neutronclient
except ImportError:
    neutronclient = None

test_template = {
    'heat_template_version': '2013-05-23',
    'resources': {
        'my_nic': {
            'type': 'AWS::EC2::NetworkInterface',
            'properties': {
                'SubnetId': 'ssss'
            }
        }
    }
}


class NetworkInterfaceTest(HeatTestCase):
    def setUp(self):
        super(NetworkInterfaceTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.m.StubOutWithMock(neutronclient.Client, 'show_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'create_port')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_port')
        self.m.StubOutWithMock(neutronclient.Client, 'update_port')
        self.stub_keystoneclient()

    def mock_show_subnet(self):
        neutronclient.Client.show_subnet('ssss').AndReturn({
            'subnet': {
                'name': 'my_subnet',
                'network_id': 'nnnn',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'allocation_pools': [{'start': '10.0.0.2',
                                      'end': '10.0.0.254'}],
                'gateway_ip': '10.0.0.1',
                'ip_version': 4,
                'cidr': '10.0.0.0/24',
                'id': 'ssss',
                'enable_dhcp': False,
            }})

    def mock_create_network_interface(self, stack_name='my_stack',
                                      resource_name='my_nic',
                                      security_groups=None):
        self.nic_name = utils.PhysName(stack_name, resource_name)
        port = {'network_id': 'nnnn',
                'fixed_ips': [{
                    'subnet_id': u'ssss'
                }],
                'name': self.nic_name,
                'admin_state_up': True}

        port_info = {
            'port': {
                'admin_state_up': True,
                'device_id': '',
                'device_owner': '',
                'fixed_ips': [
                    {
                        'ip_address': '10.0.0.100',
                        'subnet_id': 'ssss'
                    }
                ],
                'id': 'pppp',
                'mac_address': 'fa:16:3e:25:32:5d',
                'name': self.nic_name,
                'network_id': 'nnnn',
                'status': 'ACTIVE',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'
            }
        }

        if security_groups is not None:
            port['security_groups'] = security_groups
            port_info['security_groups'] = security_groups
        else:
            port_info['security_groups'] = ['default']

        neutronclient.Client.create_port({'port': port}).AndReturn(port_info)

    def mock_update_network_interface(self, update_props, port_id='pppp'):
        neutronclient.Client.update_port(
            port_id,
            {'port': update_props}).AndReturn(None)

    def mock_delete_network_interface(self, port_id='pppp'):
        neutronclient.Client.delete_port(port_id).AndReturn(None)

    def test_network_interface_create_update_delete(self):
        my_stack = utils.parse_stack(test_template, stack_name='my_stack')
        nic_rsrc = my_stack['my_nic']

        self.mock_show_subnet()
        self.mock_create_network_interface()

        update_props = {}
        update_sg_ids = ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        update_props['security_groups'] = update_sg_ids

        self.mock_update_network_interface(update_props)
        self.mock_delete_network_interface()

        self.m.ReplayAll()
        # create the nic without GroupSet
        self.assertIsNone(nic_rsrc.validate())
        scheduler.TaskRunner(nic_rsrc.create)()
        self.assertEqual((nic_rsrc.CREATE, my_stack.COMPLETE),
                         nic_rsrc.state)

        # update the nic with GroupSet
        props = copy.deepcopy(nic_rsrc.properties.data)
        props['GroupSet'] = update_sg_ids
        update_snippet = rsrc_defn.ResourceDefinition(nic_rsrc.name,
                                                      nic_rsrc.type(),
                                                      props)
        scheduler.TaskRunner(nic_rsrc.update, update_snippet)()
        self.assertEqual((nic_rsrc.UPDATE, nic_rsrc.COMPLETE), nic_rsrc.state)

        # delete the nic
        scheduler.TaskRunner(nic_rsrc.delete)()
        self.assertEqual((nic_rsrc.DELETE, nic_rsrc.COMPLETE), nic_rsrc.state)

        self.m.VerifyAll()
