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


import unittest
import mox

from nose.plugins.attrib import attr

from heat.common import context
from heat.common import template_format
from heat.engine.resources import vpc
from heat.engine import parser

test_template_vpc = '''
Resources:
  the_vpc:
    Type: AWS::EC2::VPC
    Properties: {CidrBlock: '10.0.0.0/24'}
'''


class FakeQuantum():

    def create_network(self, name):
        return {"network": {
            "status": "ACTIVE",
            "subnets": [],
            "name": "name",
            "admin_state_up": True,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "aaaa"
        }}

    def create_router(self, name):
        return {"router": {
            "status": "ACTIVE",
            "name": "name",
            "admin_state_up": True,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "bbbb"
        }}

    def delete_network(self, id):
        pass

    def delete_router(self, id):
        pass


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class QuantumTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.m.StubOutWithMock(vpc.VPC, 'quantum')

    def tearDown(self):
        self.m.UnsetStubs()
        print "QuantumTest teardown complete"

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

    def create_vpc(self, t, stack, resource_name):
        resource = vpc.VPC('the_vpc', t['Resources'][resource_name], stack)
        self.assertEqual(None, resource.create())
        self.assertEqual(vpc.VPC.CREATE_COMPLETE, resource.state)
        return resource

    def test_vpc(self):
        fq = FakeQuantum()
        vpc.VPC.quantum().MultipleTimes().AndReturn(fq)

        self.m.ReplayAll()
        t = template_format.parse(test_template_vpc)
        stack = self.parse_stack(t)
        resource = self.create_vpc(t, stack, 'the_vpc')

        resource.validate()

        ref_id = resource.FnGetRefId()
        self.assertEqual('aaaa:bbbb', ref_id)

        self.assertEqual(vpc.VPC.UPDATE_REPLACE, resource.handle_update())

        self.assertEqual(None, resource.delete())
        self.m.VerifyAll()
