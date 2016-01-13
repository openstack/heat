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
      shared: true
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


class NeutronProviderNetTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronProviderNetTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_network')
        self.m.StubOutWithMock(neutronclient.Client, 'show_network')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_network')
        self.m.StubOutWithMock(neutronclient.Client, 'update_network')
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

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
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = provider_net.ProviderNet(
            'provider_net', resource_defns['provider_network_vlan'],
            self.stack)

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
                'provider:network_type': 'vlan',
                'provider:physical_network': 'physnet_1',
                'provider:segmentation_id': '102'
            }}).AndReturn(None)

        neutronclient.Client.update_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'network': {
                'name': utils.PhysName('test_stack', 'provider_net')
            }}).AndReturn(None)

        self.m.ReplayAll()

        rsrc.validate()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        prop_diff = {
            "network_type": "vlan",
            "physical_network": "physnet_1",
            "segmentation_id": "102"
        }
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      prop_diff)
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, prop_diff))

        # name=None
        self.assertIsNone(rsrc.handle_update(update_snippet, {},
                                             {'name': None}))
        # no prop_diff
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, {}))
        self.m.VerifyAll()
