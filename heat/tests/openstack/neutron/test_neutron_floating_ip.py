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
import mox
from neutronclient.common import exceptions as qe
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.clients.os import neutron
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack as parser
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
      network: xyz1234
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
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234',
            cmd_resource=None,
        ).MultipleTimes().AndReturn('abcd1234')
        self._test_floating_ip(t, resolve_neutron=False)

    def test_floating_ip_deprecated_router_gateway(self):
        t = template_format.parse(neutron_floating_template_deprecated)
        del t['resources']['router_interface']
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234',
            cmd_resource=None,
        ).MultipleTimes().AndReturn('abcd1234')
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
                'abcd1234',
                cmd_resource=None,
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
                                 'floating_ip': {
                                     'uuid': mock.ANY,
                                     'id': mock.ANY,
                                     'action': 'CREATE',
                                     'status': 'COMPLETE',
                                     'reference_id': 'abc'}})

        rsrc = stack['floating_ip']
        self.assertEqual('abc', rsrc.FnGetRefId())

    def test_floatip_association_port(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234',
            cmd_resource=None,
        ).MultipleTimes().AndReturn('abcd1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'xyz1234',
            cmd_resource=None,
        ).MultipleTimes().AndReturn('xyz1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub1234',
            cmd_resource=None,
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
        del t['resources']['port_floating']['properties']['fixed_ips']
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

    def test_floatingip_create_specify_ip_address(self):
        t = template_format.parse(neutron_floating_template)
        props = t['resources']['floating_ip']['properties']
        props['floating_ip_address'] = '172.24.4.98'
        stack = utils.parse_stack(t)

        self.stub_NetworkConstraint_validate()
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'abcd1234',
            cmd_resource=None,
        ).AndReturn('xyz1234')
        neutronclient.Client.create_floatingip({
            'floatingip': {'floating_network_id': u'xyz1234',
                           'floating_ip_address': '172.24.4.98'}
        }).AndReturn({'floatingip': {
            'status': 'ACTIVE',
            'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            'floating_ip_address': '172.24.4.98'
        }})
        neutronclient.Client.show_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).MultipleTimes().AndReturn({'floatingip': {
            'status': 'ACTIVE',
            'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            'floating_ip_address': '172.24.4.98'
        }})

        self.m.ReplayAll()
        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual((fip.CREATE, fip.COMPLETE), fip.state)
        self.assertEqual('172.24.4.98', fip.FnGetAtt('floating_ip_address'))

        self.m.VerifyAll()

    def test_floatip_port(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'network',
            'xyz1234',
            cmd_resource=None,
        ).MultipleTimes().AndReturn('xyz1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub1234',
            cmd_resource=None,
        ).MultipleTimes().AndReturn('sub1234')
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'router',
            'None',
            cmd_resource=None,
        ).MultipleTimes().AndReturn('None')

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
            'abcd1234',
            cmd_resource=None,
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
        t['resources']['port_floating']['properties']['network'] = "xyz1234"
        t['resources']['port_floating']['properties'][
            'fixed_ips'][0]['subnet'] = "sub1234"
        t['resources']['router_interface']['properties']['subnet'] = "sub1234"
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
