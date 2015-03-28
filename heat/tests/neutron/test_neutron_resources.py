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

import mox
from neutronclient.common import exceptions as qe
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.resources.openstack.neutron import net
from heat.engine.resources.openstack.neutron import provider_net
from heat.engine.resources.openstack.neutron import router
from heat.engine.resources.openstack.neutron import subnet
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


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
        "network": { "Ref" : "network" },
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
        "network": { "Ref" : "network" },
        "fixed_ips": [{
          "subnet": { "Ref" : "subnet" },
          "ip_address": "10.0.3.21"
        }]
      }
    },
    "port2": {
      "Type": "OS::Neutron::Port",
      "Properties": {
        "name": "port2",
        "network": { "Ref" : "network" }
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
        "subnet": { "Ref" : "subnet" }
      }
    },
    "gateway": {
      "Type": "OS::Neutron::RouterGateway",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "network": { "Ref" : "network" }
      }
    }
  }
}
'''

neutron_template_deprecated = '''
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
        "shared": true
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

neutron_floating_template_deprecated = '''
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
    "router_interface": {
      "Type": "OS::Neutron::RouterInterface",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "subnet": "sub1234"
      }
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

neutron_floating_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Neutron resources",
  "Parameters" : {},
  "Resources" : {
    "port_floating": {
      "Type": "OS::Neutron::Port",
      "Properties": {
        "network": "xyz1234",
        "fixed_ips": [{
          "subnet": "sub1234",
          "ip_address": "10.0.0.10"
        }]
      }
    },
    "floating_ip": {
      "Type": "OS::Neutron::FloatingIP",
      "Properties": {
        "floating_network": "abcd1234",
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
    "router_interface": {
      "Type": "OS::Neutron::RouterInterface",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "subnet": "sub1234"
      }
    },
    "gateway": {
      "Type": "OS::Neutron::RouterGateway",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "network": "abcd1234"
      }
    }
  }
}
'''

neutron_floating_no_assoc_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Neutron resources",
  "Parameters" : {},
  "Resources" : {
    "network": {
      "Type": "OS::Neutron::Net"
    },
    "subnet": {
      "Type": "OS::Neutron::Subnet",
      "Properties": {
        "network": { "Ref" : "network" },
        "cidr": "10.0.3.0/24",
      }
    },

    "port_floating": {
      "Type": "OS::Neutron::Port",
      "Properties": {
        "network": { "Ref" : "network" },
        "fixed_ips": [{
          "subnet": { "Ref" : "subnet" },
          "ip_address": "10.0.0.10"
        }]
      }
    },
    "floating_ip": {
      "Type": "OS::Neutron::FloatingIP",
      "Properties": {
        "floating_network": "abcd1234",
        "port_id": { "Ref" : "port_floating" }
      }
    },
    "router": {
      "Type": "OS::Neutron::Router"
    },
    "router_interface": {
      "Type": "OS::Neutron::RouterInterface",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "subnet": { "Ref" : "subnet" }
      }
    },
    "gateway": {
      "Type": "OS::Neutron::RouterGateway",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "network": "abcd1234"
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
    "floating_ip": {
      "Type": "OS::Neutron::FloatingIP",
      "Properties": {
        "floating_network": {
          "Ref": "net_external"
        },
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


class NeutronNetTest(common.HeatTestCase):

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

    def create_net(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = net.Net('test_net', resource_defns[resource_name], stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_net(self):
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
        prop_diff = {
            "name": "mynet",
            "dhcp_agent_ids": [
                "bb09cfcd-5277-473d-8336-d4ed8628ae68"
            ]
        }
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        rsrc.handle_update(update_snippet, {}, prop_diff)

        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()


class NeutronProviderNetTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronProviderNetTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_network')
        self.m.StubOutWithMock(neutronclient.Client, 'show_network')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_network')
        self.m.StubOutWithMock(neutronclient.Client, 'update_network')

    def create_provider_net(self):
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
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = provider_net.ProviderNet(
            'provider_net', resource_defns['provider_network_vlan'], stack)

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

        props = {
            "name": "prov_net",
            "shared": True,
            "admin_state_up": True,
            "network_type": "vlan",
            "physical_network": "physnet_1",
            "segmentation_id": "102"
        }
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, {}))
        self.m.VerifyAll()


class NeutronSubnetTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronSubnetTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'show_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'update_subnet')
        self.m.StubOutWithMock(neutronV20, 'find_resourceid_by_name_or_id')

    def create_subnet(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = subnet.Subnet('test_subnet', resource_defns[resource_name],
                             stack)
        return rsrc

    def test_subnet(self):
        t = self._test_subnet()
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'None'
        ).AndReturn('None')
        stack = utils.parse_stack(t)
        rsrc = self.create_subnet(t, stack, 'subnet')
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
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
        props = {
            "name": 'mysubnet',
            "network_id": cfn_funcs.ResourceRef(stack, "Ref", "network"),
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "ip_version": 4,
            "cidr": "10.0.3.0/24",
            "allocation_pools": [
                {"start": "10.0.3.20", "end": "10.0.3.150"}],
            "dns_nameservers": ["8.8.8.8", "192.168.1.254"],
            "host_routes": [
                {"destination": "192.168.1.0/24", "nexthop": "194.168.1.2"}
            ]


        }
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        rsrc.handle_update(update_snippet, {}, {})

        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.m.VerifyAll()

    def test_subnet_deprecated(self):

        t = self._test_subnet(resolve_neutron=False)
        stack = utils.parse_stack(t)
        rsrc = self.create_subnet(t, stack, 'subnet')
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
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
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.m.VerifyAll()

    def _test_subnet(self, resolve_neutron=True):
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

        if resolve_neutron:
            t = template_format.parse(neutron_template)
            # Update script
            neutronclient.Client.update_subnet(
                '91e47a57-7508-46fe-afc9-fc454e8580e1',
                {'subnet': {
                 'dns_nameservers': ['8.8.8.8', '192.168.1.254'],
                 'name': 'mysubnet',
                 'enable_dhcp': True,
                 'host_routes': [
                     {'destination': '192.168.1.0/24',
                      'nexthop': '194.168.1.2'}
                 ]
                 }}
            )

        else:
            t = template_format.parse(neutron_template_deprecated)

        return t

    def test_subnet_disable_dhcp(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'None'
        ).AndReturn('None')
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

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
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

    def test_ipv6_subnet(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'None'
        ).AndReturn('None')
        neutronclient.Client.create_subnet({
            'subnet': {
                'name': utils.PhysName('test_stack', 'test_subnet'),
                'network_id': u'None',
                'dns_nameservers': [u'2001:4860:4860::8844'],
                'ip_version': 6,
                'enable_dhcp': True,
                'cidr': u'fdfa:6a50:d22b::/64',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'ipv6_address_mode': 'slaac',
                'ipv6_ra_mode': 'slaac'
            }
        }).AndReturn({
            "subnet": {
                "allocation_pools": [
                    {"start": "fdfa:6a50:d22b::2",
                     "end": "fdfa:6a50:d22b:0:ffff:ffff:ffff:fffe"}],
                "cidr": "fd00:1::/64",
                "enable_dhcp": True,
                "gateway_ip": "fdfa:6a50:d22b::1",
                "id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
                "ip_version": 6,
                "name": "name",
                "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                'ipv6_address_mode': 'slaac',
                'ipv6_ra_mode': 'slaac'
            }
        })

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        props = t['Resources']['subnet']['Properties']
        props.pop('allocation_pools')
        props.pop('host_routes')
        props['ip_version'] = 6
        props['ipv6_address_mode'] = 'slaac'
        props['ipv6_ra_mode'] = 'slaac'
        props['cidr'] = 'fdfa:6a50:d22b::/64'
        props['dns_nameservers'] = ['2001:4860:4860::8844']
        stack = utils.parse_stack(t)
        rsrc = self.create_subnet(t, stack, 'subnet')

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.validate()
        self.m.VerifyAll()

    def test_ipv6_validate_ra_mode(self):
        t = template_format.parse(neutron_template)
        props = t['Resources']['subnet']['Properties']
        props['ipv6_address_mode'] = 'dhcpv6-stateful'
        props['ipv6_ra_mode'] = 'slaac'
        props['ip_version'] = 6
        stack = utils.parse_stack(t)
        rsrc = stack['subnet']
        ex = self.assertRaises(exception.StackValidationFailed,
                               rsrc.validate)
        self.assertEqual("When both ipv6_ra_mode and ipv6_address_mode are "
                         "set, they must be equal.", six.text_type(ex))

    def test_ipv6_validate_ip_version(self):
        t = template_format.parse(neutron_template)
        props = t['Resources']['subnet']['Properties']
        props['ipv6_address_mode'] = 'slaac'
        props['ipv6_ra_mode'] = 'slaac'
        props['ip_version'] = 4
        stack = utils.parse_stack(t)
        rsrc = stack['subnet']
        ex = self.assertRaises(exception.StackValidationFailed,
                               rsrc.validate)
        self.assertEqual("ipv6_ra_mode and ipv6_address_mode are not "
                         "supported for ipv4.", six.text_type(ex))


class NeutronRouterTest(common.HeatTestCase):

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
        self.m.StubOutWithMock(neutronV20, 'find_resourceid_by_name_or_id')

    def create_router(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = router.Router('router', resource_defns[resource_name], stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_router_interface(self, t, stack, resource_name,
                                properties=None):
        properties = properties or {}
        t['Resources'][resource_name]['Properties'] = properties
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = router.RouterInterface(
            'router_interface',
            resource_defns[resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_gateway_router(self, t, stack, resource_name, properties=None):
        properties = properties or {}
        t['Resources'][resource_name]['Properties'] = properties
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = router.RouterGateway(
            'gateway',
            resource_defns[resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_router_validate_distribute_l3_agents(self):
        t = template_format.parse(neutron_template)
        props = t['Resources']['router']['Properties']

        # test distributed can not specify l3_agent_id
        props['distributed'] = True
        stack = utils.parse_stack(t)
        rsrc = stack['router']
        exc = self.assertRaises(exception.ResourcePropertyConflict,
                                rsrc.validate)
        self.assertIn('distributed, l3_agent_id/l3_agent_ids',
                      six.text_type(exc))
        # test distributed can not specify l3_agent_ids
        props['l3_agent_ids'] = ['id1', 'id2']
        stack = utils.parse_stack(t)
        rsrc = stack['router']
        rsrc.t['Properties'].pop('l3_agent_id')
        exc = self.assertRaises(exception.ResourcePropertyConflict,
                                rsrc.validate)
        self.assertIn('distributed, l3_agent_id/l3_agent_ids',
                      six.text_type(exc))

    def test_router_validate_l3_agents(self):
        t = template_format.parse(neutron_template)
        props = t['Resources']['router']['Properties']

        # test l3_agent_id and l3_agent_ids can not specify at the same time
        props['l3_agent_ids'] = ['id1', 'id2']
        stack = utils.parse_stack(t)
        rsrc = stack['router']
        exc = self.assertRaises(exception.ResourcePropertyConflict,
                                rsrc.validate)
        self.assertIn('l3_agent_id, l3_agent_ids', six.text_type(exc))

    def test_router_validate_ha_distribute(self):
        t = template_format.parse(neutron_template)
        props = t['Resources']['router']['Properties']

        # test distributed and ha can not specify at the same time
        props['ha'] = True
        props['distributed'] = True
        stack = utils.parse_stack(t)
        rsrc = stack['router']
        rsrc.t['Properties'].pop('l3_agent_id')
        exc = self.assertRaises(exception.ResourcePropertyConflict,
                                rsrc.validate)
        self.assertIn('distributed, ha', six.text_type(exc))

    def test_router_validate_ha_l3_agents(self):
        t = template_format.parse(neutron_template)
        props = t['Resources']['router']['Properties']
        # test non ha can not specify more than one l3 agent id
        props['ha'] = False
        props['l3_agent_ids'] = ['id1', 'id2']
        stack = utils.parse_stack(t)
        rsrc = stack['router']
        rsrc.t['Properties'].pop('l3_agent_id')
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn('Non HA routers can only have one L3 agent.',
                      six.text_type(exc))

    def test_router(self):
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
                "id": "3e46229d-8fce-4733-819a-b5fe630550f8",
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
        # Update again script
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
                "id": "63b3fd83-2c5f-4dad-b3ae-e0f83a40f216",
                "started_at": "2014-03-11 05:00:05",
                "topic": "l3_agent"
            }]
        })
        neutronclient.Client.remove_router_from_l3_agent(
            u'63b3fd83-2c5f-4dad-b3ae-e0f83a40f216',
            u'3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndReturn(None)
        neutronclient.Client.add_router_to_l3_agent(
            u'4c692423-2c5f-4dad-b3ae-e2339f58539f',
            {'router_id': u'3e46229d-8fce-4733-819a-b5fe630550f8'}
        ).AndReturn(None)
        neutronclient.Client.add_router_to_l3_agent(
            u'8363b3fd-2c5f-4dad-b3ae-0f216e0f83a4',
            {'router_id': u'3e46229d-8fce-4733-819a-b5fe630550f8'}
        ).AndReturn(None)
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

        prop_diff = {
            "admin_state_up": False,
            "name": "myrouter",
            "l3_agent_id": "63b3fd83-2c5f-4dad-b3ae-e0f83a40f216"
        }
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        rsrc.handle_update(update_snippet, {}, prop_diff)

        prop_diff = {
            "l3_agent_ids": ["4c692423-2c5f-4dad-b3ae-e2339f58539f",
                             "8363b3fd-2c5f-4dad-b3ae-0f216e0f83a4"]
        }
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
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
        required_by = set(stack.dependencies.required_by(stack['router']))
        self.assertIn(stack['floating_ip'], required_by)

    def test_router_interface(self):
        self._test_router_interface()

    def test_router_interface_depr_router(self):
        self._test_router_interface(resolve_router=False)

    def test_router_interface_depr_subnet(self):
        self._test_router_interface(resolve_subnet=False)

    def test_router_interface_depr_router_and_subnet(self):
        self._test_router_interface(resolve_router=False, resolve_subnet=False)

    def _test_router_interface(self, resolve_subnet=True,
                               resolve_router=True):
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
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)
        subnet_key = 'subnet_id'
        router_key = 'router_id'
        self.stub_SubnetConstraint_validate()
        self.stub_RouterConstraint_validate()
        if resolve_router:
            neutronV20.find_resourceid_by_name_or_id(
                mox.IsA(neutronclient.Client),
                'router',
                '3e46229d-8fce-4733-819a-b5fe630550f8'
            ).AndReturn('3e46229d-8fce-4733-819a-b5fe630550f8')
            router_key = 'router'
        if resolve_subnet:
            neutronV20.find_resourceid_by_name_or_id(
                mox.IsA(neutronclient.Client),
                'subnet',
                '91e47a57-7508-46fe-afc9-fc454e8580e1'
            ).AndReturn('91e47a57-7508-46fe-afc9-fc454e8580e1')
            subnet_key = 'subnet'

        self.m.ReplayAll()
        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                router_key: '3e46229d-8fce-4733-819a-b5fe630550f8',
                subnet_key: '91e47a57-7508-46fe-afc9-fc454e8580e1'
            })
        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_router_interface_with_old_data(self):
        self.stub_SubnetConstraint_validate()
        self.stub_RouterConstraint_validate()
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

    def test_router_interface_with_port(self):
        self._test_router_interface_with_port()

    def test_router_interface_with_deprecated_port(self):
        self._test_router_interface_with_port(resolve_port=False)

    def _test_router_interface_with_port(self, resolve_port=True):
        port_key = 'port_id'
        neutronclient.Client.add_interface_router(
            'ae478782-53c0-4434-ab16-49900c88016c',
            {'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        ).AndReturn(None)
        if resolve_port:
            port_key = 'port'
            neutronV20.find_resourceid_by_name_or_id(
                mox.IsA(neutronclient.Client),
                'port',
                '9577cafd-8e98-4059-a2e6-8a771b4d318e'
            ).AndReturn('9577cafd-8e98-4059-a2e6-8a771b4d318e')

        neutronclient.Client.remove_interface_router(
            'ae478782-53c0-4434-ab16-49900c88016c',
            {'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        ).AndReturn(None)
        neutronclient.Client.remove_interface_router(
            'ae478782-53c0-4434-ab16-49900c88016c',
            {'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        ).AndRaise(qe.NeutronClientException(status_code=404))
        self.stub_PortConstraint_validate()
        self.stub_RouterConstraint_validate()

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
                port_key: '9577cafd-8e98-4059-a2e6-8a771b4d318e'
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
        resource_defns = stack.t.resource_definitions(stack)
        res = router.RouterInterface('router_interface',
                                     resource_defns['router_interface'],
                                     stack)
        self.assertRaises(exception.ResourcePropertyConflict, res.validate)
        json['Properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
            'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        res = router.RouterInterface('router_interface',
                                     resource_defns['router_interface'],
                                     stack)
        self.assertIsNone(res.validate())
        json['Properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
            'subnet_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        res = router.RouterInterface('router_interface',
                                     resource_defns['router_interface'],
                                     stack)
        self.assertIsNone(res.validate())
        json['Properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c'}
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        res = router.RouterInterface('router_interface',
                                     resource_defns['router_interface'],
                                     stack)
        ex = self.assertRaises(exception.PropertyUnspecifiedError,
                               res.validate)
        self.assertEqual("At least one of the following properties "
                         "must be specified: subnet, port",
                         six.text_type(ex))

    def test_gateway_router(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).MultipleTimes().AndReturn('fc68ea2c-b60b-4b4f-bd82-94ec81110766')
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
        self.stub_RouterConstraint_validate()

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_gateway_router(
            t, stack, 'gateway', properties={
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'network': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
            })

        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def _create_router_with_gateway(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'public'
        ).MultipleTimes().AndReturn('fc68ea2c-b60b-4b4f-bd82-94ec81110766')

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
                "id": "3e46229d-8fce-4733-819a-b5fe630550f8",
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
        neutronV20.find_resourceid_by_name_or_id(
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
                "id": "3e46229d-8fce-4733-819a-b5fe630550f8",
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

        neutronV20.find_resourceid_by_name_or_id(
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


class NeutronFloatingIPTest(common.HeatTestCase):

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
        self.m.StubOutWithMock(neutronV20,
                               'find_resourceid_by_name_or_id')

    def test_floating_ip_router_interface(self):
        t = template_format.parse(neutron_floating_template)
        del t['Resources']['gateway']
        self._test_floating_ip(t)

    def test_floating_ip_router_gateway(self):
        t = template_format.parse(neutron_floating_template)
        del t['Resources']['router_interface']
        self._test_floating_ip(t, r_iface=False)

    def test_floating_ip_deprecated_router_interface(self):
        t = template_format.parse(neutron_floating_template_deprecated)
        del t['Resources']['gateway']
        self._test_floating_ip(t, resolve_neutron=False)

    def test_floating_ip_deprecated_router_gateway(self):
        t = template_format.parse(neutron_floating_template_deprecated)
        del t['Resources']['router_interface']
        self._test_floating_ip(t, resolve_neutron=False, r_iface=False)

    def _test_floating_ip(self, tmpl, resolve_neutron=True, r_iface=True):
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
        self.stub_NetworkConstraint_validate()
        if resolve_neutron:
            neutronV20.find_resourceid_by_name_or_id(
                mox.IsA(neutronclient.Client),
                'network',
                'abcd1234'
            ).MultipleTimes().AndReturn('abcd1234')

        stack = utils.parse_stack(tmpl)

        # assert the implicit dependency between the floating_ip
        # and the gateway
        self.m.ReplayAll()

        if r_iface:
            required_by = set(stack.dependencies.required_by(
                stack['router_interface']))
            self.assertIn(stack['floating_ip_assoc'], required_by)
        else:
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
        scheduler.TaskRunner(fip.delete)()
        fip.state_set(fip.CREATE, fip.COMPLETE, 'to delete again')
        scheduler.TaskRunner(fip.delete)()

        self.m.VerifyAll()

    def test_port(self):
        self.stub_NetworkConstraint_validate()
        self.stub_SubnetConstraint_validate()
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'xyz1234'
        ).AndReturn('xyz1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub1234'
        ).AndReturn('sub1234')
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
                    'device_owner': 'network:floatingip',
                    'security_groups': [
                        '8a2f582a-e1cd-480f-b85d-b02631c10656']
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

        props = {
            "network": "xyz1234",
            "fixed_ips": [{
                "subnet_id": "sub1234",
                "ip_address": "10.0.0.11"
            }],
            "name": "test_port",
            "device_id": "d6b4d3a5-c700-476f-b609-1493dd9dadc2",
            'device_owner': 'network:floatingip',
            'security_groups': ['8a2f582a-e1cd-480f-b85d-b02631c10656']
        }
        update_snippet = rsrc_defn.ResourceDefinition(p.name, p.type(), props)

        p.handle_update(update_snippet, {}, {})

        self.m.VerifyAll()

    def test_floatip_association_port(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234'
        ).MultipleTimes().AndReturn('abcd1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'xyz1234'
        ).MultipleTimes().AndReturn('xyz1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub1234'
        ).MultipleTimes().AndReturn('sub1234')
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
        # create as
        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {
                'floatingip': {
                    'port_id': u'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}}
        ).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        # update as with port_id
        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {
                'floatingip': {
                    'port_id': u'2146dfbf-ba77-4083-8e86-d052f671ece5',
                    'fixed_ip_address': None}}
        ).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        # update as with floatingip_id
        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'floatingip': {
                'port_id': None
            }}).AndReturn(None)
        neutronclient.Client.update_floatingip(
            '2146dfbf-ba77-4083-8e86-d052f671ece5',
            {
                'floatingip': {
                    'port_id': u'2146dfbf-ba77-4083-8e86-d052f671ece5',
                    'fixed_ip_address': None}}
        ).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "2146dfbf-ba77-4083-8e86-d052f671ece5"
        }})
        # update as with both
        neutronclient.Client.update_floatingip(
            '2146dfbf-ba77-4083-8e86-d052f671ece5',
            {'floatingip': {
                'port_id': None
            }}).AndReturn(None)
        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {
                'floatingip': {
                    'port_id': u'ade6fcac-7d47-416e-a3d7-ad12efe445c1',
                    'fixed_ip_address': None}}
        ).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        # delete as
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

        neutronclient.Client.delete_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.PortNotFoundClient(status_code=404))

        neutronclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.NeutronClientException(status_code=404))
        self.stub_PortConstraint_validate()

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
        self.assertIsNotNone(fipa.id)
        self.assertEqual(fipa.id, fipa.resource_id)

        fipa.validate()

        # test update FloatingIpAssociation with port_id
        props = copy.deepcopy(fipa.properties.data)
        update_port_id = '2146dfbf-ba77-4083-8e86-d052f671ece5'
        props['port_id'] = update_port_id
        update_snippet = rsrc_defn.ResourceDefinition(fipa.name, fipa.type(),
                                                      stack.t.parse(stack,
                                                                    props))

        scheduler.TaskRunner(fipa.update, update_snippet)()
        self.assertEqual((fipa.UPDATE, fipa.COMPLETE), fipa.state)

        # test update FloatingIpAssociation with floatingip_id
        props = copy.deepcopy(fipa.properties.data)
        update_flip_id = '2146dfbf-ba77-4083-8e86-d052f671ece5'
        props['floatingip_id'] = update_flip_id
        update_snippet = rsrc_defn.ResourceDefinition(fipa.name, fipa.type(),
                                                      props)

        scheduler.TaskRunner(fipa.update, update_snippet)()
        self.assertEqual((fipa.UPDATE, fipa.COMPLETE), fipa.state)

        # test update FloatingIpAssociation with port_id and floatingip_id
        props = copy.deepcopy(fipa.properties.data)
        update_flip_id = 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        update_port_id = 'ade6fcac-7d47-416e-a3d7-ad12efe445c1'
        props['floatingip_id'] = update_flip_id
        props['port_id'] = update_port_id
        update_snippet = rsrc_defn.ResourceDefinition(fipa.name, fipa.type(),
                                                      props)

        scheduler.TaskRunner(fipa.update, update_snippet)()
        self.assertEqual((fipa.UPDATE, fipa.COMPLETE), fipa.state)

        scheduler.TaskRunner(fipa.delete)()
        scheduler.TaskRunner(p.delete)()
        scheduler.TaskRunner(fip.delete)()

        fip.state_set(fip.CREATE, fip.COMPLETE, 'to delete again')
        p.state_set(p.CREATE, p.COMPLETE, 'to delete again')

        self.assertIsNone(scheduler.TaskRunner(p.delete)())
        scheduler.TaskRunner(fip.delete)()

        self.m.VerifyAll()

    def test_floatip_port_dependency_subnet(self):
        t = template_format.parse(neutron_floating_no_assoc_template)
        stack = utils.parse_stack(t)

        p_result = self.patchobject(cfn_funcs.ResourceRef, 'result')
        p_result.return_value = 'subnet_uuid'
        # check dependencies for fip resource
        required_by = set(stack.dependencies.required_by(
            stack['router_interface']))
        self.assertIn(stack['floating_ip'], required_by)

    def test_floatip_port_dependency_network(self):
        t = template_format.parse(neutron_floating_no_assoc_template)
        del t['Resources']['port_floating']['Properties']['fixed_ips']
        stack = utils.parse_stack(t)

        p_show = self.patchobject(neutronclient.Client, 'show_network')
        p_show.return_value = {'network': {'subnets': ['subnet_uuid']}}

        p_result = self.patchobject(cfn_funcs.ResourceRef, 'result',
                                    autospec=True)

        def return_uuid(self):
            if self.args == 'network':
                return 'net_uuid'
            return 'subnet_uuid'

        p_result.side_effect = return_uuid

        # check dependencies for fip resource
        required_by = set(stack.dependencies.required_by(
            stack['router_interface']))
        self.assertIn(stack['floating_ip'], required_by)
        p_show.assert_called_once_with('net_uuid')

    def test_floatip_port(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'xyz1234'
        ).MultipleTimes().AndReturn('xyz1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub1234'
        ).MultipleTimes().AndReturn('sub1234')
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
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234'
        ).MultipleTimes().AndReturn('abcd1234')
        neutronclient.Client.create_floatingip({
            'floatingip': {
                'floating_network_id': u'abcd1234',
                'port_id': u'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
            }
        }).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        # update with new port_id
        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {
                'floatingip': {
                    'port_id': u'2146dfbf-ba77-4083-8e86-d052f671ece5',
                    'fixed_ip_address': None}}
        ).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        # update with None port_id
        neutronclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {
                'floatingip': {
                    'port_id': None,
                    'fixed_ip_address': None}}
        ).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        neutronclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        neutronclient.Client.delete_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.PortNotFoundClient(status_code=404))
        self.stub_PortConstraint_validate()

        self.m.ReplayAll()

        t = template_format.parse(neutron_floating_no_assoc_template)
        t['Resources']['port_floating']['Properties']['network'] = "xyz1234"
        t['Resources']['port_floating']['Properties'][
            'fixed_ips'][0]['subnet'] = "sub1234"
        t['Resources']['router_interface']['Properties']['subnet'] = "sub1234"
        stack = utils.parse_stack(t)

        # check dependencies for fip resource
        required_by = set(stack.dependencies.required_by(
            stack['router_interface']))
        self.assertIn(stack['floating_ip'], required_by)

        p = stack['port_floating']
        scheduler.TaskRunner(p.create)()
        self.assertEqual((p.CREATE, p.COMPLETE), p.state)

        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual((fip.CREATE, fip.COMPLETE), fip.state)

        # test update FloatingIp with port_id
        props = copy.deepcopy(fip.properties.data)
        update_port_id = '2146dfbf-ba77-4083-8e86-d052f671ece5'
        props['port_id'] = update_port_id
        update_snippet = rsrc_defn.ResourceDefinition(fip.name, fip.type(),
                                                      stack.t.parse(stack,
                                                                    props))
        scheduler.TaskRunner(fip.update, update_snippet)()
        self.assertEqual((fip.UPDATE, fip.COMPLETE), fip.state)

        # test update FloatingIp with None port_id
        props = copy.deepcopy(fip.properties.data)
        del(props['port_id'])
        update_snippet = rsrc_defn.ResourceDefinition(fip.name, fip.type(),
                                                      stack.t.parse(stack,
                                                                    props))
        scheduler.TaskRunner(fip.update, update_snippet)()
        self.assertEqual((fip.UPDATE, fip.COMPLETE), fip.state)

        scheduler.TaskRunner(fip.delete)()
        scheduler.TaskRunner(p.delete)()

        self.m.VerifyAll()
