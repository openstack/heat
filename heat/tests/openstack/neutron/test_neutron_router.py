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
      l3_agent_id: 792ff887-6c85-4a56-b518-23f24fa65581

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

neutron_external_gateway_template = '''
heat_template_version: 2015-04-30
description: Template to test gateway Neutron resource
resources:
 router:
   type: OS::Neutron::Router
   properties:
     name: Test Router
     external_gateway_info:
       network: public
       enable_snat: true
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
        rsrc.t['Properties'].pop('l3_agent_ids')
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
            "l3_agent_ids": ["63b3fd83-2c5f-4dad-b3ae-e0f83a40f216"]
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

    def _test_router_interface(self, resolve_router=True):
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
        self.stub_SubnetConstraint_validate()
        self.stub_RouterConstraint_validate()
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'router',
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            cmd_resource=None,
        ).AndReturn('3e46229d-8fce-4733-819a-b5fe630550f8')
        router_key = 'router'
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            '91e47a57-7508-46fe-afc9-fc454e8580e1',
            cmd_resource=None,
        ).AndReturn('91e47a57-7508-46fe-afc9-fc454e8580e1')
        subnet_key = 'subnet'

        self.m.ReplayAll()
        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                router_key: '3e46229d-8fce-4733-819a-b5fe630550f8',
                subnet_key: '91e47a57-7508-46fe-afc9-fc454e8580e1'
            })

        # Ensure that properties correctly translates
        if not resolve_router:
            self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8',
                             rsrc.properties.get(rsrc.ROUTER))
            self.assertIsNone(rsrc.properties.get(rsrc.ROUTER_ID))

        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_router_interface_with_old_data(self):
        self.stub_SubnetConstraint_validate()
        self.stub_RouterConstraint_validate()
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'router',
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            cmd_resource=None,
        ).AndReturn('3e46229d-8fce-4733-819a-b5fe630550f8')

        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            '91e47a57-7508-46fe-afc9-fc454e8580e1',
            cmd_resource=None,
        ).AndReturn('91e47a57-7508-46fe-afc9-fc454e8580e1')
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
                'router': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'subnet': '91e47a57-7508-46fe-afc9-fc454e8580e1'
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
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'router',
            'ae478782-53c0-4434-ab16-49900c88016c',
            cmd_resource=None,
        ).AndReturn('ae478782-53c0-4434-ab16-49900c88016c')
        port_key = 'port'
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'port',
            '9577cafd-8e98-4059-a2e6-8a771b4d318e',
            cmd_resource=None,
        ).AndReturn('9577cafd-8e98-4059-a2e6-8a771b4d318e')

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
        self.stub_PortConstraint_validate()
        self.stub_RouterConstraint_validate()

        self.m.ReplayAll()
        t = template_format.parse(neutron_template)
        stack = utils.parse_stack(t)

        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                'router': 'ae478782-53c0-4434-ab16-49900c88016c',
                port_key: '9577cafd-8e98-4059-a2e6-8a771b4d318e'
            })

        # Ensure that properties correctly translates
        if not resolve_port:
            self.assertEqual('9577cafd-8e98-4059-a2e6-8a771b4d318e',
                             rsrc.properties.get(rsrc.PORT))
            self.assertIsNone(rsrc.properties.get(rsrc.PORT_ID))

        scheduler.TaskRunner(rsrc.delete)()
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_router_interface_validate(self):
        t = template_format.parse(neutron_template)
        json = t['resources']['router_interface']
        json['properties'] = {
            'router_id': 'ae478782-53c0-4434-ab16-49900c88016c',
            'subnet_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e',
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
            'subnet_id': '9577cafd-8e98-4059-a2e6-8a771b4d318e'}
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
                         "must be specified: subnet, port",
                         six.text_type(ex))

    def test_gateway_router(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            cmd_resource=None,
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
            'public',
            cmd_resource=None,
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
            'public',
            cmd_resource=None,
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
        t["resources"]["router"]["properties"]["external_gateway_info"].pop(
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
            'other_public',
            cmd_resource=None,
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
