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

from neutronclient.common import exceptions as qe
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import net
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


neutron_template = '''
heat_template_version: rocky
description: Template to test network Neutron resource
resources:
  network:
    type: OS::Neutron::Net
    properties:
      name: the_network
      tenant_id: c1210485b2424d48804aad5d39c61b8f
      shared: true
      dhcp_agent_ids:
        - 28c25a04-3f73-45a7-a2b4-59e183943ddc
      port_security_enabled: False
      dns_domain: openstack.org.
      tags:
        - tag1
        - tag2

  subnet:
    type: OS::Neutron::Subnet
    properties:
      network: { get_resource: network }
      tenant_id: c1210485b2424d48804aad5d39c61b8f
      ip_version: 4
      cidr: 10.0.3.0/24
      allocation_pools:
        - start: 10.0.3.20
          end: 10.0.3.150
      host_routes:
        - destination: 10.0.4.0/24
          nexthop: 10.0.3.20
      dns_nameservers:
        - 8.8.8.8

  router:
    type: OS::Neutron::Router
    properties:
      l3_agent_ids:
        - 792ff887-6c85-4a56-b518-23f24fa65581

  router_interface:
    type: OS::Neutron::RouterInterface
    properties:
      router_id: {get_resource: router}
      subnet: {get_resource : subnet}

  gateway:
    type: OS::Neutron::RouterGateway
    properties:
      router_id: {get_resource: router}
      network: {get_resource : network}
'''


class NeutronNetTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronNetTest, self).setUp()
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_net(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = net.Net('test_net', resource_defns[resource_name], stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_net(self):
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)
        resource_type = 'networks'
        net_info_build = {"network": {
            "status": "BUILD",
            "subnets": [],
            "name": "name",
            "admin_state_up": True,
            "shared": True,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            "mtu": 0
        }}
        net_info_active = copy.deepcopy(net_info_build)
        net_info_active['network'].update({'status': 'ACTIVE'})
        agent_info = {
            "agents": [{
                "admin_state_up": True,
                "agent_type": "DHCP agent",
                "alive": True,
                "binary": "neutron-dhcp-agent",
                "configurations": {
                    "dhcp_driver": "DummyDriver",
                    "dhcp_lease_duration": 86400,
                    "networks": 0,
                    "ports": 0,
                    "subnets": 0,
                    "use_namespaces": True},
                "created_at": "2014-03-20 05:12:34",
                "description": None,
                "heartbeat_timestamp": "2014-03-20 05:12:34",
                "host": "hostname",
                "id": "28c25a04-3f73-45a7-a2b4-59e183943ddc",
                "started_at": "2014-03-20 05:12:34",
                "topic": "dhcp_agent"
            }]
        }
        create_mock = self.patchobject(neutronclient.Client, 'create_network')
        create_mock.return_value = net_info_build
        list_dhcp_agent_mock = self.patchobject(
            neutronclient.Client,
            'list_dhcp_agent_hosting_networks')
        list_dhcp_agent_mock.side_effect = [{"agents": []},
                                            agent_info]
        add_dhcp_agent_mock = self.patchobject(
            neutronclient.Client,
            'add_network_to_dhcp_agent')

        remove_dhcp_agent_mock = self.patchobject(
            neutronclient.Client,
            'remove_network_from_dhcp_agent')
        replace_tag_mock = self.patchobject(
            neutronclient.Client,
            'replace_tag')
        show_network_mock = self.patchobject(
            neutronclient.Client,
            'show_network')
        show_network_mock.side_effect = [
            net_info_build,
            net_info_active,
            qe.NetworkNotFoundClient(status_code=404),
            net_info_active,
            net_info_active,
            qe.NetworkNotFoundClient(status_code=404)]
        update_net_mock = self.patchobject(
            neutronclient.Client,
            'update_network')

        del_net_mock = self.patchobject(
            neutronclient.Client,
            'delete_network')
        del_net_mock.side_effect = [None,
                                    qe.NetworkNotFoundClient(status_code=404)]

        self.patchobject(neutron.NeutronClientPlugin, 'get_qos_policy_id',
                         return_value='0389f747-7785-4757-b7bb-2ab07e4b09c3')

        self.patchobject(stack['router'], 'FnGetRefId',
                         return_value='792ff887-6c85-4a56-b518-23f24fa65581')

        # network create
        rsrc = self.create_net(t, stack, 'network')
        create_mock.assert_called_with(
            {'network':
                {'name': u'the_network',
                 'admin_state_up': True,
                 'tenant_id': u'c1210485b2424d48804aad5d39c61b8f',
                 'dns_domain': u'openstack.org.',
                 'shared': True,
                 'port_security_enabled': False}
             }
        )
        add_dhcp_agent_mock.assert_called_with(
            '28c25a04-3f73-45a7-a2b4-59e183943ddc',
            {'network_id': u'fc68ea2c-b60b-4b4f-bd82-94ec81110766'})
        replace_tag_mock.assert_called_with(
            resource_type,
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'tags': ['tag1', 'tag2']}
        )

        # assert the implicit dependency between the gateway and the interface
        deps = stack.dependencies[stack['router_interface']]
        self.assertIn(stack['gateway'], deps)

        # assert the implicit dependency between the gateway and the subnet
        deps = stack.dependencies[stack['subnet']]
        self.assertIn(stack['gateway'], deps)

        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)

        self.assertIsNone(rsrc.FnGetAtt('status'))
        self.assertEqual('ACTIVE', rsrc.FnGetAtt('status'))
        self.assertEqual(0, rsrc.FnGetAtt('mtu'))
        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Foo')

        # update tests
        prop_diff = {
            "name": "mynet",
            "dhcp_agent_ids": [
                "bb09cfcd-5277-473d-8336-d4ed8628ae68"
            ],
            'qos_policy': '0389f747-7785-4757-b7bb-2ab07e4b09c3'
        }
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      prop_diff)
        rsrc.handle_update(update_snippet, {}, prop_diff)
        update_net_mock.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'network': {
                'name': 'mynet',
                'qos_policy_id': '0389f747-7785-4757-b7bb-2ab07e4b09c3'
            }})
        add_dhcp_agent_mock.assert_called_with(
            'bb09cfcd-5277-473d-8336-d4ed8628ae68',
            {'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'})
        remove_dhcp_agent_mock.assert_called_with(
            '28c25a04-3f73-45a7-a2b4-59e183943ddc',
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        )
        # Update with None qos_policy
        prop_diff['qos_policy'] = None
        rsrc.handle_update(update_snippet, {}, prop_diff)
        update_net_mock.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'network': {
                'name': 'mynet',
                'qos_policy_id': None
            }}
        )
        # Update with value_specs
        prop_diff['value_specs'] = {"port_security_enabled": True}
        rsrc.handle_update(update_snippet, {}, prop_diff)
        update_net_mock.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'network': {
                'name': 'mynet',
                'port_security_enabled': True,
                'qos_policy_id': None
            }}
        )
        # Update with name = None
        rsrc.handle_update(update_snippet, {}, {'name': None})
        update_net_mock.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'network': {
                'name': utils.PhysName(stack.name, 'test_net'),
            }}
        )
        # Update with tags=[]
        rsrc.handle_update(update_snippet, {}, {'tags': []})
        replace_tag_mock.assert_called_with(
            resource_type,
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'tags': []}
        )
        # Update with empty prop_diff
        rsrc.handle_update(update_snippet, {}, {})

        # update delete
        scheduler.TaskRunner(rsrc.delete)()
        del_net_mock.assert_called_with('fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        # delete raise not found
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

    def test_net_get_live_state(self):
        tmpl = """
        heat_template_version: rocky
        resources:
          net:
            type: OS::Neutron::Net
            properties:
              value_specs:
                'test:property': test_value
         """
        t = template_format.parse(tmpl)
        stack = utils.parse_stack(t)
        show_net = self.patchobject(neutronclient.Client, 'show_network')
        show_net.return_value = {'network': {'status': 'ACTIVE'}}
        self.patchobject(neutronclient.Client,
                         'list_dhcp_agent_hosting_networks',
                         return_value={'agents': [{'id': '1111'}]})

        self.patchobject(neutronclient.Client, 'create_network',
                         return_value={"network": {
                             "status": "BUILD",
                             "subnets": [],
                             "qos_policy_id": "some",
                             "name": "name",
                             "admin_state_up": True,
                             "shared": True,
                             "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                             "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                             "mtu": 0
                         }})
        rsrc = self.create_net(t, stack, 'net')

        network_resp = {
            'name': 'net1-net-wkkl2vwupdee',
            'admin_state_up': True,
            'tenant_id': '30f466e3d14b4251853899f9c26e2b66',
            'mtu': 0,
            'router:external': False,
            'port_security_enabled': True,
            'shared': False,
            'qos_policy_id': 'some',
            'id': u'5a4bb8a0-5077-4f8a-8140-5430370020e6',
            'test:property': 'test_value_resp'
        }
        show_net.return_value = {'network': network_resp}

        reality = rsrc.get_live_state(rsrc.properties)
        expected = {
            'admin_state_up': True,
            'qos_policy': "some",
            'value_specs': {
                'test:property': 'test_value_resp'
            },
            'port_security_enabled': True,
            'dhcp_agent_ids': ['1111']
        }
        self.assertEqual(set(expected.keys()), set(reality.keys()))
        for key in expected:
            if key == 'dhcp_agent_ids':
                self.assertEqual(set(expected[key]), set(reality[key]))
                continue
            self.assertEqual(expected[key], reality[key])
