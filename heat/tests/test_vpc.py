#
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

import uuid

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine.resources.aws.ec2 import subnet as sn
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils

try:
    from neutronclient.common import exceptions as neutron_exc
    from neutronclient.v2_0 import client as neutronclient
except ImportError:
    neutronclient = None


class VPCTestBase(common.HeatTestCase):

    def setUp(self):
        super(VPCTestBase, self).setUp()
        self.m_add_interface_router = self.patchobject(
            neutronclient.Client, 'add_interface_router',
            return_value=None)
        self.m_add_gateway_router = self.patchobject(
            neutronclient.Client, 'add_gateway_router')
        self.m_create_network = self.patchobject(neutronclient.Client,
                                                 'create_network')
        self.m.StubOutWithMock(neutronclient.Client, 'create_port')
        self.m_create_router = self.patchobject(neutronclient.Client,
                                                'create_router')
        self.m_create_subnet = self.patchobject(neutronclient.Client,
                                                'create_subnet')
        self.m_delete_network = self.patchobject(neutronclient.Client,
                                                 'delete_network',
                                                 return_value=None)
        self.m.StubOutWithMock(neutronclient.Client, 'delete_port')
        self.m_delete_router = self.patchobject(neutronclient.Client,
                                                'delete_router',
                                                return_value=None)
        self.m_delete_subnet = self.patchobject(neutronclient.Client,
                                                'delete_subnet',
                                                return_value=None)
        self.m.StubOutWithMock(neutronclient.Client, 'list_networks')
        self.m_list_routers = self.patchobject(neutronclient.Client,
                                               'list_routers')
        self.m.StubOutWithMock(neutronclient.Client, 'remove_gateway_router')
        self.m_remove_interface_router = self.patchobject(
            neutronclient.Client, 'remove_interface_router',
            return_value=None)
        self.m.StubOutWithMock(neutronclient.Client, 'show_subnet')
        self.m_show_network = self.patchobject(neutronclient.Client,
                                               'show_network')
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

    def create_stack(self, templ):
        t = template_format.parse(templ)
        stack = self.parse_stack(t)
        self.assertIsNone(stack.validate())
        self.assertIsNone(stack.create())
        return stack

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = template.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, tmpl)
        stack.store()
        return stack

    def validate_mock_create_network(self):
        self.m_show_network.assert_called_with('aaaa')
        self.m_create_network.assert_called_once_with({
            'network': {'name': self.vpc_name}})
        self.m_create_router.assert_called_once()

    def mock_create_network(self):
        self.vpc_name = utils.PhysName('test_stack', 'the_vpc')
        self.m_create_network.return_value = {
            'network': {
                'status': 'BUILD',
                'subnets': [],
                'name': 'name',
                'admin_state_up': True,
                'shared': False,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'aaaa'
            }}
        show_network_returns = [
            {"network": {
                "status": "BUILD",
                "subnets": [],
                "name": self.vpc_name,
                "admin_state_up": False,
                "shared": False,
                "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                "id": "aaaa"
            }}]
        for i in range(3):
            show_network_returns.append(
                {"network": {
                    "status": "ACTIVE",
                    "subnets": [],
                    "name": self.vpc_name,
                    "admin_state_up": False,
                    "shared": False,
                    "tenant_id": "c1210485b2424d48804aad5d39c61b8f",
                    "id": "aaaa"
                }})
        self.m_show_network.side_effect = show_network_returns

        self.m_create_router.return_value = {
            'router': {
                'status': 'BUILD',
                'name': self.vpc_name,
                'admin_state_up': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'bbbb'
            }}
        self.mock_router_for_vpc()

    def mock_create_subnet(self):
        self.subnet_name = utils.PhysName('test_stack', 'the_subnet')
        self.m_create_subnet.return_value = {
            'subnet': {
                'status': 'ACTIVE',
                'name': self.subnet_name,
                'admin_state_up': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'cccc'}}

        self.mock_router_for_vpc()

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
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': '0389f747-7785-4757-b7bb-2ab07e4b09c3'
            }
        }).AndReturn({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
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
                        'port_range_max': 22,
                        'id': 'bbbb',
                        'ethertype': 'IPv4',
                        'security_group_id': ('0389f747-7785-4757-b7bb-'
                                              '2ab07e4b09c3'),
                        'remote_group_id': None,
                        'remote_ip_prefix': '0.0.0.0/0',
                        'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                        'port_range_min': 22
                    }],
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3'}})
        elif group == 'INVALID-NO-REF':
            neutronclient.Client.show_security_group(group).AndRaise(
                neutron_exc.NeutronClientException(status_code=404))
        elif group == 'RaiseException':
            neutronclient.Client.show_security_group(
                '0389f747-7785-4757-b7bb-2ab07e4b09c3').AndRaise(
                    neutron_exc.NeutronClientException(status_code=403))

    def mock_delete_security_group(self):
        self.mock_show_security_group()
        neutronclient.Client.delete_security_group_rule(
            'bbbb').AndReturn(None)
        neutronclient.Client.delete_security_group(
            '0389f747-7785-4757-b7bb-2ab07e4b09c3').AndReturn(None)

    def mock_router_for_vpc(self):
        self.m_list_routers.return_value = {
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
        }

    def mock_delete_subnet(self):
        # TODO(ricolin) remove this func once we all move to mock
        self.mock_router_for_vpc()

    def mock_create_route_table(self):
        self.rt_name = utils.PhysName('test_stack', 'the_route_table')
        self.m_create_router.return_value = {
            'router': {
                'status': 'BUILD',
                'name': self.rt_name,
                'admin_state_up': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'ffff'
            }
        }
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

    def mock_create_association(self):
        # TODO(ricolin) merge mock_create_association and
        # mock_delete_association func once we all move to mock
        self.mock_show_subnet()
        self.mock_router_for_vpc()

    def mock_delete_association(self):
        self.mock_show_subnet()
        self.mock_router_for_vpc()

    def mock_delete_route_table(self):
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

    def mock_create_network_failed(self):
        self.vpc_name = utils.PhysName('test_stack', 'the_vpc')
        self.m_create_network.side_effect = neutron_exc.NeutronClientException

    def test_vpc(self):
        self.mock_create_network()

        stack = self.create_stack(self.test_template)
        vpc = stack['the_vpc']
        self.assertResourceState(vpc, 'aaaa')
        self.validate_mock_create_network()
        self.assertEqual(3, self.m_show_network.call_count)

        scheduler.TaskRunner(vpc.delete)()

        self.m_show_network.assert_called_with('aaaa')
        self.assertEqual(4, self.m_show_network.call_count)
        self.assertEqual(2, self.m_list_routers.call_count)
        self.m_list_routers.assert_called_with(name=self.vpc_name)
        self.m_delete_router.assert_called_once_with('bbbb')
        self.m_delete_network.assert_called_once_with('aaaa')

    def test_vpc_delete_successful_if_created_failed(self):
        self.mock_create_network_failed()

        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        scheduler.TaskRunner(stack.create)()
        self.assertEqual((stack.CREATE, stack.FAILED), stack.state)
        self.m_create_network.assert_called_once_with(
            {'network': {'name': self.vpc_name}})
        scheduler.TaskRunner(stack.delete)()
        self.m_delete_network.assert_not_called()


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

        # mock delete subnet which is already deleted
        self.mock_router_for_vpc()
        exc = neutron_exc.NeutronClientException(status_code=404)
        self.m_remove_interface_router.side_effect = exc
        self.m_delete_subnet.side_effect = neutron_exc.NeutronClientException(
            status_code=404)

        stack = self.create_stack(self.test_template)

        subnet = stack['the_subnet']

        self.assertResourceState(subnet, 'cccc')
        self.m_list_routers.assert_called_with(name=self.vpc_name)

        self.validate_mock_create_network()

        self.m_add_interface_router.assert_called_once_with(
            u'bbbb', {'subnet_id': 'cccc'})
        self.m_create_subnet.assert_called_once_with(
            {'subnet': {
                'network_id': u'aaaa',
                'cidr': u'10.0.0.0/24',
                'ip_version': 4,
                'name': self.subnet_name}})
        self.assertEqual(4, self.m_show_network.call_count)
        self.assertRaises(
            exception.InvalidTemplateAttribute,
            subnet.FnGetAtt,
            'Foo')
        self.assertEqual('moon', subnet.FnGetAtt('AvailabilityZone'))

        scheduler.TaskRunner(subnet.delete)()
        subnet.state_set(subnet.CREATE, subnet.COMPLETE, 'to delete again')
        scheduler.TaskRunner(subnet.delete)()
        scheduler.TaskRunner(stack['the_vpc'].delete)()

        self.m_show_network.assert_called_with('aaaa')
        self.m_list_routers.assert_called_with(name=self.vpc_name)
        self.assertEqual(2, self.m_list_routers.call_count)

        self.assertEqual(7, self.m_show_network.call_count)

    def _mock_create_subnet_failed(self, stack_name):
        self.subnet_name = utils.PhysName(stack_name, 'the_subnet')
        self.m_create_subnet.return_value = {
            'subnet': {
                'status': 'ACTIVE',
                'name': self.subnet_name,
                'admin_state_up': True,
                'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
                'id': 'cccc'}}

        self.m_show_network.side_effect = neutron_exc.NeutronClientException(
            status_code=404)

    def test_create_failed_delete_success(self):
        stack_name = 'test_subnet_'
        self._mock_create_subnet_failed(stack_name)

        t = template_format.parse(self.test_template)
        tmpl = template.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, tmpl,
                             stack_id=str(uuid.uuid4()))
        tmpl.t['Resources']['the_subnet']['Properties']['VpcId'] = 'aaaa'
        resource_defns = tmpl.resource_definitions(stack)
        rsrc = sn.Subnet('the_subnet',
                         resource_defns['the_subnet'],
                         stack)
        rsrc.validate()
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        ref_id = rsrc.FnGetRefId()
        self.assertEqual(u'cccc', ref_id)

        self.m_create_subnet.assert_called_once_with(
            {'subnet': {
                'network_id': u'aaaa',
                'cidr': u'10.0.0.0/24',
                'ip_version': 4,
                'name': self.subnet_name}})
        self.assertEqual(1, self.m_show_network.call_count)

        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.assertEqual(2, self.m_show_network.call_count)
        self.m_delete_subnet.assert_called_once_with('cccc')


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

        self.patchobject(resource.Resource, 'is_using_neutron',
                         return_value=True)
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
        self.mock_create_security_group()
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_show_subnet()
        self.stub_SubnetConstraint_validate()
        self.mock_create_network_interface()
        self.mock_show_network_interface()
        self.mock_delete_network_interface()
        self.mock_delete_subnet()
        self.mock_delete_security_group()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        try:
            self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
            rsrc = stack['the_nic']
            self.assertResourceState(rsrc, 'dddd')
            self.assertEqual('10.0.0.100', rsrc.FnGetAtt('PrivateIpAddress'))
        finally:
            scheduler.TaskRunner(stack.delete)()

        self.m.VerifyAll()

    def test_network_interface_existing_groupset(self):
        self.m.StubOutWithMock(parser.Stack, 'resource_by_refid')

        self.mock_create_security_group()
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_show_subnet()
        self.stub_SubnetConstraint_validate()
        self.mock_create_network_interface()
        self.mock_delete_network_interface()
        self.mock_delete_subnet()
        self.mock_delete_security_group()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        try:
            self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
            rsrc = stack['the_nic']
            self.assertResourceState(rsrc, 'dddd')
        finally:
            stack.delete()

        self.m.VerifyAll()

    def test_network_interface_no_groupset(self):
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_show_subnet()
        self.stub_SubnetConstraint_validate()
        self.mock_create_network_interface(security_groups=None)
        self.mock_delete_network_interface()
        self.mock_delete_subnet()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template_no_groupset)
        stack.delete()

        self.m.VerifyAll()

    def test_network_interface_error(self):
        self.assertRaises(
            exception.StackValidationFailed,
            self.create_stack,
            self.test_template_error)


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

    def mock_delete_gateway_attachment(self):
        neutronclient.Client.remove_gateway_router('ffff').AndReturn(None)

    def test_internet_gateway(self):
        self.mock_create_internet_gateway()
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_create_route_table()
        self.stub_SubnetConstraint_validate()
        self.mock_create_association()
        self.mock_delete_gateway_attachment()
        self.mock_delete_association()
        self.mock_delete_route_table()
        self.mock_delete_subnet()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        self.m_create_router.assert_called_with(
            {'router': {'name': self.rt_name}})
        self.m_add_interface_router.assert_called_once_with(
            u'bbbb', {'subnet_id': 'cccc'})

        gateway = stack['the_gateway']
        self.assertResourceState(gateway, gateway.physical_resource_name())
        self.m_add_gateway_router.assert_called_once_with(
            'ffff', {'network_id': '0389f747-7785-4757-b7bb-2ab07e4b09c3'})

        attachment = stack['the_attachment']
        self.assertResourceState(attachment, 'the_attachment')

        route_table = stack['the_route_table']
        self.assertEqual([route_table], list(attachment._vpc_route_tables()))

        stack.delete()
        self.m_remove_interface_router.assert_called_with(
            'ffff',
            {'subnet_id': u'cccc'})
        self.m_delete_router.assert_called_once_with('ffff')
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
        self.mock_create_network()
        self.mock_create_subnet()
        self.mock_create_route_table()
        self.stub_SubnetConstraint_validate()
        self.mock_create_association()
        self.mock_delete_association()
        self.mock_delete_route_table()
        self.mock_delete_subnet()

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        self.m_create_router.assert_called_with(
            {'router': {'name': self.rt_name}})
        self.m_add_interface_router.assert_called_once_with(
            u'bbbb', {'subnet_id': 'cccc'})

        route_table = stack['the_route_table']
        self.assertResourceState(route_table, 'ffff')

        association = stack['the_association']
        self.assertResourceState(association, 'the_association')

        scheduler.TaskRunner(association.delete)()
        scheduler.TaskRunner(route_table.delete)()

        stack.delete()
        self.m_remove_interface_router.assert_called_with(
            'ffff',
            {'subnet_id': u'cccc'})
        self.m_delete_router.assert_called_once_with('ffff')
        self.m.VerifyAll()
