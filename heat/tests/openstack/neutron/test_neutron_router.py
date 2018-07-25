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
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import router
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


neutron_template = '''
heat_template_version: 2015-04-30
description: Template to test router related Neutron resources
resources:
  router:
    type: OS::Neutron::Router
    properties:
      l3_agent_ids:
       - 792ff887-6c85-4a56-b518-23f24fa65581

  router_interface:
    type: OS::Neutron::RouterInterface
    properties:
      router_id: { get_resource: router }
      subnet: sub1234

  gateway:
    type: OS::Neutron::RouterGateway
    properties:
      router_id: { get_resource: router }
      network: net1234
'''

hidden_property_router_template = '''
heat_template_version: 2015-04-30
description: Template to test router related Neutron resources
resources:
  router:
    type: OS::Neutron::Router
    properties:
      l3_agent_id: 792ff887-6c85-4a56-b518-23f24fa65581
'''

neutron_external_gateway_template = '''
heat_template_version: 2016-04-08
description: Template to test gateway Neutron resource
resources:
 router:
   type: OS::Neutron::Router
   properties:
     name: Test Router
     external_gateway_info:
       network: public
       enable_snat: true
       external_fixed_ips:
        - ip_address: 192.168.10.99
          subnet: sub1234
'''

neutron_subnet_and_external_gateway_template = '''
heat_template_version: 2015-04-30
description: Template to test gateway Neutron resource
resources:
  net_external:
    type: OS::Neutron::Net
    properties:
      name: net_external
      admin_state_up: true
      value_specs:
        provider:network_type: flat
        provider:physical_network: default
        router:external: true

  subnet_external:
    type: OS::Neutron::Subnet
    properties:
      name: subnet_external
      network_id: { get_resource: net_external}
      ip_version: 4
      cidr: 192.168.10.0/24
      gateway_ip: 192.168.10.11
      enable_dhcp: false

  floating_ip:
    type: OS::Neutron::FloatingIP
    properties:
      floating_network: { get_resource: net_external}

  router:
    type: OS::Neutron::Router
    properties:
      name: router_heat
      external_gateway_info:
        network: { get_resource: net_external}
'''


class NeutronRouterTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronRouterTest, self).setUp()
        self.create_mock = self.patchobject(neutronclient.Client,
                                            'create_router')
        self.delete_mock = self.patchobject(neutronclient.Client,
                                            'delete_router')
        self.show_mock = self.patchobject(neutronclient.Client,
                                          'show_router')
        self.update_mock = self.patchobject(neutronclient.Client,
                                            'update_router')
        self.add_if_mock = self.patchobject(neutronclient.Client,
                                            'add_interface_router')
        self.remove_if_mock = self.patchobject(neutronclient.Client,
                                               'remove_interface_router')
        self.add_gw_mock = self.patchobject(neutronclient.Client,
                                            'add_gateway_router')
        self.remove_gw_mock = self.patchobject(neutronclient.Client,
                                               'remove_gateway_router')
        self.add_router_mock = self.patchobject(
            neutronclient.Client,
            'add_router_to_l3_agent')
        self.remove_router_mock = self.patchobject(
            neutronclient.Client,
            'remove_router_from_l3_agent')
        self.list_l3_hr_mock = self.patchobject(
            neutronclient.Client,
            'list_l3_agent_hosting_routers')
        self.find_rsrc_mock = self.patchobject(
            neutron.NeutronClientPlugin,
            'find_resourceid_by_name_or_id')
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_router(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = router.Router('router', resource_defns[resource_name], stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_router_interface(self, t, stack, resource_name,
                                properties=None):
        properties = properties or {}
        t['resources'][resource_name]['properties'] = properties
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
        t['resources'][resource_name]['properties'] = properties
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = router.RouterGateway(
            'gateway',
            resource_defns[resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_router_hidden_property_translation(self):
        t = template_format.parse(hidden_property_router_template)
        stack = utils.parse_stack(t)
        rsrc = stack['router']
        self.assertIsNone(rsrc.properties['l3_agent_id'])
        self.assertEqual([u'792ff887-6c85-4a56-b518-23f24fa65581'],
                         rsrc.properties['l3_agent_ids'])

    def test_router_validate_distribute_l3_agents(self):
        t = template_format.parse(neutron_template)
        props = t['resources']['router']['properties']

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
        exc = self.assertRaises(exception.ResourcePropertyConflict,
                                rsrc.validate)
        self.assertIn('distributed, l3_agent_id/l3_agent_ids',
                      six.text_type(exc))

    def test_router_validate_l3_agents(self):
        t = template_format.parse(neutron_template)
        props = t['resources']['router']['properties']

        # test l3_agent_id and l3_agent_ids can not specify at the same time
        props['l3_agent_ids'] = ['id1', 'id2']
        stack = utils.parse_stack(t)
        rsrc = stack['router']
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn('Non HA routers can only have one L3 agent',
                      six.text_type(exc))
        self.assertIsNone(rsrc.properties.get(rsrc.L3_AGENT_ID))

    def test_router_validate_ha_distribute(self):
        t = template_format.parse(neutron_template)
        props = t['resources']['router']['properties']

        # test distributed and ha can not specify at the same time
        props['ha'] = True
        props['distributed'] = True
        stack = utils.parse_stack(t)
        rsrc = stack['router']
        update_props = props.copy()
        del update_props['l3_agent_ids']
        rsrc.t = rsrc.t.freeze(properties=update_props)
        rsrc.reparse()
        exc = self.assertRaises(exception.ResourcePropertyConflict,
                                rsrc.validate)
        self.assertIn('distributed, ha', six.text_type(exc))

    def test_router_validate_ha_l3_agents(self):
        t = template_format.parse(neutron_template)
        props = t['resources']['router']['properties']
        # test non ha can not specify more than one l3 agent id
        props['ha'] = False
        props['l3_agent_ids'] = ['id1', 'id2']
        stack = utils.parse_stack(t)
        rsrc = stack['router']
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn('Non HA routers can only have one L3 agent.',
                      six.text_type(exc))

    def test_router(self):
        t = template_format.parse(neutron_template)
        tags = ['for_test']
        t['resources']['router']['properties']['tags'] = tags
        stack = utils.parse_stack(t)
        create_body = {
            'router': {
                'name': utils.PhysName(stack.name, 'router'),
                'admin_state_up': True}}
        router_base_info = {
            'router': {
                "status": "BUILD",
                "external_gateway_info": None,
                "name": utils.PhysName(stack.name, 'router'),
                "admin_state_up": True,
                "tenant_id": "3e21026f2dc94372b105808c0e721661",
                "id": "3e46229d-8fce-4733-819a-b5fe630550f8"}}
        router_active_info = copy.deepcopy(router_base_info)
        router_active_info['router']['status'] = 'ACTIVE'
        self.create_mock.return_value = router_base_info
        self.show_mock.side_effect = [
            # create complete check
            router_base_info,
            router_active_info,
            # first get_attr tenant
            qe.NeutronClientException(status_code=404),
            # second get_attr tenant
            router_active_info,
            # delete complete check
            qe.NeutronClientException(status_code=404)]

        agents_info = {
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
        }
        agents_info1 = copy.deepcopy(agents_info)
        agent = agents_info1['agents'][0]
        agent['id'] = '63b3fd83-2c5f-4dad-b3ae-e0f83a40f216'
        self.list_l3_hr_mock.side_effect = [
            {"agents": []},
            agents_info,
            agents_info1
        ]

        self.delete_mock.side_effect = [
            None,
            qe.NeutronClientException(status_code=404)]
        set_tag_mock = self.patchobject(neutronclient.Client, 'replace_tag')
        rsrc = self.create_router(t, stack, 'router')
        self.create_mock.assert_called_with(create_body)
        set_tag_mock.assert_called_with(
            'routers',
            rsrc.resource_id,
            {'tags': tags}
        )
        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8', ref_id)
        self.assertIsNone(rsrc.FnGetAtt('tenant_id'))
        self.assertEqual('3e21026f2dc94372b105808c0e721661',
                         rsrc.FnGetAtt('tenant_id'))

        prop_diff = {
            "admin_state_up": False,
            "name": "myrouter",
            "l3_agent_ids": ["63b3fd83-2c5f-4dad-b3ae-e0f83a40f216"],
            'tags': ['new_tag']
        }
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        rsrc.handle_update(update_snippet, {}, prop_diff)
        set_tag_mock.assert_called_with(
            'routers',
            rsrc.resource_id,
            {'tags': ['new_tag']}
        )
        self.update_mock.assert_called_with(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'router': {
                'name': 'myrouter',
                'admin_state_up': False
            }}
        )
        prop_diff = {
            "l3_agent_ids": ["4c692423-2c5f-4dad-b3ae-e2339f58539f",
                             "8363b3fd-2c5f-4dad-b3ae-0f216e0f83a4"]
        }
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        rsrc.handle_update(update_snippet, {}, prop_diff)

        add_router_calls = [
            # create
            mock.call(
                u'792ff887-6c85-4a56-b518-23f24fa65581',
                {'router_id': u'3e46229d-8fce-4733-819a-b5fe630550f8'}),
            # first update
            mock.call(
                u'63b3fd83-2c5f-4dad-b3ae-e0f83a40f216',
                {'router_id': u'3e46229d-8fce-4733-819a-b5fe630550f8'}),
            # second update
            mock.call(
                u'4c692423-2c5f-4dad-b3ae-e2339f58539f',
                {'router_id': u'3e46229d-8fce-4733-819a-b5fe630550f8'}),
            mock.call(
                u'8363b3fd-2c5f-4dad-b3ae-0f216e0f83a4',
                {'router_id': u'3e46229d-8fce-4733-819a-b5fe630550f8'})
        ]
        remove_router_calls = [
            # first update
            mock.call(
                u'792ff887-6c85-4a56-b518-23f24fa65581',
                u'3e46229d-8fce-4733-819a-b5fe630550f8'),
            # second update
            mock.call(
                u'63b3fd83-2c5f-4dad-b3ae-e0f83a40f216',
                u'3e46229d-8fce-4733-819a-b5fe630550f8')
        ]
        self.add_router_mock.assert_has_calls(add_router_calls)
        self.remove_router_mock.assert_has_calls(remove_router_calls)
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())

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

    def _test_router_interface(self, resolve_router=True):
        self.remove_if_mock.side_effect = [
            None,
            qe.NeutronClientException(status_code=404)
        ]
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)
        self.stub_SubnetConstraint_validate()
        self.stub_RouterConstraint_validate()

        def find_rsrc(resource, name_or_id, cmd_resource=None):
            id_mapping = {
                'subnet': '91e47a57-7508-46fe-afc9-fc454e8580e1',
                'router': '3e46229d-8fce-4733-819a-b5fe630550f8'}
            return id_mapping.get(resource)
        self.find_rsrc_mock.side_effect = find_rsrc
        router_key = 'router'
        subnet_key = 'subnet'
        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                router_key: '3e46229d-8fce-4733-819a-b5fe630550f8',
                subnet_key: '91e47a57-7508-46fe-afc9-fc454e8580e1'
            })
        self.add_if_mock.assert_called_with(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'})
        # Ensure that properties correctly translates
        if not resolve_router:
            self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8',
                             rsrc.properties.get(rsrc.ROUTER))
            self.assertIsNone(rsrc.properties.get(rsrc.ROUTER_ID))

        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()

    def test_router_interface_with_old_data(self):
        self.stub_SubnetConstraint_validate()
        self.stub_RouterConstraint_validate()

        def find_rsrc(resource, name_or_id, cmd_resource=None):
            id_mapping = {
                'subnet': '91e47a57-7508-46fe-afc9-fc454e8580e1',
                'router': '3e46229d-8fce-4733-819a-b5fe630550f8'}
            return id_mapping.get(resource)

        self.find_rsrc_mock.side_effect = find_rsrc

        self.remove_if_mock.side_effect = [
            None,
            qe.NeutronClientException(status_code=404)
        ]

        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                'router': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'subnet': '91e47a57-7508-46fe-afc9-fc454e8580e1'
            })
        self.add_if_mock.assert_called_with(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        )
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

    def test_router_interface_with_port(self):
        self._test_router_interface_with_port()

    def test_router_interface_with_deprecated_port(self):
        self._test_router_interface_with_port(resolve_port=False)

    def _test_router_interface_with_port(self, resolve_port=True):
        def find_rsrc(resource, name_or_id, cmd_resource=None):
            id_mapping = {
                'router': 'ae478782-53c0-4434-ab16-49900c88016c',
                'port': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
            return id_mapping.get(resource)

        self.find_rsrc_mock.side_effect = find_rsrc

        self.remove_if_mock.side_effect = [
            None,
            qe.NeutronClientException(status_code=404)]

        self.stub_PortConstraint_validate()
        self.stub_RouterConstraint_validate()

        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                'router': 'ae478782-53c0-4434-ab16-49900c88016c',
                'port': '9577cafd-8e98-4059-a2e6-8a771b4d318e'
            })

        # Ensure that properties correctly translates
        if not resolve_port:
            self.assertEqual('9577cafd-8e98-4059-a2e6-8a771b4d318e',
                             rsrc.properties.get(rsrc.PORT))
            self.assertIsNone(rsrc.properties.get(rsrc.PORT_ID))

        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()

    def test_router_interface_conflict(self):
        self.add_if_mock.side_effect = [qe.Conflict, None]

        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)
        props = {
            'router': '3e46229d-8fce-4733-819a-b5fe630550f8',
            'subnet': '91e47a57-7508-46fe-afc9-fc454e8580e1'
        }

        def find_rsrc(resource, name_or_id, cmd_resource=None):
            return props.get(resource, resource)

        self.find_rsrc_mock.side_effect = find_rsrc
        self.create_router_interface(
            t, stack, 'router_interface', properties=props)
        self.assertEqual(2, self.add_if_mock.call_count)

    def test_router_interface_validate(self):
        def find_rsrc(resource, name_or_id, cmd_resource=None):
            id_mapping = {
                'router': 'ae478782-53c0-4434-ab16-49900c88016c',
                'subnet': '8577cafd-8e98-4059-a2e6-8a771b4d318e',
                'port': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
            return id_mapping.get(resource)

        self.find_rsrc_mock.side_effect = find_rsrc

        t = template_format.parse(neutron_template)
        json = t['resources']['router_interface']
        json['properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
            'subnet_id': '8577cafd-8e98-4059-a2e6-8a771b4d318e',
            'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        res = router.RouterInterface('router_interface',
                                     resource_defns['router_interface'],
                                     stack)
        self.assertRaises(exception.ResourcePropertyConflict, res.validate)
        json['properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
            'port_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        res = router.RouterInterface('router_interface',
                                     resource_defns['router_interface'],
                                     stack)
        self.assertIsNone(res.validate())
        json['properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
            'subnet_id': '8577cafd-8e98-4059-a2e6-8a771b4d318e'}
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        res = router.RouterInterface('router_interface',
                                     resource_defns['router_interface'],
                                     stack)
        self.assertIsNone(res.validate())
        json['properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c'}
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        res = router.RouterInterface('router_interface',
                                     resource_defns['router_interface'],
                                     stack)
        ex = self.assertRaises(exception.PropertyUnspecifiedError,
                               res.validate)
        self.assertEqual("At least one of the following properties "
                         "must be specified: subnet, port.",
                         six.text_type(ex))

    def test_gateway_router(self):
        def find_rsrc(resource, name_or_id, cmd_resource=None):
            id_mapping = {
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'network': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}
            return id_mapping.get(resource)

        self.find_rsrc_mock.side_effect = find_rsrc

        self.remove_gw_mock.side_effect = [
            None,
            qe.NeutronClientException(status_code=404)]
        self.stub_RouterConstraint_validate()

        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_gateway_router(
            t, stack, 'gateway', properties={
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'network': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
            })
        self.add_gw_mock.assert_called_with(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}
        )
        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()

    def _test_router_with_gateway(self, for_delete=False, for_update=False):
        t = template_format.parse(neutron_external_gateway_template)
        stack = utils.parse_stack(t)

        def find_rsrc(resource, name_or_id, cmd_resource=None):
            id_mapping = {
                'subnet': 'sub1234',
                'network': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}
            return id_mapping.get(resource)

        self.find_rsrc_mock.side_effect = find_rsrc
        base_info = {
            "router": {
                "status": "BUILD",
                "external_gateway_info": None,
                "name": "Test Router",
                "admin_state_up": True,
                "tenant_id": "3e21026f2dc94372b105808c0e721661",
                "id": "3e46229d-8fce-4733-819a-b5fe630550f8",
            }
        }
        external_gw_info = {
            "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            "enable_snat": True,
            'external_fixed_ips': [{
                'ip_address': '192.168.10.99',
                'subnet_id': 'sub1234'
            }]}
        active_info = copy.deepcopy(base_info)
        active_info['router']['status'] = 'ACTIVE'
        active_info['router']['external_gateway_info'] = external_gw_info
        ex_gw_info1 = copy.deepcopy(external_gw_info)
        ex_gw_info1['network_id'] = '91e47a57-7508-46fe-afc9-fc454e8580e1'
        ex_gw_info1['enable_snat'] = False
        active_info1 = copy.deepcopy(active_info)
        active_info1['router']['external_gateway_info'] = ex_gw_info1
        self.create_mock.return_value = base_info
        if for_delete:
            self.show_mock.side_effect = [
                # create complete check
                active_info,
                # delete complete check
                qe.NeutronClientException(status_code=404)]
        elif for_update:
            self.show_mock.side_effect = [
                # create complete check
                active_info,
                # get attr after create
                active_info,
                # get attr after update
                active_info1]
        else:
            self.show_mock.side_effect = [
                # create complete check
                active_info,
                # get attr after create
                active_info]

        return t, stack

    def test_create_router_gateway_as_property(self):
        t, stack = self._test_router_with_gateway()
        rsrc = self.create_router(t, stack, 'router')
        self._assert_mock_call_create_with_router_gw()
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8', ref_id)
        gateway_info = rsrc.FnGetAtt('external_gateway_info')
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         gateway_info.get('network_id'))
        self.assertTrue(gateway_info.get('enable_snat'))
        self.assertEqual([{'subnet_id': 'sub1234',
                           'ip_address': '192.168.10.99'}],
                         gateway_info.get('external_fixed_ips'))

    def test_create_router_gateway_enable_snat(self):
        self.find_rsrc_mock.side_effect = [
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766']
        router_info = {
            "router": {
                "name": "Test Router",
                "external_gateway_info": {
                    'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                },
                "admin_state_up": True,
                'status': 'BUILD',
                'id': '3e46229d-8fce-4733-819a-b5fe630550f8'
            }
        }
        active_info = copy.deepcopy(router_info)
        active_info['router']['status'] = 'ACTIVE'
        self.create_mock.return_value = router_info
        self.show_mock.side_effect = [
            # create complete check
            active_info,
            # get attr
            active_info
        ]

        t = template_format.parse(neutron_external_gateway_template)
        t["resources"]["router"]["properties"]["external_gateway_info"].pop(
            "enable_snat")
        t["resources"]["router"]["properties"]["external_gateway_info"].pop(
            "external_fixed_ips")
        stack = utils.parse_stack(t)
        rsrc = self.create_router(t, stack, 'router')
        self.create_mock.assert_called_with(
            {
                "router": {
                    "name": "Test Router",
                    "external_gateway_info": {
                        'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                    },
                    "admin_state_up": True,
                }
            }
        )
        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8', ref_id)
        gateway_info = rsrc.FnGetAtt('external_gateway_info')
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         gateway_info.get('network_id'))

    def test_update_router_gateway_as_property(self):
        t, stack = self._test_router_with_gateway(for_update=True)
        rsrc = self.create_router(t, stack, 'router')
        self._assert_mock_call_create_with_router_gw()
        gateway_info = rsrc.FnGetAtt('external_gateway_info')
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         gateway_info.get('network_id'))
        self.assertTrue(gateway_info.get('enable_snat'))
        props = t['resources']['router']['properties'].copy()
        props['external_gateway_info'] = {
            "network": "other_public",
            "enable_snat": False
        }
        update_template = rsrc.t.freeze(properties=props)

        def find_rsrc_for_update(resource, name_or_id, cmd_resource=None):
            id_mapping = {
                'subnet': 'sub1234',
                'network': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
            return id_mapping.get(resource)

        self.find_rsrc_mock.side_effect = find_rsrc_for_update
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.update_mock.assert_called_with(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'router': {
                "external_gateway_info": {
                    'network_id': '91e47a57-7508-46fe-afc9-fc454e8580e1',
                    'enable_snat': False
                },
            }}
        )
        gateway_info = rsrc.FnGetAtt('external_gateway_info')
        self.assertEqual('91e47a57-7508-46fe-afc9-fc454e8580e1',
                         gateway_info.get('network_id'))
        self.assertFalse(gateway_info.get('enable_snat'))

    def _assert_mock_call_create_with_router_gw(self):
        self.create_mock.assert_called_with({
            "router": {
                "name": "Test Router",
                "external_gateway_info": {
                    'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                    'enable_snat': True,
                    'external_fixed_ips': [{
                        'ip_address': '192.168.10.99',
                        'subnet_id': 'sub1234'
                    }]
                },
                "admin_state_up": True,
            }
        })

    def test_delete_router_gateway_as_property(self):
        t, stack = self._test_router_with_gateway(for_delete=True)

        rsrc = self.create_router(t, stack, 'router')
        self._assert_mock_call_create_with_router_gw()
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())

    def test_router_get_live_state(self):
        tmpl = """
        heat_template_version: 2015-10-15
        resources:
          router:
            type: OS::Neutron::Router
            properties:
              external_gateway_info:
                network: public
                enable_snat: true
              value_specs:
                test_value_spec: spec_value
        """
        t = template_format.parse(tmpl)
        stack = utils.parse_stack(t)

        rsrc = stack['router']

        router_resp = {
            'status': 'ACTIVE',
            'external_gateway_info': {
                'network_id': '1ede231a-0b46-40fc-ab3b-8029446d0d1b',
                'enable_snat': True,
                'external_fixed_ips': [
                    {'subnet_id': '8eea1723-6de7-4255-9f8a-a0ce0db8b995',
                     'ip_address': '10.0.3.3'}]
            },
            'name': 'er-router-naqzmqnzk4ej',
            'admin_state_up': True,
            'tenant_id': '30f466e3d14b4251853899f9c26e2b66',
            'distributed': False,
            'routes': [],
            'ha': False,
            'id': 'b047ff06-487d-48d7-a735-a54e2fd836c2',
            'test_value_spec': 'spec_value'
        }
        rsrc.client().show_router = mock.MagicMock(
            return_value={'router': router_resp})
        rsrc.client().list_l3_agent_hosting_routers = mock.MagicMock(
            return_value={'agents': [{'id': '1234'}, {'id': '5678'}]})

        reality = rsrc.get_live_state(rsrc.properties)
        expected = {
            'external_gateway_info': {
                'network': '1ede231a-0b46-40fc-ab3b-8029446d0d1b',
                'enable_snat': True
            },
            'admin_state_up': True,
            'value_specs': {
                'test_value_spec': 'spec_value'
            },
            'l3_agent_ids': ['1234', '5678']
        }

        self.assertEqual(set(expected.keys()), set(reality.keys()))
        for key in expected:
            if key == 'external_gateway_info':
                for info in expected[key]:
                    self.assertEqual(expected[key][info], reality[key][info])
            self.assertEqual(expected[key], reality[key])
