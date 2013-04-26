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


import os

from testtools import skipIf

from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.engine import properties
from heat.engine import scheduler
from heat.engine.resources.quantum import net
from heat.engine.resources.quantum import floatingip
from heat.engine.resources.quantum import port
from heat.engine.resources.quantum.quantum import QuantumResource as qr
from heat.engine import parser
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db


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


class QuantumTest(HeatTestCase):
    def setUp(self):
        super(QuantumTest, self).setUp()
        self.m.StubOutWithMock(net.Net, 'quantum')
        setup_dummy_db()

    def load_template(self):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/Quantum.template" % self.path)
        t = template_format.parse(f.read())
        f.close()
        return t

    def parse_stack(self, t):
        ctx = context.RequestContext.from_dict({
            'tenant': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'auth_url': 'http://localhost:5000/v2.0'})
        stack_name = 'test_stack'
        tmpl = parser.Template(t)
        params = parser.Parameters(stack_name, tmpl,
                                   {'external_network': 'abcd1234'})
        stack = parser.Stack(ctx, stack_name, tmpl, params)

        return stack

    def create_net(self, t, stack, resource_name):
        resource = net.Net('test_net', t['Resources'][resource_name], stack)
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(net.Net.CREATE_COMPLETE, resource.state)
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

    def test_net(self):
        skipIf(net.clients.quantumclient is None, 'quantumclient unavailable')

        fq = FakeQuantum()
        net.Net.quantum().MultipleTimes().AndReturn(fq)

        self.m.ReplayAll()
        t = self.load_template()
        stack = self.parse_stack(t)
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


class QuantumFloatingIPTest(HeatTestCase):
    def setUp(self):
        super(QuantumFloatingIPTest, self).setUp()
        self.m.StubOutWithMock(floatingip.FloatingIP, 'quantum')
        self.m.StubOutWithMock(floatingip.FloatingIPAssociation, 'quantum')
        self.m.StubOutWithMock(port.Port, 'quantum')
        setup_dummy_db()

    def load_template(self, name='Quantum'):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/%s.template" % (self.path, name))
        t = template_format.parse(f.read())
        f.close()
        return t

    def parse_stack(self, t):
        ctx = context.RequestContext.from_dict({
            'tenant': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'auth_url': 'http://localhost:5000/v2.0'})
        stack_name = 'test_stack'
        tmpl = parser.Template(t)
        params = parser.Parameters(stack_name, tmpl,
                                   {'external_network': 'abcd1234',
                                    'internal_network': 'xyz1234',
                                    'internal_subnet': '12.12.12.0'})
        stack = parser.Stack(ctx, stack_name, tmpl, params)

        return stack

    def test_floating_ip(self):
        if net.clients.quantumclient is None:
            raise SkipTest

        fq = FakeQuantum()
        floatingip.FloatingIP.quantum().MultipleTimes().AndReturn(fq)

        self.m.ReplayAll()

        t = self.load_template('Quantum_floating')
        stack = self.parse_stack(t)

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

    def test_port(self):
        if net.clients.quantumclient is None:
            raise SkipTest

        fq = FakeQuantum()
        port.Port.quantum().MultipleTimes().AndReturn(fq)

        self.m.ReplayAll()

        t = self.load_template('Quantum_floating')
        stack = self.parse_stack(t)

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

    def test_floatip_port(self):
        if net.clients.quantumclient is None:
            raise SkipTest

        fq = FakeQuantum()
        floatingip.FloatingIP.quantum().MultipleTimes().AndReturn(fq)
        floatingip.FloatingIPAssociation.quantum().\
            MultipleTimes().AndReturn(fq)
        port.Port.quantum().MultipleTimes().AndReturn(fq)

        self.m.ReplayAll()

        t = self.load_template('Quantum_floating')
        stack = self.parse_stack(t)

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
