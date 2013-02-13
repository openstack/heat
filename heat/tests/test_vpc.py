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
from heat.engine.resources import network_interface
from heat.engine.resources import subnet
from heat.engine.resources import vpc
from heat.engine import parser

from quantumclient.common.exceptions import QuantumClientException
from quantumclient.v2_0 import client as quantumclient

test_template_vpc = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_vpc:
    Type: AWS::EC2::VPC
    Properties: {CidrBlock: '10.0.0.0/16'}
'''

test_template_subnet = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_vpc:
    Type: AWS::EC2::VPC
    Properties: {CidrBlock: '10.0.0.0/16'}
  the_subnet:
    Type: AWS::EC2::Subnet
    Properties:
      CidrBlock: 10.0.0.0/24
      VpcId: {Ref: the_vpc}
      AvailabilityZone: moon
'''

test_template_nic = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_vpc:
    Type: AWS::EC2::VPC
    Properties: {CidrBlock: '10.0.0.0/16'}
  the_subnet:
    Type: AWS::EC2::Subnet
    Properties:
      CidrBlock: 10.0.0.0/24
      VpcId: {Ref: the_vpc}
      AvailabilityZone: moon
  the_nic:
    Type: AWS::EC2::NetworkInterface
    Properties:
      PrivateIpAddress: 10.0.0.100
      SubnetId: {Ref: the_subnet}
'''


class VPCTestBase(unittest.TestCase):

    def setUp(self):
        self.m = mox.Mox()
        self.m.StubOutWithMock(quantumclient.Client, 'create_network')
        self.m.StubOutWithMock(quantumclient.Client, 'create_router')
        self.m.StubOutWithMock(quantumclient.Client, 'create_subnet')
        self.m.StubOutWithMock(quantumclient.Client, 'show_subnet')
        self.m.StubOutWithMock(quantumclient.Client, 'create_port')
        self.m.StubOutWithMock(quantumclient.Client, 'add_interface_router')
        self.m.StubOutWithMock(quantumclient.Client, 'remove_interface_router')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_network')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_router')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_subnet')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_port')

    def tearDown(self):
        self.m.UnsetStubs()

    def create_stack(self, temlate):
        t = template_format.parse(temlate)
        stack = self.parse_stack(t)
        stack.create()
        return stack

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
        stack.store()
        return stack

    def mock_create_network(self):
        quantumclient.Client.create_network(
            {'network': {'name': 'the_vpc'}}).AndReturn({'network': {
                'status': 'ACTIVE',
                'subnets': [],
                'name': 'name',
                'admin_state_up': True,
                'shared': False,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'aaaa'
            }})
        quantumclient.Client.create_router(
            {'router': {'name': 'the_vpc'}}).AndReturn({'router': {
                'status': 'ACTIVE',
                'name': 'name',
                'admin_state_up': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'bbbb'
            }})

    def mock_create_subnet(self):
        quantumclient.Client.create_subnet(
            {'subnet': {
                'network_id': u'aaaa',
                'cidr': u'10.0.0.0/24',
                'ip_version': 4,
                'name': u'the_subnet'}}).AndReturn({
                    'subnet': {
                        'status': 'ACTIVE',
                        'name': 'the_subnet',
                        'admin_state_up': True,
                        'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                        'id': 'cccc'}})
        quantumclient.Client.add_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)

    def mock_create_network_interface(self):
        quantumclient.Client.show_subnet('cccc').AndReturn({
            'subnet': {
                'name': 'the_subnet',
                'network_id': 'aaaa',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'allocation_pools': [{
                    'start': '10.10.0.2', 'end': '10.10.0.254'}],
                'gateway_ip': '10.10.0.1',
                'ip_version': 4,
                'cidr': '10.10.0.0/24',
                'id': 'cccc',
                'enable_dhcp': False}
        })
        quantumclient.Client.create_port({
            'port': {
                'status': 'ACTIVE',
                'device_owner': '',
                'name': '',
                'admin_state_up': True,
                'network_id': 'aaaa',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'mac_address': 'fa:16:3e:25:32:5d',
                'fixed_ips': [{
                    'subnet_id': 'cccc',
                    'ip_address': '10.0.0.100'}],
                'id': 'dddd',
                'device_id': ''
            }}).AndReturn({
                'port': {
                    'admin_state_up': True,
                    'device_id': '',
                    'device_owner': '',
                    'fixed_ips': [
                        {
                            'ip_address': '10.0.0.100',
                            'subnet_id': 'cccc'
                        }
                    ],
                    'id': 'dddd',
                    'mac_address': 'fa:16:3e:25:32:5d',
                    'name': '',
                    'network_id': 'aaaa',
                    'status': 'ACTIVE',
                    'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'
                }
            })

    def mock_delete_network_interface(self):
        quantumclient.Client.delete_port('dddd').AndReturn(None)

    def mock_delete_network(self):
        quantumclient.Client.delete_router('bbbb').AndReturn(None)
        quantumclient.Client.delete_network('aaaa').AndReturn(None)

    def mock_delete_subnet(self):
        quantumclient.Client.remove_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)
        quantumclient.Client.delete_subnet('cccc').AndReturn(None)


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class VPCTest(VPCTestBase):

    def test_vpc(self):
        self.mock_create_network()
        self.mock_delete_network()
        self.m.ReplayAll()
        stack = self.create_stack(test_template_vpc)
        resource = stack['the_vpc']

        resource.validate()

        ref_id = resource.FnGetRefId()
        self.assertEqual('aaaa:bbbb', ref_id)

        self.assertEqual(vpc.VPC.UPDATE_REPLACE, resource.handle_update({}))

        self.assertEqual(None, resource.delete())
        self.m.VerifyAll()


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class SubnetTest(VPCTestBase):

    def test_subnet(self):
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_delete_subnet()
        self.mock_delete_network()

        # mock delete subnet which is already deleted
        quantumclient.Client.remove_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndRaise(
                QuantumClientException(status_code=404))
        quantumclient.Client.delete_subnet('cccc').AndRaise(
            QuantumClientException(status_code=404))

        self.m.ReplayAll()
        stack = self.create_stack(test_template_subnet)

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
        self.assertEqual(None, stack['the_vpc'].delete())
        self.m.VerifyAll()


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class NetworkInterfaceTest(VPCTestBase):

    def test_network_interface(self):
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_create_network_interface()
        #self.mock_delete_network_interface()
        #self.mock_delete_subnet()
        #self.mock_delete_network()

        self.m.ReplayAll()

        stack = self.create_stack(test_template_nic)
        resource = stack['the_nic']

        resource.validate()
#
#        ref_id = resource.FnGetRefId()
#        self.assertEqual('dddd', ref_id)

        self.m.VerifyAll()
