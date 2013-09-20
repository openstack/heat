# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Licensed under the Apache License, Version 2.0 (the 'License"); you may
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
from heat.engine import parser
import heat.engine.resources  # pyflakes_bypass review 23102

try:
    from quantumclient.common.exceptions import QuantumClientException
    from quantumclient.v2_0 import client as quantumclient
except ImportError:
    from nose.exc import SkipTest
    raise SkipTest()


class VPCTestBase(unittest.TestCase):

    def setUp(self):
        self.m = mox.Mox()
        self.m.StubOutWithMock(quantumclient.Client, 'add_interface_router')
        self.m.StubOutWithMock(quantumclient.Client, 'add_gateway_router')
        self.m.StubOutWithMock(quantumclient.Client, 'create_network')
        self.m.StubOutWithMock(quantumclient.Client, 'create_port')
        self.m.StubOutWithMock(quantumclient.Client, 'create_router')
        self.m.StubOutWithMock(quantumclient.Client, 'create_subnet')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_network')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_port')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_router')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_subnet')
        self.m.StubOutWithMock(quantumclient.Client, 'list_networks')
        self.m.StubOutWithMock(quantumclient.Client, 'remove_gateway_router')
        self.m.StubOutWithMock(quantumclient.Client, 'remove_interface_router')
        self.m.StubOutWithMock(quantumclient.Client, 'show_subnet')
        self.m.StubOutWithMock(quantumclient.Client, 'show_network')

    def tearDown(self):
        self.m.UnsetStubs()

    def create_stack(self, template):
        t = template_format.parse(template)
        stack = self.parse_stack(t)
        self.assertEqual(None, stack.create())
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
            {
                'network': {'name': 'test_stack.the_vpc'}
            }).AndReturn({'network': {
                'status': 'ACTIVE',
                'subnets': [],
                'name': 'name',
                'admin_state_up': True,
                'shared': False,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'aaaa'
            }})
        quantumclient.Client.create_router(
            {'router': {'name': 'test_stack.the_vpc'}}).AndReturn({'router': {
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
                'name': u'test_stack.the_subnet'}}).AndReturn({
                    'subnet': {
                        'status': 'ACTIVE',
                        'name': 'test_stack.the_subnet',
                        'admin_state_up': True,
                        'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                        'id': 'cccc'}})
        quantumclient.Client.add_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)

    def mock_show_subnet(self):
        quantumclient.Client.show_subnet('cccc').AndReturn({
            'subnet': {
                'name': 'test_stack.the_subnet',
                'network_id': 'aaaa',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'allocation_pools': [{'start': '10.0.0.2',
                                      'end': '10.0.0.254'}],
                'gateway_ip': '10.0.0.1',
                'ip_version': 4,
                'cidr': '10.0.0.0/24',
                'id': 'cccc',
                'enable_dhcp': False,
            }})

    def mock_delete_network(self):
        quantumclient.Client.delete_router('bbbb').AndReturn(None)
        quantumclient.Client.delete_network('aaaa').AndReturn(None)

    def mock_delete_subnet(self):
        quantumclient.Client.remove_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)
        quantumclient.Client.delete_subnet('cccc').AndReturn(None)

    def assertResourceState(self, resource, ref_id, metadata={}):
        self.assertEqual(None, resource.validate())
        self.assertEqual(resource.CREATE_COMPLETE, resource.state)
        self.assertEqual(ref_id, resource.FnGetRefId())
        self.assertEqual(metadata, dict(resource.metadata))


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class VPCTest(VPCTestBase):

    test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_vpc:
    Type: AWS::EC2::VPC
    Properties: {CidrBlock: '10.0.0.0/16'}
'''

    def test_vpc(self):
        self.mock_create_network()
        self.mock_delete_network()
        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        resource = stack['the_vpc']
        self.assertResourceState(resource, 'aaaa', {
            'router_id': 'bbbb',
            'all_router_ids': ['bbbb']})
        self.assertEqual(resource.UPDATE_REPLACE, resource.handle_update({}))

        self.assertEqual(None, resource.delete())
        self.m.VerifyAll()


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class SubnetTest(VPCTestBase):

    test_template = '''
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
        stack = self.create_stack(self.test_template)

        resource = stack['the_subnet']
        self.assertResourceState(resource, 'cccc', {
            'router_id': 'bbbb',
            'default_router_id': 'bbbb'})

        self.assertEqual(resource.UPDATE_REPLACE, resource.handle_update({}))
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

    test_template = '''
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

    def mock_create_network_interface(self):
        quantumclient.Client.create_port({
            'port': {
                'network_id': 'aaaa', 'fixed_ips': [{
                    'subnet_id': u'cccc',
                    'ip_address': u'10.0.0.100'
                }],
                'name': u'test_stack.the_nic',
                'admin_state_up': True
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
                    'name': 'test_stack.the_nic',
                    'network_id': 'aaaa',
                    'status': 'ACTIVE',
                    'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'
                }
            })

    def mock_delete_network_interface(self):
        quantumclient.Client.delete_port('dddd').AndReturn(None)

    def test_network_interface(self):
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_show_subnet()
        self.mock_create_network_interface()
        self.mock_delete_network_interface()
        self.mock_delete_subnet()
        self.mock_delete_network()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        resource = stack['the_nic']
        self.assertResourceState(resource, 'dddd')

        self.assertEqual(resource.UPDATE_REPLACE, resource.handle_update({}))

        stack.delete()
        self.m.VerifyAll()


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class InternetGatewayTest(VPCTestBase):

    test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_gateway:
    Type: AWS::EC2::InternetGateway
  the_vpc:
    Type: AWS::EC2::VPC
    DependsOn : the_gateway
    Properties:
      CidrBlock: '10.0.0.0/16'
  the_subnet:
    Type: AWS::EC2::Subnet
    Properties:
      CidrBlock: 10.0.0.0/24
      VpcId: {Ref: the_vpc}
      AvailabilityZone: moon
  the_attachment:
    Type: AWS::EC2::VPCGatewayAttachment
    DependsOn : the_subnet
    Properties:
      VpcId: {Ref: the_vpc}
      InternetGatewayId: {Ref: the_gateway}
'''

    def mock_create_internet_gateway(self):
        quantumclient.Client.list_networks(
            **{'router:external': True}).AndReturn({'networks': [{
                'status': 'ACTIVE',
                'subnets': [],
                'name': 'nova',
                'router:external': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'admin_state_up': True,
                'shared': True,
                'id': 'eeee'
            }]})

    def mock_create_gateway_attachment(self):
        quantumclient.Client.add_gateway_router(
            'bbbb', {'network_id': 'eeee'}).AndReturn(None)

    def mock_delete_gateway_attachment(self):
        quantumclient.Client.remove_gateway_router('bbbb').AndReturn(None)

    def test_internet_gateway(self):
        self.mock_create_internet_gateway()
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_create_gateway_attachment()
        self.mock_delete_gateway_attachment()
        self.mock_delete_subnet()
        self.mock_delete_network()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)

        gateway = stack['the_gateway']
        self.assertResourceState(gateway, 'the_gateway', {
            'external_network_id': 'eeee'})
        self.assertEqual(gateway.UPDATE_REPLACE, gateway.handle_update({}))

        attachment = stack['the_attachment']
        self.assertResourceState(attachment, 'the_attachment')
        self.assertEqual(gateway.UPDATE_REPLACE, attachment.handle_update({}))

        stack.delete()
        self.m.VerifyAll()


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class RouteTableTest(VPCTestBase):

    test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_vpc:
    Type: AWS::EC2::VPC
    Properties:
      CidrBlock: '10.0.0.0/16'
  the_subnet:
    Type: AWS::EC2::Subnet
    Properties:
      CidrBlock: 10.0.0.0/24
      VpcId: {Ref: the_vpc}
      AvailabilityZone: moon
  the_route_table:
    Type: AWS::EC2::RouteTable
    Properties:
      VpcId: {Ref: the_vpc}
  the_association:
    Type: AWS::EC2::SubnetRouteTableAssocation
    Properties:
      RouteTableId: {Ref: the_route_table}
      SubnetId: {Ref: the_subnet}
'''

    def mock_create_route_table(self):
        quantumclient.Client.create_router(
            {'router': {'name': u'test_stack.the_route_table'}}).AndReturn({
                'router': {
                    'status': 'ACTIVE',
                    'name': 'name',
                    'admin_state_up': True,
                    'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                    'id': 'ffff'
                }
            })

    def mock_create_association(self):
        quantumclient.Client.remove_interface_router(
            'bbbb',
            {'subnet_id': u'cccc'}).AndReturn(None)
        quantumclient.Client.add_interface_router(
            u'ffff',
            {'subnet_id': 'cccc'}).AndReturn(None)

    def mock_delete_association(self):
        quantumclient.Client.remove_interface_router(
            'ffff',
            {'subnet_id': u'cccc'}).AndReturn(None)
        quantumclient.Client.add_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)

    def mock_delete_route_table(self):
        quantumclient.Client.delete_router('ffff').AndReturn(None)

    def test_route_table(self):
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_create_route_table()
        self.mock_create_association()
        self.mock_delete_association()
        self.mock_delete_route_table()
        self.mock_delete_subnet()
        self.mock_delete_network()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)

        vpc = stack['the_vpc']
        self.assertEqual(['bbbb', 'ffff'], vpc.metadata['all_router_ids'])

        route_table = stack['the_route_table']
        self.assertResourceState(route_table, 'ffff', {})
        self.assertEqual(
            route_table.UPDATE_REPLACE,
            route_table.handle_update({}))

        association = stack['the_association']
        self.assertResourceState(association, 'the_association', {})
        self.assertEqual(
            association.UPDATE_REPLACE,
            association.handle_update({}))

        association.delete()
        route_table.delete()

        vpc = stack['the_vpc']
        self.assertEqual(['bbbb'], vpc.metadata['all_router_ids'])

        stack.delete()
        self.m.VerifyAll()
