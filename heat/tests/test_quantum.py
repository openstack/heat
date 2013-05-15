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


from testtools import skipIf

from heat.common import exception
from heat.common import template_format
from heat.engine import properties
from heat.engine import scheduler
from heat.engine.resources.quantum import net
from heat.engine.resources.quantum import subnet
from heat.engine.resources.quantum import floatingip
from heat.engine.resources.quantum import port
from heat.engine.resources.quantum.quantum import QuantumResource as qr
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db
from heat.tests.utils import parse_stack

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


class FakeQuantum():

    def create_floatingip(self, props):
        return {'floatingip': {
                "status": "ACTIVE",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }}

    def delete_floatingip(self, id):
        return None

    def show_floatingip(self, id):
        return {'floatingip': {
                "status": "ACTIVE",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }}

    def update_floatingip(self, id, props):
        return {'floatingip': {
                "status": "ACTIVE",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }}

    def create_port(self, props):
        return {'port': {
                "status": "ACTIVE",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }}

    def delete_port(self, id):
        return None

    def show_port(self, id):
        return {'port': {
                "status": "ACTIVE",
                "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
                }}

    def create_network(self, name):
        return {"network": {
            "status": "ACTIVE",
            "subnets": [],
            "name": "name",
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }}

    def delete_network(self, id):
        return None

    def show_network(self, id):
        return {"network": {
            "status": "ACTIVE",
            "subnets": [],
            "name": "name",
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
        }}

    def create_subnet(self, name):
        return {"subnet": {
            "allocation_pools": [{"start": "10.0.3.20", "end": "10.0.3.150"}],
            "cidr": "10.0.3.0/24",
            "dns_nameservers": ["8.8.8.8"],
            "enable_dhcp": True,
            "gateway_ip": "10.0.3.1",
            "id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
            "ip_version": 4,
            "name": "name",
            "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f"
        }}

    def delete_subnet(self, id):
        return None

    def show_subnet(self, id):
        return {"subnet": {
            "name": "name",
            "network_id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "allocation_pools": [{"start": "10.0.3.20", "end": "10.0.3.150"}],
            "gateway_ip": "10.0.3.1",
            "ip_version": 4,
            "cidr": "10.0.3.0/24",
            "dns_nameservers": ["8.8.8.8"],
            "id": "91e47a57-7508-46fe-afc9-fc454e8580e1",
            "enable_dhcp": False,
        }}


class QuantumTest(HeatTestCase):
    def setUp(self):
        super(QuantumTest, self).setUp()
        self.m.StubOutWithMock(net.Net, 'quantum')
        self.m.StubOutWithMock(subnet.Subnet, 'quantum')
        setup_dummy_db()

    def create_net(self, t, stack, resource_name):
        resource = net.Net('test_net', t['Resources'][resource_name], stack)
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(net.Net.CREATE_COMPLETE, resource.state)
        return resource

    def create_subnet(self, t, stack, resource_name):
        resource = subnet.Subnet('test_subnet', t['Resources'][resource_name],
                                 stack)
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(subnet.Subnet.CREATE_COMPLETE, resource.state)
        return resource

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

    @skipIf(net.clients.quantumclient is None, 'quantumclient unavailable')
    def test_net(self):

        fq = FakeQuantum()
        net.Net.quantum().MultipleTimes().AndReturn(fq)

        self.m.ReplayAll()
        t = template_format.parse(quantum_template)
        stack = parse_stack(t)
        resource = self.create_net(t, stack, 'network')

        resource.validate()

        ref_id = resource.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)

        self.assertEqual('ACTIVE', resource.FnGetAtt('status'))
        try:
            resource.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except exception.InvalidTemplateAttribute:
            pass

        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         resource.FnGetAtt('id'))

        self.assertEqual(net.Net.UPDATE_REPLACE, resource.handle_update({}))

        resource.delete()
        self.m.VerifyAll()

    def test_subnet(self):
        skipIf(subnet.clients.quantumclient is None,
               'quantumclient unavailable')

        fq = FakeQuantum()
        subnet.Subnet.quantum().MultipleTimes().AndReturn(fq)

        self.m.ReplayAll()
        t = template_format.parse(quantum_template)
        stack = parse_stack(t)
        resource = self.create_subnet(t, stack, 'subnet')

        resource.validate()

        ref_id = resource.FnGetRefId()
        self.assertEqual('91e47a57-7508-46fe-afc9-fc454e8580e1', ref_id)
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         resource.FnGetAtt('network_id'))
        self.assertEqual('8.8.8.8', resource.FnGetAtt('dns_nameservers')[0])
        self.assertEqual('91e47a57-7508-46fe-afc9-fc454e8580e1',
                         resource.FnGetAtt('id'))

        self.assertEqual(subnet.Subnet.UPDATE_REPLACE,
                         resource.handle_update({}))

        resource.delete()
        self.m.VerifyAll()


class QuantumFloatingIPTest(HeatTestCase):
    def setUp(self):
        super(QuantumFloatingIPTest, self).setUp()
        self.m.StubOutWithMock(floatingip.FloatingIP, 'quantum')
        self.m.StubOutWithMock(floatingip.FloatingIPAssociation, 'quantum')
        self.m.StubOutWithMock(port.Port, 'quantum')
        setup_dummy_db()

    @skipIf(net.clients.quantumclient is None, 'quantumclient unavailable')
    def test_floating_ip(self):

        fq = FakeQuantum()
        floatingip.FloatingIP.quantum().MultipleTimes().AndReturn(fq)

        self.m.ReplayAll()

        t = template_format.parse(quantum_floating_template)
        stack = parse_stack(t)

        fip = stack['floating_ip']
        scheduler.TaskRunner(fip.create)()
        self.assertEqual(floatingip.FloatingIP.CREATE_COMPLETE, fip.state)
        fip.validate()

        fip_id = fip.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', fip_id)

        self.assertEqual('ACTIVE', fip.FnGetAtt('status'))
        try:
            fip.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except exception.InvalidTemplateAttribute:
            pass

        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         fip.FnGetAtt('id'))
        self.assertEqual(floatingip.FloatingIP.UPDATE_REPLACE,
                         fip.handle_update({}))
        self.assertEqual(fip.delete(), None)

        self.m.VerifyAll()

    @skipIf(net.clients.quantumclient is None, 'quantumclient unavailable')
    def test_port(self):

        fq = FakeQuantum()
        port.Port.quantum().MultipleTimes().AndReturn(fq)

        self.m.ReplayAll()

        t = template_format.parse(quantum_floating_template)
        stack = parse_stack(t)

        p = stack['port_floating']
        scheduler.TaskRunner(p.create)()
        self.assertEqual(port.Port.CREATE_COMPLETE, p.state)
        p.validate()

        port_id = p.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', port_id)

        self.assertEqual('ACTIVE', p.FnGetAtt('status'))
        try:
            p.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except exception.InvalidTemplateAttribute:
            pass

        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         p.FnGetAtt('id'))

        self.assertEqual(port.Port.UPDATE_REPLACE,
                         p.handle_update({}))

        self.m.VerifyAll()

    @skipIf(net.clients.quantumclient is None, 'quantumclient unavailable')
    def test_floatip_port(self):

        fq = FakeQuantum()
        floatingip.FloatingIP.quantum().MultipleTimes().AndReturn(fq)
        floatingip.FloatingIPAssociation.quantum().\
            MultipleTimes().AndReturn(fq)
        port.Port.quantum().MultipleTimes().AndReturn(fq)

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
        self.assertEqual(floatingip.FloatingIP.UPDATE_REPLACE,
                         fipa.handle_update({}))

        self.assertEqual(fipa.delete(), None)
        self.assertEqual(p.delete(), None)
        self.assertEqual(fip.delete(), None)

        self.m.VerifyAll()
