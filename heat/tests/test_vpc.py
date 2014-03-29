
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
from heat.engine import clients
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils

try:
    from neutronclient.common.exceptions import NeutronClientException
    from neutronclient.v2_0 import client as neutronclient
except ImportError:
    neutronclient = None


class VPCTestBase(HeatTestCase):

    @skipIf(neutronclient is None, 'neutronclient unavaialble')
    def setUp(self):
        super(VPCTestBase, self).setUp()
        utils.setup_dummy_db()
        self.m.StubOutWithMock(neutronclient.Client, 'add_interface_router')
        self.m.StubOutWithMock(neutronclient.Client, 'add_gateway_router')
        self.m.StubOutWithMock(neutronclient.Client, 'create_network')
        self.m.StubOutWithMock(neutronclient.Client, 'create_port')
        self.m.StubOutWithMock(neutronclient.Client, 'create_router')
        self.m.StubOutWithMock(neutronclient.Client, 'create_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_network')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_port')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_router')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'list_networks')
        self.m.StubOutWithMock(neutronclient.Client, 'list_routers')
        self.m.StubOutWithMock(neutronclient.Client, 'remove_gateway_router')
        self.m.StubOutWithMock(neutronclient.Client, 'remove_interface_router')
        self.m.StubOutWithMock(neutronclient.Client, 'show_subnet')
        self.m.StubOutWithMock(neutronclient.Client, 'show_network')
        self.m.StubOutWithMock(neutronclient.Client, 'show_port')
        self.m.StubOutWithMock(neutronclient.Client, 'show_router')
        self.m.StubOutWithMock(neutronclient.Client, 'create_security_group')
        self.m.StubOutWithMock(neutronclient.Client, 'show_security_group')
        self.m.StubOutWithMock(neutronclient.Client, 'list_security_groups')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_security_group')
        self.m.StubOutWithMock(
            neutronclient.Client, 'create_security_group_rule')
        self.m.StubOutWithMock(
            neutronclient.Client, 'delete_security_group_rule')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')

    def create_stack(self, template):
        t = template_format.parse(template)
        stack = self.parse_stack(t)
        self.assertIsNone(stack.create())
        return stack

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, tmpl)
        stack.store()
        return stack

    def mock_keystone(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())

    def mock_create_network(self):
        self.vpc_name = utils.PhysName('test_stack', 'the_vpc')
        neutronclient.Client.create_network(
            {
                'network': {'name': self.vpc_name}
            }).AndReturn({'network': {
                'status': 'BUILD',
                'subnets': [],
                'name': 'name',
                'admin_state_up': True,
                'shared': False,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'aaaa'
            }})
        neutronclient.Client.show_network(
            'aaaa'
        ).AndReturn({"network": {
            "status": "BUILD",
            "subnets": [],
            "name": self.vpc_name,
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "aaaa"
        }})

        neutronclient.Client.show_network(
            'aaaa'
        ).MultipleTimes().AndReturn({"network": {
            "status": "ACTIVE",
            "subnets": [],
            "name": self.vpc_name,
            "admin_state_up": False,
            "shared": False,
            "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
            "id": "aaaa"
        }})
        neutronclient.Client.create_router(
            {'router': {'name': self.vpc_name}}).AndReturn({
                'router': {
                    'status': 'BUILD',
                    'name': self.vpc_name,
                    'admin_state_up': True,
                    'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                    'id': 'bbbb'
                }})
        neutronclient.Client.list_routers(name=self.vpc_name).AndReturn({
            "routers": [{
                "status": "BUILD",
                "external_gateway_info": None,
                "name": self.vpc_name,
                "admin_state_up": True,
                "tenant_id": "3e21026f2dc94372b105808c0e721661",
                "routes": [],
                "id": "bbbb"
            }]
        })
        self.mock_router_for_vpc()

    def mock_create_subnet(self):
        self.subnet_name = utils.PhysName('test_stack', 'the_subnet')
        neutronclient.Client.create_subnet(
            {'subnet': {
                'network_id': u'aaaa',
                'cidr': u'10.0.0.0/24',
                'ip_version': 4,
                'name': self.subnet_name}}).AndReturn({
                    'subnet': {
                        'status': 'ACTIVE',
                        'name': self.subnet_name,
                        'admin_state_up': True,
                        'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                        'id': 'cccc'}})
        self.mock_router_for_vpc()
        neutronclient.Client.add_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)

    def mock_show_subnet(self):
        neutronclient.Client.show_subnet('cccc').AndReturn({
            'subnet': {
                'name': self.subnet_name,
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
        self.sg_name = utils.PhysName('test_stack', 'the_sg')
        neutronclient.Client.create_security_group({
            'security_group': {
                'name': self.sg_name,
                'description': 'SSH access'
            }
        }).AndReturn({
            'security_group': {
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'name': self.sg_name,
                'description': 'SSH access',
                'security_group_rules': [],
                'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3'
            }
        })

        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': '22',
                'ethertype': 'IPv4',
                'port_range_max': '22',
                'protocol': 'tcp',
                'security_group_id': '0389f747-7785-4757-b7bb-2ab07e4b09c3'
            }
        }).AndReturn({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': '22',
                'ethertype': 'IPv4',
                'port_range_max': '22',
                'protocol': 'tcp',
                'security_group_id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                'id': 'bbbb'
            }
        })

    def mock_show_security_group(self, group=None):
        sg_name = utils.PhysName('test_stack', 'the_sg')
        group = group or '0389f747-7785-4757-b7bb-2ab07e4b09c3'
        if group == '0389f747-7785-4757-b7bb-2ab07e4b09c3':
            neutronclient.Client.show_security_group(group).AndReturn({
                'security_group': {
                    'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                    'name': sg_name,
                    'description': '',
                    'security_group_rules': [{
                        'direction': 'ingress',
                        'protocol': 'tcp',
                        'port_range_max': '22',
                        'id': 'bbbb',
                        'ethertype': 'IPv4',
                        'security_group_id': ('0389f747-7785-4757-b7bb-'
                                              '2ab07e4b09c3'),
                        'remote_group_id': None,
                        'remote_ip_prefix': '0.0.0.0/0',
                        'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                        'port_range_min': '22'
                    }],
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3'}})
        elif group == 'INVALID-NO-REF':
            neutronclient.Client.show_security_group(group).AndRaise(
                NeutronClientException(status_code=404))
        elif group == 'RaiseException':
            neutronclient.Client.show_security_group(
                '0389f747-7785-4757-b7bb-2ab07e4b09c3').AndRaise(
                    NeutronClientException(status_code=403))

    def mock_delete_security_group(self):
        self.mock_show_security_group()
        neutronclient.Client.delete_security_group_rule(
            'bbbb').AndReturn(None)
        neutronclient.Client.delete_security_group(
            '0389f747-7785-4757-b7bb-2ab07e4b09c3').AndReturn(None)

    def mock_router_for_vpc(self):
        neutronclient.Client.list_routers(name=self.vpc_name).AndReturn({
            "routers": [{
                "status": "ACTIVE",
                "external_gateway_info": {
                    "network_id": "zzzz",
                    "enable_snat": True},
                "name": self.vpc_name,
                "admin_state_up": True,
                "tenant_id": "3e21026f2dc94372b105808c0e721661",
                "routes": [],
                "id": "bbbb"
            }]
        })

    def mock_delete_network(self):
        self.mock_router_for_vpc()
        neutronclient.Client.delete_router('bbbb').AndReturn(None)
        neutronclient.Client.delete_network('aaaa').AndReturn(None)

    def mock_delete_subnet(self):
        self.mock_router_for_vpc()
        neutronclient.Client.remove_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)
        neutronclient.Client.delete_subnet('cccc').AndReturn(None)

    def mock_create_route_table(self):
        self.rt_name = utils.PhysName('test_stack', 'the_route_table')
        neutronclient.Client.create_router({
            'router': {'name': self.rt_name}}).AndReturn({
                'router': {
                    'status': 'BUILD',
                    'name': self.rt_name,
                    'admin_state_up': True,
                    'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                    'id': 'ffff'
                }
            })
        neutronclient.Client.show_router('ffff').AndReturn({
            'router': {
                'status': 'BUILD',
                'name': self.rt_name,
                'admin_state_up': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'ffff'
            }
        })
        neutronclient.Client.show_router('ffff').AndReturn({
            'router': {
                'status': 'ACTIVE',
                'name': self.rt_name,
                'admin_state_up': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'ffff'
            }
        })
        self.mock_router_for_vpc()
        neutronclient.Client.add_gateway_router(
            'ffff', {'network_id': 'zzzz'}).AndReturn(None)

    def mock_create_association(self):
        self.mock_show_subnet()
        self.mock_router_for_vpc()
        neutronclient.Client.remove_interface_router(
            'bbbb',
            {'subnet_id': u'cccc'}).AndReturn(None)
        neutronclient.Client.add_interface_router(
            u'ffff',
            {'subnet_id': 'cccc'}).AndReturn(None)

    def mock_delete_association(self):
        self.mock_show_subnet()
        self.mock_router_for_vpc()
        neutronclient.Client.remove_interface_router(
            'ffff',
            {'subnet_id': u'cccc'}).AndReturn(None)
        neutronclient.Client.add_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndReturn(None)

    def mock_delete_route_table(self):
        neutronclient.Client.delete_router('ffff').AndReturn(None)
        neutronclient.Client.remove_gateway_router('ffff').AndReturn(None)

    def assertResourceState(self, resource, ref_id):
        self.assertIsNone(resource.validate())
        self.assertEqual((resource.CREATE, resource.COMPLETE), resource.state)
        self.assertEqual(ref_id, resource.FnGetRefId())


class VPCTest(VPCTestBase):

    test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_vpc:
    Type: AWS::EC2::VPC
    Properties: {CidrBlock: '10.0.0.0/16'}
'''

    def test_vpc(self):
        self.mock_keystone()
        self.mock_create_network()
        self.mock_delete_network()
        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        vpc = stack['the_vpc']
        self.assertResourceState(vpc, 'aaaa')
        self.assertRaises(resource.UpdateReplace,
                          vpc.handle_update, {}, {}, {})

        scheduler.TaskRunner(vpc.delete)()
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
        self.mock_keystone()
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_delete_subnet()
        self.mock_delete_network()

        # mock delete subnet which is already deleted
        self.mock_router_for_vpc()
        neutronclient.Client.remove_interface_router(
            u'bbbb',
            {'subnet_id': 'cccc'}).AndRaise(
                NeutronClientException(status_code=404))
        neutronclient.Client.delete_subnet('cccc').AndRaise(
            NeutronClientException(status_code=404))

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template)

        subnet = stack['the_subnet']
        self.assertResourceState(subnet, 'cccc')

        self.assertRaises(resource.UpdateReplace,
                          subnet.handle_update, {}, {}, {})
        self.assertRaises(
            exception.InvalidTemplateAttribute,
            subnet.FnGetAtt,
            'Foo')

        self.assertEqual('moon', subnet.FnGetAtt('AvailabilityZone'))

        scheduler.TaskRunner(subnet.delete)()
        subnet.state_set(subnet.CREATE, subnet.COMPLETE, 'to delete again')
        scheduler.TaskRunner(subnet.delete)()
        scheduler.TaskRunner(stack['the_vpc'].delete)()
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
          FromPort: "22"
          ToPort: "22"
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
          FromPort: "22"
          ToPort: "22"
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

    def mock_create_network_interface(
            self, security_groups=['0389f747-7785-4757-b7bb-2ab07e4b09c3']):

        self.nic_name = utils.PhysName('test_stack', 'the_nic')
        port = {'network_id': 'aaaa',
                'fixed_ips': [{
                    'subnet_id': u'cccc',
                    'ip_address': u'10.0.0.100'
                }],
                'name': self.nic_name,
                'admin_state_up': True}
        if security_groups:
                port['security_groups'] = security_groups

        neutronclient.Client.create_port({'port': port}).AndReturn({
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
                'name': self.nic_name,
                'network_id': 'aaaa',
                'status': 'ACTIVE',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'
            }
        })

    def mock_show_network_interface(self):
        self.nic_name = utils.PhysName('test_stack', 'the_nic')
        neutronclient.Client.show_port('dddd').AndReturn({
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
                'name': self.nic_name,
                'network_id': 'aaaa',
                'security_groups': ['0389f747-7785-4757-b7bb-2ab07e4b09c3'],
                'status': 'ACTIVE',
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'
            }
        })

    def mock_delete_network_interface(self):
        neutronclient.Client.delete_port('dddd').AndReturn(None)

    def test_network_interface(self):
        self.mock_keystone()
        self.mock_create_security_group()
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_show_subnet()
        self.mock_create_network_interface()
        self.mock_show_network_interface()
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
            self.assertEqual('10.0.0.100', rsrc.FnGetAtt('PrivateIpAddress'))

            self.assertRaises(resource.UpdateReplace,
                              rsrc.handle_update, {}, {}, {})

        finally:
            scheduler.TaskRunner(stack.delete)()

        self.m.VerifyAll()

    def test_network_interface_existing_groupset(self):
        self.m.StubOutWithMock(parser.Stack, 'resource_by_refid')

        self.mock_keystone()
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
        self.mock_keystone()
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
            key='the_nic.Properties.GroupSet[0]')

        self.assertEqual(str(expected_exception), str(real_exception))


class InternetGatewayTest(VPCTestBase):

    test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_gateway:
    Type: AWS::EC2::InternetGateway
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
  the_attachment:
    Type: AWS::EC2::VPCGatewayAttachment
    Properties:
      VpcId: {Ref: the_vpc}
      InternetGatewayId: {Ref: the_gateway}
  the_route_table:
    Type: AWS::EC2::RouteTable
    Properties:
      VpcId: {Ref: the_vpc}
  the_association:
    Type: AWS::EC2::SubnetRouteTableAssociation
    Properties:
      RouteTableId: {Ref: the_route_table}
      SubnetId: {Ref: the_subnet}
'''

    def mock_create_internet_gateway(self):
        neutronclient.Client.list_networks(
            **{'router:external': True}).AndReturn({'networks': [{
                'status': 'ACTIVE',
                'subnets': [],
                'name': 'nova',
                'router:external': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'admin_state_up': True,
                'shared': True,
                'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3'
            }]})

    def mock_create_gateway_attachment(self):
        neutronclient.Client.add_gateway_router(
            'ffff', {'network_id': '0389f747-7785-4757-b7bb-2ab07e4b09c3'}
        ).AndReturn(None)

    def mock_delete_gateway_attachment(self):
        neutronclient.Client.remove_gateway_router('ffff').AndReturn(None)

    def test_internet_gateway(self):
        self.mock_keystone()
        self.mock_create_internet_gateway()
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_create_route_table()
        self.mock_create_association()
        self.mock_create_gateway_attachment()
        self.mock_delete_gateway_attachment()
        self.mock_delete_association()
        self.mock_delete_route_table()
        self.mock_delete_subnet()
        self.mock_delete_network()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)

        gateway = stack['the_gateway']
        self.assertResourceState(gateway, gateway.physical_resource_name())
        self.assertRaises(resource.UpdateReplace, gateway.handle_update,
                          {}, {}, {})

        attachment = stack['the_attachment']
        self.assertResourceState(attachment, 'the_attachment')
        self.assertRaises(resource.UpdateReplace,
                          attachment.handle_update, {}, {}, {})

        route_table = stack['the_route_table']
        self.assertEqual(list(attachment._vpc_route_tables()), [route_table])

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
    Type: AWS::EC2::SubnetRouteTableAssociation
    Properties:
      RouteTableId: {Ref: the_route_table}
      SubnetId: {Ref: the_subnet}
'''

    def test_route_table(self):
        self.mock_keystone()
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

        route_table = stack['the_route_table']
        self.assertResourceState(route_table, 'ffff')
        self.assertRaises(
            resource.UpdateReplace,
            route_table.handle_update, {}, {}, {})

        association = stack['the_association']
        self.assertResourceState(association, 'the_association')
        self.assertRaises(
            resource.UpdateReplace,
            association.handle_update, {}, {}, {})

        scheduler.TaskRunner(association.delete)()
        scheduler.TaskRunner(route_table.delete)()

        stack.delete()
        self.m.VerifyAll()
