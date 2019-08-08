# Copyright 2019 Ericsson Software Technology
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy

from oslo_log import log as logging

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import extrarouteset
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils
from neutronclient.common import exceptions as ncex
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient


LOG = logging.getLogger(__name__)

template = '''
heat_template_version: rocky
description: Test create OS::Neutron::ExtraRouteSet
resources:
  extrarouteset0:
    type: OS::Neutron::ExtraRouteSet
    properties:
      router: 88ce38c4-be8e-11e9-a0a5-5f64570eeec8
      routes:
        - destination: 10.0.1.0/24
          nexthop: 10.0.0.11
        - destination: 10.0.2.0/24
          nexthop: 10.0.0.12
'''


class NeutronExtraRouteSetTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronExtraRouteSetTest, self).setUp()

        self.patchobject(
            neutron.NeutronClientPlugin, 'has_extension', return_value=True)

        self.add_extra_routes_mock = self.patchobject(
            neutronclient.Client, 'add_extra_routes_to_router')
        self.add_extra_routes_mock.return_value = {
            'router': {
                'id': '85b91046-be84-11e9-b518-2714ef1d76c3',
                'routes': [
                    {'destination': '10.0.1.0/24', 'nexthop': '10.0.0.11'},
                    {'destination': '10.0.2.0/24', 'nexthop': '10.0.0.12'},
                ],
            }
        }

        self.remove_extra_routes_mock = self.patchobject(
            neutronclient.Client, 'remove_extra_routes_from_router')
        self.remove_extra_routes_mock.return_value = {
            'router': {
                'id': '85b91046-be84-11e9-b518-2714ef1d76c3',
                'routes': [
                    {'destination': '10.0.1.0/24', 'nexthop': '10.0.0.11'},
                    {'destination': '10.0.2.0/24', 'nexthop': '10.0.0.12'},
                ],
            }
        }

        self.show_router_mock = self.patchobject(
            neutronclient.Client, 'show_router')
        self.show_router_mock.return_value = {
            'router': {
                'id': '85b91046-be84-11e9-b518-2714ef1d76c3',
                'routes': [],
            }
        }

        def find_resourceid_by_name_or_id(
                _client, _resource, name_or_id, **_kwargs):
            return name_or_id

        self.find_resource_mock = self.patchobject(
            neutronV20, 'find_resourceid_by_name_or_id')
        self.find_resource_mock.side_effect = find_resourceid_by_name_or_id

    def test_routes_to_set_to_routes(self):
        routes = [{'destination': '10.0.1.0/24', 'nexthop': '10.0.0.11'}]
        self.assertEqual(
            routes,
            extrarouteset._set_to_routes(extrarouteset._routes_to_set(routes))
        )

    def test_diff_routes(self):
        old = [
            {'destination': '10.0.1.0/24', 'nexthop': '10.0.0.11'},
            {'destination': '10.0.2.0/24', 'nexthop': '10.0.0.12'},
        ]
        new = [
            {'destination': '10.0.1.0/24', 'nexthop': '10.0.0.11'},
            {'destination': '10.0.3.0/24', 'nexthop': '10.0.0.13'},
        ]

        add = extrarouteset._set_to_routes(
            extrarouteset._routes_to_set(new) -
            extrarouteset._routes_to_set(old))
        remove = extrarouteset._set_to_routes(
            extrarouteset._routes_to_set(old) -
            extrarouteset._routes_to_set(new))

        self.assertEqual(
            [{'destination': '10.0.3.0/24', 'nexthop': '10.0.0.13'}], add)
        self.assertEqual(
            [{'destination': '10.0.2.0/24', 'nexthop': '10.0.0.12'}], remove)

    def test__raise_if_duplicate_positive(self):
        self.assertRaises(
            exception.PhysicalResourceExists,
            extrarouteset._raise_if_duplicate,
            {'router': {'routes': [
                {'destination': 'dst1', 'nexthop': 'hop1'},
            ]}},
            [{'destination': 'dst1', 'nexthop': 'hop1'}],
        )

    def test__raise_if_duplicate_negative(self):
        try:
            extrarouteset._raise_if_duplicate(
                {'router': {'routes': [
                    {'destination': 'dst1', 'nexthop': 'hop1'},
                ]}},
                [{'destination': 'dst2', 'nexthop': 'hop2'}],
            )
        except exception.PhysicalResourceExists:
            self.fail('Unexpected exception in detecting duplicate routes')

    def test_create(self):
        t = template_format.parse(template)
        stack = utils.parse_stack(t)

        extra_routes = stack['extrarouteset0']
        scheduler.TaskRunner(extra_routes.create)()

        self.assertEqual(
            (extra_routes.CREATE, extra_routes.COMPLETE), extra_routes.state)
        self.add_extra_routes_mock.assert_called_once_with(
            '88ce38c4-be8e-11e9-a0a5-5f64570eeec8',
            {'router': {
                'routes': [
                    {'destination': '10.0.1.0/24', 'nexthop': '10.0.0.11'},
                    {'destination': '10.0.2.0/24', 'nexthop': '10.0.0.12'},
                ]}})

    def test_delete_proper(self):
        t = template_format.parse(template)
        stack = utils.parse_stack(t)

        extra_routes = stack['extrarouteset0']
        scheduler.TaskRunner(extra_routes.create)()
        scheduler.TaskRunner(extra_routes.delete)()

        self.assertEqual(
            (extra_routes.DELETE, extra_routes.COMPLETE), extra_routes.state)
        self.remove_extra_routes_mock.assert_called_once_with(
            '88ce38c4-be8e-11e9-a0a5-5f64570eeec8',
            {'router': {
                'routes': [
                    {'destination': '10.0.1.0/24', 'nexthop': '10.0.0.11'},
                    {'destination': '10.0.2.0/24', 'nexthop': '10.0.0.12'},
                ]}})

    def test_delete_router_already_gone(self):
        t = template_format.parse(template)
        stack = utils.parse_stack(t)

        self.remove_extra_routes_mock.side_effect = (
            ncex.NeutronClientException(status_code=404))

        extra_routes = stack['extrarouteset0']
        scheduler.TaskRunner(extra_routes.create)()
        scheduler.TaskRunner(extra_routes.delete)()

        self.assertEqual(
            (extra_routes.DELETE, extra_routes.COMPLETE), extra_routes.state)
        self.remove_extra_routes_mock.assert_called_once_with(
            '88ce38c4-be8e-11e9-a0a5-5f64570eeec8',
            {'router': {
                'routes': [
                    {'destination': '10.0.1.0/24', 'nexthop': '10.0.0.11'},
                    {'destination': '10.0.2.0/24', 'nexthop': '10.0.0.12'},
                ]}})

    def test_update(self):
        t = template_format.parse(template)
        stack = utils.parse_stack(t)

        extra_routes = stack['extrarouteset0']
        scheduler.TaskRunner(extra_routes.create)()
        self.assertEqual(
            (extra_routes.CREATE, extra_routes.COMPLETE), extra_routes.state)

        self.add_extra_routes_mock.reset_mock()

        rsrc_defn = stack.defn.resource_definition('extrarouteset0')

        props = copy.deepcopy(t['resources']['extrarouteset0']['properties'])
        props['routes'][1] = {
            'destination': '10.0.3.0/24', 'nexthop': '10.0.0.13'}
        rsrc_defn = rsrc_defn.freeze(properties=props)

        scheduler.TaskRunner(extra_routes.update, rsrc_defn)()
        self.assertEqual(
            (extra_routes.UPDATE, extra_routes.COMPLETE), extra_routes.state)

        self.remove_extra_routes_mock.assert_called_once_with(
            '88ce38c4-be8e-11e9-a0a5-5f64570eeec8',
            {'router': {
                'routes': [
                    {'destination': '10.0.2.0/24', 'nexthop': '10.0.0.12'},
                ]}})
        self.add_extra_routes_mock.assert_called_once_with(
            '88ce38c4-be8e-11e9-a0a5-5f64570eeec8',
            {'router': {
                'routes': [
                    {'destination': '10.0.3.0/24', 'nexthop': '10.0.0.13'},
                ]}})
