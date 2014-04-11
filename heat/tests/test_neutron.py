
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

import mox
from testtools import skipIf

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.neutron import net
from heat.engine.resources.neutron.neutron import NeutronResource as qr
from heat.engine.resources.neutron import provider_net
from heat.engine.resources.neutron import router
from heat.engine.resources.neutron import subnet
from heat.engine import scheduler
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils

neutronclient = try_import('neutronclient.v2_0.client')
qe = try_import('neutronclient.common.exceptions')

neutron_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Neutron resources",
  "Parameters" : {},
  "Resources" : {
    "network": {
      "Type": "OS::Neutron::Net",
      "Properties": {
        "name": "the_network",
        "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
        "shared": true,
        "dhcp_agent_ids": [
          "28c25a04-3f73-45a7-a2b4-59e183943ddc"
        ]
      }
    },
    "unnamed_network": {
      "Type": "OS::Neutron::Net"
    },
    "admin_down_network": {
      "Type": "OS::Neutron::Net",
      "Properties": {
        "admin_state_up": false
      }
    },
    "subnet": {
      "Type": "OS::Neutron::Subnet",
      "Properties": {
        "network_id": { "Ref" : "network" },
        "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
        "ip_version": 4,
        "cidr": "10.0.3.0/24",
        "allocation_pools": [{"start": "10.0.3.20", "end": "10.0.3.150"}],
        "host_routes": [
            {"destination": "10.0.4.0/24", "nexthop": "10.0.3.20"}],
        "dns_nameservers": ["8.8.8.8"]
      }
    },
    "port": {
      "Type": "OS::Neutron::Port",
      "Properties": {
        "device_id": "d6b4d3a5-c700-476f-b609-1493dd9dadc0",
        "name": "port1",
        "network_id": { "Ref" : "network" },
        "fixed_ips": [{
          "subnet_id": { "Ref" : "subnet" },
          "ip_address": "10.0.3.21"
        }]
      }
    },
    "port2": {
      "Type": "OS::Neutron::Port",
      "Properties": {
        "name": "port2",
        "network_id": { "Ref" : "network" }
      }
    },
    "router": {
      "Type": "OS::Neutron::Router",
      "Properties": {
        "l3_agent_id": "792ff887-6c85-4a56-b518-23f24fa65581"
      }
    },
    "router_interface": {
      "Type": "OS::Neutron::RouterInterface",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "subnet_id": { "Ref" : "subnet" }
      }
    },
    "gateway": {
      "Type": "OS::Neutron::RouterGateway",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "network_id": { "Ref" : "network" }
      }
    }
  }
}
'''

provider_network_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Neutron resources",
  "Resources" : {
    "provider_network_vlan": {
      "Type": "OS::Neutron::ProviderNet",
      "Properties": {
        "name": "the_provider_network",
        "network_type": "vlan",
        "physical_network": "physnet_1",
        "segmentation_id": "101",
        "shared": true
      }
    }
  }
}
'''

neutron_external_gateway_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Neutron resources",
  "Parameters" : {},
  "Resources" : {
    "router": {
      "Type": "OS::Neutron::Router",
      "Properties": {
        "name": "Test Router",
        "external_gateway_info": {
          "network": "public",
          "enable_snat": true
        }
      }
    }
  }
}
'''

neutron_floating_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Neutron resources",
  "Parameters" : {},
  "Resources" : {
    "port_floating": {
      "Type": "OS::Neutron::Port",
      "Properties": {
        "network_id": "xyz1234",
        "fixed_ips": [{
          "subnet_id": "sub1234",
          "ip_address": "10.0.0.10"
        }]
      }
    },
    "floating_ip": {
      "Type": "OS::Neutron::FloatingIP",
      "Properties": {
        "floating_network_id": "abcd1234",
      }
    },
    "floating_ip_assoc": {
      "Type": "OS::Neutron::FloatingIPAssociation",
      "Properties": {
        "floatingip_id": { "Ref" : "floating_ip" },
        "port_id": { "Ref" : "port_floating" }
      }
    },
    "router": {
      "Type": "OS::Neutron::Router"
    },
    "gateway": {
      "Type": "OS::Neutron::RouterGateway",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "network_id": "abcd1234"
      }
    }
  }
}
'''

neutron_port_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Neutron resources",
  "Parameters" : {},
  "Resources" : {
    "port": {
      "Type": "OS::Neutron::Port",
      "Properties": {
        "network_id": "net1234",
        "fixed_ips": [{
          "subnet_id": "sub1234",
          "ip_address": "10.0.3.21"
        }],
        "device_owner": "network:dhcp"
      }
    }
  }
}
'''

neutron_port_with_address_pair_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Neutron resources",
  "Parameters" : {},
  "Resources" : {
    "port": {
      "Type": "OS::Neutron::Port",
      "Properties": {
        "network_id": "abcd1234",
        "allowed_address_pairs": [{
          "ip_address": "10.0.3.21",
          "mac_address": "00-B0-D0-86-BB-F7"
        }]
      }
    }
  }
}
'''

neutron_subnet_and_external_gateway_template = '''
{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Resources": {
    "net_external": {
      "Type": "OS::Neutron::Net",
      "Properties": {
        "name": "net_external",
        "admin_state_up": true,
        "value_specs": {
          "provider:network_type": "flat",
          "provider:physical_network": "default",
          "router:external": true
        }
      }
    },
    "subnet_external": {
      "Type": "OS::Neutron::Subnet",
      "Properties": {
        "name": "subnet_external",
        "network_id": {
          "Ref": "net_external"
        },
        "ip_version": 4,
        "cidr": "192.168.10.0/24",
        "gateway_ip": "192.168.10.11",
        "enable_dhcp": false
      }
    },
    "router": {
      "Type": "OS::Neutron::Router",
      "Properties": {
        "name": "router_heat",
        "external_gateway_info": {
          "network": {
            "Ref": "net_external"
          }
        }
      }
    }
  }
}
'''

stpna = {
    "network": {
        "status": "ACTIVE",
        "subnets": [],
        "name": "the_provider_network",
        "admin_state_up": True,
        "shared": True,
        "provider:network_type": "vlan",
        "provider:physical_network": "physnet_1",
        "provider:segmentation_id": "101",
        "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
        "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
    }
}

stpnb = copy.deepcopy(stpna)
stpnb['network']['status'] = "BUILD"


class NeutronTest(HeatTestCase):

    def test_validate_properties(self):
        vs = {'router:external': True}
        data = {'admin_state_up': False,
                'value_specs': vs}
        p = properties.Properties(net.Net.properties_schema, data)
        self.assertIsNone(qr.validate_properties(p))

        vs['shared'] = True
        self.assertEqual('shared not allowed in value_specs',
                         qr.validate_properties(p))
        vs.pop('shared')

        vs['name'] = 'foo'
        self.assertEqual('name not allowed in value_specs',
                         qr.validate_properties(p))
        vs.pop('name')

        vs['tenant_id'] = '1234'
        self.assertEqual('tenant_id not allowed in value_specs',
                         qr.validate_properties(p))
        vs.pop('tenant_id')

        vs['foo'] = '1234'
        self.assertIsNone(qr.validate_properties(p))

    def test_prepare_properties(self):
        data = {'admin_state_up': False,
                'value_specs': {'router:external': True}}
        p = properties.Properties(net.Net.properties_schema, data)
        props = qr.prepare_properties(p, 'resource_name')
        self.assertEqual({'name': 'resource_name',
                          'router:external': True,
                          'admin_state_up': False,
                          'shared': False}, props)

    def test_is_built(self):
        self.assertTrue(qr.is_built({
            'name': 'the_net',
            'status': 'ACTIVE'
        }))
        self.assertTrue(qr.is_built({
            'name': 'the_net',
            'status': 'DOWN'
        }))
        self.assertFalse(qr.is_built({
            'name': 'the_net',
            'status': 'BUILD'
        }))
        self.assertRaises(exception.Error, qr.is_built, {
            'name': 'the_net',
            'status': 'FROBULATING'
        })


@skipIf(neutronclient is None, 'neutronclient unavailable')
class NeutronNetTest(HeatTestCase):

    def setUp(self):
        super(NeutronNetTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_network')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_network')
        self.m.StubOutWithMock(neutronclient.Client, 'show_network')
        self.m.StubOutWithMock(neutronclient.Client, 'update_network')
        self.m.StubOutWithMock(neutronclient.Client,
                               'add_network_to_dhcp_agent')
        self.m.StubOutWithMock(neutronclient.Client,
                               'remove_network_from_dhcp_agent')
        self.m.StubOutWithMock(neutronclient.Client,
                               'list_dhcp_agent_hosting_networks')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_net(self, t, stack, resource_name):
        rsrc = net.Net('test_net', t['Resources'][resource_name], stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_net(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())

        # Create script
        neutronclient.Client.create_network({
            'network': {
                'name': u'the_network',
                'admin_state_up': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'shared': True}
        }).AndReturn({"network": {
            "status": "BUILD",
            "subnets": [],
            "name": "name",
            "admin_state_up": True,
            "shared": True,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        neutronclient.Client.list_dhcp_agent_hosting_networks(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({"agents": []})

        neutronclient.Client.add_network_to_dhcp_agent(
            '28c25a04-3f73-45a7-a2b4-59e183943ddc',
            {'network_id': u'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}
        ).AndReturn(None)

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({"network": {
            "status": "BUILD",
            "subnets": [],
            "name": "name",
            "admin_state_up": True,
            "shared": True,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({"network": {
            "status": "ACTIVE",
            "subnets": [],
            "name": "name",
            "admin_state_up": True,
            "shared": True,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.NetworkNotFoundClient(status_code=404))

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({"network": {
            "status": "ACTIVE",
            "subnets": [],
            "name": "name",
            "admin_state_up": True,
            "shared": True,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({"network": {
            "status": "ACTIVE",
            "subnets": [],
            "name": "name",
            "admin_state_up": True,
            "shared": True,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        # Update script
        neutronclient.Client.list_dhcp_agent_hosting_networks(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({
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
        })

        neutronclient.Client.add_network_to_dhcp_agent(
            'bb09cfcd-5277-473d-8336-d4ed8628ae68',
            {'network_id': u'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}
        ).AndReturn(None)

        neutronclient.Client.remove_network_from_dhcp_agent(
            '28c25a04-3f73-45a7-a2b4-59e183943ddc',
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        neutronclient.Client.update_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'network': {
                'shared': True,
                'name': 'mynet',
                'admin_state_up': True
            }}).AndReturn(None)

        # Delete script
        neutronclient.Client.delete_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.NetworkNotFoundClient(status_code=404))

        neutronclient.Client.delete_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.NetworkNotFoundClient(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_net(t, stack, 'network')

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
        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Foo')
        update_snippet = {
            "Type": "OS::Neutron::Net",
            "Properties": {
                "name": "mynet",
                "shared": True,
                "admin_state_up": True,
                "dhcp_agent_ids": [
                    "bb09cfcd-5277-473d-8336-d4ed8628ae68"
                ]
            }
        }
        prop_diff = {
            "name": "mynet",
            "dhcp_agent_ids": [
                "bb09cfcd-5277-473d-8336-d4ed8628ae68"
            ]
        }
        rsrc.handle_update(update_snippet, {}, prop_diff)

        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()


@skipIf(neutronclient is None, 'neutronclient unavailable')
class NeutronProviderNetTest(HeatTestCase):
    def setUp(self):
        super(NeutronProviderNetTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_network')
        self.m.StubOutWithMock(neutronclient.Client, 'show_network')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_network')
        self.m.StubOutWithMock(neutronclient.Client, 'update_network')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_provider_net(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())

        # Create script
        neutronclient.Client.create_network({
            'network': {
                'name': u'the_provider_network',
                'admin_state_up': True,
                'provider:network_type': 'vlan',
                'provider:physical_network': 'physnet_1',
                'provider:segmentation_id': '101',
                'shared': True}
        }).AndReturn(stpnb)

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(stpnb)

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(stpna)

        t = template_format.parse(provider_network_template)
        stack = utils.parse_stack(t)
        rsrc = provider_net.ProviderNet(
            'provider_net', t['Resources']['provider_network_vlan'], stack)

        return rsrc

    def test_create_provider_net(self):
        rsrc = self.create_provider_net()

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.NetworkNotFoundClient(status_code=404))

        # Delete script
        neutronclient.Client.delete_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(stpna)

        neutronclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.NetworkNotFoundClient(status_code=404))

        neutronclient.Client.delete_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.NetworkNotFoundClient(status_code=404))

        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)

        self.assertIsNone(rsrc.FnGetAtt('status'))
        self.assertEqual('ACTIVE', rsrc.FnGetAtt('status'))
        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Foo')

        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_provider_net(self):
        rsrc = self.create_provider_net()

        neutronclient.Client.update_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'network': {
                'shared': True,
                'name': 'prov_net',
                'admin_state_up': True,
                'provider:network_type': 'vlan',
                'provider:physical_network': 'physnet_1',
                'provider:segmentation_id': '102'
            }}).AndReturn(None)

        self.m.ReplayAll()

        rsrc.validate()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        update_snippet = {
            "Type": "OS::Neutron::ProviderNet",
            "Properties": {
                "name": "prov_net",
                "shared": True,
                "admin_state_up": True,
                "network_type": "vlan",
                "physical_network": "physnet_1",
                "segmentation_id": "102"
            }
        }
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, {}))
        self.m.VerifyAll()


@skipIf(neutronclient is None, 'neutronclient unavailable')
class NeutronSubnetTest(HeatTestCase):

    def setUp(self):
        super(NeutronSubnetTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'show_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'update_subnet')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_subnet(self, t, stack, resource_name):
        rsrc = subnet.Subnet('test_subnet', t['Resources'][resource_name],
                             stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_subnet(self):

        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_subnet({
            'subnet': {
                'name': utils.PhysName('test_stack', 'test_subnet'),
                'network_id': u'None',
                'dns_nameservers': [u'8.8.8.8'],
                'allocation_pools': [
                    {'start': u'10.0.3.20', 'end': u'10.0.3.150'}],
                'host_routes': [
                    {'destination': u'10.0.4.0/24', 'nexthop': u'10.0.3.20'}],
                'ip_version': 4,
                'cidr': u'10.0.3.0/24',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'enable_dhcp': True
            }
        }).AndReturn({
            "subnet": {
                "allocation_pools": [
                    {"start": "10.0.3.20", "end": "10.0.3.150"}],
                "cidr": "10.0.3.0/24",
                "dns_nameservers": ["8.8.8.8"],
                "enable_dhcp": True,
                "gateway_ip": "10.0.3.1",
                "host_routes": [
                    {"destination": "10.0.4.0/24", "nexthop": "10.0.3.20"}],
                "id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
                "ip_version": 4,
                "name": "name",
                "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f"
            }
        })
        neutronclient.Client.show_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1').AndRaise(
                qe.NeutronClientException(status_code=404))
        sn = {
            "subnet": {
                "name": "name",
                "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                "allocation_pools": [
                    {"start": "10.0.3.20", "end": "10.0.3.150"}],
                "gateway_ip": "10.0.3.1",
                'host_routes': [
                    {'destination': u'10.0.4.0/24', 'nexthop': u'10.0.3.20'}],
                "ip_version": 4,
                "cidr": "10.0.3.0/24",
                "dns_nameservers": ["8.8.8.8"],
                "id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
                "enable_dhcp": True,
            }
        }
        neutronclient.Client.show_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1').AndReturn(sn)
        neutronclient.Client.show_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1').AndReturn(sn)
        neutronclient.Client.show_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1').AndReturn(sn)

        # Update script
        neutronclient.Client.update_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1',
            {'subnet': {
                'dns_nameservers': ['8.8.8.8', '192.168.1.254'],
                'name': 'mysubnet',
                'enable_dhcp': True
            }}
        )

        # Delete script
        neutronclient.Client.delete_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1'
        ).AndReturn(None)

        neutronclient.Client.show_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1'
        ).AndRaise(qe.NeutronClientException(status_code=404))

        neutronclient.Client.delete_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1'
        ).AndRaise(qe.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_subnet(t, stack, 'subnet')

        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('91e47a57-7508-46fe-afc9-fc454e8580e1', ref_id)
        self.assertIsNone(rsrc.FnGetAtt('network_id'))
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         rsrc.FnGetAtt('network_id'))
        self.assertEqual('8.8.8.8', rsrc.FnGetAtt('dns_nameservers')[0])

        # assert the dependency (implicit or explicit) between the ports
        # and the subnet
        self.assertIn(stack['port'], stack.dependencies[stack['subnet']])
        self.assertIn(stack['port2'], stack.dependencies[stack['subnet']])

        update_snippet = {
            "Type": "OS::Neutron::Subnet",
            "Properties": {
                "name": 'mysubnet',
                "network_id": {"Ref": "network"},
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                "ip_version": 4,
                "cidr": "10.0.3.0/24",
                "allocation_pools": [
                    {"start": "10.0.3.20", "end": "10.0.3.150"}],
                "dns_nameservers": ["8.8.8.8", "192.168.1.254"],
                'host_routes': [
                    {'destination': u'10.0.4.0/24', 'nexthop': u'10.0.3.20'}]
            }
        }
        rsrc.handle_update(stack.resolve_static_data(update_snippet), {}, {})

        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.m.VerifyAll()

    def test_subnet_disable_dhcp(self):

        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_subnet({
            'subnet': {
                'name': utils.PhysName('test_stack', 'test_subnet'),
                'network_id': u'None',
                'dns_nameservers': [u'8.8.8.8'],
                'allocation_pools': [
                    {'start': u'10.0.3.20', 'end': u'10.0.3.150'}],
                'host_routes': [
                    {'destination': u'10.0.4.0/24', 'nexthop': u'10.0.3.20'}],
                'ip_version': 4,
                'enable_dhcp': False,
                'cidr': u'10.0.3.0/24',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'
            }
        }).AndReturn({
            "subnet": {
                "allocation_pools": [
                    {"start": "10.0.3.20", "end": "10.0.3.150"}],
                "host_routes": [
                    {"destination": "10.0.4.0/24", "nexthop": "10.0.3.20"}],
                "cidr": "10.0.3.0/24",
                "dns_nameservers": ["8.8.8.8"],
                "enable_dhcp": False,
                "gateway_ip": "10.0.3.1",
                "id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
                "ip_version": 4,
                "name": "name",
                "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f"
            }
        })

        neutronclient.Client.show_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1').AndReturn({
                "subnet": {
                    "name": "name",
                    "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                    "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                    "allocation_pools": [
                        {"start": "10.0.3.20", "end": "10.0.3.150"}],
                    "host_routes": [
                        {"destination": "10.0.4.0/24",
                         "nexthop": "10.0.3.20"}],
                    "gateway_ip": "10.0.3.1",
                    "ip_version": 4,
                    "cidr": "10.0.3.0/24",
                    "dns_nameservers": ["8.8.8.8"],
                    "id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
                    "enable_dhcp": False,
                }
            })

        neutronclient.Client.delete_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1'
        ).AndReturn(None)

        neutronclient.Client.show_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1'
        ).AndRaise(qe.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        t['Resources']['subnet']['Properties']['enable_dhcp'] = 'False'
        stack = utils.parse_stack(t)
        rsrc = self.create_subnet(t, stack, 'subnet')

        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('91e47a57-7508-46fe-afc9-fc454e8580e1', ref_id)
        self.assertIs(False, rsrc.FnGetAtt('enable_dhcp'))
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_null_gateway_ip(self):
        p = {}
        subnet.Subnet._null_gateway_ip(p)
        self.assertEqual({}, p)

        p = {'foo': 'bar'}
        subnet.Subnet._null_gateway_ip(p)
        self.assertEqual({'foo': 'bar'}, p)

        p = {
            'foo': 'bar',
            'gateway_ip': '198.51.100.0'
        }
        subnet.Subnet._null_gateway_ip(p)
        self.assertEqual({
            'foo': 'bar',
            'gateway_ip': '198.51.100.0'
        }, p)

        p = {
            'foo': 'bar',
            'gateway_ip': ''
        }
        subnet.Subnet._null_gateway_ip(p)
        self.assertEqual({
            'foo': 'bar',
            'gateway_ip': None
        }, p)

        # This should not happen as prepare_properties
        # strips out None values, but testing anyway
        p = {
            'foo': 'bar',
            'gateway_ip': None
        }
        subnet.Subnet._null_gateway_ip(p)
        self.assertEqual({
            'foo': 'bar',
            'gateway_ip': None
        }, p)


@skipIf(neutronclient is None, 'neutronclient unavailable')
class NeutronRouterTest(HeatTestCase):

    @skipIf(router.neutronV20 is None, "Missing Neutron v2_0")
    def setUp(self):
        super(NeutronRouterTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_router')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_router')
        self.m.StubOutWithMock(neutronclient.Client, 'show_router')
        self.m.StubOutWithMock(neutronclient.Client, 'update_router')
        self.m.StubOutWithMock(neutronclient.Client, 'add_interface_router')
        self.m.StubOutWithMock(neutronclient.Client, 'remove_interface_router')
        self.m.StubOutWithMock(neutronclient.Client, 'add_gateway_router')
        self.m.StubOutWithMock(neutronclient.Client, 'remove_gateway_router')
        self.m.StubOutWithMock(neutronclient.Client,
                               'add_router_to_l3_agent')
        self.m.StubOutWithMock(neutronclient.Client,
                               'remove_router_from_l3_agent')
        self.m.StubOutWithMock(neutronclient.Client,
                               'list_l3_agent_hosting_routers')
        self.m.StubOutWithMock(router.neutronV20,
                               'find_resourceid_by_name_or_id')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_router(self, t, stack, resource_name):
        rsrc = router.Router('router', t['Resources'][resource_name], stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_router_interface(self, t, stack, resource_name, properties={}):
        t['Resources'][resource_name]['Properties'] = properties
        rsrc = router.RouterInterface(
            'router_interface',
            t['Resources'][resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_gateway_router(self, t, stack, resource_name, properties={}):
        t['Resources'][resource_name]['Properties'] = properties
        rsrc = router.RouterGateway(
            'gateway',
            t['Resources'][resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_router(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_router({
            'router': {
                'name': utils.PhysName('test_stack', 'router'),
                'admin_state_up': True,
            }
        }).AndReturn({
            "router": {
                "status": "BUILD",
                "external_gateway_info": None,
                "name": utils.PhysName('test_stack', 'router'),
                "admin_state_up": True,
                "tenant_id": "3e21026f2dc94372b105808c0e721661",
                "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
            }
        })
        neutronclient.Client.list_l3_agent_hosting_routers(
            u'3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndReturn({"agents": []})
        neutronclient.Client.add_router_to_l3_agent(
            u'792ff887-6c85-4a56-b518-23f24fa65581',
            {'router_id': u'3e46229d-8fce-4733-819a-b5fe630550f8'}
        ).AndReturn(None)
        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').AndReturn({
                "router": {
                    "status": "BUILD",
                    "external_gateway_info": None,
                    "name": utils.PhysName('test_stack', 'router'),
                    "admin_state_up": True,
                    "tenant_id": "3e21026f2dc94372b105808c0e721661",
                    "routes": [],
                    "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
                }
            })
        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').AndReturn({
                "router": {
                    "status": "ACTIVE",
                    "external_gateway_info": None,
                    "name": utils.PhysName('test_stack', 'router'),
                    "admin_state_up": True,
                    "tenant_id": "3e21026f2dc94372b105808c0e721661",
                    "routes": [],
                    "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
                }
            })
        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').AndRaise(
                qe.NeutronClientException(status_code=404))
        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').AndReturn({
                "router": {
                    "status": "ACTIVE",
                    "external_gateway_info": None,
                    "name": utils.PhysName('test_stack', 'router'),
                    "admin_state_up": True,
                    "tenant_id": "3e21026f2dc94372b105808c0e721661",
                    "routes": [],
                    "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
                }
            })
        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').AndReturn({
                "router": {
                    "status": "ACTIVE",
                    "external_gateway_info": None,
                    "name": utils.PhysName('test_stack', 'router'),
                    "admin_state_up": True,
                    "tenant_id": "3e21026f2dc94372b105808c0e721661",
                    "routes": [],
                    "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
                }
            })

        # Update script
        neutronclient.Client.list_l3_agent_hosting_routers(
            u'3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndReturn({
            "agents": [{
                "admin_state_up": True,
                "agent_type": "L3 agent",
                "alive": True,
                "binary": "neutron-l3-agent",
                "configurations": {
                    "ex_gw_ports": 1,
                    "floating_ips": 0,
                    "gateway_external_network_id": "",
                    "handle_internal_only_routers": True,
                    "interface_driver": "DummyDriver",
                    "interfaces": 1,
                    "router_id": "",
                    "routers": 1,
                    "use_namespaces": True},
                "created_at": "2014-03-11 05:00:05",
                "description": None,
                "heartbeat_timestamp": "2014-03-11 05:01:49",
                "host": "l3_agent_host",
                "id": "792ff887-6c85-4a56-b518-23f24fa65581",
                "started_at": "2014-03-11 05:00:05",
                "topic": "l3_agent"
            }]
        })
        neutronclient.Client.remove_router_from_l3_agent(
            u'792ff887-6c85-4a56-b518-23f24fa65581',
            u'3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndReturn(None)
        neutronclient.Client.add_router_to_l3_agent(
            u'63b3fd83-2c5f-4dad-b3ae-e0f83a40f216',
            {'router_id': u'3e46229d-8fce-4733-819a-b5fe630550f8'}
        ).AndReturn(None)
        neutronclient.Client.update_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'router': {
                'name': 'myrouter',
                'admin_state_up': False
            }}
        )

        # Delete script
        neutronclient.Client.delete_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndReturn(None)

        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndRaise(qe.NeutronClientException(status_code=404))

        neutronclient.Client.delete_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndRaise(qe.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_router(t, stack, 'router')

        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8', ref_id)
        self.assertIsNone(rsrc.FnGetAtt('tenant_id'))
        self.assertEqual('3e21026f2dc94372b105808c0e721661',
                         rsrc.FnGetAtt('tenant_id'))

        update_snippet = {
            "Type": "OS::Neutron::Router",
            "Properties": {
                "admin_state_up": False,
                "name": "myrouter",
                "l3_agent_id": "63b3fd83-2c5f-4dad-b3ae-e0f83a40f216"
            }
        }
        prop_diff = {
            "admin_state_up": False,
            "name": "myrouter",
            "l3_agent_id": "63b3fd83-2c5f-4dad-b3ae-e0f83a40f216"
        }
        rsrc.handle_update(update_snippet, {}, prop_diff)

        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.m.VerifyAll()

    def test_router_dependence(self):
        # assert the implicit dependency between the router
        # and subnet
        t = template_format.parse(
            neutron_subnet_and_external_gateway_template)
        stack = utils.parse_stack(t)
        deps = stack.dependencies[stack['subnet_external']]
        self.assertIn(stack['router'], deps)

    def test_router_interface(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.add_interface_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        ).AndReturn(None)
        neutronclient.Client.remove_interface_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        ).AndReturn(None)
        neutronclient.Client.remove_interface_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        ).AndRaise(qe.NeutronClientException(status_code=404))
        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'
            })

        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_router_interface_with_old_data(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.add_interface_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        ).AndReturn(None)
        neutronclient.Client.remove_interface_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        ).AndReturn(None)
        neutronclient.Client.remove_interface_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        ).AndRaise(qe.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'
            })
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8'
                         ':subnet_id=91e47a57-7508-46fe-afc9-fc454e8580e1',
                         rsrc.resource_id)
        (rsrc.resource_id) = ('3e46229d-8fce-4733-819a-b5fe630550f8:'
                              '91e47a57-7508-46fe-afc9-fc454e8580e1')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8'
                         ':91e47a57-7508-46fe-afc9-fc454e8580e1',
                         rsrc.resource_id)
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_router_interface_with_port_id(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.add_interface_router(
            'ae478782-53c0-4434-ab16-49900c88016c',
            {'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        ).AndReturn(None)
        neutronclient.Client.remove_interface_router(
            'ae478782-53c0-4434-ab16-49900c88016c',
            {'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        ).AndReturn(None)
        neutronclient.Client.remove_interface_router(
            'ae478782-53c0-4434-ab16-49900c88016c',
            {'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        ).AndRaise(qe.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
                'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'
            })
        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_router_interface_validate(self):
        t = template_format.parse(neutron_template)
        json = t['Resources']['router_interface']
        json['Properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
            'subnet_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e',
            'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        stack = utils.parse_stack(t)
        res = router.RouterInterface('router_interface', json, stack)
        self.assertRaises(exception.ResourcePropertyConflict, res.validate)
        json['Properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
            'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        stack = utils.parse_stack(t)
        res = router.RouterInterface('router_interface', json, stack)
        self.assertIsNone(res.validate())
        json['Properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
            'subnet_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        stack = utils.parse_stack(t)
        res = router.RouterInterface('router_interface', json, stack)
        self.assertIsNone(res.validate())
        json['Properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c'}
        stack = utils.parse_stack(t)
        res = router.RouterInterface('router_interface', json, stack)
        ex = self.assertRaises(exception.StackValidationFailed, res.validate)
        self.assertEqual("Either subnet_id or port_id must be specified.",
                         str(ex))

    def test_gateway_router(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        router.neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn('fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        neutronclient.Client.add_gateway_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}
        ).AndReturn(None)
        neutronclient.Client.remove_gateway_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndReturn(None)
        neutronclient.Client.remove_gateway_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndRaise(qe.NeutronClientException(status_code=404))
        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_gateway_router(
            t, stack, 'gateway', properties={
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
            })

        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def _create_router_with_gateway(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())

        router.neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'public'
        ).AndReturn('fc68ea2c-b60b-4b4f-bd82-94ec81110766')

        neutronclient.Client.create_router({
            "router": {
                "name": "Test Router",
                "external_gateway_info": {
                    'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                    'enable_snat': True
                },
                "admin_state_up": True,
            }
        }).AndReturn({
            "router": {
                "status": "BUILD",
                "external_gateway_info": None,
                "name": "Test Router",
                "admin_state_up": True,
                "tenant_id": "3e21026f2dc94372b105808c0e721661",
                "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
            }
        })

        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').AndReturn({
                "router": {
                    "status": "ACTIVE",
                    "external_gateway_info": {
                        "network_id":
                        "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                        "enable_snat": True
                    },
                    "name": "Test Router",
                    "admin_state_up": True,
                    "tenant_id": "3e21026f2dc94372b105808c0e721661",
                    "routes": [],
                    "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
                }
            })

    def test_create_router_gateway_as_property(self):
        self._create_router_with_gateway()

        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').AndReturn({
                "router": {
                    "status": "ACTIVE",
                    "external_gateway_info": {
                        "network_id":
                        "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                        "enable_snat": True
                    },
                    "name": "Test Router",
                    "admin_state_up": True,
                    "tenant_id": "3e21026f2dc94372b105808c0e721661",
                    "routes": [],
                    "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
                }
            })

        self.m.ReplayAll()
        t = template_format.parse(neutron_external_gateway_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_router(t, stack, 'router')

        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8', ref_id)
        gateway_info = rsrc.FnGetAtt('external_gateway_info')
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         gateway_info.get('network_id'))
        self.assertTrue(gateway_info.get('enable_snat'))
        self.m.VerifyAll()

    def test_create_router_gateway_enable_snat(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())

        router.neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'public'
        ).AndReturn('fc68ea2c-b60b-4b4f-bd82-94ec81110766')

        neutronclient.Client.create_router({
            "router": {
                "name": "Test Router",
                "external_gateway_info": {
                    'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                },
                "admin_state_up": True,
            }
        }).AndReturn({
            "router": {
                "status": "BUILD",
                "external_gateway_info": None,
                "name": "Test Router",
                "admin_state_up": True,
                "tenant_id": "3e21026f2dc94372b105808c0e721661",
                "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
            }
        })

        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').MultipleTimes().AndReturn({
                "router": {
                    "status": "ACTIVE",
                    "external_gateway_info": {
                        "network_id":
                        "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                        "enable_snat": True
                    },
                    "name": "Test Router",
                    "admin_state_up": True,
                    "tenant_id": "3e21026f2dc94372b105808c0e721661",
                    "routes": [],
                    "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
                }
            })

        self.m.ReplayAll()
        t = template_format.parse(neutron_external_gateway_template)
        t["Resources"]["router"]["Properties"]["external_gateway_info"].pop(
            "enable_snat")
        stack = utils.parse_stack(t)
        rsrc = self.create_router(t, stack, 'router')

        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8', ref_id)
        gateway_info = rsrc.FnGetAtt('external_gateway_info')
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         gateway_info.get('network_id'))
        self.m.VerifyAll()

    def test_update_router_gateway_as_property(self):
        self._create_router_with_gateway()

        router.neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'other_public'
        ).AndReturn('91e47a57-7508-46fe-afc9-fc454e8580e1')

        neutronclient.Client.update_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'router': {
                "name": "Test Router",
                "external_gateway_info": {
                    'network_id': '91e47a57-7508-46fe-afc9-fc454e8580e1',
                    'enable_snat': False
                },
                "admin_state_up": True}}
        ).AndReturn(None)

        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').AndReturn({
                "router": {
                    "status": "ACTIVE",
                    "external_gateway_info": {
                        "network_id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
                        "enable_snat": False
                    },
                    "name": "Test Router",
                    "admin_state_up": True,
                    "tenant_id": "3e21026f2dc94372b105808c0e721661",
                    "routes": [],
                    "id": "3e46229d-8fce-4733-819a-b5fe630550f8"
                }
            })

        self.m.ReplayAll()
        t = template_format.parse(neutron_external_gateway_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_router(t, stack, 'router')

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['external_gateway_info'] = {
            "network": "other_public",
            "enable_snat": False
        }
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        gateway_info = rsrc.FnGetAtt('external_gateway_info')
        self.assertEqual('91e47a57-7508-46fe-afc9-fc454e8580e1',
                         gateway_info.get('network_id'))
        self.assertFalse(gateway_info.get('enable_snat'))

        self.m.VerifyAll()

    def test_delete_router_gateway_as_property(self):
        self._create_router_with_gateway()
        neutronclient.Client.delete_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndReturn(None)

        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndRaise(qe.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(neutron_external_gateway_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_router(t, stack, 'router')
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.m.VerifyAll()


@skipIf(neutronclient is None, 'neutronclient unavailable')
class NeutronFloatingIPTest(HeatTestCase):

    @skipIf(net.clients.neutronclient is None, "Missing Neutron Client")
    def setUp(self):
        super(NeutronFloatingIPTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_floatingip')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_floatingip')
        self.m.StubOutWithMock(neutronclient.Client, 'show_floatingip')
        self.m.StubOutWithMock(neutronclient.Client, 'update_floatingip')
        self.m.StubOutWithMock(neutronclient.Client, 'create_port')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_port')
        self.m.StubOutWithMock(neutronclient.Client, 'update_port')
        self.m.StubOutWithMock(neutronclient.Client, 'show_port')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def test_floating_ip(self):

        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_floatingip({
            'floatingip': {'floating_network_id': u'abcd1234'}
        }).AndReturn({'floatingip': {
            'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            'floating_network_id': u'abcd1234'
        }})

        neutronclient.Client.show_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.NeutronClientException(status_code=404))
        neutronclient.Client.show_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).MultipleTimes().AndReturn({'floatingip': {
            'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            'floating_network_id': u'abcd1234'
        }})

        neutronclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766').AndReturn(None)
        neutronclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766').AndRaise(
                qe.NeutronClientException(status_code=404))
        self.m.ReplayAll()

        t = template_format.parse(neutron_floating_template)
        stack = utils.parse_stack(t)

        # assert the implicit dependency between the floating_ip
        # and the gateway
        deps = stack.dependencies[stack['gateway']]
        self.assertIn(stack['floating_ip'], deps)

        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual((fip.CREATE, fip.COMPLETE), fip.state)
        fip.validate()

        fip_id = fip.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', fip_id)

        self.assertIsNone(fip.FnGetAtt('show'))
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         fip.FnGetAtt('show')['id'])
        self.assertRaises(exception.InvalidTemplateAttribute,
                          fip.FnGetAtt, 'Foo')

        self.assertEqual(u'abcd1234', fip.FnGetAtt('floating_network_id'))
        self.assertRaises(resource.UpdateReplace,
                          fip.handle_update, {}, {}, {})
        scheduler.TaskRunner(fip.delete)()
        fip.state_set(fip.CREATE, fip.COMPLETE, 'to delete again')
        scheduler.TaskRunner(fip.delete)()

        self.m.VerifyAll()

    def test_port(self):

        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_port({'port': {
            'network_id': u'xyz1234',
            'fixed_ips': [
                {'subnet_id': u'sub1234', 'ip_address': u'10.0.0.10'}
            ],
            'name': utils.PhysName('test_stack', 'port_floating'),
            'admin_state_up': True}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.PortNotFoundClient(status_code=404))
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).MultipleTimes().AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        neutronclient.Client.update_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766', {
                'port': {
                    'fixed_ips': [
                        {'subnet_id': 'sub1234', 'ip_address': '10.0.0.11'}
                    ],
                    'admin_state_up': True,
                    'name': 'test_port',
                    'device_id': 'd6b4d3a5-c700-476f-b609-1493dd9dadc2',
                    'device_owner': 'network:floatingip'
                }
            }
        ).AndReturn(None)

        self.m.ReplayAll()

        t = template_format.parse(neutron_floating_template)
        stack = utils.parse_stack(t)

        p = stack['port_floating']
        scheduler.TaskRunner(p.create)()
        self.assertEqual((p.CREATE, p.COMPLETE), p.state)
        p.validate()

        port_id = p.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', port_id)

        self.assertIsNone(p.FnGetAtt('status'))
        self.assertEqual('ACTIVE', p.FnGetAtt('status'))
        self.assertRaises(
            exception.InvalidTemplateAttribute, p.FnGetAtt, 'Foo')

        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         p.resource_id)

        update_snippet = {
            "Type": "OS::Neutron::Port",
            "Properties": {
                "network_id": "xyz1234",
                "fixed_ips": [{
                    "subnet_id": "sub1234",
                    "ip_address": "10.0.0.11"
                }],
                "name": "test_port",
                "device_id": "d6b4d3a5-c700-476f-b609-1493dd9dadc2",
                'device_owner': 'network:floatingip'
            }
        }

        p.handle_update(update_snippet, {}, {})

        self.m.VerifyAll()

    def test_floatip_port(self):

        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_floatingip({
            'floatingip': {'floating_network_id': u'abcd1234'}
        }).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        neutronclient.Client.create_port({'port': {
            'network_id': u'xyz1234',
            'fixed_ips': [
                {'subnet_id': u'sub1234', 'ip_address': u'10.0.0.10'}
            ],
            'name': utils.PhysName('test_stack', 'port_floating'),
            'admin_state_up': True}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {
                'floatingip': {
                    'port_id': u'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}}
        ).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'floatingip': {
                'port_id': None
            }}).AndReturn(None)

        neutronclient.Client.delete_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.PortNotFoundClient(status_code=404))

        neutronclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'floatingip': {
                'port_id': None
            }}).AndRaise(qe.NeutronClientException(status_code=404))

        neutronclient.Client.delete_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.PortNotFoundClient(status_code=404))

        neutronclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.NeutronClientException(status_code=404))

        self.m.ReplayAll()

        t = template_format.parse(neutron_floating_template)
        stack = utils.parse_stack(t)

        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual((fip.CREATE, fip.COMPLETE), fip.state)

        p = stack['port_floating']
        scheduler.TaskRunner(p.create)()
        self.assertEqual((p.CREATE, p.COMPLETE), p.state)

        fipa = stack['floating_ip_assoc']
        scheduler.TaskRunner(fipa.create)()
        self.assertEqual((fipa.CREATE, fipa.COMPLETE), fipa.state)

        fipa.validate()

        fipa_id = fipa.FnGetRefId()
        fip_id = fip.FnGetRefId()
        port_id = p.FnGetRefId()
        self.assertEqual('%s:%s' % (fip_id, port_id), fipa_id)
        self.assertRaises(resource.UpdateReplace,
                          fipa.handle_update, {}, {}, {})

        scheduler.TaskRunner(fipa.delete)()
        scheduler.TaskRunner(p.delete)()
        scheduler.TaskRunner(fip.delete)()

        fipa.state_set(fipa.CREATE, fipa.COMPLETE, 'to delete again')
        fip.state_set(fip.CREATE, fip.COMPLETE, 'to delete again')
        p.state_set(p.CREATE, p.COMPLETE, 'to delete again')

        scheduler.TaskRunner(fipa.delete)()
        self.assertIsNone(scheduler.TaskRunner(p.delete)())
        scheduler.TaskRunner(fip.delete)()

        self.m.VerifyAll()


@skipIf(neutronclient is None, 'neutronclient unavailable')
class NeutronPortTest(HeatTestCase):

    @skipIf(net.clients.neutronclient is None, "Missing Neutron Client")
    def setUp(self):
        super(NeutronPortTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_port')
        self.m.StubOutWithMock(neutronclient.Client, 'show_port')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def test_missing_subnet_id(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_port({'port': {
            'network_id': u'net1234',
            'fixed_ips': [
                {'ip_address': u'10.0.3.21'}
            ],
            'name': utils.PhysName('test_stack', 'port'),
            'admin_state_up': True,
            'device_owner': u'network:dhcp'}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        self.m.ReplayAll()

        t = template_format.parse(neutron_port_template)
        t['Resources']['port']['Properties']['fixed_ips'][0].pop('subnet_id')
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()

        self.m.VerifyAll()

    def test_missing_ip_address(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_port({'port': {
            'network_id': u'net1234',
            'fixed_ips': [
                {'subnet_id': u'sub1234'}
            ],
            'name': utils.PhysName('test_stack', 'port'),
            'admin_state_up': True,
            'device_owner': u'network:dhcp'}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        self.m.ReplayAll()

        t = template_format.parse(neutron_port_template)
        t['Resources']['port']['Properties']['fixed_ips'][0].pop('ip_address')
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()
        self.m.VerifyAll()

    def test_missing_fixed_ips(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_port({'port': {
            'network_id': u'net1234',
            'name': utils.PhysName('test_stack', 'port'),
            'admin_state_up': True,
            'device_owner': u'network:dhcp'}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            "fixed_ips": {
                "subnet_id": "d0e971a6-a6b4-4f4c-8c88-b75e9c120b7e",
                "ip_address": "10.0.0.2"
            }
        }})

        self.m.ReplayAll()

        t = template_format.parse(neutron_port_template)
        t['Resources']['port']['Properties'].pop('fixed_ips')
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()
        self.m.VerifyAll()

    def test_allowed_address_pair(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_port({'port': {
            'network_id': u'abcd1234',
            'allowed_address_pairs': [{
                'ip_address': u'10.0.3.21',
                'mac_address': u'00-B0-D0-86-BB-F7'
            }],
            'name': utils.PhysName('test_stack', 'port'),
            'admin_state_up': True}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        self.m.ReplayAll()

        t = template_format.parse(neutron_port_with_address_pair_template)
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()
        self.m.VerifyAll()

    def test_missing_mac_address(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_port({'port': {
            'network_id': u'abcd1234',
            'allowed_address_pairs': [{
                'ip_address': u'10.0.3.21',
            }],
            'name': utils.PhysName('test_stack', 'port'),
            'admin_state_up': True}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        self.m.ReplayAll()

        t = template_format.parse(neutron_port_with_address_pair_template)
        t['Resources']['port']['Properties']['allowed_address_pairs'][0].pop(
            'mac_address'
        )
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()
        self.m.VerifyAll()

    def test_security_groups(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_port({'port': {
            'network_id': u'net1234',
            'security_groups': ['8a2f582a-e1cd-480f-b85d-b02631c10656',
                                '024613dc-b489-4478-b46f-ada462738740'],
            'fixed_ips': [
                {'subnet_id': u'sub1234', 'ip_address': u'10.0.3.21'}
            ],
            'name': utils.PhysName('test_stack', 'port'),
            'admin_state_up': True,
            'device_owner': u'network:dhcp'}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        self.m.ReplayAll()

        t = template_format.parse(neutron_port_template)
        t['Resources']['port']['Properties']['security_groups'] = [
            '8a2f582a-e1cd-480f-b85d-b02631c10656',
            '024613dc-b489-4478-b46f-ada462738740']
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()

        self.m.VerifyAll()


@skipIf(neutronclient is None, 'neutronclient unavailable')
class NetworkConstraintTest(HeatTestCase):

    def test_validate(self):
        self.m.StubOutWithMock(clients.OpenStackClients, 'neutron')
        clients.OpenStackClients.neutron().MultipleTimes().AndReturn(None)
        self.m.StubOutWithMock(net.neutronV20, 'find_resourceid_by_name_or_id')
        net.neutronV20.find_resourceid_by_name_or_id(
            None, 'network', 'foo'
        ).AndReturn('foo')
        net.neutronV20.find_resourceid_by_name_or_id(
            None, 'network', 'bar'
        ).AndRaise(qe.NeutronClientException(status_code=404))
        self.m.ReplayAll()

        constraint = net.NetworkConstraint()
        self.assertTrue(constraint.validate("foo", None))
        self.assertFalse(constraint.validate("bar", None))

        self.m.VerifyAll()
