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

import mox

from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.utils import setup_dummy_db

try:
    from quantumclient.common.exceptions import QuantumClientException
    from quantumclient.v2_0 import client as quantumclient
except ImportError:
    quantumclient = None


class VPCTestBase(HeatTestCase):

    @skipIf(quantumclient is None, 'quantumclient unavaialble')
    def setUp(self):
        super(VPCTestBase, self).setUp()
        setup_dummy_db()
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
        self.m.StubOutWithMock(quantumclient.Client, 'create_security_group')
        self.m.StubOutWithMock(quantumclient.Client, 'show_security_group')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_security_group')
        self.m.StubOutWithMock(
            quantumclient.Client, 'create_security_group_rule')
        self.m.StubOutWithMock(
            quantumclient.Client, 'delete_security_group_rule')

    def stub_sleep(self):
        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        scheduler.TaskRunner._sleep(mox.IsA(int)).MultipleTimes()
        mox.Replay(scheduler.TaskRunner._sleep)

    def create_stack(self, template):
        t = template_format.parse(template)
        stack = self.parse_stack(t)
        self.stub_sleep()
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
        stack = parser.Stack(ctx, stack_name, tmpl)
        stack.store()
        return stack

    def mock_create_network(self):
        vpc_name = utils.PhysName('test_stack', 'the_vpc')
        quantumclient.Client.create_network(
            {
                'network': {'name': vpc_name}
            }).AndReturn({'network': {
                'status': 'ACTIVE',
                'subnets': [],
                'name': vpc_name,
                'admin_state_up': True,
                'shared': False,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'aaaa'
            }})
        quantumclient.Client.create_router(
            {'router': {'name': vpc_name}}).AndReturn({'router': {
                'status': 'ACTIVE',
                'name': vpc_name,
                'admin_state_up': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'rrrr'
            }})

    def mock_create_subnet(self):
        subnet_name = utils.PhysName('test_stack', 'the_subnet')
        quantumclient.Client.create_subnet(
            {'subnet': {
                'network_id': u'aaaa',
                'cidr': u'10.0.0.0/24',
                'ip_version': 4,
                'name': subnet_name}}).AndReturn({
                    'subnet': {
                        'status': 'ACTIVE',
                        'name': subnet_name,
                        'admin_state_up': True,
                        'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                        'id': 'cccc'}})
        quantumclient.Client.add_interface_router(
            u'rrrr',
            {'subnet_id': 'cccc'}).AndReturn(None)

    def mock_show_subnet(self):
        subnet_name = utils.PhysName('test_stack', 'the_subnet')
        quantumclient.Client.show_subnet('cccc').AndReturn({
            'subnet': {
                'name': subnet_name,
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

    def mock_create_security_group(self):
        sg_name = utils.PhysName('test_stack', 'the_sg')
        quantumclient.Client.create_security_group({
            'security_group': {
                'name': sg_name,
                'description': 'SSH access'
            }
        }).AndReturn({
            'security_group': {
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'name': sg_name,
                'description': 'SSH access',
                'security_group_rules': [],
                'id': 'eeee'
            }
        })

        quantumclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'eeee'
            }
        }).AndReturn({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'eeee',
                'id': 'bbbb'
            }
        })

    def mock_delete_security_group(self):
        sg_name = utils.PhysName('test_stack', 'the_sg')
        quantumclient.Client.show_security_group('eeee').AndReturn({
            'security_group': {
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'name': sg_name,
                'description': '',
                'security_group_rules': [{
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': 22,
                    'id': 'bbbb',
                    'ethertype': 'IPv4',
                    'security_group_id': 'eeee',
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                    'port_range_min': 22
                }],
                'id': 'eeee'}})
        quantumclient.Client.delete_security_group_rule('bbbb').AndReturn(None)
        quantumclient.Client.delete_security_group('eeee').AndReturn(None)

    def mock_delete_network(self):
        quantumclient.Client.delete_router('rrrr').AndReturn(None)
        quantumclient.Client.delete_network('aaaa').AndReturn(None)

    def mock_delete_subnet(self):
        quantumclient.Client.remove_interface_router(
            u'rrrr',
            {'subnet_id': 'cccc'}).AndReturn(None)
        quantumclient.Client.delete_subnet('cccc').AndReturn(None)

    def assertResourceState(self, rsrc, ref_id, metadata={}):
        self.assertEqual(None, rsrc.validate())
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(ref_id, rsrc.FnGetRefId())
        self.assertEqual(metadata, dict(rsrc.metadata))


class VPCTest(VPCTestBase):

    test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_vpc:
    Type: AWS::EC2::VPC
    Properties: {CidrBlock: '10.0.0.0/16'}
'''

    def stub_sleep(self):
        pass

    def test_vpc(self):
        self.mock_create_network()
        self.mock_delete_network()
        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        rsrc = stack['the_vpc']
        self.assertResourceState(rsrc, 'aaaa', {
            'router_id': 'rrrr',
            'all_router_ids': ['rrrr']})
        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})

        self.assertEqual(None, rsrc.delete())
        self.m.VerifyAll()


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
            u'rrrr',
            {'subnet_id': 'cccc'}).AndRaise(
                QuantumClientException(status_code=404))
        quantumclient.Client.delete_subnet('cccc').AndRaise(
            QuantumClientException(status_code=404))

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template)

        rsrc = stack['the_subnet']
        self.assertResourceState(rsrc, 'cccc', {
            'router_id': 'rrrr',
            'default_router_id': 'rrrr'})

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})
        self.assertRaises(
            exception.InvalidTemplateAttribute,
            rsrc.FnGetAtt,
            'Foo')

        self.assertEqual('moon', rsrc.FnGetAtt('AvailabilityZone'))

        self.assertEqual(None, rsrc.delete())
        rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE, 'to delete again')
        self.assertEqual(None, rsrc.delete())
        self.assertEqual(None, stack['the_vpc'].delete())
        self.m.VerifyAll()


class NetworkInterfaceTest(VPCTestBase):

    test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_sg:
    Type: AWS::EC2::SecurityGroup
    Properties:
      VpcId: {Ref: the_vpc}
      GroupDescription: SSH access
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 22
          ToPort: 22
          CidrIp: 0.0.0.0/0
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
      GroupSet:
      - Ref: the_sg
'''

    test_template_no_groupset = '''
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

    test_template_error = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_sg:
    Type: AWS::EC2::SecurityGroup
    Properties:
      VpcId: {Ref: the_vpc}
      GroupDescription: SSH access
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 22
          ToPort: 22
          CidrIp: 0.0.0.0/0
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
      GroupSet:
      - Ref: INVALID-REF-IN-TEMPLATE
'''

    test_template_error_no_ref = '''
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
      GroupSet:
      - INVALID-NO-REF
'''

    def mock_create_network_interface(self, security_groups=['eeee']):
        nic_name = utils.PhysName('test_stack', 'the_nic')
        port = {'network_id': 'aaaa',
                'fixed_ips': [{
                    'subnet_id': u'cccc',
                    'ip_address': u'10.0.0.100'
                }],
                'name': nic_name,
                'admin_state_up': True}
        if security_groups:
                port['security_groups'] = security_groups

        quantumclient.Client.create_port({'port': port}).AndReturn({
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
                'name': nic_name,
                'network_id': 'aaaa',
                'status': 'ACTIVE',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'
            }
        })

    def mock_delete_network_interface(self):
        quantumclient.Client.delete_port('dddd').AndReturn(None)

    def test_network_interface(self):
        self.mock_create_security_group()
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_show_subnet()
        self.mock_create_network_interface()
        self.mock_delete_network_interface()
        self.mock_delete_subnet()
        self.mock_delete_network()
        self.mock_delete_security_group()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        try:
            self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
            rsrc = stack['the_nic']
            self.assertResourceState(rsrc, 'dddd')

            self.assertRaises(resource.UpdateReplace,
                              rsrc.handle_update, {}, {}, {})

        finally:
            stack.delete()

        self.m.VerifyAll()

    def test_network_interface_no_groupset(self):
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_show_subnet()
        self.mock_create_network_interface(security_groups=None)
        self.mock_delete_network_interface()
        self.mock_delete_subnet()
        self.mock_delete_network()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template_no_groupset)
        stack.delete()

        self.m.VerifyAll()

    def test_network_interface_error(self):
        real_exception = self.assertRaises(
            exception.InvalidTemplateReference,
            self.create_stack,
            self.test_template_error)
        expected_exception = exception.InvalidTemplateReference(
            resource='INVALID-REF-IN-TEMPLATE',
            key='GroupSet')

        self.assertEquals(str(expected_exception), str(real_exception))

    def test_network_interface_error_no_ref(self):
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_show_subnet()
        self.mock_delete_subnet()
        self.mock_delete_network()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template_error_no_ref)
        try:
            self.assertEqual((stack.CREATE, stack.FAILED), stack.state)
            rsrc = stack['the_nic']
            self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
            reason = rsrc.status_reason
            self.assertTrue(reason.startswith('InvalidTemplateAttribute:'))
        finally:
            stack.delete()

        self.m.VerifyAll()


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
            'rrrr', {'network_id': 'eeee'}).AndReturn(None)

    def mock_delete_gateway_attachment(self):
        quantumclient.Client.remove_gateway_router('rrrr').AndReturn(None)

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
        self.assertRaises(resource.UpdateReplace, gateway.handle_update,
                          {}, {}, {})

        attachment = stack['the_attachment']
        self.assertResourceState(attachment, 'the_attachment')
        self.assertRaises(resource.UpdateReplace,
                          attachment.handle_update, {}, {}, {})

        stack.delete()
        self.m.VerifyAll()


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
        rt_name = utils.PhysName('test_stack', 'the_route_table')
        quantumclient.Client.create_router(
            {'router': {'name': rt_name}}).AndReturn({
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
            'rrrr',
            {'subnet_id': u'cccc'}).AndReturn(None)
        quantumclient.Client.add_interface_router(
            u'ffff',
            {'subnet_id': 'cccc'}).AndReturn(None)

    def mock_delete_association(self):
        quantumclient.Client.remove_interface_router(
            'ffff',
            {'subnet_id': u'cccc'}).AndReturn(None)
        quantumclient.Client.add_interface_router(
            u'rrrr',
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
        self.assertEqual(['rrrr', 'ffff'], vpc.metadata['all_router_ids'])

        route_table = stack['the_route_table']
        self.assertResourceState(route_table, 'ffff', {})
        self.assertRaises(
            resource.UpdateReplace,
            route_table.handle_update, {}, {}, {})

        association = stack['the_association']
        self.assertResourceState(association, 'the_association', {})
        self.assertRaises(
            resource.UpdateReplace,
            association.handle_update, {}, {}, {})

        association.delete()
        route_table.delete()

        vpc = stack['the_vpc']
        self.assertEqual(['rrrr'], vpc.metadata['all_router_ids'])

        stack.delete()
        self.m.VerifyAll()
