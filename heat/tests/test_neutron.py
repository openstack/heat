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
import six

import mock
import mox
from neutronclient.common import exceptions as qe
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.clients.os import neutron
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.neutron import net
from heat.engine.resources.neutron.neutron import NeutronResource as qr
from heat.engine.resources.neutron import provider_net
from heat.engine.resources.neutron import router
from heat.engine.resources.neutron import subnet
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
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
        "network": "abcd1234"
      }
    }
  }
}
'''

neutron_port_template_deprecated = '''
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

neutron_port_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Neutron resources",
  "Parameters" : {},
  "Resources" : {
    "port": {
      "Type": "OS::Neutron::Port",
      "Properties": {
        "network": "net1234",
        "fixed_ips": [{
          "subnet": "sub1234",
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
        "network": "abcd1234",
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

    def test_validate_depr_properties_required(self):
        data = {'network_id': '1234',
                'network': 'abc'}
        p = properties.Properties(subnet.Subnet.properties_schema, data)
        self.assertRaises(exception.ResourcePropertyConflict,
                          qr._validate_depr_property_required,
                          p, 'network', 'network_id')
        data = {}
        p = properties.Properties(subnet.Subnet.properties_schema, data)
        self.assertRaises(exception.StackValidationFailed,
                          qr._validate_depr_property_required,
                          p, 'network', 'network_id')

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
        self.assertTrue(qr.is_built({'status': 'ACTIVE'}))
        self.assertTrue(qr.is_built({'status': 'DOWN'}))
        self.assertFalse(qr.is_built({'status': 'BUILD'}))
        e = self.assertRaises(resource.ResourceInError, qr.is_built, {
            'status': 'ERROR'
        })
        self.assertEqual(
            'Went to status ERROR due to "Unknown"',
            six.text_type(e))
        e = self.assertRaises(resource.ResourceUnknownStatus, qr.is_built, {
            'status': 'FROBULATING'
        })
        self.assertEqual(
            'Resource is not built - Unknown status FROBULATING',
            six.text_type(e))

    def test_resolve_attribute(self):
        class SomeNeutronResource(qr):
            properties_schema = {}

        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        stack = mock.MagicMock()
        res = SomeNeutronResource('aresource', tmpl, stack)

        mock_show_resource = mock.MagicMock()
        mock_show_resource.side_effect = [{'attr1': 'val1', 'attr2': 'val2'},
                                          {'attr1': 'val1', 'attr2': 'val2'},
                                          {'attr1': 'val1', 'attr2': 'val2'},
                                          qe.NeutronClientException]
        res._show_resource = mock_show_resource

        self.assertEqual({'attr1': 'val1', 'attr2': 'val2'},
                         res._resolve_attribute('show'))
        self.assertEqual('val2', res._resolve_attribute('attr2'))
        self.assertRaises(KeyError, res._resolve_attribute, 'attr3')
        self.assertIsNone(res._resolve_attribute('attr2'))

    def test_get_secgroup_uuids(self):
        # test get_secgroup_uuids with uuid
        security_groups = ['b62c3079-6946-44f5-a67b-6b9091884d4f',
                           '9887157c-d092-40f5-b547-6361915fce7d']
        self.assertEqual(security_groups,
                         qr.get_secgroup_uuids(security_groups, None, None))
        # test get_secgroup_uuids with name
        secgroups = ['security_group_1']
        expected_groups = ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        ctx = utils.dummy_context(
            tenant_id='dc4b074874244f7693dd65583733a758')
        fake_groups_list = {
            'security_groups': [
                {
                    'tenant_id': 'dc4b074874244f7693dd65583733a758',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }
        nclient = neutronclient.Client()
        self.m.StubOutWithMock(neutronclient.Client, 'list_security_groups')
        neutronclient.Client.list_security_groups().AndReturn(
            fake_groups_list)
        self.m.ReplayAll()
        self.assertEqual(expected_groups,
                         qr.get_secgroup_uuids(secgroups, nclient,
                                               ctx.tenant_id))
        self.m.VerifyAll()
        self.m.UnsetStubs()
        # test there are two securityGroups with same name, but there is
        # one belongs to the tenant
        fake_groups_list = {
            'security_groups': [
                {
                    'tenant_id': 'dc4b074874244f7693dd65583733a758',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'tenant_id': '64395a8e5beb4930a18245f76a5b1570',
                    'id': '384ccd91-447c-4d83-832c-06974a7d3d05',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }
        self.m.StubOutWithMock(neutronclient.Client, 'list_security_groups')
        neutronclient.Client.list_security_groups().AndReturn(
            fake_groups_list)
        self.m.ReplayAll()
        self.assertEqual(expected_groups,
                         qr.get_secgroup_uuids(secgroups, nclient,
                                               ctx.tenant_id))
        self.m.VerifyAll()
        self.m.UnsetStubs()
        # test there are two securityGroups with same name, and the two
        # all belong to the tenant
        fake_groups_list = {
            'security_groups': [
                {
                    'tenant_id': 'dc4b074874244f7693dd65583733a758',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'tenant_id': 'dc4b074874244f7693dd65583733a758',
                    'id': '384ccd91-447c-4d83-832c-06974a7d3d05',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }
        self.m.StubOutWithMock(neutronclient.Client, 'list_security_groups')
        neutronclient.Client.list_security_groups().AndReturn(fake_groups_list)
        self.m.ReplayAll()
        self.assertRaises(exception.PhysicalResourceNameAmbiguity,
                          qr.get_secgroup_uuids,
                          secgroups, nclient, ctx.tenant_id)
        self.m.VerifyAll()
        self.m.UnsetStubs()


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
        self.stub_keystoneclient()

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


class NeutronProviderNetTest(HeatTestCase):

    def setUp(self):
        super(NeutronProviderNetTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_network')
        self.m.StubOutWithMock(neutronclient.Client, 'show_network')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_network')
        self.m.StubOutWithMock(neutronclient.Client, 'update_network')
        self.stub_keystoneclient()

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


class NeutronSubnetTest(HeatTestCase):

    def setUp(self):
        super(NeutronSubnetTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'show_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'update_subnet')
        self.m.StubOutWithMock(neutronV20, 'find_resourceid_by_name_or_id')
        self.stub_keystoneclient()

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
                 'enable_dhcp': True
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


class NeutronRouterTest(HeatTestCase):

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
        self.stub_keystoneclient()

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
        self._test_router_interface()

    def test_router_interface_deprecated(self):
        self._test_router_interface(resolve_neutron=False)

    def _test_router_interface(self, resolve_neutron=True):
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
        if resolve_neutron:
            neutronV20.find_resourceid_by_name_or_id(
                mox.IsA(neutronclient.Client),
                'subnet',
                '91e47a57-7508-46fe-afc9-fc454e8580e1'
            ).AndReturn('91e47a57-7508-46fe-afc9-fc454e8580e1')
            self.m.ReplayAll()
            rsrc = self.create_router_interface(
                t, stack, 'router_interface', properties={
                    'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                    'subnet': '91e47a57-7508-46fe-afc9-fc454e8580e1'
                })
        else:
            self.m.ReplayAll()
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
        ex = self.assertRaises(exception.StackValidationFailed, res.validate)
        self.assertEqual("Either subnet or port_id must be specified.",
                         six.text_type(ex))

    def test_gateway_router(self):
        neutronV20.find_resourceid_by_name_or_id(
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


class NeutronFloatingIPTest(HeatTestCase):

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
        self.stub_keystoneclient()

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
        if resolve_neutron:
            neutronV20.find_resourceid_by_name_or_id(
                mox.IsA(neutronclient.Client),
                'network',
                'abcd1234'
            ).AndReturn('abcd1234')

        stack = utils.parse_stack(tmpl)

        # assert the implicit dependency between the floating_ip
        # and the gateway
        self.m.ReplayAll()

        if r_iface:
            deps = stack.dependencies[stack['router_interface']]
            self.assertIn(stack['floating_ip'], deps)
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

        props = {
            "network": "xyz1234",
            "fixed_ips": [{
                "subnet_id": "sub1234",
                "ip_address": "10.0.0.11"
            }],
            "name": "test_port",
            "device_id": "d6b4d3a5-c700-476f-b609-1493dd9dadc2",
            'device_owner': 'network:floatingip'
        }
        update_snippet = rsrc_defn.ResourceDefinition(p.name, p.type(), props)

        p.handle_update(update_snippet, {}, {})

        self.m.VerifyAll()

    def test_floatip_association_port(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234'
        ).AndReturn('abcd1234')
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

        fipa.state_set(fipa.CREATE, fipa.COMPLETE, 'to delete again')
        fip.state_set(fip.CREATE, fip.COMPLETE, 'to delete again')
        p.state_set(p.CREATE, p.COMPLETE, 'to delete again')

        scheduler.TaskRunner(fipa.delete)()
        self.assertIsNone(scheduler.TaskRunner(p.delete)())
        scheduler.TaskRunner(fip.delete)()

        self.m.VerifyAll()

    def test_floatip_port(self):
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
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234'
        ).AndReturn('abcd1234')
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

        self.m.ReplayAll()

        t = template_format.parse(neutron_floating_no_assoc_template)
        stack = utils.parse_stack(t)

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


class NeutronPortTest(HeatTestCase):

    def setUp(self):
        super(NeutronPortTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_port')
        self.m.StubOutWithMock(neutronclient.Client, 'show_port')
        self.m.StubOutWithMock(neutronclient.Client, 'update_port')
        self.m.StubOutWithMock(neutronclient.Client, 'show_subnet')
        self.m.StubOutWithMock(neutronV20, 'find_resourceid_by_name_or_id')
        self.stub_keystoneclient()

    def test_missing_subnet_id(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'net1234'
        ).AndReturn('net1234')
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
        t['Resources']['port']['Properties']['fixed_ips'][0].pop('subnet')
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()

        self.m.VerifyAll()

    def test_missing_ip_address(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'net1234'
        ).AndReturn('net1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub1234'
        ).AndReturn('sub1234')

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
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'net1234'
        ).AndReturn('net1234')
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
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234'
        ).AndReturn('abcd1234')
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
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234'
        ).AndReturn('abcd1234')
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
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'net1234'
        ).AndReturn('net1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub1234'
        ).AndReturn('sub1234')
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

    def test_create_and_update_port(self):
        props = {'network_id': u'net1234',
                 'name': utils.PhysName('test_stack', 'port'),
                 'admin_state_up': True,
                 'device_owner': u'network:dhcp'}
        new_props = props.copy()
        new_props['name'] = "new_name"
        new_props_update = new_props.copy()
        new_props_update.pop('network_id')

        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'net1234'
        ).AndReturn('net1234')
        neutronclient.Client.create_port(
            {'port': props}
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
        neutronclient.Client.update_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'port': new_props_update}
        ).AndReturn(None)

        self.m.ReplayAll()

        # create port
        t = template_format.parse(neutron_port_template)
        t['Resources']['port']['Properties'].pop('fixed_ips')
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()

        # update port
        update_snippet = rsrc_defn.ResourceDefinition(port.name, port.type(),
                                                      new_props)
        self.assertIsNone(port.handle_update(update_snippet, {}, {}))

        self.m.VerifyAll()

    def test_port_needs_update(self):
        props = {'network_id': u'net1234',
                 'name': utils.PhysName('test_stack', 'port'),
                 'admin_state_up': True,
                 'device_owner': u'network:dhcp'}

        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'net1234'
        ).AndReturn('net1234')
        neutronclient.Client.create_port(
            {'port': props}
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

        # create port
        t = template_format.parse(neutron_port_template)
        t['Resources']['port']['Properties'].pop('fixed_ips')
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()

        new_props = props.copy()

        # test always replace
        new_props['replacement_policy'] = 'REPLACE_ALWAYS'
        update_snippet = rsrc_defn.ResourceDefinition(port.name, port.type(),
                                                      new_props)
        self.assertRaises(resource.UpdateReplace, port._needs_update,
                          update_snippet, port.frozen_definition(),
                          new_props, props, None)

        # test deferring to Resource._needs_update
        new_props['replacement_policy'] = 'AUTO'
        update_snippet = rsrc_defn.ResourceDefinition(port.name, port.type(),
                                                      new_props)
        self.assertTrue(port._needs_update(update_snippet,
                                           port.frozen_definition(),
                                           new_props, props, None))

        self.m.VerifyAll()

    def test_get_port_attributes(self):
        subnet_dict = {'name': 'test-subnet', 'enable_dhcp': True,
                       'network_id': 'net1234', 'dns_nameservers': [],
                       'tenant_id': '58a61fc3992944ce971404a2ece6ff98',
                       'ipv6_ra_mode': None, 'cidr': '10.0.0.0/24',
                       'allocation_pools': [{'start': '10.0.0.2',
                                             'end': u'10.0.0.254'}],
                       'gateway_ip': '10.0.0.1', 'ipv6_address_mode': None,
                       'ip_version': 4, 'host_routes': [],
                       'id': '6dd609ad-d52a-4587-b1a0-b335f76062a5'}
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'net1234'
        ).AndReturn('net1234')
        neutronclient.Client.create_port({'port': {
            'network_id': u'net1234',
            'name': utils.PhysName('test_stack', 'port'),
            'admin_state_up': True,
            'device_owner': u'network:dhcp'}}
        ).AndReturn({'port': {
            'status': 'BUILD',
            'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        }})
        neutronclient.Client.show_subnet(
            'd0e971a6-a6b4-4f4c-8c88-b75e9c120b7e'
        ).AndReturn({'subnet': subnet_dict})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).MultipleTimes().AndReturn({'port': {
            'status': 'DOWN',
            'name': utils.PhysName('test_stack', 'port'),
            'allowed_address_pairs': [],
            'admin_state_up': True,
            'network_id': 'net1234',
            'device_id': 'dc68eg2c-b60g-4b3f-bd82-67ec87650532',
            'mac_address': 'fa:16:3e:75:67:60',
            'tenant_id': '58a61fc3992944ce971404a2ece6ff98',
            'security_groups': ['5b15d80c-6b70-4a1c-89c9-253538c5ade6'],
            'fixed_ips': [{'subnet_id': 'd0e971a6-a6b4-4f4c-8c88-b75e9c120b7e',
                           'ip_address': '10.0.0.2'}]
        }})
        self.m.ReplayAll()

        t = template_format.parse(neutron_port_template)
        t['Resources']['port']['Properties'].pop('fixed_ips')
        stack = utils.parse_stack(t)

        port = stack['port']
        scheduler.TaskRunner(port.create)()
        self.assertEqual('DOWN', port.FnGetAtt('status'))
        self.assertEqual([], port.FnGetAtt('allowed_address_pairs'))
        self.assertEqual(True, port.FnGetAtt('admin_state_up'))
        self.assertEqual('net1234', port.FnGetAtt('network_id'))
        self.assertEqual('fa:16:3e:75:67:60', port.FnGetAtt('mac_address'))
        self.assertEqual(utils.PhysName('test_stack', 'port'),
                         port.FnGetAtt('name'))
        self.assertEqual('dc68eg2c-b60g-4b3f-bd82-67ec87650532',
                         port.FnGetAtt('device_id'))
        self.assertEqual('58a61fc3992944ce971404a2ece6ff98',
                         port.FnGetAtt('tenant_id'))
        self.assertEqual(['5b15d80c-6b70-4a1c-89c9-253538c5ade6'],
                         port.FnGetAtt('security_groups'))
        self.assertEqual([{'subnet_id': 'd0e971a6-a6b4-4f4c-8c88-b75e9c120b7e',
                           'ip_address': '10.0.0.2'}],
                         port.FnGetAtt('fixed_ips'))
        self.assertEqual([subnet_dict], port.FnGetAtt('subnets'))
        self.assertRaises(exception.InvalidTemplateAttribute,
                          port.FnGetAtt, 'Foo')
        self.m.VerifyAll()

    def test_subnet_attribute_exception(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'net1234'
        ).AndReturn('net1234')
        neutronclient.Client.create_port({'port': {
            'network_id': u'net1234',
            'name': utils.PhysName('test_stack', 'port'),
            'admin_state_up': True,
            'device_owner': u'network:dhcp'}}
        ).AndReturn({'port': {
            'status': 'BUILD',
            'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        }})
        neutronclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).MultipleTimes().AndReturn({'port': {
            'status': 'DOWN',
            'name': utils.PhysName('test_stack', 'port'),
            'allowed_address_pairs': [],
            'admin_state_up': True,
            'network_id': 'net1234',
            'device_id': 'dc68eg2c-b60g-4b3f-bd82-67ec87650532',
            'mac_address': 'fa:16:3e:75:67:60',
            'tenant_id': '58a61fc3992944ce971404a2ece6ff98',
            'security_groups': ['5b15d80c-6b70-4a1c-89c9-253538c5ade6'],
            'fixed_ips': [{'subnet_id': 'd0e971a6-a6b4-4f4c-8c88-b75e9c120b7e',
                           'ip_address': '10.0.0.2'}]
        }})
        neutronclient.Client.show_subnet(
            'd0e971a6-a6b4-4f4c-8c88-b75e9c120b7e'
        ).AndRaise(qe.NeutronClientException('ConnectionFailed: Connection '
                                             'to neutron failed: Maximum '
                                             'attempts reached'))
        self.m.ReplayAll()

        t = template_format.parse(neutron_port_template)
        t['Resources']['port']['Properties'].pop('fixed_ips')
        stack = utils.parse_stack(t)
        port = stack['port']
        scheduler.TaskRunner(port.create)()
        self.assertIsNone(port.FnGetAtt('subnets'))
        log_msg = ('Failed to fetch resource attributes: ConnectionFailed: '
                   'Connection to neutron failed: Maximum attempts reached')
        self.assertIn(log_msg, self.LOG.output)
        self.m.VerifyAll()


class NetworkConstraintTest(HeatTestCase):

    def test_validate(self):
        nc = self.m.CreateMockAnything()
        self.m.StubOutWithMock(neutron.NeutronClientPlugin, '_create')
        neutron.NeutronClientPlugin._create().AndReturn(nc)
        self.m.StubOutWithMock(neutron.neutronV20,
                               'find_resourceid_by_name_or_id')
        neutron.neutronV20.find_resourceid_by_name_or_id(
            nc, 'network', 'foo'
        ).AndReturn('foo')
        neutron.neutronV20.find_resourceid_by_name_or_id(
            nc, 'network', 'bar'
        ).AndRaise(qe.NeutronClientException(status_code=404))
        self.m.ReplayAll()

        constraint = neutron.NetworkConstraint()
        ctx = utils.dummy_context()
        self.assertTrue(constraint.validate("foo", ctx))
        self.assertFalse(constraint.validate("bar", ctx))

        self.m.VerifyAll()


class PortConstraintTest(HeatTestCase):

    def test_validate(self):
        nc = self.m.CreateMockAnything()
        self.m.StubOutWithMock(neutron.NeutronClientPlugin, '_create')
        neutron.NeutronClientPlugin._create().AndReturn(nc)
        self.m.StubOutWithMock(neutron.neutronV20,
                               'find_resourceid_by_name_or_id')
        neutron.neutronV20.find_resourceid_by_name_or_id(
            nc, 'port', 'foo'
        ).AndReturn('foo')
        neutron.neutronV20.find_resourceid_by_name_or_id(
            nc, 'port', 'bar'
        ).AndRaise(qe.NeutronClientException(status_code=404))
        self.m.ReplayAll()

        constraint = neutron.PortConstraint()
        ctx = utils.dummy_context()
        self.assertTrue(constraint.validate("foo", ctx))
        self.assertFalse(constraint.validate("bar", ctx))

        self.m.VerifyAll()


class RouterConstraintTest(HeatTestCase):

    def test_validate(self):
        nc = self.m.CreateMockAnything()
        self.m.StubOutWithMock(neutron.NeutronClientPlugin, '_create')
        neutron.NeutronClientPlugin._create().AndReturn(nc)
        self.m.StubOutWithMock(neutron.neutronV20,
                               'find_resourceid_by_name_or_id')
        neutron.neutronV20.find_resourceid_by_name_or_id(
            nc, 'router', 'foo'
        ).AndReturn('foo')
        neutron.neutronV20.find_resourceid_by_name_or_id(
            nc, 'router', 'bar'
        ).AndRaise(qe.NeutronClientException(status_code=404))
        self.m.ReplayAll()

        constraint = neutron.RouterConstraint()
        ctx = utils.dummy_context()
        self.assertTrue(constraint.validate("foo", ctx))
        self.assertFalse(constraint.validate("bar", ctx))

        self.m.VerifyAll()


class SubnetConstraintTest(HeatTestCase):

    def test_validate(self):
        nc = self.m.CreateMockAnything()
        self.m.StubOutWithMock(neutron.NeutronClientPlugin, '_create')
        neutron.NeutronClientPlugin._create().AndReturn(nc)
        self.m.StubOutWithMock(neutron.neutronV20,
                               'find_resourceid_by_name_or_id')
        neutron.neutronV20.find_resourceid_by_name_or_id(
            nc, 'subnet', 'foo'
        ).AndReturn('foo')
        neutron.neutronV20.find_resourceid_by_name_or_id(
            nc, 'subnet', 'bar'
        ).AndRaise(qe.NeutronClientException(status_code=404))
        self.m.ReplayAll()

        constraint = neutron.SubnetConstraint()
        ctx = utils.dummy_context()
        self.assertTrue(constraint.validate("foo", ctx))
        self.assertFalse(constraint.validate("bar", ctx))

        self.m.VerifyAll()
