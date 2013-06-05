# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import mox
from testtools import skipIf

from heat.common import exception
from heat.common import template_format
from heat.engine import properties
from heat.engine import resource
from heat.engine import scheduler
from heat.engine.resources.quantum import net
from heat.engine.resources.quantum import subnet
from heat.engine.resources.quantum import floatingip
from heat.engine.resources.quantum import port
from heat.engine.resources.quantum import router
from heat.engine.resources.quantum.quantum import QuantumResource as qr
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.utils import setup_dummy_db
from heat.tests.utils import parse_stack

quantumclient = try_import('quantumclient.v2_0.client')
qe = try_import('quantumclient.common.exceptions')

quantum_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Quantum resources",
  "Parameters" : {},
  "Resources" : {
    "network": {
      "Type": "OS::Quantum::Net",
      "Properties": {
        "name": "the_network"
      }
    },
    "unnamed_network": {
      "Type": "OS::Quantum::Net"
    },
    "admin_down_network": {
      "Type": "OS::Quantum::Net",
      "Properties": {
        "admin_state_up": false
      }
    },
    "subnet": {
      "Type": "OS::Quantum::Subnet",
      "Properties": {
        "network_id": { "Ref" : "network" },
        "ip_version": 4,
        "cidr": "10.0.3.0/24",
        "allocation_pools": [{"start": "10.0.3.20", "end": "10.0.3.150"}],
        "dns_nameservers": ["8.8.8.8"]
      }
    },
    "port": {
      "Type": "OS::Quantum::Port",
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
    "router": {
      "Type": "OS::Quantum::Router"
    },
    "router_interface": {
      "Type": "OS::Quantum::RouterInterface",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "subnet_id": { "Ref" : "subnet" }
      }
    },
    "gateway": {
      "Type": "OS::Quantum::RouterGateway",
      "Properties": {
        "router_id": { "Ref" : "router" },
        "network_id": { "Ref" : "network" }
      }
    }
  }
}
'''

quantum_floating_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test Quantum resources",
  "Parameters" : {},
  "Resources" : {
    "port_floating": {
      "Type": "OS::Quantum::Port",
      "Properties": {
        "network_id": "xyz1234",
        "fixed_ips": [{
          "subnet_id": "12.12.12.0",
          "ip_address": "10.0.0.10"
        }]
      }
    },
    "floating_ip": {
      "Type": "OS::Quantum::FloatingIP",
      "Properties": {
        "floating_network_id": "abcd1234",
      }
    },
    "floating_ip_assoc": {
      "Type": "OS::Quantum::FloatingIPAssociation",
      "Properties": {
        "floatingip_id": { "Ref" : "floating_ip" },
        "port_id": { "Ref" : "port_floating" }
      }
    }
  }
}
'''


class QuantumTest(HeatTestCase):

    def test_validate_properties(self):
        vs = {'router:external': True}
        data = {'admin_state_up': False,
                'value_specs': vs}
        p = properties.Properties(net.Net.properties_schema, data)
        self.assertEqual(None, qr.validate_properties(p))

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
        self.assertEqual(None, qr.validate_properties(p))

    def test_prepare_properties(self):
        data = {'admin_state_up': False,
                'value_specs': {'router:external': True}}
        p = properties.Properties(net.Net.properties_schema, data)
        props = qr.prepare_properties(p, 'resource_name')
        self.assertEqual({'name': 'resource_name',
                          'router:external': True,
                          'admin_state_up': False}, props)

    def test_is_built(self):
        self.assertTrue(qr.is_built({
            'name': 'the_net',
            'status': 'ACTIVE'
        }))
        self.assertTrue(qr.is_built({
            'name': 'the_net',
            'status': 'DOWN'
        }))
        self.assertFalse(qr.is_built({
            'name': 'the_net',
            'status': 'BUILD'
        }))
        self.assertRaises(exception.Error, qr.is_built, {
            'name': 'the_net',
            'status': 'FROBULATING'
        })


@skipIf(quantumclient is None, 'quantumclient unavailable')
class QuantumNetTest(HeatTestCase):

    def setUp(self):
        super(QuantumNetTest, self).setUp()
        self.m.StubOutWithMock(quantumclient.Client, 'create_network')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_network')
        self.m.StubOutWithMock(quantumclient.Client, 'show_network')
        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        setup_dummy_db()

    def create_net(self, t, stack, resource_name):
        rsrc = net.Net('test_net', t['Resources'][resource_name], stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual(net.Net.CREATE_COMPLETE, rsrc.state)
        return rsrc

    def test_net(self):
        quantumclient.Client.create_network({
            'network': {'name': u'the_network', 'admin_state_up': True}
        }).AndReturn({"network": {
            "status": "BUILD",
            "subnets": [],
            "name": "name",
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        quantumclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({"network": {
            "status": "BUILD",
            "subnets": [],
            "name": "name",
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)

        quantumclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({"network": {
            "status": "ACTIVE",
            "subnets": [],
            "name": "name",
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        quantumclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.QuantumClientException(status_code=404))

        quantumclient.Client.show_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).MultipleTimes().AndReturn({"network": {
            "status": "ACTIVE",
            "subnets": [],
            "name": "name",
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        quantumclient.Client.delete_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        quantumclient.Client.delete_network(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.QuantumClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(quantum_template)
        stack = parse_stack(t)
        rsrc = self.create_net(t, stack, 'network')

        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)

        self.assertEqual(None, rsrc.FnGetAtt('status'))
        self.assertEqual('ACTIVE', rsrc.FnGetAtt('status'))
        try:
            rsrc.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except exception.InvalidTemplateAttribute:
            pass

        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         rsrc.FnGetAtt('id'))

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})

        rsrc.delete()
        rsrc.state_set(rsrc.CREATE_COMPLETE, 'to delete again')
        rsrc.delete()
        self.m.VerifyAll()


@skipIf(quantumclient is None, 'quantumclient unavailable')
class QuantumSubnetTest(HeatTestCase):

    def setUp(self):
        super(QuantumSubnetTest, self).setUp()
        self.m.StubOutWithMock(quantumclient.Client, 'create_subnet')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_subnet')
        self.m.StubOutWithMock(quantumclient.Client, 'show_subnet')
        setup_dummy_db()

    def create_subnet(self, t, stack, resource_name):
        rsrc = subnet.Subnet('test_subnet', t['Resources'][resource_name],
                             stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual(subnet.Subnet.CREATE_COMPLETE, rsrc.state)
        return rsrc

    def test_subnet(self):

        quantumclient.Client.create_subnet({
            'subnet': {
                'name': utils.PhysName('test_stack', 'test_subnet'),
                'network_id': u'None',
                'dns_nameservers': [u'8.8.8.8'],
                'allocation_pools': [
                    {'start': u'10.0.3.20', 'end': u'10.0.3.150'}],
                'ip_version': 4,
                'cidr': u'10.0.3.0/24'
            }
        }).AndReturn({
            "subnet": {
                "allocation_pools": [
                    {"start": "10.0.3.20", "end": "10.0.3.150"}],
                "cidr": "10.0.3.0/24",
                "dns_nameservers": ["8.8.8.8"],
                "enable_dhcp": True,
                "gateway_ip": "10.0.3.1",
                "id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
                "ip_version": 4,
                "name": "name",
                "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f"
            }
        })
        quantumclient.Client.show_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1').AndRaise(
                qe.QuantumClientException(status_code=404))
        quantumclient.Client.show_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1').MultipleTimes().AndReturn({
                "subnet": {
                    "name": "name",
                    "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
                    "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                    "allocation_pools": [
                        {"start": "10.0.3.20", "end": "10.0.3.150"}],
                    "gateway_ip": "10.0.3.1",
                    "ip_version": 4,
                    "cidr": "10.0.3.0/24",
                    "dns_nameservers": ["8.8.8.8"],
                    "id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
                    "enable_dhcp": False,
                }
            })

        quantumclient.Client.delete_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1'
        ).AndReturn(None)
        quantumclient.Client.delete_subnet(
            '91e47a57-7508-46fe-afc9-fc454e8580e1'
        ).AndRaise(qe.QuantumClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(quantum_template)
        stack = parse_stack(t)
        rsrc = self.create_subnet(t, stack, 'subnet')

        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('91e47a57-7508-46fe-afc9-fc454e8580e1', ref_id)
        self.assertEqual(None,
                         rsrc.FnGetAtt('network_id'))
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         rsrc.FnGetAtt('network_id'))
        self.assertEqual('8.8.8.8', rsrc.FnGetAtt('dns_nameservers')[0])
        self.assertEqual('91e47a57-7508-46fe-afc9-fc454e8580e1',
                         rsrc.FnGetAtt('id'))

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})

        self.assertEqual(rsrc.delete(), None)
        rsrc.state_set(rsrc.CREATE_COMPLETE, 'to delete again')
        self.assertEqual(rsrc.delete(), None)
        self.m.VerifyAll()


@skipIf(quantumclient is None, 'quantumclient unavailable')
class QuantumRouterTest(HeatTestCase):
    def setUp(self):
        super(QuantumRouterTest, self).setUp()
        self.m.StubOutWithMock(quantumclient.Client, 'create_router')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_router')
        self.m.StubOutWithMock(quantumclient.Client, 'show_router')
        self.m.StubOutWithMock(quantumclient.Client, 'add_interface_router')
        self.m.StubOutWithMock(quantumclient.Client, 'remove_interface_router')
        self.m.StubOutWithMock(quantumclient.Client, 'add_gateway_router')
        self.m.StubOutWithMock(quantumclient.Client, 'remove_gateway_router')
        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        setup_dummy_db()

    def create_router(self, t, stack, resource_name):
        rsrc = router.Router('router', t['Resources'][resource_name], stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual(router.Router.CREATE_COMPLETE, rsrc.state)
        return rsrc

    def create_router_interface(self, t, stack, resource_name, properties={}):
        t['Resources'][resource_name]['Properties'] = properties
        rsrc = router.RouterInterface(
            'router_interface',
            t['Resources'][resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual(
            router.RouterInterface.CREATE_COMPLETE, rsrc.state)
        return rsrc

    def create_gateway_router(self, t, stack, resource_name, properties={}):
        t['Resources'][resource_name]['Properties'] = properties
        rsrc = router.RouterGateway(
            'gateway',
            t['Resources'][resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual(router.RouterGateway.CREATE_COMPLETE, rsrc.state)
        return rsrc

    def test_router(self):
        quantumclient.Client.create_router({
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
        quantumclient.Client.show_router(
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
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        quantumclient.Client.show_router(
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

        quantumclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').AndRaise(
                qe.QuantumClientException(status_code=404))
        quantumclient.Client.show_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8').MultipleTimes().AndReturn({
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

        quantumclient.Client.delete_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndReturn(None)
        quantumclient.Client.delete_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndRaise(qe.QuantumClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(quantum_template)
        stack = parse_stack(t)
        rsrc = self.create_router(t, stack, 'router')

        rsrc.validate()

        ref_id = rsrc.FnGetRefId()
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8', ref_id)
        self.assertEqual(None,
                         rsrc.FnGetAtt('tenant_id'))
        self.assertEqual('3e21026f2dc94372b105808c0e721661',
                         rsrc.FnGetAtt('tenant_id'))
        self.assertEqual('3e46229d-8fce-4733-819a-b5fe630550f8',
                         rsrc.FnGetAtt('id'))

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})

        self.assertEqual(rsrc.delete(), None)
        rsrc.state_set(rsrc.CREATE_COMPLETE, 'to delete again')
        self.assertEqual(rsrc.delete(), None)
        self.m.VerifyAll()

    def test_router_interface(self):
        quantumclient.Client.add_interface_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        ).AndReturn(None)
        quantumclient.Client.remove_interface_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        ).AndReturn(None)
        quantumclient.Client.remove_interface_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'}
        ).AndRaise(qe.QuantumClientException(status_code=404))
        self.m.ReplayAll()
        t = template_format.parse(quantum_template)
        stack = parse_stack(t)

        rsrc = self.create_router_interface(
            t, stack, 'router_interface', properties={
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'subnet_id': '91e47a57-7508-46fe-afc9-fc454e8580e1'
            })

        self.assertEqual(rsrc.delete(), None)
        rsrc.state_set(rsrc.CREATE_COMPLETE, 'to delete again')
        self.assertEqual(rsrc.delete(), None)
        self.m.VerifyAll()

    def test_gateway_router(self):
        quantumclient.Client.add_gateway_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8',
            {'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}
        ).AndReturn(None)
        quantumclient.Client.remove_gateway_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndReturn(None)
        quantumclient.Client.remove_gateway_router(
            '3e46229d-8fce-4733-819a-b5fe630550f8'
        ).AndRaise(qe.QuantumClientException(status_code=404))
        self.m.ReplayAll()
        t = template_format.parse(quantum_template)
        stack = parse_stack(t)

        rsrc = self.create_gateway_router(
            t, stack, 'gateway', properties={
                'router_id': '3e46229d-8fce-4733-819a-b5fe630550f8',
                'network_id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
            })

        self.assertEqual(rsrc.delete(), None)
        rsrc.state_set(rsrc.CREATE_COMPLETE, 'to delete again')
        self.assertEqual(rsrc.delete(), None)
        self.m.VerifyAll()


@skipIf(quantumclient is None, 'quantumclient unavailable')
class QuantumFloatingIPTest(HeatTestCase):
    @skipIf(net.clients.quantumclient is None, "Missing Quantum Client")
    def setUp(self):
        super(QuantumFloatingIPTest, self).setUp()
        self.m.StubOutWithMock(quantumclient.Client, 'create_floatingip')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_floatingip')
        self.m.StubOutWithMock(quantumclient.Client, 'show_floatingip')
        self.m.StubOutWithMock(quantumclient.Client, 'update_floatingip')
        self.m.StubOutWithMock(quantumclient.Client, 'create_port')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_port')
        self.m.StubOutWithMock(quantumclient.Client, 'show_port')
        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        setup_dummy_db()

    def test_floating_ip(self):

        quantumclient.Client.create_floatingip({
            'floatingip': {'floating_network_id': u'abcd1234'}
        }).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        quantumclient.Client.show_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.QuantumClientException(status_code=404))
        quantumclient.Client.show_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).MultipleTimes().AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        quantumclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766').AndReturn(None)
        quantumclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766').AndRaise(
                qe.QuantumClientException(status_code=404))
        self.m.ReplayAll()

        t = template_format.parse(quantum_floating_template)
        stack = parse_stack(t)

        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual(floatingip.FloatingIP.CREATE_COMPLETE, fip.state)
        fip.validate()

        fip_id = fip.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', fip_id)

        self.assertEqual(None, fip.FnGetAtt('status'))
        self.assertEqual('ACTIVE', fip.FnGetAtt('status'))
        try:
            fip.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except exception.InvalidTemplateAttribute:
            pass

        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         fip.FnGetAtt('id'))
        self.assertRaises(resource.UpdateReplace,
                          fip.handle_update, {}, {}, {})
        self.assertEqual(fip.delete(), None)
        fip.state_set(fip.CREATE_COMPLETE, 'to delete again')
        self.assertEqual(fip.delete(), None)

        self.m.VerifyAll()

    def test_port(self):

        quantumclient.Client.create_port({'port': {
            'network_id': u'xyz1234',
            'fixed_ips': [
                {'subnet_id': u'12.12.12.0', 'ip_address': u'10.0.0.10'}
            ],
            'name': utils.PhysName('test_stack', 'port_floating'),
            'admin_state_up': True}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        quantumclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        quantumclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        quantumclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.QuantumClientException(status_code=404))
        quantumclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).MultipleTimes().AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        self.m.ReplayAll()

        t = template_format.parse(quantum_floating_template)
        stack = parse_stack(t)

        p = stack['port_floating']
        scheduler.TaskRunner(p.create)()
        self.assertEqual(port.Port.CREATE_COMPLETE, p.state)
        p.validate()

        port_id = p.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', port_id)

        self.assertEqual(None, p.FnGetAtt('status'))
        self.assertEqual('ACTIVE', p.FnGetAtt('status'))
        try:
            p.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except exception.InvalidTemplateAttribute:
            pass

        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         p.FnGetAtt('id'))

        self.assertRaises(resource.UpdateReplace,
                          p.handle_update, {}, {}, {})

        self.m.VerifyAll()

    def test_floatip_port(self):

        quantumclient.Client.create_floatingip({
            'floatingip': {'floating_network_id': u'abcd1234'}
        }).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        quantumclient.Client.create_port({'port': {
            'network_id': u'xyz1234',
            'fixed_ips': [
                {'subnet_id': u'12.12.12.0', 'ip_address': u'10.0.0.10'}
            ],
            'name': utils.PhysName('test_stack', 'port_floating'),
            'admin_state_up': True}}
        ).AndReturn({'port': {
            "status": "BUILD",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        quantumclient.Client.show_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn({'port': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})
        quantumclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {
                'floatingip': {
                    'port_id': u'fc68ea2c-b60b-4b4f-bd82-94ec81110766'}}
        ).AndReturn({'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }})

        quantumclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'floatingip': {
                'port_id': None
            }}).AndReturn(None)

        quantumclient.Client.delete_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        quantumclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndReturn(None)

        quantumclient.Client.update_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'floatingip': {
                'port_id': None
            }}).AndRaise(qe.QuantumClientException(status_code=404))

        quantumclient.Client.delete_port(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.QuantumClientException(status_code=404))

        quantumclient.Client.delete_floatingip(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
        ).AndRaise(qe.QuantumClientException(status_code=404))

        self.m.ReplayAll()

        t = template_format.parse(quantum_floating_template)
        stack = parse_stack(t)

        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual(floatingip.FloatingIP.CREATE_COMPLETE, fip.state)

        p = stack['port_floating']
        scheduler.TaskRunner(p.create)()
        self.assertEqual(port.Port.CREATE_COMPLETE, p.state)

        fipa = stack['floating_ip_assoc']
        scheduler.TaskRunner(fipa.create)()
        self.assertEqual(floatingip.FloatingIPAssociation.CREATE_COMPLETE,
                         fipa.state)

        fipa.validate()

        fipa_id = fipa.FnGetRefId()
        fip_id = fip.FnGetRefId()
        port_id = p.FnGetRefId()
        self.assertEqual('%s:%s' % (fip_id, port_id), fipa_id)
        self.assertRaises(resource.UpdateReplace,
                          fipa.handle_update, {}, {}, {})

        self.assertEqual(fipa.delete(), None)
        self.assertEqual(p.delete(), None)
        self.assertEqual(fip.delete(), None)

        fipa.state_set(fipa.CREATE_COMPLETE, 'to delete again')
        fip.state_set(fip.CREATE_COMPLETE, 'to delete again')
        p.state_set(p.CREATE_COMPLETE, 'to delete again')

        self.assertEqual(fipa.delete(), None)
        self.assertEqual(p.delete(), None)
        self.assertEqual(fip.delete(), None)

        self.m.VerifyAll()
