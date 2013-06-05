# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Licensed under the Apache License, Version 2.0 (the 'License'); you may
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

from heat.engine import clients
from heat.common import context
from heat.common import template_format
from heat.engine import parser
from heat.engine import resource
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db
from heat.tests.v1_1 import fakes
from heat.tests import utils
from heat.tests.utils import stack_delete_after

from novaclient.v1_1 import security_groups as nova_sg
from novaclient.v1_1 import security_group_rules as nova_sgr
from quantumclient.common.exceptions import QuantumClientException
from quantumclient.v2_0 import client as quantumclient

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
          FromPort: 22
          ToPort: 22
          CidrIp: 0.0.0.0/0
        - IpProtocol: tcp
          FromPort : 80
          ToPort : 80
          CidrIp : 0.0.0.0/0
'''

    test_template_quantum = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_sg:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: HTTP and SSH access
      VpcId: aaaa
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 22
          ToPort: 22
          CidrIp: 0.0.0.0/0
        - IpProtocol: tcp
          FromPort : 80
          ToPort : 80
          CidrIp : 0.0.0.0/0
      SecurityGroupEgress:
        - IpProtocol: tcp
          FromPort: 22
          ToPort: 22
          CidrIp: 10.0.1.0/24
'''

    def setUp(self):
        super(SecurityGroupTest, self).setUp()
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        self.m.StubOutWithMock(nova_sgr.SecurityGroupRuleManager, 'create')
        self.m.StubOutWithMock(nova_sgr.SecurityGroupRuleManager, 'delete')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'create')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'delete')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'get')
        self.m.StubOutWithMock(nova_sg.SecurityGroupManager, 'list')
        setup_dummy_db()
        self.m.StubOutWithMock(quantumclient.Client, 'create_security_group')
        self.m.StubOutWithMock(
            quantumclient.Client, 'create_security_group_rule')
        self.m.StubOutWithMock(quantumclient.Client, 'show_security_group')
        self.m.StubOutWithMock(
            quantumclient.Client, 'delete_security_group_rule')
        self.m.StubOutWithMock(quantumclient.Client, 'delete_security_group')

    def create_stack(self, template):
        t = template_format.parse(template)
        self.stack = self.parse_stack(t)
        self.assertEqual(None, self.stack.create())
        return self.stack

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

    def assertResourceState(self, rsrc, ref_id, metadata={}):
        self.assertEqual(None, rsrc.validate())
        self.assertEqual(rsrc.CREATE_COMPLETE, rsrc.state)
        self.assertEqual(ref_id, rsrc.FnGetRefId())
        self.assertEqual(metadata, dict(rsrc.metadata))

    @stack_delete_after
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
            2, 'tcp', 22, 22, '0.0.0.0/0').AndReturn(None)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', 80, 80, '0.0.0.0/0').AndReturn(None)

        # delete script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
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
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(130).AndReturn(None)
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(131).AndReturn(None)
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.delete(2).AndReturn(None)

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_nova)

        sg = stack['the_sg']
        self.assertRaises(resource.UpdateReplace, sg.handle_update, {}, {}, {})

        self.assertResourceState(sg, utils.PhysName('test_stack', 'the_sg'))

        stack.delete()
        self.m.VerifyAll()

    @stack_delete_after
    def test_security_group_nova_exception(self):
        #create script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        sg_name = utils.PhysName('test_stack', 'the_sg')
        nova_sg.SecurityGroupManager.list().AndReturn([NovaSG(
            id=2,
            name=sg_name,
            description='HTTP and SSH access',
            rules=[],
        )])

        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', 22, 22, '0.0.0.0/0').AndRaise(
                clients.novaclient.exceptions.BadRequest(
                    400, 'Rule already exists'))
        nova_sgr.SecurityGroupRuleManager.create(
            2, 'tcp', 80, 80, '0.0.0.0/0').AndReturn(
                clients.novaclient.exceptions.BadRequest(
                    400, 'Rule already exists'))

        # delete script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
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
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(130).AndRaise(
            clients.novaclient.exceptions.NotFound('goneburger'))
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sgr.SecurityGroupRuleManager.delete(131).AndRaise(
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

        self.assertEqual(None, sg.delete())

        sg.state_set(sg.CREATE_COMPLETE, 'to delete again')
        sg.resource_id = 2
        stack.delete()

        self.m.VerifyAll()

    @stack_delete_after
    def test_security_group_quantum(self):
        #create script
        sg_name = utils.PhysName('test_stack', 'the_sg')
        quantumclient.Client.create_security_group({
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

        quantumclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
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
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa',
                'id': 'bbbb'
            }
        })
        quantumclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
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
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 80,
                'ethertype': 'IPv4',
                'port_range_max': 80,
                'protocol': 'tcp',
                'security_group_id': 'aaaa',
                'id': 'cccc'
            }
        })
        quantumclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'egress',
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
                'remote_ip_prefix': '10.0.1.0/24',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa',
                'id': 'dddd'
            }
        })

        # delete script
        quantumclient.Client.show_security_group('aaaa').AndReturn({
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
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 80
                }, {
                    'direction': 'egress',
                    'protocol': 'tcp',
                    'port_range_max': 22,
                    'id': 'dddd',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_ip_prefix': '10.0.1.0/24',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 22
                }],
                'id': 'aaaa'}})
        quantumclient.Client.delete_security_group_rule('bbbb').AndReturn(None)
        quantumclient.Client.delete_security_group_rule('cccc').AndReturn(None)
        quantumclient.Client.delete_security_group_rule('dddd').AndReturn(None)
        quantumclient.Client.delete_security_group('aaaa').AndReturn(None)

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_quantum)

        sg = stack['the_sg']
        self.assertRaises(resource.UpdateReplace, sg.handle_update, {}, {}, {})

        self.assertResourceState(sg, 'aaaa')

        stack.delete()
        self.m.VerifyAll()

    @stack_delete_after
    def test_security_group_quantum_exception(self):
        #create script
        sg_name = utils.PhysName('test_stack', 'the_sg')
        quantumclient.Client.create_security_group({
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

        quantumclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            QuantumClientException(status_code=409))
        quantumclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'ingress',
                'remote_ip_prefix': '0.0.0.0/0',
                'port_range_min': 80,
                'ethertype': 'IPv4',
                'port_range_max': 80,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            QuantumClientException(status_code=409))
        quantumclient.Client.create_security_group_rule({
            'security_group_rule': {
                'direction': 'egress',
                'remote_ip_prefix': '10.0.1.0/24',
                'port_range_min': 22,
                'ethertype': 'IPv4',
                'port_range_max': 22,
                'protocol': 'tcp',
                'security_group_id': 'aaaa'
            }
        }).AndRaise(
            QuantumClientException(status_code=409))

        # delete script
        quantumclient.Client.show_security_group('aaaa').AndReturn({
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
                    'remote_ip_prefix': '0.0.0.0/0',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 80
                }, {
                    'direction': 'egress',
                    'protocol': 'tcp',
                    'port_range_max': 22,
                    'id': 'dddd',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                    'remote_ip_prefix': '10.0.1.0/24',
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'port_range_min': 22
                }],
                'id': 'aaaa'}})
        quantumclient.Client.delete_security_group_rule('bbbb').AndRaise(
            QuantumClientException(status_code=404))
        quantumclient.Client.delete_security_group_rule('cccc').AndRaise(
            QuantumClientException(status_code=404))
        quantumclient.Client.delete_security_group_rule('dddd').AndRaise(
            QuantumClientException(status_code=404))
        quantumclient.Client.delete_security_group('aaaa').AndRaise(
            QuantumClientException(status_code=404))

        quantumclient.Client.show_security_group('aaaa').AndRaise(
            QuantumClientException(status_code=404))

        self.m.ReplayAll()
        stack = self.create_stack(self.test_template_quantum)

        sg = stack['the_sg']
        self.assertRaises(resource.UpdateReplace, sg.handle_update, {}, {}, {})

        self.assertResourceState(sg, 'aaaa')

        self.assertEqual(None, sg.delete())

        sg.state_set(sg.CREATE_COMPLETE, 'to delete again')
        sg.resource_id = 'aaaa'
        stack.delete()

        self.m.VerifyAll()
