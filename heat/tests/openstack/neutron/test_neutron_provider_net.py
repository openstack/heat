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
import mock

from neutronclient.common import exceptions as qe
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import provider_net
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


provider_network_template = '''
heat_template_version: 2015-04-30
description: Template to test provider_net Neutron resources
resources:
  provider_network_vlan:
    type: OS::Neutron::ProviderNet
    properties:
      name: the_provider_network
      network_type: vlan
      physical_network: physnet_1
      segmentation_id: 101
      router_external: False
      shared: true
      tags:
        - tag1
        - tag2
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
        "router:external": False,
        "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
        "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
    }
}

stpnb = copy.deepcopy(stpna)
stpnb['network']['status'] = "BUILD"


class NeutronProviderNetTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronProviderNetTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_provider_net(self):
        # Create script
        self.mockclient.create_network.return_value = stpnb

        t = template_format.parse(provider_network_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = provider_net.ProviderNet(
            'provider_net', resource_defns['provider_network_vlan'],
            self.stack)

        return rsrc

    def test_create_provider_net(self):
        resource_type = 'networks'
        rsrc = self.create_provider_net()
        self.mockclient.show_network.side_effect = [
            stpnb,
            stpna,
            qe.NetworkNotFoundClient(status_code=404),
            stpna,
            qe.NetworkNotFoundClient(status_code=404),
        ]
        self.mockclient.delete_network.side_effect = [
            None,
            qe.NetworkNotFoundClient(status_code=404),
        ]

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

        self.mockclient.create_network.assert_called_once_with({
            'network': {
                'name': u'the_provider_network',
                'admin_state_up': True,
                'provider:network_type': 'vlan',
                'provider:physical_network': 'physnet_1',
                'provider:segmentation_id': '101',
                'router:external': False,
                'shared': True
            }
        })
        self.mockclient.replace_tag.assert_called_with(
            resource_type,
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'tags': ['tag1', 'tag2']}
        )
        self.mockclient.show_network.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        self.assertEqual(5, self.mockclient.show_network.call_count)
        self.mockclient.delete_network.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        self.assertEqual(2, self.mockclient.delete_network.call_count)

    def test_update_provider_net(self):
        resource_type = 'networks'
        rsrc = self.create_provider_net()
        self.mockclient.show_network.side_effect = [stpnb, stpna]
        self.mockclient.update_network.return_value = None

        rsrc.validate()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        prop_diff = {
            'network_type': 'vlan',
            'physical_network': 'physnet_1',
            'segmentation_id': '102',
            'port_security_enabled': False,
            'router_external': True,
            'tags': [],
        }
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      prop_diff)
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, prop_diff))

        # name=None
        self.assertIsNone(rsrc.handle_update(update_snippet, {},
                                             {'name': None}))
        # no prop_diff
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, {}))

        self.mockclient.create_network.assert_called_once_with({
            'network': {
                'name': u'the_provider_network',
                'admin_state_up': True,
                'provider:network_type': 'vlan',
                'provider:physical_network': 'physnet_1',
                'provider:segmentation_id': '101',
                'router:external': False,
                'shared': True}
        })
        self.mockclient.replace_tag.assert_called_with(
            resource_type,
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'tags': []}
        )
        self.mockclient.show_network.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        self.assertEqual(2, self.mockclient.show_network.call_count)
        self.mockclient.update_network.assert_has_calls([
            mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                      {
                          'network': {
                              'provider:network_type': 'vlan',
                              'provider:physical_network': 'physnet_1',
                              'provider:segmentation_id': '102',
                              'port_security_enabled': False,
                              'router:external': True
                          }
                      }),
            mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                      {
                          'network': {
                              'name': utils.PhysName(rsrc.stack.name,
                                                     'provider_net'),
                          }
                      }),
        ])
        self.assertEqual(2, self.mockclient.update_network.call_count)

    def test_get_live_state(self):
        rsrc = self.create_provider_net()
        self.mockclient.show_network.return_value = {
            'network': {
                'status': 'ACTIVE',
                'subnets': [],
                'availability_zone_hints': [],
                'availability_zones': [],
                'name': 'prov-provider-nhalkd5xftp3',
                'provider:physical_network': 'public',
                'admin_state_up': True,
                'tenant_id': 'df49ea64e87c43a792a510698364f03e',
                'mtu': 0,
                'router:external': False,
                'port_security_enabled': True,
                'shared': True,
                'provider:network_type': 'flat',
                'id': 'af216806-4462-4c68-bfa4-9580857e71c3',
                'provider:segmentation_id': None,
                'tags': ['tag1', 'tag2'],
            }
        }

        reality = rsrc.get_live_state(rsrc.properties)
        expected = {
            'name': 'prov-provider-nhalkd5xftp3',
            'physical_network': 'public',
            'admin_state_up': True,
            'network_type': 'flat',
            'port_security_enabled': True,
            'segmentation_id': None,
            'router_external': False,
            'tags': ['tag1', 'tag2'],
        }

        self.assertEqual(expected, reality)

        self.mockclient.show_network.assert_called_once()
