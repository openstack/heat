
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

from testtools import skipIf

from heat.common import template_format
from heat.engine import clients
from heat.engine import resource
from heat.engine.resources.neutron import router
from heat.engine import scheduler
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils

from ..resources import extraroute  # noqa

neutronclient = try_import('neutronclient.v2_0.client')
qe = try_import('neutronclient.common.exceptions')

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


@skipIf(neutronclient is None, 'neutronclient unavailable')
class NeutronExtraRouteTest(HeatTestCase):
    @skipIf(router.neutronV20 is None, "Missing Neutron v2_0")
    def setUp(self):
        super(NeutronExtraRouteTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'show_router')
        self.m.StubOutWithMock(neutronclient.Client, 'update_router')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')

        utils.setup_dummy_db()

        resource._register_class("OS::Neutron::ExtraRoute",
                                 extraroute.ExtraRoute)

    def create_extraroute(self, t, stack, resource_name, properties={}):
        t['Resources'][resource_name]['Properties'] = properties
        rsrc = extraroute.ExtraRoute(
            resource_name,
            t['Resources'][resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_extraroute(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        # add first route
        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8')\
            .AndReturn({'router': {'routes': []}})
        neutronclient.Client.update_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {"router": {
                "routes": [
                    {"destination": "192.168.0.0/24", "nexthop": "1.1.1.1"},
                ]
            }}).AndReturn(None)
        # add second route
        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8')\
            .AndReturn({'router': {'routes': [{"destination": "192.168.0.0/24",
                                               "nexthop": "1.1.1.1"}]}})
        neutronclient.Client.update_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {"router": {
                "routes": [
                    {"destination": "192.168.0.0/24", "nexthop": "1.1.1.1"},
                    {"destination": "192.168.255.0/24", "nexthop": "1.1.1.1"}
                ]
            }}).AndReturn(None)
        # first delete
        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8')\
            .AndReturn({'router':
                        {'routes': [{"destination": "192.168.0.0/24",
                                     "nexthop": "1.1.1.1"},
                                    {"destination": "192.168.255.0/24",
                                     "nexthop": "1.1.1.1"}]}})
        neutronclient.Client.update_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {"router": {
                "routes": [
                    {"destination": "192.168.255.0/24", "nexthop": "1.1.1.1"}
                ]
            }}).AndReturn(None)
        # second delete
        neutronclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8')\
            .AndReturn({'router':
                        {'routes': [{"destination": "192.168.255.0/24",
                                     "nexthop": "1.1.1.1"}]}})
        self.m.ReplayAll()
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
        self.m.VerifyAll()
