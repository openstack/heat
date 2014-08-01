
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

import collections

from neutronclient.common.exceptions import NeutronClientException
from neutronclient.v2_0 import client as neutronclient
from novaclient.v1_1 import security_group_rules as nova_sgr
from novaclient.v1_1 import security_groups as nova_sg

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests.fakes import FakeKeystoneClient
from heat.tests import utils
from heat.tests.v1_1 import fakes


NovaSG = collections.namedtuple('NovaSG',
                                ' '.join([
                                    'name',
                                    'id',
                                    'rules',
                                    'description',
                                ]))


class SecurityGroupTest(HeatTestCase):

    test_template_nova = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_sg:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: HTTP and SSH access
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: "22"
          ToPort: "22"
          CidrIp: 0.0.0.0/0
        - IpProtocol: tcp
          FromPort : "80"
          ToPort : "80"
          CidrIp : 0.0.0.0/0
        - IpProtocol: tcp
          SourceSecurityGroupName: test
        - IpProtocol: icmp
          SourceSecurityGroupId: "1"
'''

    test_template_nova_bad_source_group = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_sg:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: HTTP and SSH access
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: "22"
          ToPort: "22"
          CidrIp: 0.0.0.0/0
        - IpProtocol: tcp
          FromPort : "80"
          ToPort : "80"
          CidrIp : 0.0.0.0/0
        - IpProtocol: tcp
          SourceSecurityGroupName: thisdoesnotexist
        - IpProtocol: icmp
          SourceSecurityGroupId: "1"
'''

    test_template_nova_with_egress = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_sg:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: HTTP and SSH access
      SecurityGroupEgress:
        - IpProtocol: tcp
          FromPort: "22"
          ToPort: "22"
          CidrIp: 0.0.0.0/0
'''

    test_template_neutron = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_sg:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: HTTP and SSH access
      VpcId: aaaa
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: "22"
          ToPort: "22"
          CidrIp: 0.0.0.0/0
        - IpProtocol: tcp
          FromPort : "80"
          ToPort : "80"
          CidrIp : 0.0.0.0/0
        - IpProtocol: tcp
          SourceSecurityGroupId: wwww
      SecurityGroupEgress:
        - IpProtocol: tcp
          FromPort: "22"
          ToPort: "22"
          CidrIp: 10.0.1.0/24
        - SourceSecurityGroupName: xxxx
'''

    def setUp(self):
        super(SecurityGroupTest, self).setUp()
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        self.m.StubOutWithMock(nova_sgr.SecurityGroupRuleManager, 'create')
        self.m.StubOutWithMock(nova_sgr.SecurityGroupRuleManager, 'delete')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'create')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'delete')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'get')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'list')
        utils.setup_dummy_db()
        self.m.StubOutWithMock(neutronclient.Client, 'create_security_group')
        self.m.StubOutWithMock(
            neutronclient.Client, 'create_security_group_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'show_security_group')
        self.m.StubOutWithMock(
            neutronclient.Client, 'delete_security_group_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_security_group')

    def create_stack(self, template):
        t = template_format.parse(template)
        self.stack = self.parse_stack(t)
        self.assertIsNone(self.stack.create())
        return self.stack

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, tmpl)
        stack.store()
        return stack

    def assertResourceState(self, rsrc, ref_id, metadata={}):
        self.assertIsNone(rsrc.validate())
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(ref_id, rsrc.FnGetRefId())
        self.assertEqual(metadata, dict(rsrc.metadata))

    @utils.stack_delete_after
    def test_security_group_nova(self):
        #create script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.list().AndReturn([NovaSG(
            id=1,
            name='test',
            description='FAKE_SECURITY_GROUP',
            rules=[],
        )])
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        sg_name = utils.PhysName('test_stack', 'the_sg')
        nova_sg.SecurityGroupManager.create(
            sg_name,
            'HTTP and SSH access').AndReturn(NovaSG(
                id=2,
                name=sg_name,
                description='HTTP and SSH access',
                rules=[]))

        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', '22', '22', '0.0.0.0/0', None).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', '80', '80', '0.0.0.0/0', None).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', None, None, None, 1).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'icmp', None, None, None, '1').AndReturn(None)

        # delete script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.get(2).AndReturn(NovaSG(
            id=2,
            name=sg_name,
            description='HTTP and SSH access',
            rules=[{
                "from_port": '22',
                "group": {},
                "ip_protocol": "tcp",
                "to_port": '22',
                "parent_group_id": 2,
                "ip_range": {
                    "cidr": "0.0.0.0/0"
                },
                'id': 130
            }, {
                'from_port': '80',
                'group': {},
                'ip_protocol': 'tcp',
                'to_port': '80',
                'parent_group_id': 2,
                'ip_range': {
                    'cidr': '0.0.0.0/0'
                },
                'id': 131
            }, {
                'from_port': None,
                'group': {
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'name': 'test'
                },
                'ip_protocol': 'tcp',
                'to_port': None,
                'parent_group_id': 2,
                'ip_range': {},
                'id': 132
            }, {
                'from_port': None,
                'group': {
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'name': 'test'
                },
                'ip_protocol': 'icmp',
                'to_port': None,
                'parent_group_id': 2,
                'ip_range': {},
                'id': 133
            }]
        ))
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(130).AndReturn(None)
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(131).AndReturn(None)
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(132).AndReturn(None)
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(133).AndReturn(None)
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.delete(2).AndReturn(None)

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_nova)

        sg = stack['the_sg']
        self.assertRaises(resource.UpdateReplace, sg.handle_update, {}, {}, {})

        self.assertResourceState(sg, utils.PhysName('test_stack', 'the_sg'))

        stack.delete()
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_security_group_nova_bad_source_group(self):
        #create script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.list().AndReturn([NovaSG(
            id=1,
            name='test',
            description='FAKE_SECURITY_GROUP',
            rules=[],
        )])
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        sg_name = utils.PhysName('test_stack', 'the_sg')
        nova_sg.SecurityGroupManager.create(
            sg_name,
            'HTTP and SSH access').AndReturn(NovaSG(
                id=2,
                name=sg_name,
                description='HTTP and SSH access',
                rules=[]))

        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', '22', '22', '0.0.0.0/0', None).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', '80', '80', '0.0.0.0/0', None).AndReturn(None)

        # delete script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.get(2).AndReturn(NovaSG(
            id=2,
            name=sg_name,
            description='HTTP and SSH access',
            rules=[{
                "from_port": '22',
                "group": {},
                "ip_protocol": "tcp",
                "to_port": '22',
                "parent_group_id": 2,
                "ip_range": {
                    "cidr": "0.0.0.0/0"
                },
                'id': 130
            }, {
                'from_port': '80',
                'group': {},
                'ip_protocol': 'tcp',
                'to_port': '80',
                'parent_group_id': 2,
                'ip_range': {
                    'cidr': '0.0.0.0/0'
                },
                'id': 131
            }]
        ))
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(130).AndReturn(None)
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(131).AndReturn(None)
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.delete(2).AndReturn(None)

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_nova_bad_source_group)

        sg = stack['the_sg']
        self.assertEqual(sg.FAILED, sg.status)
        self.assertIn('not found', sg.status_reason)

        stack.delete()
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_security_group_nova_exception(self):
        #create script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        sg_name = utils.PhysName('test_stack', 'the_sg')
        nova_sg.SecurityGroupManager.list().AndReturn([
            NovaSG(
                id=2,
                name=sg_name,
                description='HTTP and SSH access',
                rules=[],
            ),
            NovaSG(
                id=1,
                name='test',
                description='FAKE_SECURITY_GROUP',
                rules=[],
            )
        ])

        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', '22', '22', '0.0.0.0/0', None).AndRaise(
                fakes.fake_exception(400, 'Rule already exists'))
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', '80', '80', '0.0.0.0/0', None).AndReturn(
                fakes.fake_exception(400, 'Rule already exists'))
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', None, None, None, 1).AndReturn(
                fakes.fake_exception(400, 'Rule already exists'))
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'icmp', None, None, None, '1').AndReturn(
                fakes.fake_exception(400, 'Rule already exists'))

        # delete script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.get(2).AndReturn(NovaSG(
            id=2,
            name=sg_name,
            description='HTTP and SSH access',
            rules=[{
                "from_port": '22',
                "group": {},
                "ip_protocol": "tcp",
                "to_port": '22',
                "parent_group_id": 2,
                "ip_range": {
                    "cidr": "0.0.0.0/0"
                },
                'id': 130
            }, {
                'from_port': '80',
                'group': {},
                'ip_protocol': 'tcp',
                'to_port': '80',
                'parent_group_id': 2,
                'ip_range': {
                    'cidr': '0.0.0.0/0'
                },
                'id': 131
            }, {
                'from_port': None,
                'group': {
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'name': 'test'
                },
                'ip_protocol': 'tcp',
                'to_port': None,
                'parent_group_id': 2,
                'ip_range': {},
                'id': 132
            }, {
                'from_port': None,
                'group': {
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'name': 'test'
                },
                'ip_protocol': 'icmp',
                'to_port': None,
                'parent_group_id': 2,
                'ip_range': {},
                'id': 133
            }]
        ))
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(130).AndRaise(
            clients.novaclient.exceptions.NotFound('goneburger'))
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(131).AndRaise(
            clients.novaclient.exceptions.NotFound('goneburger'))
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(132).AndRaise(
            clients.novaclient.exceptions.NotFound('goneburger'))
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(133).AndRaise(
            clients.novaclient.exceptions.NotFound('goneburger'))
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.delete(2).AndReturn(None)

        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.get(2).AndRaise(
            clients.novaclient.exceptions.NotFound('goneburger'))

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_nova)

        sg = stack['the_sg']
        self.assertRaises(resource.UpdateReplace, sg.handle_update, {}, {}, {})

        self.assertResourceState(sg, utils.PhysName('test_stack', 'the_sg'))

        scheduler.TaskRunner(sg.delete)()

        sg.state_set(sg.CREATE, sg.COMPLETE, 'to delete again')
        sg.resource_id = 2
        stack.delete()

        self.m.VerifyAll()

    def test_security_group_nova_with_egress_rules(self):
        t = template_format.parse(self.test_template_nova_with_egress)
        stack = self.parse_stack(t)

        sg = stack['the_sg']
        self.assertRaises(exception.EgressRuleNotAllowed, sg.validate)

    @utils.stack_delete_after
    def test_security_group_neutron(self):
        #create script
        clients.OpenStackClients.keystone().AndReturn(
            FakeKeystoneClient())
        sg_name = utils.PhysName('test_stack', 'the_sg')
        neutronclient.Client.create_security_group({
            'security_group': {
                'name': sg_name,
                'description': 'HTTP and SSH access'
            }
        }).AndReturn({
            'security_group': {
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'name': sg_name,
                'description': 'HTTP and SSH access',
                'security_group_rules': [{
                    "direction": "egress",
                    "ethertype": "IPv4",
                    "id": "aaaa-1",
                    "port_range_max": None,
                    "port_range_min": None,
                    "protocol": None,
                    "remote_group_id": None,
                    "remote_ip_prefix": None,
                    "security_group_id": "aaaa",
                    "tenant_id": "f18ca530cc05425e8bac0a5ff92f7e88"
                }, {
                    "direction": "egress",
                    "ethertype": "IPv6",
                    "id": "aaaa-2",
                    "port_range_max": None,
                    "port_range_min": None,
                    "protocol": None,
                    "remote_group_id": None,
                    "remote_ip_prefix": None,
                    "security_group_id": "aaaa",
                    "tenant_id": "f18ca530cc05425e8bac0a5ff92f7e88"
                }],
                'id': 'aaaa'
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
                'security_group_id': 'aaaa'
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
                'security_group_id': 'aaaa',
                'id': 'bbbb'
            }
        })
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': '80',
                'ethertype': 'IPv4',
                'port_range_max': '80',
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndReturn({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': '80',
                'ethertype': 'IPv4',
                'port_range_max': '80',
                'protocol': 'tcp',
                'security_group_id': 'aaaa',
                'id': 'cccc'
            }
        })
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': 'wwww',
                'remote_ip_prefix': None,
                'port_range_min': None,
                'ethertype': 'IPv4',
                'port_range_max': None,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndReturn({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': 'wwww',
                'remote_ip_prefix': None,
                'port_range_min': None,
                'ethertype': 'IPv4',
                'port_range_max': None,
                'protocol': 'tcp',
                'security_group_id': 'aaaa',
                'id': 'dddd'
            }
        })
        neutronclient.Client.delete_security_group_rule('aaaa-1').AndReturn(
            None)
        neutronclient.Client.delete_security_group_rule('aaaa-2').AndReturn(
            None)
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': None,
                'remote_ip_prefix': '10.0.1.0/24',
                'port_range_min': '22',
                'ethertype': 'IPv4',
                'port_range_max': '22',
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndReturn({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': None,
                'remote_ip_prefix': '10.0.1.0/24',
                'port_range_min': '22',
                'ethertype': 'IPv4',
                'port_range_max': '22',
                'protocol': 'tcp',
                'security_group_id': 'aaaa',
                'id': 'eeee'
            }
        })
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': 'xxxx',
                'remote_ip_prefix': None,
                'port_range_min': None,
                'ethertype': 'IPv4',
                'port_range_max': None,
                'protocol': None,
                'security_group_id': 'aaaa'
            }
        }).AndReturn({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': 'xxxx',
                'remote_ip_prefix': None,
                'port_range_min': None,
                'ethertype': 'IPv4',
                'port_range_max': None,
                'protocol': None,
                'security_group_id': 'aaaa',
                'id': 'ffff'
            }
        })

        # delete script
        neutronclient.Client.show_security_group('aaaa').AndReturn({
            'security_group': {
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'name': 'sc1',
                'description': '',
                'security_group_rules': [{
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': '22',
                    'id': 'bbbb',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': '22'
                }, {
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': '80',
                    'id': 'cccc',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': '80'
                }, {
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': None,
                    'id': 'dddd',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': 'wwww',
                    'remote_ip_prefix': None,
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': None
                }, {
                    'direction': 'egress',
                    'protocol': 'tcp',
                    'port_range_max': '22',
                    'id': 'eeee',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '10.0.1.0/24',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': '22'
                }, {
                    'direction': 'egress',
                    'protocol': None,
                    'port_range_max': None,
                    'id': 'ffff',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': None,
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': None
                }],
                'id': 'aaaa'}})
        neutronclient.Client.delete_security_group_rule('bbbb').AndReturn(None)
        neutronclient.Client.delete_security_group_rule('cccc').AndReturn(None)
        neutronclient.Client.delete_security_group_rule('dddd').AndReturn(None)
        neutronclient.Client.delete_security_group_rule('eeee').AndReturn(None)
        neutronclient.Client.delete_security_group_rule('ffff').AndReturn(None)
        neutronclient.Client.delete_security_group('aaaa').AndReturn(None)

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_neutron)

        sg = stack['the_sg']
        self.assertRaises(resource.UpdateReplace, sg.handle_update, {}, {}, {})

        self.assertResourceState(sg, 'aaaa')

        stack.delete()
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_security_group_neutron_exception(self):
        #create script
        clients.OpenStackClients.keystone().AndReturn(
            FakeKeystoneClient())
        sg_name = utils.PhysName('test_stack', 'the_sg')
        neutronclient.Client.create_security_group({
            'security_group': {
                'name': sg_name,
                'description': 'HTTP and SSH access'
            }
        }).AndReturn({
            'security_group': {
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'name': sg_name,
                'description': 'HTTP and SSH access',
                'security_group_rules': [],
                'id': 'aaaa'
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
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            NeutronClientException(status_code=409))
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': '80',
                'ethertype': 'IPv4',
                'port_range_max': '80',
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            NeutronClientException(status_code=409))
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': 'wwww',
                'remote_ip_prefix': None,
                'port_range_min': None,
                'ethertype': 'IPv4',
                'port_range_max': None,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            NeutronClientException(status_code=409))
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': None,
                'remote_ip_prefix': '10.0.1.0/24',
                'port_range_min': '22',
                'ethertype': 'IPv4',
                'port_range_max': '22',
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            NeutronClientException(status_code=409))
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': 'xxxx',
                'remote_ip_prefix': None,
                'port_range_min': None,
                'ethertype': 'IPv4',
                'port_range_max': None,
                'protocol': None,
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            NeutronClientException(status_code=409))

        # delete script
        neutronclient.Client.show_security_group('aaaa').AndReturn({
            'security_group': {
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'name': 'sc1',
                'description': '',
                'security_group_rules': [{
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': '22',
                    'id': 'bbbb',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': '22'
                }, {
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': '80',
                    'id': 'cccc',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': '80'
                }, {
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': None,
                    'id': 'dddd',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': 'wwww',
                    'remote_ip_prefix': None,
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': None
                }, {
                    'direction': 'egress',
                    'protocol': 'tcp',
                    'port_range_max': '22',
                    'id': 'eeee',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '10.0.1.0/24',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': '22'
                }, {
                    'direction': 'egress',
                    'protocol': None,
                    'port_range_max': None,
                    'id': 'ffff',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': None,
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': None
                }],
                'id': 'aaaa'}})
        neutronclient.Client.delete_security_group_rule('bbbb').AndRaise(
            NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group_rule('cccc').AndRaise(
            NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group_rule('dddd').AndRaise(
            NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group_rule('eeee').AndRaise(
            NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group_rule('ffff').AndRaise(
            NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group('aaaa').AndRaise(
            NeutronClientException(status_code=404))

        neutronclient.Client.show_security_group('aaaa').AndRaise(
            NeutronClientException(status_code=404))

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_neutron)

        sg = stack['the_sg']
        self.assertRaises(resource.UpdateReplace, sg.handle_update, {}, {}, {})

        self.assertResourceState(sg, 'aaaa')

        scheduler.TaskRunner(sg.delete)()

        sg.state_set(sg.CREATE, sg.COMPLETE, 'to delete again')
        sg.resource_id = 'aaaa'
        stack.delete()

        self.m.VerifyAll()
