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
from heat.common import exception
from heat.common import template_format
from heat.engine.resources import vpc
from heat.engine.resources import subnet
from heat.engine import parser

from quantumclient.common.exceptions import QuantumClientException
from quantumclient.v2_0 import client as quantumclient

test_template_vpc = '''
Resources:
  the_vpc:
    Type: AWS::EC2::VPC
    Properties: {CidrBlock: '10.0.0.0/16'}
'''

test_template_subnet = '''
Resources:
  the_vpc2:
    Type: AWS::EC2::VPC
    Properties: {CidrBlock: '10.0.0.0/16'}
  the_subnet:
    Type: AWS::EC2::Subnet
    Properties:
      CidrBlock: 10.0.0.0/24
      VpcId: {Ref: the_vpc2}
      AvailabilityZone: moon
'''


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class VPCTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.m.StubOutWithMock(quantumclient.Client, 'create_network')
        self.m.StubOutWithMock(quantumclient.Client, 'create_router')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_network')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_router')

    def tearDown(self):
        self.m.UnsetStubs()
        print "VPCTest teardown complete"

    def parse_stack(self, t):
        ctx = context.RequestContext.from_dict({
            'tenant': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'auth_url': 'http://localhost:5000/v2.0'})
        stack_name = 'test_stack'
        tmpl = parser.Template(t)
        params = parser.Parameters(stack_name, tmpl, {})
        stack = parser.Stack(ctx, stack_name, tmpl, params)

        return stack

    def create_vpc(self, t, stack, resource_name):
        resource = vpc.VPC(
            resource_name,
            t['Resources'][resource_name],
            stack)
        self.assertEqual(None, resource.create())
        self.assertEqual(vpc.VPC.CREATE_COMPLETE, resource.state)
        return resource

    def test_vpc(self):
        quantumclient.Client.create_network(
            {'network': {'name': 'the_vpc'}}).AndReturn({"network": {
                "status": "ACTIVE",
                "subnets": [],
                "name": "name",
                "admin_state_up": True,
                "shared": False,
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                "id": "aaaa"
            }})
        quantumclient.Client.create_router(
            {'router': {'name': 'the_vpc'}}).AndReturn({"router": {
                "status": "ACTIVE",
                "name": "name",
                "admin_state_up": True,
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                "id": "bbbb"
            }})
        quantumclient.Client.delete_router('bbbb').AndReturn(None)
        quantumclient.Client.delete_network('aaaa').AndReturn(None)
        self.m.ReplayAll()
        t = template_format.parse(test_template_vpc)
        stack = self.parse_stack(t)
        resource = self.create_vpc(t, stack, 'the_vpc')

        resource.validate()

        ref_id = resource.FnGetRefId()
        self.assertEqual('aaaa:bbbb', ref_id)

        self.assertEqual(vpc.VPC.UPDATE_REPLACE, resource.handle_update({}))

        self.assertEqual(None, resource.delete())
        self.m.VerifyAll()


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class SubnetTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.m.StubOutWithMock(quantumclient.Client, 'create_network')
        self.m.StubOutWithMock(quantumclient.Client, 'create_router')
        self.m.StubOutWithMock(quantumclient.Client, 'create_subnet')
        self.m.StubOutWithMock(quantumclient.Client, 'add_interface_router')
        self.m.StubOutWithMock(quantumclient.Client, 'remove_interface_router')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_network')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_router')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_subnet')

    def tearDown(self):
        self.m.UnsetStubs()
        print "SubnetTest teardown complete"

    def parse_stack(self, t):
        ctx = context.RequestContext.from_dict({
            'tenant': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'auth_url': 'http://localhost:5000/v2.0'})
        params = parser.Parameters('test_stack', t, {})
        stack = parser.Stack(
            ctx,
            'test_stack',
            parser.Template(t),
            parameters=params)
        stack.store()
        return stack

    def create_vpc(self, t, stack, resource_name):
        resource = vpc.VPC(
            resource_name,
            t['Resources'][resource_name],
            stack)
        self.assertEqual(None, resource.create())
        self.assertEqual(vpc.VPC.CREATE_COMPLETE, resource.state)
        return resource

    def create_subnet(self, t, stack, resource_name):
        resource = subnet.Subnet(
            resource_name,
            t['Resources'][resource_name],
            stack)
        self.assertEqual(None, resource.create())
        self.assertEqual(subnet.Subnet.CREATE_COMPLETE, resource.state)
        return resource

    def test_subnet(self):
        quantumclient.Client.create_network(
            {'network': {'name': 'the_vpc2'}}).AndReturn({"network": {
                "status": "ACTIVE",
                "subnets": [],
                "name": "the_vpc2",
                "admin_state_up": True,
                "shared": False,
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                "id": "aaaa"
            }})
        quantumclient.Client.create_router(
            {'router': {'name': 'the_vpc2'}}).AndReturn({"router": {
                "status": "ACTIVE",
                "name": "the_vpc2",
                "admin_state_up": True,
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                "id": "bbbb"
            }})
        quantumclient.Client.create_subnet(
            {'subnet': {
                'network_id': u'aaaa',
                'cidr': u'10.0.0.0/24',
                'name': u'the_subnet'}}).AndReturn({
                    "subnet": {
                        "status": "ACTIVE",
                        "name": "the_subnet",
                        "admin_state_up": True,
                        "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                        "id": "cccc"}})
        quantumclient.Client.add_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)
        quantumclient.Client.remove_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)
        quantumclient.Client.delete_subnet('cccc').AndReturn(None)
        quantumclient.Client.delete_router('bbbb').AndReturn(None)
        quantumclient.Client.delete_network('aaaa').AndReturn(None)

        quantumclient.Client.remove_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndRaise(
                QuantumClientException(status_code=404))
        quantumclient.Client.delete_subnet('cccc').AndRaise(
            QuantumClientException(status_code=404))

        self.m.ReplayAll()
        t = template_format.parse(test_template_subnet)
        stack = self.parse_stack(t)
        stack.create()
        resource = stack['the_subnet']

        resource.validate()

        ref_id = resource.FnGetRefId()
        self.assertEqual('cccc', ref_id)

        self.assertEqual(vpc.VPC.UPDATE_REPLACE, resource.handle_update({}))
        self.assertRaises(
            exception.InvalidTemplateAttribute,
            resource.FnGetAtt,
            'Foo')

        self.assertEqual('moon', resource.FnGetAtt('AvailabilityZone'))

        self.assertEqual(None, resource.delete())
        resource.state_set(resource.CREATE_COMPLETE, 'to delete again')
        self.assertEqual(None, resource.delete())
        self.assertEqual(None, stack['the_vpc2'].delete())
        self.m.VerifyAll()
