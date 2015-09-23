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

import collections
import copy
import mock

from keystoneclient import exceptions as keystone_exc
from neutronclient.common import exceptions as neutron_exc
from neutronclient.v2_0 import client as neutronclient
from novaclient.v2 import security_group_rules as nova_sgr
from novaclient.v2 import security_groups as nova_sg

from heat.common import exception
from heat.common import short_id
from heat.common import template_format
from heat.engine.clients.os import nova
from heat.engine.resources.aws.ec2 import security_group
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests.nova import fakes as fakes_nova
from heat.tests import utils


NovaSG = collections.namedtuple('NovaSG',
                                ' '.join([
                                    'name',
                                    'id',
                                    'rules',
                                    'description',
                                ]))


class SecurityGroupTest(common.HeatTestCase):

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
        self.fc = fakes_nova.FakeClient()
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        self.m.StubOutWithMock(nova_sgr.SecurityGroupRuleManager, 'create')
        self.m.StubOutWithMock(nova_sgr.SecurityGroupRuleManager, 'delete')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'create')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'delete')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'get')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'list')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'update')
        self.m.StubOutWithMock(neutronclient.Client, 'create_security_group')
        self.m.StubOutWithMock(
            neutronclient.Client, 'create_security_group_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'show_security_group')
        self.m.StubOutWithMock(
            neutronclient.Client, 'delete_security_group_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_security_group')
        self.m.StubOutWithMock(neutronclient.Client, 'update_security_group')

    def mock_no_neutron(self):
        mock_create = self.patch(
            'heat.engine.clients.os.neutron.NeutronClientPlugin._create')
        mock_create.side_effect = keystone_exc.EndpointNotFound()

    def create_stack(self, templ):
        self.stack = self.parse_stack(template_format.parse(templ))
        self.assertIsNone(self.stack.create())
        return self.stack

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = template.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, tmpl)
        stack.store()
        return stack

    def assertResourceState(self, rsrc, ref_id, metadata=None):
        metadata = metadata or {}
        self.assertIsNone(rsrc.validate())
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(ref_id, rsrc.FnGetRefId())
        self.assertEqual(metadata, dict(rsrc.metadata_get()))

    def stubout_nova_create_security_group(self):
        # create script
        self.mock_no_neutron()
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        nova_sg.SecurityGroupManager.list().AndReturn([NovaSG(
            id=1,
            name='test',
            description='FAKE_SECURITY_GROUP',
            rules=[],
        )])
        nova_sg.SecurityGroupManager.list().AndReturn([NovaSG(
            id=1,
            name='test',
            description='FAKE_SECURITY_GROUP',
            rules=[],
        )])

        sg_name = utils.PhysName('test_stack', 'the_sg')
        nova_sg.SecurityGroupManager.create(
            sg_name,
            'HTTP and SSH access').AndReturn(NovaSG(
                id=2,
                name=sg_name,
                description='HTTP and SSH access',
                rules=[]))

        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', 22, 22, '0.0.0.0/0', None).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', 80, 80, '0.0.0.0/0', None).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', None, None, None, 1).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'icmp', None, None, None, '1').AndReturn(None)
        return sg_name

    def stubout_nova_get_security_group(self, sg_name):
        nova_sg.SecurityGroupManager.get(2).AndReturn(NovaSG(
            id=2,
            name=sg_name,
            description='',
            rules=[{
                "from_port": 22,
                "group": {},
                "ip_protocol": "tcp",
                "to_port": 22,
                "parent_group_id": 2,
                "ip_range": {
                    "cidr": "0.0.0.0/0"
                },
                'id': 130
            }, {
                'from_port': 80,
                'group': {},
                'ip_protocol': 'tcp',
                'to_port': 80,
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

    def stubout_nova_delete_security_group_rules(self, sg_name):
        self.stubout_nova_get_security_group(sg_name)
        nova_sgr.SecurityGroupRuleManager.delete(130).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.delete(131).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.delete(132).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.delete(133).AndReturn(None)

    def stubout_neutron_create_security_group(self):
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

        neutronclient.Client.delete_security_group_rule('aaaa-1').AndReturn(
            None)
        neutronclient.Client.delete_security_group_rule('aaaa-2').AndReturn(
            None)

        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
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
                'security_group_id': 'aaaa',
                'id': 'bbbb'
            }
        })
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 80,
                'ethertype': 'IPv4',
                'port_range_max': 80,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndReturn({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 80,
                'ethertype': 'IPv4',
                'port_range_max': 80,
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
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': None,
                'remote_ip_prefix': '10.0.1.0/24',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndReturn({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': None,
                'remote_ip_prefix': '10.0.1.0/24',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
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

    def stubout_neutron_get_security_group(self):
        neutronclient.Client.show_security_group('aaaa').AndReturn({
            'security_group': {
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'name': 'sc1',
                'description': '',
                'security_group_rules': [{
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': 22,
                    'id': 'bbbb',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 22
                }, {
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': 80,
                    'id': 'cccc',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 80
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
                    'port_range_max': 22,
                    'id': 'eeee',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '10.0.1.0/24',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 22
                }, {
                    'direction': 'egress',
                    'protocol': None,
                    'port_range_max': None,
                    'id': 'ffff',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': 'xxxx',
                    'remote_ip_prefix': None,
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': None
                }],
                'id': 'aaaa'}})

    def stubout_neutron_delete_security_group_rules(self):
        self.stubout_neutron_get_security_group()
        neutronclient.Client.delete_security_group_rule('bbbb').AndReturn(None)
        neutronclient.Client.delete_security_group_rule('cccc').AndReturn(None)
        neutronclient.Client.delete_security_group_rule('dddd').AndReturn(None)
        neutronclient.Client.delete_security_group_rule('eeee').AndReturn(None)
        neutronclient.Client.delete_security_group_rule('ffff').AndReturn(None)

    def test_security_group_nova(self):
        # create script
        sg_name = self.stubout_nova_create_security_group()

        # delete script
        self.stubout_nova_delete_security_group_rules(sg_name)
        nova_sg.SecurityGroupManager.delete(2).AndReturn(None)

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_nova)

        sg = stack['the_sg']

        self.assertResourceState(sg, utils.PhysName('test_stack', 'the_sg'))

        stack.delete()
        self.m.VerifyAll()

    def test_security_group_nova_bad_source_group(self):
        # create script
        self.mock_no_neutron()
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        nova_sg.SecurityGroupManager.list().MultipleTimes().AndReturn([NovaSG(
            id=1,
            name='test',
            description='FAKE_SECURITY_GROUP',
            rules=[],
        )])
        sg_name = utils.PhysName('test_stack', 'the_sg')
        nova_sg.SecurityGroupManager.create(
            sg_name,
            'HTTP and SSH access').AndReturn(NovaSG(
                id=2,
                name=sg_name,
                description='HTTP and SSH access',
                rules=[]))

        # delete script
        nova_sg.SecurityGroupManager.get(2).AndReturn(NovaSG(
            id=2,
            name=sg_name,
            description='HTTP and SSH access',
            rules=[{
                "from_port": 22,
                "group": {},
                "ip_protocol": "tcp",
                "to_port": 22,
                "parent_group_id": 2,
                "ip_range": {
                    "cidr": "0.0.0.0/0"
                },
                'id': 130
            }, {
                'from_port': 80,
                'group': {},
                'ip_protocol': 'tcp',
                'to_port': 80,
                'parent_group_id': 2,
                'ip_range': {
                    'cidr': '0.0.0.0/0'
                },
                'id': 131
            }]
        ))
        nova_sgr.SecurityGroupRuleManager.delete(130).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.delete(131).AndReturn(None)
        nova_sg.SecurityGroupManager.delete(2).AndReturn(None)

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_nova_bad_source_group)

        sg = stack['the_sg']
        self.assertEqual(sg.FAILED, sg.status)
        self.assertIn('not found', sg.status_reason)

        stack.delete()
        self.m.VerifyAll()

    def test_security_group_nova_exception(self):
        # create script
        self.mock_no_neutron()
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        sg_name = utils.PhysName('test_stack', 'the_sg')
        nova_sg.SecurityGroupManager.list().MultipleTimes().AndReturn([
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

        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', 22, 22, '0.0.0.0/0', None).AndRaise(
                fakes_nova.fake_exception(400, 'Rule already exists'))
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', 80, 80, '0.0.0.0/0', None).AndReturn(
                fakes_nova.fake_exception(400, 'Rule already exists'))
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', None, None, None, 1).AndReturn(
                fakes_nova.fake_exception(400, 'Rule already exists'))
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'icmp', None, None, None, '1').AndReturn(
                fakes_nova.fake_exception(400, 'Rule already exists'))

        # delete script
        nova_sg.SecurityGroupManager.get(2).AndReturn(NovaSG(
            id=2,
            name=sg_name,
            description='HTTP and SSH access',
            rules=[{
                "from_port": 22,
                "group": {},
                "ip_protocol": "tcp",
                "to_port": 22,
                "parent_group_id": 2,
                "ip_range": {
                    "cidr": "0.0.0.0/0"
                },
                'id': 130
            }, {
                'from_port': 80,
                'group': {},
                'ip_protocol': 'tcp',
                'to_port': 80,
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
        nova_sgr.SecurityGroupRuleManager.delete(130).AndRaise(
            fakes_nova.fake_exception())
        nova_sgr.SecurityGroupRuleManager.delete(131).AndRaise(
            fakes_nova.fake_exception())
        nova_sgr.SecurityGroupRuleManager.delete(132).AndRaise(
            fakes_nova.fake_exception())
        nova_sgr.SecurityGroupRuleManager.delete(133).AndRaise(
            fakes_nova.fake_exception())
        nova_sg.SecurityGroupManager.delete(2).AndReturn(None)

        nova_sg.SecurityGroupManager.get(2).AndRaise(
            fakes_nova.fake_exception())

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_nova)

        sg = stack['the_sg']

        self.assertResourceState(sg, utils.PhysName('test_stack', 'the_sg'))

        scheduler.TaskRunner(sg.delete)()

        sg.state_set(sg.CREATE, sg.COMPLETE, 'to delete again')
        sg.resource_id = 2
        stack.delete()

        self.m.VerifyAll()

    def test_security_group_nova_with_egress_rules(self):
        self.mock_no_neutron()
        t = template_format.parse(self.test_template_nova_with_egress)
        stack = self.parse_stack(t)

        sg = stack['the_sg']
        self.assertRaises(exception.EgressRuleNotAllowed, sg.validate)

    def test_security_group_neutron(self):
        # create script
        self.stubout_neutron_create_security_group()

        # delete script
        self.stubout_neutron_delete_security_group_rules()
        neutronclient.Client.delete_security_group('aaaa').AndReturn(None)

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_neutron)

        sg = stack['the_sg']

        self.assertResourceState(sg, 'aaaa')

        stack.delete()
        self.m.VerifyAll()

    def test_security_group_neutron_exception(self):
        # create script
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
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            neutron_exc.Conflict())
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 80,
                'ethertype': 'IPv4',
                'port_range_max': 80,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            neutron_exc.Conflict())
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
            neutron_exc.Conflict())
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': None,
                'remote_ip_prefix': '10.0.1.0/24',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            neutron_exc.Conflict())
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
            neutron_exc.Conflict())

        # delete script
        neutronclient.Client.show_security_group('aaaa').AndReturn({
            'security_group': {
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'name': 'sc1',
                'description': '',
                'security_group_rules': [{
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': 22,
                    'id': 'bbbb',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 22
                }, {
                    'direction': 'ingress',
                    'protocol': 'tcp',
                    'port_range_max': 80,
                    'id': 'cccc',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 80
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
                    'port_range_max': 22,
                    'id': 'eeee',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_group_id': None,
                    'remote_ip_prefix': '10.0.1.0/24',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 22
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
            neutron_exc.NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group_rule('cccc').AndRaise(
            neutron_exc.NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group_rule('dddd').AndRaise(
            neutron_exc.NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group_rule('eeee').AndRaise(
            neutron_exc.NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group_rule('ffff').AndRaise(
            neutron_exc.NeutronClientException(status_code=404))
        neutronclient.Client.delete_security_group('aaaa').AndRaise(
            neutron_exc.NeutronClientException(status_code=404))

        neutronclient.Client.show_security_group('aaaa').AndRaise(
            neutron_exc.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_neutron)

        sg = stack['the_sg']

        self.assertResourceState(sg, 'aaaa')

        scheduler.TaskRunner(sg.delete)()

        sg.state_set(sg.CREATE, sg.COMPLETE, 'to delete again')
        sg.resource_id = 'aaaa'
        stack.delete()

        self.m.VerifyAll()

    def test_security_group_nova_update(self):
        # create script
        sg_name = self.stubout_nova_create_security_group()
        # update script
        nova_sg.SecurityGroupManager.list().MultipleTimes().AndReturn([
            NovaSG(id='1',
                   name='test',
                   description='FAKE_SECURITY_GROUP',
                   rules=[]),
            NovaSG(id='2',
                   name=sg_name,
                   description='HTTPS access',
                   rules=[]),
            NovaSG(id='3',
                   name='test2',
                   description='FAKE_SECURITY_GROUP',
                   rules=[]),
        ])

        # remove deleted groups
        self.stubout_nova_get_security_group(sg_name)
        nova_sgr.SecurityGroupRuleManager.delete(131).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.delete(132).AndReturn(None)

        # create missing groups
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', 443, 443, '0.0.0.0/0', None).AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', None, None, None, '3').AndReturn(None)

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template_nova)
        sg = stack['the_sg']
        self.assertResourceState(sg, utils.PhysName('test_stack', 'the_sg'))

        # make updated template
        props = copy.deepcopy(sg.properties.data)
        props['SecurityGroupIngress'] = [
            {'IpProtocol': 'tcp',
             'FromPort': '22',
             'ToPort': '22',
             'CidrIp': '0.0.0.0/0'},
            {'IpProtocol': 'tcp',
             'FromPort': '443',
             'ToPort': '443',
             'CidrIp': '0.0.0.0/0'},
            {'IpProtocol': 'tcp',
             'SourceSecurityGroupName': 'test2'},
            {'IpProtocol': 'icmp',
             'SourceSecurityGroupId': '1'},
        ]
        after = rsrc_defn.ResourceDefinition(sg.name, sg.type(), props)

        scheduler.TaskRunner(sg.update, after)()

        self.assertEqual((sg.UPDATE, sg.COMPLETE), sg.state)
        self.m.VerifyAll()

    def test_security_group_neutron_update(self):
        # create script
        self.stubout_neutron_create_security_group()

        # update script
        # delete old not needed rules
        self.stubout_neutron_get_security_group()
        neutronclient.Client.delete_security_group_rule(
            'bbbb').InAnyOrder().AndReturn(None)
        neutronclient.Client.delete_security_group_rule(
            'dddd').InAnyOrder().AndReturn(None)
        neutronclient.Client.delete_security_group_rule(
            'eeee').InAnyOrder().AndReturn(None)

        # create missing rules
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 443,
                'ethertype': 'IPv4',
                'port_range_max': 443,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).InAnyOrder().AndReturn({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 443,
                'ethertype': 'IPv4',
                'port_range_max': 443,
                'protocol': 'tcp',
                'security_group_id': 'aaaa',
                'id': 'bbbb'
            }
        })
        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': 'zzzz',
                'remote_ip_prefix': None,
                'port_range_min': None,
                'ethertype': 'IPv4',
                'port_range_max': None,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).InAnyOrder().AndReturn({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_group_id': 'zzzz',
                'remote_ip_prefix': None,
                'port_range_min': None,
                'ethertype': 'IPv4',
                'port_range_max': None,
                'protocol': 'tcp',
                'security_group_id': 'aaaa',
                'id': 'dddd'
            }
        })

        neutronclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).InAnyOrder().AndReturn({
            'security_group_rule': {
                'direction': 'egress',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa',
                'id': 'eeee'
            }
        })

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template_neutron)
        sg = stack['the_sg']
        self.assertResourceState(sg, 'aaaa')

        # make updated template
        props = copy.deepcopy(sg.properties.data)
        props['SecurityGroupIngress'] = [
            {'IpProtocol': 'tcp',
             'FromPort': '80',
             'ToPort': '80',
             'CidrIp': '0.0.0.0/0'},
            {'IpProtocol': 'tcp',
             'FromPort': '443',
             'ToPort': '443',
             'CidrIp': '0.0.0.0/0'},
            {'IpProtocol': 'tcp',
             'SourceSecurityGroupId': 'zzzz'},
        ]
        props['SecurityGroupEgress'] = [
            {'IpProtocol': 'tcp',
             'FromPort': '22',
             'ToPort': '22',
             'CidrIp': '0.0.0.0/0'},
            {'SourceSecurityGroupName': 'xxxx'},
        ]
        after = rsrc_defn.ResourceDefinition(sg.name, sg.type(), props)
        scheduler.TaskRunner(sg.update, after)()

        self.assertEqual((sg.UPDATE, sg.COMPLETE), sg.state)

        self.m.VerifyAll()

    @mock.patch.object(security_group.SecurityGroup, 'is_using_neutron')
    def test_security_group_refid_rsrc_name(self, mock_using_neutron):
        mock_using_neutron.return_value = False
        t = template_format.parse(self.test_template_nova)
        stack = utils.parse_stack(t)
        rsrc = stack['the_sg']
        rsrc.id = '123'
        rsrc.uuid = '9bfb9456-3fe8-41f4-b318-9dba18eeef74'
        rsrc.action = 'CREATE'
        expected = '%s-%s-%s' % (rsrc.stack.name,
                                 rsrc.name,
                                 short_id.get_id(rsrc.uuid))
        self.assertEqual(expected, rsrc.FnGetRefId())

    @mock.patch.object(security_group.SecurityGroup, 'is_using_neutron')
    def test_security_group_refid_rsrc_id(self, mock_using_neutron):
        mock_using_neutron.return_value = True
        t = template_format.parse(self.test_template_nova)
        stack = utils.parse_stack(t)
        rsrc = stack['the_sg']
        rsrc.resource_id = 'phy-rsrc-id'
        self.assertEqual('phy-rsrc-id', rsrc.FnGetRefId())

    def test_security_group_refid_convg_cache_data(self):
        t = template_format.parse(self.test_template_nova)
        cache_data = {'the_sg': {
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        }}
        stack = utils.parse_stack(t, cache_data=cache_data)
        rsrc = stack['the_sg']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())
