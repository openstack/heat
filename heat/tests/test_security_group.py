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

import collections

from heat.engine import clients
from heat.common import context
from heat.common import template_format
from heat.engine import parser
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db
from heat.tests.v1_1 import fakes

from novaclient.v1_1 import security_groups as nova_sg
from novaclient.v1_1 import security_group_rules as nova_sgr

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

    def assertResourceState(self, resource, ref_id, metadata={}):
        self.assertEqual(None, resource.validate())
        self.assertEqual(resource.CREATE_COMPLETE, resource.state)
        self.assertEqual(ref_id, resource.FnGetRefId())
        self.assertEqual(metadata, dict(resource.metadata))

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
        nova_sg.SecurityGroupManager.create(
            'test_stack.the_sg',
            'HTTP and SSH access').AndReturn(NovaSG(
                id=2,
                name='test_stack.the_sg',
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
            name='test_stack.the_sg',
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
                "id": 130
            }, {
                "from_port": 80,
                "group": {},
                "ip_protocol": "tcp",
                "to_port": 80,
                "parent_group_id": 2,
                "ip_range": {
                    "cidr": "0.0.0.0/0"
                },
                "id": 131
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
        self.assertEqual(sg.UPDATE_REPLACE, sg.handle_update({}))

        self.assertResourceState(sg, 'the_sg')

        stack.delete()
        self.m.VerifyAll()

    def test_security_group_nova_exception(self):
        #create script
        clients.OpenStackClients.nova('compute').AndReturn(self.fc)
        nova_sg.SecurityGroupManager.list().AndReturn([NovaSG(
            id=2,
            name='test_stack.the_sg',
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
            name='test_stack.the_sg',
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
                "id": 130
            }, {
                "from_port": 80,
                "group": {},
                "ip_protocol": "tcp",
                "to_port": 80,
                "parent_group_id": 2,
                "ip_range": {
                    "cidr": "0.0.0.0/0"
                },
                "id": 131
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
        self.assertEqual(sg.UPDATE_REPLACE, sg.handle_update({}))

        self.assertResourceState(sg, 'the_sg')

        self.assertEqual(None, sg.delete())

        sg.state_set(sg.CREATE_COMPLETE, 'to delete again')
        sg.resource_id = 2
        stack.delete()

        self.m.VerifyAll()
