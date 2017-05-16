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

from neutronclient.common import exceptions as neutron_exc
from neutronclient.v2_0 import client as neutronclient

from heat.common import template_format
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils

NovaSG = collections.namedtuple('NovaSG',
                                ' '.join([
                                    'name',
                                    'id',
                                    'rules',
                                    'description',
                                ]))


class SecurityGroupTest(common.HeatTestCase):

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
        self.m.StubOutWithMock(neutronclient.Client, 'create_security_group')
        self.m.StubOutWithMock(
            neutronclient.Client, 'create_security_group_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'show_security_group')
        self.m.StubOutWithMock(
            neutronclient.Client, 'delete_security_group_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_security_group')
        self.m.StubOutWithMock(neutronclient.Client, 'update_security_group')
        self.patchobject(resource.Resource, 'is_using_neutron',
                         return_value=True)

    def mock_no_neutron(self):
        self.patchobject(resource.Resource, 'is_using_neutron',
                         return_value=False)

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

    def test_security_group_neutron_update_with_empty_rules(self):
        # create script
        self.stubout_neutron_create_security_group()

        # update script
        # delete old not needed rules
        self.stubout_neutron_get_security_group()
        neutronclient.Client.delete_security_group_rule(
            'eeee').InAnyOrder().AndReturn(None)
        neutronclient.Client.delete_security_group_rule(
            'ffff').InAnyOrder().AndReturn(None)

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template_neutron)
        sg = stack['the_sg']
        self.assertResourceState(sg, 'aaaa')

        # make updated template
        props = copy.deepcopy(sg.properties.data)
        del props['SecurityGroupEgress']
        after = rsrc_defn.ResourceDefinition(sg.name, sg.type(), props)
        scheduler.TaskRunner(sg.update, after)()

        self.assertEqual((sg.UPDATE, sg.COMPLETE), sg.state)

        self.m.VerifyAll()
