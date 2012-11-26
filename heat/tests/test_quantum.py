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


import sys
import os

import nose
import unittest
import mox
import json

from nose.plugins.attrib import attr

from heat.common import context
from heat.common import exception
from heat.engine import format
from heat.engine.resources import properties
from heat.engine.resources.quantum import net
from heat.engine.resources.quantum.quantum import QuantumResource as qr
from heat.engine import parser
from utils import skip_if

try:
    from quantumclient.v2_0 import client as quantumclient
except:
    skip_test = True
else:
    skip_test = False


class FakeQuantum():

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


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class QuantumTest(unittest.TestCase):
    @skip_if(skip_test, 'unable to import quantumclient')
    def setUp(self):
        self.m = mox.Mox()
        self.m.CreateMock(quantumclient)
        self.m.StubOutWithMock(net.Net, 'quantum')

    def tearDown(self):
        self.m.UnsetStubs()
        print "QuantumTest teardown complete"

    def load_template(self):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/Quantum.template" % self.path)
        t = format.parse_to_template(f.read())
        f.close()
        return t

    def parse_stack(self, t):
        ctx = context.RequestContext.from_dict({
            'tenant': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'auth_url': 'http://localhost:5000/v2.0'})
        stack = parser.Stack(ctx, 'test_stack', parser.Template(t),
            stack_id=-1, parameters={'external_network': 'abcd1234'})

        return stack

    def create_net(self, t, stack, resource_name):
        resource = net.Net('test_net',
                                      t['Resources'][resource_name],
                                      stack)
        self.assertEqual(None, resource.create())
        self.assertEqual(net.Net.CREATE_COMPLETE, resource.state)
        return resource

    def test_validate_properties(self):
        vs = {'router:external': True}
        data = {
            'admin_state_up': False,
            'value_specs': vs
        }
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
        data = {
            'admin_state_up': False,
            'value_specs': {'router:external': True}
        }
        p = properties.Properties(net.Net.properties_schema, data)
        props = qr.prepare_properties(p, 'resource_name')
        self.assertEqual({
            'name': 'resource_name',
            'router:external': True,
            'admin_state_up': False
        }, props)

    @skip_if(skip_test, 'unable to import quantumclient')
    def test_net(self):
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

        self.assertEqual(net.Net.UPDATE_REPLACE, resource.handle_update())

        resource.delete()
        self.m.VerifyAll()

    # allows testing of the test directly, shown below
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
