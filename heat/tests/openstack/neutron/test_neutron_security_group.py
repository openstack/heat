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

import mock

from neutronclient.common import exceptions as neutron_exc
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils


class SecurityGroupTest(common.HeatTestCase):

    test_template = '''
heat_template_version: 2015-04-30
resources:
  the_sg:
    type: OS::Neutron::SecurityGroup
    properties:
      description: HTTP and SSH access
      rules:
      - port_range_min: 22
        port_range_max: 22
        remote_ip_prefix: 0.0.0.0/0
        protocol: tcp
      - port_range_min: 80
        port_range_max: 80
        protocol: tcp
        remote_ip_prefix: 0.0.0.0/0
      - remote_mode: remote_group_id
        remote_group_id: wwww
        protocol: tcp
      - direction: egress
        port_range_min: 22
        port_range_max: 22
        protocol: tcp
        remote_ip_prefix: 10.0.1.0/24
      - direction: egress
        remote_mode: remote_group_id
        remote_group_id: xxxx
      - direction: egress
        remote_mode: remote_group_id
'''

    test_template_update = '''
heat_template_version: 2015-04-30
resources:
  the_sg:
    type: OS::Neutron::SecurityGroup
    properties:
      description: SSH access for private network
      name: myrules
      rules:
      - port_range_min: 22
        port_range_max: 22
        remote_ip_prefix: 10.0.0.10/24
        protocol: tcp
'''

    test_template_validate = '''
heat_template_version: 2015-04-30
resources:
  the_sg:
    type: OS::Neutron::SecurityGroup
    properties:
      name: default
'''

    def setUp(self):
        super(SecurityGroupTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

        def lookup(client, lookup_type, name, cmd_resource):
            return name

        self.patchobject(neutronV20, 'find_resourceid_by_name_or_id',
                         side_effect=lookup)
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_stack(self, templ):
        t = template_format.parse(templ)
        self.stack = self.parse_stack(t)
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

    def test_security_group(self):

        show_created = {'security_group': {
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
                'remote_group_id': 'xxxx',
                'remote_ip_prefix': None,
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'port_range_min': None
            }, {
                'direction': 'egress',
                'protocol': None,
                'port_range_max': None,
                'id': 'gggg',
                'ethertype': 'IPv4',
                'security_group_id': 'aaaa',
                'remote_group_id': 'aaaa',
                'remote_ip_prefix': None,
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'port_range_min': None
            }],
            'id': 'aaaa'}
        }

        # create script
        sg_name = utils.PhysName('test_stack', 'the_sg')
        self.mockclient.create_security_group.return_value = {
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
        }

        self.mockclient.create_security_group_rule.side_effect = [
            {
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
            },
            {
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
            },
            {
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
            },
            {
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
            },
            {
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
            },
            {
                'security_group_rule': {
                    'direction': 'egress',
                    'remote_group_id': 'aaaa',
                    'remote_ip_prefix': None,
                    'port_range_min': None,
                    'ethertype': 'IPv4',
                    'port_range_max': None,
                    'protocol': None,
                    'security_group_id': 'aaaa',
                    'id': 'gggg'
                }
            },
            {
                'security_group_rule': {
                    'direction': 'egress',
                    'remote_group_id': None,
                    'remote_ip_prefix': None,
                    'port_range_min': None,
                    'ethertype': 'IPv4',
                    'port_range_max': None,
                    'protocol': None,
                    'security_group_id': 'aaaa',
                    'id': 'hhhh'
                }
            },
            {
                'security_group_rule': {
                    'direction': 'egress',
                    'remote_group_id': None,
                    'remote_ip_prefix': None,
                    'port_range_min': None,
                    'ethertype': 'IPv6',
                    'port_range_max': None,
                    'protocol': None,
                    'security_group_id': 'aaaa',
                    'id': 'iiii'
                }
            },
            {
                'security_group_rule': {
                    'direction': 'ingress',
                    'remote_group_id': None,
                    'remote_ip_prefix': '10.0.0.10/24',
                    'port_range_min': '22',
                    'ethertype': 'IPv4',
                    'port_range_max': '22',
                    'protocol': 'tcp',
                    'security_group_id': 'aaaa',
                    'id': 'jjjj'
                }
            },
        ]

        self.mockclient.show_security_group.side_effect = [
            {
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
            },
            show_created,
            {
                'security_group': {
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'name': 'sc1',
                    'description': '',
                    'security_group_rules': [],
                    'id': 'aaaa'
                }
            },
            show_created,
        ]
        self.mockclient.delete_security_group_rule.return_value = None

        # update script
        self.mockclient.update_security_group.return_value = {
            'security_group': {
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'name': 'myrules',
                'description': 'SSH access for private network',
                'security_group_rules': [],
                'id': 'aaaa'
            }
        }

        # delete script
        self.mockclient.delete_security_group.return_value = None

        stack = self.create_stack(self.test_template)

        sg = stack['the_sg']
        self.assertResourceState(sg, 'aaaa')

        updated_tmpl = template_format.parse(self.test_template_update)
        updated_stack = utils.parse_stack(updated_tmpl)
        stack.update(updated_stack)

        stack.delete()

        self.mockclient.create_security_group.assert_called_once_with({
            'security_group': {
                'name': sg_name,
                'description': 'HTTP and SSH access'
            }
        })
        self.mockclient.create_security_group_rule.assert_has_calls([
            mock.call({
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
            }),
            mock.call({
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
            }),
            mock.call({
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
            }),
            mock.call({
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
            }),
            mock.call({
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
            }),
            mock.call({
                'security_group_rule': {
                    'direction': 'egress',
                    'remote_group_id': 'aaaa',
                    'remote_ip_prefix': None,
                    'port_range_min': None,
                    'ethertype': 'IPv4',
                    'port_range_max': None,
                    'protocol': None,
                    'security_group_id': 'aaaa'
                }
            }),
            mock.call({
                'security_group_rule': {
                    'direction': 'egress',
                    'ethertype': 'IPv4',
                    'security_group_id': 'aaaa',
                }
            }),
            mock.call({
                'security_group_rule': {
                    'direction': 'egress',
                    'ethertype': 'IPv6',
                    'security_group_id': 'aaaa',
                }
            }),
            mock.call({
                'security_group_rule': {
                    'direction': 'ingress',
                    'remote_group_id': None,
                    'remote_ip_prefix': '10.0.0.10/24',
                    'port_range_min': '22',
                    'ethertype': 'IPv4',
                    'port_range_max': '22',
                    'protocol': 'tcp',
                    'security_group_id': 'aaaa'
                }
            }),
        ])
        self.mockclient.show_security_group.assert_called_with('aaaa')
        self.mockclient.delete_security_group_rule.assert_has_calls([
            mock.call('aaaa-1'),
            mock.call('aaaa-2'),
            # update script
            mock.call('bbbb'),
            mock.call('cccc'),
            mock.call('dddd'),
            mock.call('eeee'),
            mock.call('ffff'),
            mock.call('gggg'),
            # delete script
            mock.call('bbbb'),
            mock.call('cccc'),
            mock.call('dddd'),
            mock.call('eeee'),
            mock.call('ffff'),
            mock.call('gggg'),
        ])
        self.mockclient.update_security_group.assert_called_once_with(
            'aaaa',
            {'security_group': {
                'description': 'SSH access for private network',
                'name': 'myrules'}}
        )
        self.mockclient.delete_security_group.assert_called_once_with('aaaa')

    def test_security_group_exception(self):
        # create script
        sg_name = utils.PhysName('test_stack', 'the_sg')
        self.mockclient.create_security_group.return_value = {
            'security_group': {
                'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                'name': sg_name,
                'description': 'HTTP and SSH access',
                'security_group_rules': [],
                'id': 'aaaa'
            }
        }
        self.mockclient.create_security_group_rule.side_effect = [
            neutron_exc.Conflict,
            neutron_exc.Conflict,
            neutron_exc.Conflict,
            neutron_exc.Conflict,
            neutron_exc.Conflict,
            neutron_exc.Conflict,
        ]

        self.mockclient.show_security_group.side_effect = [
            {
                'security_group': {
                    'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                    'name': sg_name,
                    'description': 'HTTP and SSH access',
                    'security_group_rules': [],
                    'id': 'aaaa'
                }
            },
            # delete script
            {
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
                        'remote_ip_prefix': 'xxxx',
                        'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                        'port_range_min': None
                    }, {
                        'direction': 'egress',
                        'protocol': None,
                        'port_range_max': None,
                        'id': 'gggg',
                        'ethertype': 'IPv4',
                        'security_group_id': 'aaaa',
                        'remote_group_id': None,
                        'remote_ip_prefix': 'aaaa',
                        'tenant_id': 'f18ca530cc05425e8bac0a5ff92f7e88',
                        'port_range_min': None
                    }],
                    'id': 'aaaa'}
            },
            neutron_exc.NeutronClientException(status_code=404),
        ]

        # delete script
        self.mockclient.delete_security_group_rule.side_effect = (
            neutron_exc.NeutronClientException(status_code=404))
        self.mockclient.delete_security_group.side_effect = (
            neutron_exc.NeutronClientException(status_code=404))

        stack = self.create_stack(self.test_template)

        sg = stack['the_sg']

        self.assertResourceState(sg, 'aaaa')

        scheduler.TaskRunner(sg.delete)()

        sg.state_set(sg.CREATE, sg.COMPLETE, 'to delete again')
        sg.resource_id = 'aaaa'
        stack.delete()

        self.mockclient.create_security_group.assert_called_once_with({
            'security_group': {
                'name': sg_name,
                'description': 'HTTP and SSH access'
            }
        })
        self.mockclient.create_security_group_rule.assert_has_calls([
            mock.call({
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
            }),
            mock.call({
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
            }),
            mock.call({
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
            }),
            mock.call({
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
            }),
            mock.call({
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
            }),
            mock.call({
                'security_group_rule': {
                    'direction': 'egress',
                    'remote_group_id': 'aaaa',
                    'remote_ip_prefix': None,
                    'port_range_min': None,
                    'ethertype': 'IPv4',
                    'port_range_max': None,
                    'protocol': None,
                    'security_group_id': 'aaaa'
                }
            }),
        ])
        self.mockclient.show_security_group.assert_called_with('aaaa')
        self.mockclient.delete_security_group_rule.assert_has_calls([
            mock.call('bbbb'),
            mock.call('cccc'),
            mock.call('dddd'),
            mock.call('eeee'),
            mock.call('ffff'),
            mock.call('gggg'),
        ])
        self.mockclient.delete_security_group.assert_called_with('aaaa')

    def test_security_group_validate(self):
        stack = self.create_stack(self.test_template_validate)
        sg = stack['the_sg']
        ex = self.assertRaises(exception.StackValidationFailed, sg.validate)
        self.assertEqual(
            'Security groups cannot be assigned the name "default".',
            ex.message)
