
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

import mock

from neutronclient.v2_0 import client as neutronclient

from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import extraroute
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


neutron_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test OS::Neutron::ExtraRoute resources",
  "Parameters" : {},
  "Resources" : {
    "router": {
      "Type": "OS::Neutron::Router"
    },
    "extraroute1": {
      "Type": "OS::Neutron::ExtraRoute",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "destination" : "192.168.0.0/24",
        "nexthop": "1.1.1.1"
      }
    },
    "extraroute2": {
      "Type": "OS::Neutron::ExtraRoute",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "destination" : "192.168.255.0/24",
        "nexthop": "1.1.1.1"
      }
    }
  }
}
'''


class NeutronExtraRouteTest(common.HeatTestCase):
    def setUp(self):
        super(NeutronExtraRouteTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client',
                         return_value=self.mockclient)

        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_extraroute(self, t, stack, resource_name, properties=None):
        properties = properties or {}
        t['Resources'][resource_name]['Properties'] = properties
        rsrc = extraroute.ExtraRoute(
            resource_name,
            stack.t.resource_definitions(stack)[resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_extraroute(self):
        route1 = {"destination": "192.168.0.0/24",
                  "nexthop": "1.1.1.1"}
        route2 = {"destination": "192.168.255.0/24",
                  "nexthop": "1.1.1.1"}

        self.stub_RouterConstraint_validate()

        self.mockclient.show_router.side_effect = [
            # add first route
            {'router': {'routes': []}},
            # add second route
            {'router': {'routes': [route1.copy()]}},
            # first delete
            {'router': {'routes': [route1.copy(), route2.copy()]}},
            # second delete
            {'router': {'routes': [route2.copy()]}},
        ]
        self.mockclient.update_router.return_value = None

        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc1 = self.create_extraroute(
            t, stack, 'extraroute1', properties={
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'destination': '192.168.0.0/24',
                'nexthop': '1.1.1.1'})

        self.create_extraroute(
            t, stack, 'extraroute2', properties={
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'destination': '192.168.255.0/24',
                'nexthop': '1.1.1.1'})

        scheduler.TaskRunner(rsrc1.delete)()
        rsrc1.state_set(rsrc1.CREATE, rsrc1.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc1.delete)()

        self.mockclient.show_router.assert_called_with(
            '3e46229d-8fce-4733-819a-b5fe630550f8')
        self.mockclient.update_router.assert_has_calls([
            # add first route
            mock.call('3e46229d-8fce-4733-819a-b5fe630550f8',
                      {'router': {'routes': [route1.copy()]}}),
            # add second route
            mock.call('3e46229d-8fce-4733-819a-b5fe630550f8',
                      {'router': {'routes': [route1.copy(),
                                             route2.copy()]}}),
            # first delete
            mock.call('3e46229d-8fce-4733-819a-b5fe630550f8',
                      {'router': {'routes': [route2.copy()]}}),
        ])
