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
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.common import timeutils
from heat.engine.clients.os import neutron
from heat.engine.hot import functions as hot_funcs
from heat.engine import node_data
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import stk_defn
from heat.engine import template as tmpl
from heat.tests import common
from heat.tests import utils


neutron_floating_template = '''
heat_template_version: 2015-04-30
description: Template to test floatingip Neutron resource
resources:
  port_floating:
    type: OS::Neutron::Port
    properties:
      network: abcd1234
      fixed_ips:
        - subnet: sub1234
          ip_address: 10.0.0.10

  floating_ip:
    type: OS::Neutron::FloatingIP
    properties:
      floating_network: abcd1234

  floating_ip_assoc:
    type: OS::Neutron::FloatingIPAssociation
    properties:
      floatingip_id: { get_resource: floating_ip }
      port_id: { get_resource: port_floating }

  router:
    type: OS::Neutron::Router

  router_interface:
    type: OS::Neutron::RouterInterface
    properties:
      router_id: { get_resource: router }
      subnet: sub1234

  gateway:
    type: OS::Neutron::RouterGateway
    properties:
      router_id: { get_resource: router }
      network: abcd1234
'''

neutron_floating_no_assoc_template = '''
heat_template_version: 2015-04-30
description: Template to test floatingip Neutron resource
resources:
  network:
    type: OS::Neutron::Net

  subnet:
    type: OS::Neutron::Subnet
    properties:
      network: { get_resource: network }
      cidr: 10.0.3.0/24,

  port_floating:
    type: OS::Neutron::Port
    properties:
      network: { get_resource: network }
      fixed_ips:
        - subnet: { get_resource: subnet }
          ip_address: 10.0.0.10

  floating_ip:
    type: OS::Neutron::FloatingIP
    properties:
      floating_network: abcd1234
      port_id: { get_resource: port_floating }

  router:
    type: OS::Neutron::Router

  router_interface:
    type: OS::Neutron::RouterInterface
    properties:
      router_id: { get_resource: router }
      subnet: { get_resource: subnet }

  gateway:
    type: OS::Neutron::RouterGateway
    properties:
      router_id: { get_resource: router }
      network: abcd1234
'''

neutron_floating_template_deprecated = neutron_floating_template.replace(
    'network', 'network_id').replace('subnet', 'subnet_id')


class NeutronFloatingIPTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronFloatingIPTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

        def lookup(client, lookup_type, name, cmd_resource):
            return name

        self.patchobject(neutronV20,
                         'find_resourceid_by_name_or_id',
                         side_effect=lookup)

        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def test_floating_ip_validate(self):
        t = template_format.parse(neutron_floating_no_assoc_template)
        stack = utils.parse_stack(t)
        fip = stack['floating_ip']
        self.assertIsNone(fip.validate())
        del t['resources']['floating_ip']['properties']['port_id']
        t['resources']['floating_ip']['properties'][
            'fixed_ip_address'] = '10.0.0.12'
        stack = utils.parse_stack(t)
        fip = stack['floating_ip']
        self.assertRaises(exception.ResourcePropertyDependency,
                          fip.validate)

    def test_floating_ip_router_interface(self):
        t = template_format.parse(neutron_floating_template)
        del t['resources']['gateway']
        self._test_floating_ip(t)

    def test_floating_ip_router_gateway(self):
        t = template_format.parse(neutron_floating_template)
        del t['resources']['router_interface']
        self._test_floating_ip(t, r_iface=False)

    def test_floating_ip_deprecated_router_interface(self):
        t = template_format.parse(neutron_floating_template_deprecated)
        del t['resources']['gateway']
        self._test_floating_ip(t)

    def test_floating_ip_deprecated_router_gateway(self):
        t = template_format.parse(neutron_floating_template_deprecated)
        del t['resources']['router_interface']
        self._test_floating_ip(t, r_iface=False)

    def _test_floating_ip(self, tmpl, r_iface=True):
        self.mockclient.create_floatingip.return_value = {
            'floatingip': {
                'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                'floating_network_id': u'abcd1234'
            }
        }

        self.mockclient.show_floatingip.side_effect = [
            qe.NeutronClientException(status_code=404),
            {
                'floatingip': {
                    'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                    'floating_network_id': u'abcd1234'
                }
            },
            {
                'floatingip': {
                    'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                    'floating_network_id': u'abcd1234'
                }
            },
            # Start delete
            {
                'floatingip': {
                    'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                    'floating_network_id': u'abcd1234'
                }
            },
            qe.NeutronClientException(status_code=404),
        ]

        retry_delay = self.patchobject(timeutils, 'retry_backoff_delay',
                                       return_value=0.01)
        self.mockclient.delete_floatingip.side_effect = [
            None,
            None,
            qe.NeutronClientException(status_code=404),
        ]

        self.stub_NetworkConstraint_validate()
        stack = utils.parse_stack(tmpl)

        # assert the implicit dependency between the floating_ip
        # and the gateway

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

        self.mockclient.create_floatingip.assert_called_once_with({
            'floatingip': {'floating_network_id': u'abcd1234'}
        })
        self.mockclient.show_floatingip.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        retry_delay.assert_called_once_with(1, jitter_max=2.0)
        self.mockclient.delete_floatingip.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')

    def test_FnGetRefId(self):
        t = template_format.parse(neutron_floating_template)
        stack = utils.parse_stack(t)
        rsrc = stack['floating_ip']
        rsrc.resource_id = 'xyz'
        self.assertEqual('xyz', rsrc.FnGetRefId())

    def test_FnGetRefId_convergence_cache_data(self):
        t = template_format.parse(neutron_floating_template)
        template = tmpl.Template(t)
        stack = parser.Stack(utils.dummy_context(), 'test', template,
                             cache_data={
                                 'floating_ip': node_data.NodeData.from_dict({
                                     'uuid': mock.ANY,
                                     'id': mock.ANY,
                                     'action': 'CREATE',
                                     'status': 'COMPLETE',
                                     'reference_id': 'abc'})})

        rsrc = stack.defn['floating_ip']
        self.assertEqual('abc', rsrc.FnGetRefId())

    def test_floatip_association_port(self):
        t = template_format.parse(neutron_floating_template)
        stack = utils.parse_stack(t)

        self.mockclient.create_floatingip.return_value = {
            'floatingip': {
                "status": "ACTIVE",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
            }
        }
        self.mockclient.create_port.return_value = {
            'port': {
                "status": "BUILD",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
            }
        }
        self.mockclient.show_port.side_effect = [
            {
                'port': {
                    "status": "ACTIVE",
                    "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }
            },
            # delete
            qe.PortNotFoundClient(status_code=404),
        ]

        self.mockclient.update_floatingip.side_effect = [
            # create as
            {
                'floatingip': {
                    "status": "ACTIVE",
                    "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }
            },
            # update as with port_id
            {
                'floatingip': {
                    "status": "ACTIVE",
                    "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }
            },
            # update as with floatingip_id
            None,
            {
                'floatingip': {
                    "status": "ACTIVE",
                    "id": "2146dfbf-ba77-4083-8e86-d052f671ece5"
                }
            },
            # update as with both
            None,
            {
                'floatingip': {
                    "status": "ACTIVE",
                    "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }
            },
            # delete as
            None,
        ]

        self.mockclient.delete_port.side_effect = [
            None,
            qe.PortNotFoundClient(status_code=404),
        ]
        self.mockclient.delete_floatingip.side_effect = [
            None,
            qe.PortNotFoundClient(status_code=404),
        ]
        self.mockclient.show_floatingip.side_effect = (
            qe.NeutronClientException(status_code=404))

        self.stub_PortConstraint_validate()

        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual((fip.CREATE, fip.COMPLETE), fip.state)
        stk_defn.update_resource_data(stack.defn, fip.name, fip.node_data())

        p = stack['port_floating']
        scheduler.TaskRunner(p.create)()
        self.assertEqual((p.CREATE, p.COMPLETE), p.state)
        stk_defn.update_resource_data(stack.defn, p.name, p.node_data())

        fipa = stack['floating_ip_assoc']
        scheduler.TaskRunner(fipa.create)()
        self.assertEqual((fipa.CREATE, fipa.COMPLETE), fipa.state)
        stk_defn.update_resource_data(stack.defn, fipa.name, fipa.node_data())
        self.assertIsNotNone(fipa.id)
        self.assertEqual(fipa.id, fipa.resource_id)

        fipa.validate()

        # test update FloatingIpAssociation with port_id
        props = copy.deepcopy(fipa.properties.data)
        update_port_id = '2146dfbf-ba77-4083-8e86-d052f671ece5'
        props['port_id'] = update_port_id
        update_snippet = rsrc_defn.ResourceDefinition(fipa.name, fipa.type(),
                                                      stack.t.parse(stack.defn,
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

        self.mockclient.create_floatingip.assert_called_once_with({
            'floatingip': {'floating_network_id': u'abcd1234'}
        })
        self.mockclient.create_port.assert_called_once_with({
            'port': {
                'network_id': u'abcd1234',
                'fixed_ips': [
                    {'subnet_id': u'sub1234', 'ip_address': u'10.0.0.10'}
                ],
                'name': utils.PhysName(stack.name, 'port_floating'),
                'admin_state_up': True,
                'device_owner': '',
                'device_id': '',
                'binding:vnic_type': 'normal'
            }
        })
        self.mockclient.show_port.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        )
        self.mockclient.update_floatingip.assert_has_calls([
            # create as
            mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                      {'floatingip': {
                          'port_id': u'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
                      }}),
            # update as with port_id
            mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                      {'floatingip': {
                          'port_id': u'2146dfbf-ba77-4083-8e86-d052f671ece5',
                          'fixed_ip_address': None
                      }}),
            # update as with floatingip_id
            mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                      {'floatingip': {'port_id': None}}),
            mock.call('2146dfbf-ba77-4083-8e86-d052f671ece5',
                      {'floatingip': {
                          'port_id': u'2146dfbf-ba77-4083-8e86-d052f671ece5',
                          'fixed_ip_address': None
                      }}),
            # update as with both
            mock.call('2146dfbf-ba77-4083-8e86-d052f671ece5',
                      {'floatingip': {'port_id': None}}),
            mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                      {'floatingip': {
                          'port_id': u'ade6fcac-7d47-416e-a3d7-ad12efe445c1',
                          'fixed_ip_address': None
                      }}),
            # delete as
            mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                      {'floatingip': {'port_id': None}})
        ])

        self.mockclient.delete_port.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        self.mockclient.delete_floatingip.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        self.mockclient.show_floatingip.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')

    def test_floatip_port_dependency_subnet(self):
        t = template_format.parse(neutron_floating_no_assoc_template)
        stack = utils.parse_stack(t)

        p_result = self.patchobject(hot_funcs.GetResource, 'result')
        p_result.return_value = 'subnet_uuid'
        # check dependencies for fip resource
        required_by = set(stack.dependencies.required_by(
            stack['router_interface']))
        self.assertIn(stack['floating_ip'], required_by)

    def test_floatip_port_dependency_network(self):
        t = template_format.parse(neutron_floating_no_assoc_template)
        del t['resources']['port_floating']['properties']['fixed_ips']
        stack = utils.parse_stack(t)

        p_show = self.mockclient.show_network
        p_show.return_value = {'network': {'subnets': ['subnet_uuid']}}

        p_result = self.patchobject(hot_funcs.GetResource, 'result',
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

    def test_floatingip_create_specify_ip_address(self):
        self.stub_NetworkConstraint_validate()
        self.mockclient.create_floatingip.return_value = {
            'floatingip': {
                'status': 'ACTIVE',
                'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                'floating_ip_address': '172.24.4.98'
            }
        }

        self.mockclient.show_floatingip.return_value = {
            'floatingip': {
                'status': 'ACTIVE',
                'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                'floating_ip_address': '172.24.4.98'
            }
        }

        t = template_format.parse(neutron_floating_template)
        props = t['resources']['floating_ip']['properties']
        props['floating_ip_address'] = '172.24.4.98'
        stack = utils.parse_stack(t)
        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual((fip.CREATE, fip.COMPLETE), fip.state)
        self.assertEqual('172.24.4.98', fip.FnGetAtt('floating_ip_address'))

        self.mockclient.create_floatingip.assert_called_once_with({
            'floatingip': {'floating_network_id': u'abcd1234',
                           'floating_ip_address': '172.24.4.98'}
        })
        self.mockclient.show_floatingip.assert_called_once_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')

    def test_floatingip_create_specify_dns(self):
        self.stub_NetworkConstraint_validate()
        self.mockclient.create_floatingip.return_value = {
            'floatingip': {
                'status': 'ACTIVE',
                'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                'floating_ip_address': '172.24.4.98'
            }
        }

        t = template_format.parse(neutron_floating_template)
        props = t['resources']['floating_ip']['properties']
        props['dns_name'] = 'myvm'
        props['dns_domain'] = 'openstack.org.'
        stack = utils.parse_stack(t)
        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual((fip.CREATE, fip.COMPLETE), fip.state)

        self.mockclient.create_floatingip.assert_called_once_with({
            'floatingip': {'floating_network_id': u'abcd1234',
                           'dns_name': 'myvm',
                           'dns_domain': 'openstack.org.'}
        })

    def test_floatingip_create_specify_subnet(self):
        self.stub_NetworkConstraint_validate()
        self.mockclient.create_floatingip.return_value = {
            'floatingip': {
                'status': 'ACTIVE',
                'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                'floating_ip_address': '172.24.4.98'
            }
        }

        t = template_format.parse(neutron_floating_template)
        props = t['resources']['floating_ip']['properties']
        props['floating_subnet'] = 'sub1234'
        stack = utils.parse_stack(t)
        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual((fip.CREATE, fip.COMPLETE), fip.state)

        self.mockclient.create_floatingip.assert_called_once_with({
            'floatingip': {'floating_network_id': u'abcd1234',
                           'subnet_id': u'sub1234'}
        })

    def test_floatip_port(self):
        t = template_format.parse(neutron_floating_no_assoc_template)
        t['resources']['port_floating']['properties']['network'] = "xyz1234"
        t['resources']['port_floating']['properties'][
            'fixed_ips'][0]['subnet'] = "sub1234"
        t['resources']['router_interface']['properties']['subnet'] = "sub1234"
        stack = utils.parse_stack(t)

        self.mockclient.create_port.return_value = {
            'port': {
                "status": "BUILD",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
            }
        }
        self.mockclient.show_port.side_effect = [
            {
                'port': {
                    "status": "ACTIVE",
                    "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }
            },
            # delete
            qe.PortNotFoundClient(status_code=404),
        ]
        self.mockclient.create_floatingip.return_value = {
            'floatingip': {
                "status": "ACTIVE",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
            }
        }

        self.mockclient.update_floatingip.return_value = {
            'floatingip': {
                "status": "ACTIVE",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
            }
        }

        self.mockclient.delete_floatingip.return_value = None
        self.mockclient.delete_port.return_value = None
        self.mockclient.show_floatingip.side_effect = (
            qe.PortNotFoundClient(status_code=404))

        self.stub_PortConstraint_validate()

        # check dependencies for fip resource
        required_by = set(stack.dependencies.required_by(
            stack['router_interface']))
        self.assertIn(stack['floating_ip'], required_by)

        p = stack['port_floating']
        scheduler.TaskRunner(p.create)()
        self.assertEqual((p.CREATE, p.COMPLETE), p.state)
        stk_defn.update_resource_data(stack.defn, p.name, p.node_data())

        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual((fip.CREATE, fip.COMPLETE), fip.state)
        stk_defn.update_resource_data(stack.defn, fip.name, fip.node_data())

        # test update FloatingIp with port_id
        props = copy.deepcopy(fip.properties.data)
        update_port_id = '2146dfbf-ba77-4083-8e86-d052f671ece5'
        props['port_id'] = update_port_id
        update_snippet = rsrc_defn.ResourceDefinition(fip.name, fip.type(),
                                                      stack.t.parse(stack.defn,
                                                                    props))
        scheduler.TaskRunner(fip.update, update_snippet)()
        self.assertEqual((fip.UPDATE, fip.COMPLETE), fip.state)
        stk_defn.update_resource_data(stack.defn, fip.name, fip.node_data())

        # test update FloatingIp with None port_id
        props = copy.deepcopy(fip.properties.data)
        del(props['port_id'])
        update_snippet = rsrc_defn.ResourceDefinition(fip.name, fip.type(),
                                                      stack.t.parse(stack.defn,
                                                                    props))
        scheduler.TaskRunner(fip.update, update_snippet)()
        self.assertEqual((fip.UPDATE, fip.COMPLETE), fip.state)

        scheduler.TaskRunner(fip.delete)()
        scheduler.TaskRunner(p.delete)()

        self.mockclient.create_port.assert_called_once_with({
            'port': {
                'network_id': u'xyz1234',
                'fixed_ips': [
                    {'subnet_id': u'sub1234', 'ip_address': u'10.0.0.10'}
                ],
                'name': utils.PhysName(stack.name, 'port_floating'),
                'admin_state_up': True,
                'binding:vnic_type': 'normal',
                'device_owner': '',
                'device_id': ''
            }
        })
        self.mockclient.show_port.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        self.mockclient.create_floatingip.assert_called_once_with({
            'floatingip': {
                'floating_network_id': u'abcd1234',
                'port_id': u'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
            }
        })
        self.mockclient.update_floatingip.assert_has_calls([
            # update with new port_id
            mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                      {'floatingip': {
                          'port_id': u'2146dfbf-ba77-4083-8e86-d052f671ece5',
                          'fixed_ip_address': None
                      }}),
            # update with None port_id
            mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                      {'floatingip': {
                          'port_id': None,
                          'fixed_ip_address': None
                      }})
        ])

        self.mockclient.delete_floatingip.assert_called_once_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        self.mockclient.show_floatingip.assert_called_once_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')
        self.mockclient.delete_port.assert_called_once_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')

    def test_add_dependencies(self):
        t = template_format.parse(neutron_floating_template)
        stack = utils.parse_stack(t)
        fipa = stack['floating_ip_assoc']
        port = stack['port_floating']
        r_int = stack['router_interface']
        deps = mock.MagicMock()
        dep_list = []

        def iadd(obj):
            dep_list.append(obj[1])
        deps.__iadd__.side_effect = iadd
        deps.graph.return_value = {fipa: [port]}
        fipa.add_dependencies(deps)
        self.assertEqual([r_int], dep_list)

    def test_add_dependencies_without_fixed_ips_in_port(self):
        t = template_format.parse(neutron_floating_template)
        del t['resources']['port_floating']['properties']['fixed_ips']
        stack = utils.parse_stack(t)
        fipa = stack['floating_ip_assoc']
        port = stack['port_floating']
        deps = mock.MagicMock()
        dep_list = []

        def iadd(obj):
            dep_list.append(obj[1])
        deps.__iadd__.side_effect = iadd
        deps.graph.return_value = {fipa: [port]}
        fipa.add_dependencies(deps)
        self.assertEqual([], dep_list)
