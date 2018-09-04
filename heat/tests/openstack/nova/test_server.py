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
import contextlib
import copy
import mock

from keystoneauth1 import exceptions as ks_exceptions
from neutronclient.v2_0 import client as neutronclient
from novaclient import exceptions as nova_exceptions
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
import requests
import six
from six.moves.urllib import parse as urlparse

from heat.common import exception
from heat.common.i18n import _
from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import heat_plugin
from heat.engine.clients.os import neutron
from heat.engine.clients.os import nova
from heat.engine.clients.os import swift
from heat.engine.clients.os import zaqar
from heat.engine import environment
from heat.engine import resource
from heat.engine.resources.openstack.nova import server as servers
from heat.engine.resources.openstack.nova import server_network_mixin
from heat.engine.resources import scheduler_hints as sh
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.objects import resource_data as resource_data_object
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils

wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "key_name" : {
      "Description" : "key_name",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "OS::Nova::Server",
      "Properties": {
        "image" : "F18-x86_64-gold",
        "flavor"   : "m1.large",
        "key_name"        : "test",
        "user_data"       : "wordpress"
      }
    }
  }
}
'''

ns_template = '''
heat_template_version: 2015-04-30
resources:
  server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      user_data: {get_file: a_file}
      networks: [{'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}]
'''

with_port_template = '''
heat_template_version: 2015-04-30
resources:
  port:
    type: OS::Neutron::Port
    properties:
      network: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
  server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.small
      networks:
        - port: {get_resource: port}
          fixed_ip: 10.0.0.99
'''

bdm_v2_template = '''
heat_template_version: 2015-04-30
resources:
  server:
    type: OS::Nova::Server
    properties:
      flavor: m1.tiny
      block_device_mapping_v2:
        - device_name: vda
          delete_on_termination: true
          image_id: F17-x86_64-gold
'''

subnet_template = '''
heat_template_version: 2013-05-23
resources:
  server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      networks:
      - { network: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' }
  subnet:
    type: OS::Neutron::Subnet
    properties:
      network: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
  subnet_unreferenced:
    type: OS::Neutron::Subnet
    properties:
      network: 'bbccbbcc-bbcc-bbcc-bbcc-bbccbbccbbcc'
'''

multi_subnet_template = '''
heat_template_version: 2013-05-23
resources:
  server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      networks:
      - network: {get_resource: network}
  network:
    type: OS::Neutron::Net
    properties:
      name: NewNetwork
  subnet1:
    type: OS::Neutron::Subnet
    properties:
      network: {get_resource: network}
      name: NewSubnet1
  subnet2:
    type: OS::Neutron::Subnet
    properties:
      network: {get_resource: network}
      name: NewSubnet2
'''

no_subnet_template = '''
heat_template_version: 2013-05-23
resources:
  server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
  subnet:
    type: OS::Neutron::Subnet
    properties:
      network: 12345
'''

tmpl_server_with_network_id = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Nova::Server
    properties:
      flavor: m1.small
      image: F17-x86_64-gold
      networks:
        - network: 4321
"""

tmpl_server_with_sub_secu_group = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Nova::Server
    properties:
      flavor: m1.small
      image: F17-x86_64-gold
      networks:
        - subnet: 2a60cbaa-3d33-4af6-a9ce-83594ac546fc
      security_groups:
        - my_seg
"""

server_with_sw_config_personality = """
heat_template_version: 2014-10-16
resources:
  swconfig:
    type: OS::Heat::SoftwareConfig
    properties:
      config: |
        #!/bin/bash
        echo -e "test"
  server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      personality: { /tmp/test: { get_attr: [swconfig, config]}}
"""


def create_fake_iface(port=None, net=None, mac=None, ip=None, subnet=None):
    class fake_interface(object):
        def __init__(self, port_id, net_id, mac_addr, fixed_ip, subnet_id):
            self.port_id = port_id
            self.net_id = net_id
            self.mac_addr = mac_addr
            self.fixed_ips = [{'ip_address': fixed_ip, 'subnet_id': subnet_id}]

    return fake_interface(port, net, mac, ip, subnet)


class ServerStatus(object):
    def __init__(self, server, statuses):
        self._server = server
        self._status = iter(statuses)

    def __call__(self, server_id):
        try:
            self._server.status = next(self._status)
        except StopIteration:
            raise AssertionError('Unexpected call to servers.get()')
        return self._server


class ServersTest(common.HeatTestCase):
    def setUp(self):
        super(ServersTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.limits = mock.Mock()
        self.limits.absolute = self._limits_absolute()
        self.mock_flavor = mock.Mock(ram=4, disk=4)
        self.mock_image = mock.Mock(min_ram=1, min_disk=1, status='ACTIVE')

        def flavor_side_effect(*args):
            return 2 if args[0] == 'm1.small' else 1

        def image_side_effect(*args):
            return 2 if args[0] == 'F17-x86_64-gold' else 1

        self.patchobject(nova.NovaClientPlugin, 'find_flavor_by_name_or_id',
                         side_effect=flavor_side_effect)
        self.patchobject(glance.GlanceClientPlugin, 'find_image_by_name_or_id',
                         side_effect=image_side_effect)

        self.port_show = self.patchobject(neutronclient.Client,
                                          'show_port')
        self.subnet_show = self.patchobject(neutronclient.Client,
                                            'show_subnet')
        self.network_show = self.patchobject(neutronclient.Client,
                                             'show_network')

    def _limits_absolute(self):
        max_personality = mock.Mock()
        max_personality.name = 'maxPersonality'
        max_personality.value = 5
        max_personality_size = mock.Mock()
        max_personality_size.name = 'maxPersonalitySize'
        max_personality_size.value = 10240
        max_server_meta = mock.Mock()
        max_server_meta.name = 'maxServerMeta'
        max_server_meta.value = 3
        yield max_personality
        yield max_personality_size
        yield max_server_meta

    def _setup_test_stack(self, stack_name, test_templ=wp_template):
        t = template_format.parse(test_templ)
        files = {}
        if test_templ == ns_template:
            files = {'a_file': 'stub'}
        templ = template.Template(t,
                                  env=environment.Environment(
                                      {'key_name': 'test'}),
                                  files=files)
        stack = parser.Stack(utils.dummy_context(region_name="RegionOne"),
                             stack_name, templ,
                             stack_id=uuidutils.generate_uuid(),
                             stack_user_project_id='8888')
        return templ, stack

    def _prepare_server_check(self, status='ACTIVE'):
        templ, self.stack = self._setup_test_stack('server_check')
        server = self.fc.servers.list()[1]
        server.status = status
        res = self.stack['WebServer']
        res.state_set(res.CREATE, res.COMPLETE)
        res.client = mock.Mock()
        res.client().servers.get.return_value = server
        return res

    def test_check(self):
        res = self._prepare_server_check()
        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

    def test_check_fail(self):
        res = self._prepare_server_check()
        res.client().servers.get.side_effect = Exception('boom')

        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(res.check))
        self.assertIn('boom', six.text_type(exc))
        self.assertEqual((res.CHECK, res.FAILED), res.state)

    def test_check_not_active(self):
        res = self._prepare_server_check(status='FOO')
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(res.check))
        self.assertIn('FOO', six.text_type(exc))

    def _get_test_template(self, stack_name, server_name=None,
                           image_id=None):
        tmpl, stack = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties'][
            'image'] = image_id or 'CentOS 5.2'
        tmpl.t['Resources']['WebServer']['Properties'][
            'flavor'] = '256 MB Server'

        if server_name is not None:
            tmpl.t['Resources']['WebServer']['Properties'][
                'name'] = server_name

        return tmpl, stack

    def _setup_test_server(self, return_server, name, image_id=None,
                           override_name=False, stub_create=True,
                           networks=None):
        stack_name = '%s_s' % name

        def _mock_find_id(resource, name_or_id, cmd_resource=None):
            return name_or_id

        mock_find = self.patchobject(neutron.NeutronClientPlugin,
                                     'find_resourceid_by_name_or_id')
        mock_find.side_effect = _mock_find_id

        server_name = str(name) if override_name else None
        tmpl, self.stack = self._get_test_template(stack_name, server_name,
                                                   image_id)
        props = tmpl.t['Resources']['WebServer']['Properties']
        # set old_networks for server
        if networks is not None:
            props['networks'] = networks
        self.server_props = props
        resource_defns = tmpl.resource_definitions(self.stack)
        server = servers.Server(str(name), resource_defns['WebServer'],
                                self.stack)

        self.patchobject(server, 'store_external_ports')
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        if stub_create:
            self.patchobject(self.fc.servers, 'create',
                             return_value=return_server)
            # mock check_create_complete innards
            self.patchobject(self.fc.servers, 'get',
                             return_value=return_server)
        return server

    def _create_test_server(self, return_server, name, override_name=False,
                            stub_create=True, networks=None):
        server = self._setup_test_server(return_server, name,
                                         stub_create=stub_create,
                                         networks=networks)
        scheduler.TaskRunner(server.create)()
        return server

    def test_subnet_dependency_by_network_id(self):
        templ, stack = self._setup_test_stack('subnet-test',
                                              subnet_template)
        server_rsrc = stack['server']
        subnet_rsrc = stack['subnet']
        deps = []
        server_rsrc.add_explicit_dependencies(deps)
        server_rsrc.add_dependencies(deps)
        self.assertEqual(4, len(deps))
        self.assertEqual(subnet_rsrc, deps[3])
        self.assertNotIn(stack['subnet_unreferenced'], deps)

    def test_subnet_dependency_unknown_network_id(self):
        # The use case here is creating a network + subnets + server
        # from within one stack
        templ, stack = self._setup_test_stack('subnet-test',
                                              multi_subnet_template)
        server_rsrc = stack['server']
        subnet1_rsrc = stack['subnet1']
        subnet2_rsrc = stack['subnet2']
        deps = []
        server_rsrc.add_explicit_dependencies(deps)
        server_rsrc.add_dependencies(deps)
        self.assertEqual(8, len(deps))
        self.assertIn(subnet1_rsrc, deps)
        self.assertIn(subnet2_rsrc, deps)

    def test_subnet_nodeps(self):
        templ, stack = self._setup_test_stack('subnet-test',
                                              no_subnet_template)
        server_rsrc = stack['server']
        subnet_rsrc = stack['subnet']
        deps = []
        server_rsrc.add_explicit_dependencies(deps)
        server_rsrc.add_dependencies(deps)
        self.assertEqual(2, len(deps))
        self.assertNotIn(subnet_rsrc, deps)

    def test_server_create(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        return_server._info['os_collect_config'] = {}
        server_name = 'test_server_create'
        stack_name = '%s_s' % server_name
        server = self._create_test_server(return_server, server_name)
        self.patchobject(nova.NovaClientPlugin, 'is_version_supported',
                         return_value=True)

        # this makes sure the auto increment worked on server creation
        self.assertGreater(server.id, 0)

        interfaces = [create_fake_iface(port='1234',
                                        mac='fa:16:3e:8c:22:aa',
                                        ip='4.5.6.7'),
                      create_fake_iface(port='5678',
                                        mac='fa:16:3e:8c:33:bb',
                                        ip='5.6.9.8'),
                      create_fake_iface(port='1013',
                                        mac='fa:16:3e:8c:44:cc',
                                        ip='10.13.12.13')]

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        self.patchobject(return_server, 'interface_list',
                         return_value=interfaces)
        self.patchobject(self.fc.servers, 'tag_list', return_value=['test'])

        self.port_show.return_value = {
            'port': {'id': '1234',
                     'network_id': 'the_network',
                     'fixed_ips': [{
                         'ip_address': '4.5.6.7',
                         'subnet_id': 'the_subnet'}]
                     }
        }
        subnet_dict = {
            'subnet': {
                'name': 'subnet_name',
                'cidr': '10.0.0.0/24',
                'allocation_pools': [{'start': '10.0.0.2',
                                      'end': u'10.0.0.254'}],
                'gateway_ip': '10.0.0.1',
                'id': 'the_subnet',
                'network_id': 'the_network'
            }
        }
        network_dict = {
            'network': {
                'name': 'network_name',
                'mtu': 1500,
                'subnets': [subnet_dict['subnet']['id']],
                'id': 'the_network'
            }
        }
        self.subnet_show.return_value = subnet_dict
        self.network_show.return_value = network_dict

        public_ip = return_server.networks['public'][0]
        self.assertEqual('1234',
                         server.FnGetAtt('addresses')['public'][0]['port'])
        self.assertEqual('5678',
                         server.FnGetAtt('addresses')['public'][1]['port'])
        self.assertEqual(public_ip,
                         server.FnGetAtt('addresses')['public'][0]['addr'])
        self.assertEqual(public_ip,
                         server.FnGetAtt('networks')['public'][0])

        private_ip = return_server.networks['private'][0]
        self.assertEqual('1013',
                         server.FnGetAtt('addresses')['private'][0]['port'])
        self.assertEqual(private_ip,
                         server.FnGetAtt('addresses')['private'][0]['addr'])
        self.assertEqual([subnet_dict['subnet']],
                         server.FnGetAtt('addresses')['private'][0]['subnets'])
        self.assertEqual(network_dict['network'],
                         server.FnGetAtt('addresses')['private'][0]['network'])
        self.assertEqual(private_ip,
                         server.FnGetAtt('networks')['private'][0])

        self.assertEqual(return_server._info, server.FnGetAtt('show'))
        self.assertEqual('sample-server2', server.FnGetAtt('instance_name'))
        self.assertEqual('192.0.2.0', server.FnGetAtt('accessIPv4'))
        self.assertEqual('::babe:4317:0A83', server.FnGetAtt('accessIPv6'))

        expected_name = utils.PhysName(stack_name, server.name)
        self.assertEqual(expected_name, server.FnGetAtt('name'))
        self.assertEqual(['test'], server.FnGetAtt('tags'))
        # test with unsupported version
        self.patchobject(nova.NovaClientPlugin, 'is_version_supported',
                         return_value=False)
        if server.attributes._resolved_values.get('tags'):
            del server.attributes._resolved_values['tags']
        self.assertIsNone(server.FnGetAtt('tags'))
        self.assertEqual({}, server.FnGetAtt('os_collect_config'))

    def test_server_network_subnet_address_attr_port_not_found(self):
        return_server = self.fc.servers.list()[1]
        server_name = 'network-subnet-attr-server'
        server = self._create_test_server(return_server, server_name)
        interfaces = [create_fake_iface(port='1234',
                                        mac='fa:16:3e:8c:22:aa',
                                        ip='4.5.6.7')]
        self.patchobject(return_server, 'interface_list',
                         return_value=interfaces)
        self.port_show.side_effect = neutron.exceptions.NotFound()
        self.assertEqual(None,
                         server.FnGetAtt('addresses')['private'][0]['subnets'])
        self.assertEqual(None,
                         server.FnGetAtt('addresses')['private'][0]['network'])

    def test_server_create_metadata(self):
        stack_name = 'create_metadata_test_stack'
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl['Resources']['WebServer']['Properties'][
            'metadata'] = {'a': 1}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('create_metadata_test_server',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        mock_create = self.patchobject(self.fc.servers, 'create',
                                       return_value=return_server)
        scheduler.TaskRunner(server.create)()
        args, kwargs = mock_create.call_args
        self.assertEqual({'a': "1"}, kwargs['meta'])

    def test_server_create_with_subnet_security_group(self):
        stack_name = 'server_with_subnet_security_group'
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        (tmpl, stack) = self._setup_test_stack(
            stack_name, test_templ=tmpl_server_with_sub_secu_group)

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_with_sub_secu',
                                resource_defns['server'], stack)
        mock_find = self.patchobject(
            neutron.NeutronClientPlugin,
            'find_resourceid_by_name_or_id',
            return_value='2a60cbaa-3d33-4af6-a9ce-83594ac546fc')

        sec_uuids = ['86c0f8ae-23a8-464f-8603-c54113ef5467']
        self.patchobject(neutron.NeutronClientPlugin,
                         'get_secgroup_uuids', return_value=sec_uuids)
        self.patchobject(server, 'store_external_ports')
        self.patchobject(neutron.NeutronClientPlugin,
                         'network_id_from_subnet_id',
                         return_value='05d8e681-4b37-4570-bc8d-810089f706b2')
        mock_create_port = self.patchobject(
            neutronclient.Client, 'create_port')

        mock_create = self.patchobject(
            self.fc.servers, 'create', return_value=return_server)

        scheduler.TaskRunner(server.create)()

        kwargs = {'network_id': '05d8e681-4b37-4570-bc8d-810089f706b2',
                  'fixed_ips': [
                      {'subnet_id': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}],
                  'security_groups': sec_uuids,
                  'name': 'server_with_sub_secu-port-0',
                  }
        mock_create_port.assert_called_with({'port': kwargs})
        self.assertEqual(1, mock_find.call_count)
        args, kwargs = mock_create.call_args
        self.assertEqual({}, kwargs['meta'])

    def test_server_create_with_str_network(self):
        stack_name = 'server_with_str_network'
        return_server = self.fc.servers.list()[1]
        (tmpl, stack) = self._setup_test_stack(stack_name)
        mock_nc = self.patchobject(nova.NovaClientPlugin, 'client',
                                   return_value=self.fc)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id')

        props = tmpl['Resources']['WebServer']['Properties']
        props['networks'] = [{'allocate_network': 'none'}]
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')
        create_mock = self.patchobject(self.fc.servers, 'create',
                                       return_value=return_server)
        scheduler.TaskRunner(server.create)()
        mock_nc.assert_called_with()
        self.assertEqual(3, mock_nc.call_count)
        self.assertEqual('none', create_mock.call_args[1]['nics'])

    def test_server_create_with_image_id(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server_name = 'test_server_create_image_id'
        server = self._setup_test_server(return_server,
                                         server_name,
                                         override_name=True)
        server.resource_id = '1234'

        interfaces = [create_fake_iface(port='1234',
                                        mac='fa:16:3e:8c:22:aa',
                                        ip='4.5.6.7'),
                      create_fake_iface(port='5678',
                                        mac='fa:16:3e:8c:33:bb',
                                        ip='5.6.9.8'),
                      create_fake_iface(port='1013',
                                        mac='fa:16:3e:8c:44:cc',
                                        ip='10.13.12.13')]

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        self.patchobject(return_server, 'interface_list',
                         return_value=interfaces)
        self.patchobject(return_server, 'interface_detach')
        self.patchobject(return_server, 'interface_attach')

        public_ip = return_server.networks['public'][0]
        self.assertEqual('1234',
                         server.FnGetAtt('addresses')['public'][0]['port'])
        self.assertEqual('5678',
                         server.FnGetAtt('addresses')['public'][1]['port'])
        self.assertEqual(public_ip,
                         server.FnGetAtt('addresses')['public'][0]['addr'])
        self.assertEqual(public_ip,
                         server.FnGetAtt('networks')['public'][0])

        private_ip = return_server.networks['private'][0]
        self.assertEqual('1013',
                         server.FnGetAtt('addresses')['private'][0]['port'])
        self.assertEqual(private_ip,
                         server.FnGetAtt('addresses')['private'][0]['addr'])
        self.assertEqual(private_ip,
                         server.FnGetAtt('networks')['private'][0])

        self.assertEqual(server_name, server.FnGetAtt('name'))

    def test_server_image_name_err(self):
        stack_name = 'img_name_err'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        mock_image = self.patchobject(glance.GlanceClientPlugin,
                                      'find_image_by_name_or_id')
        self.stub_KeypairConstraint_validate()
        mock_image.side_effect = (
            glance.client_exception.EntityMatchNotFound(
                entity='image', args={'name': 'Slackware'}))
        # Init a server with non exist image name
        tmpl['Resources']['WebServer']['Properties']['image'] = 'Slackware'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(server.create))
        self.assertIn("No image matching {'name': 'Slackware'}.",
                      six.text_type(error))

    def test_server_duplicate_image_name_err(self):
        stack_name = 'img_dup_err'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        mock_image = self.patchobject(glance.GlanceClientPlugin,
                                      'find_image_by_name_or_id')
        self.stub_KeypairConstraint_validate()
        mock_image.side_effect = (
            glance.client_exception.EntityUniqueMatchNotFound(
                entity='image', args='CentOS 5.2'))
        tmpl['Resources']['WebServer']['Properties']['image'] = 'CentOS 5.2'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(server.create))
        self.assertIn('No image unique match found for CentOS 5.2.',
                      six.text_type(error))

    def test_server_create_unexpected_status(self):
        # NOTE(pshchelo) checking is done only on check_create_complete
        # level so not to mock out all delete/retry logic that kicks in
        # on resource create failure
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'cr_unexp_sts')
        return_server.status = 'BOGUS'
        self.patchobject(self.fc.servers, 'get',
                         return_value=return_server)
        e = self.assertRaises(exception.ResourceUnknownStatus,
                              server.check_create_complete,
                              server.resource_id)
        self.assertEqual('Server is not active - Unknown status BOGUS due to '
                         '"Unknown"', six.text_type(e))

    def test_server_create_error_status(self):
        # NOTE(pshchelo) checking is done only on check_create_complete
        # level so not to mock out all delete/retry logic that kicks in
        # on resource create failure
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'cr_err_sts')
        return_server.status = 'ERROR'
        return_server.fault = {
            'message': 'NoValidHost',
            'code': 500,
            'created': '2013-08-14T03:12:10Z'
        }
        self.patchobject(self.fc.servers, 'get',
                         return_value=return_server)
        e = self.assertRaises(exception.ResourceInError,
                              server.check_create_complete,
                              server.resource_id)
        self.assertEqual(
            'Went to status ERROR due to "Message: NoValidHost, Code: 500"',
            six.text_type(e))

    def test_server_create_raw_userdata(self):
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        stack_name = 'raw_userdata_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl['Resources']['WebServer']['Properties'][
            'user_data_format'] = 'RAW'

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        mock_create = self.patchobject(self.fc.servers, 'create',
                                       return_value=return_server)
        scheduler.TaskRunner(server.create)()
        args, kwargs = mock_create.call_args
        self.assertEqual('wordpress', kwargs['userdata'])
        self.assertEqual({}, kwargs['meta'])

    def test_server_create_raw_config_userdata(self):
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        stack_name = 'raw_userdata_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl['Resources']['WebServer']['Properties'][
            'user_data_format'] = 'RAW'
        tmpl['Resources']['WebServer']['Properties'][
            'user_data'] = '8c813873-f6ee-4809-8eec-959ef39acb55'

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        self.rpc_client = mock.MagicMock()
        server._rpc_client = self.rpc_client

        sc = {'config': 'wordpress from config'}
        self.rpc_client.show_software_config.return_value = sc
        mock_create = self.patchobject(self.fc.servers, 'create',
                                       return_value=return_server)
        scheduler.TaskRunner(server.create)()
        args, kwargs = mock_create.call_args
        self.assertEqual('wordpress from config', kwargs['userdata'])
        self.assertEqual({}, kwargs['meta'])

    def test_server_create_raw_config_userdata_None(self):
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        stack_name = 'raw_userdata_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        sc_id = '8c813873-f6ee-4809-8eec-959ef39acb55'
        tmpl['Resources']['WebServer']['Properties'][
            'user_data_format'] = 'RAW'
        tmpl['Resources']['WebServer']['Properties']['user_data'] = sc_id
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        self.rpc_client = mock.MagicMock()
        server._rpc_client = self.rpc_client

        @contextlib.contextmanager
        def exc_filter(*args):
            try:
                yield
            except exception.NotFound:
                pass

        self.rpc_client.ignore_error_by_name.side_effect = exc_filter
        self.rpc_client.show_software_config.side_effect = exception.NotFound
        mock_create = self.patchobject(self.fc.servers, 'create',
                                       return_value=return_server)
        scheduler.TaskRunner(server.create)()
        args, kwargs = mock_create.call_args
        self.assertEqual(sc_id, kwargs['userdata'])
        self.assertEqual({}, kwargs['meta'])

    def _server_create_software_config(self, md=None,
                                       stack_name='software_config_s',
                                       ret_tmpl=False):
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.stack = stack
        self.server_props = tmpl['Resources']['WebServer']['Properties']
        self.server_props['user_data_format'] = 'SOFTWARE_CONFIG'
        if md is not None:
            tmpl['Resources']['WebServer']['Metadata'] = md

        stack.stack_user_project_id = '8888'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')
        self.patchobject(server, 'heat')
        self.patchobject(self.fc.servers, 'create',
                         return_value=return_server)
        scheduler.TaskRunner(server.create)()

        self.assertEqual('4567', server.access_key)
        self.assertEqual('8901', server.secret_key)
        self.assertEqual('1234', server._get_user_id())
        self.assertEqual('POLL_SERVER_CFN',
                         server.properties.get('software_config_transport'))

        self.assertTrue(stack.access_allowed('4567', 'WebServer'))
        self.assertFalse(stack.access_allowed('45678', 'WebServer'))
        self.assertFalse(stack.access_allowed('4567', 'wWebServer'))
        if ret_tmpl:
            return server, tmpl
        else:
            return server

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'url_for')
    def test_server_create_software_config(self, fake_url):
        fake_url.return_value = 'http://ip:8000/v1'
        server = self._server_create_software_config()

        self.assertEqual({
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': 'http://ip:8000/v1/',
                    'path': 'WebServer.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'software_config_s'
                },
                'collectors': ['ec2', 'cfn', 'local']
            },
            'deployments': []
        }, server.metadata_get())

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'url_for')
    def test_resolve_attribute_os_collect_config(self, fake_url):
        fake_url.return_value = 'http://ip/heat-api-cfn/v1'
        server = self._server_create_software_config()

        self.assertEqual({
            'cfn': {
                'access_key_id': '4567',
                'metadata_url': 'http://ip/heat-api-cfn/v1/',
                'path': 'WebServer.Metadata',
                'secret_access_key': '8901',
                'stack_name': 'software_config_s'
            },
            'collectors': ['ec2', 'cfn', 'local']
        }, server.FnGetAtt('os_collect_config'))

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'url_for')
    def test_server_create_software_config_metadata(self, fake_url):
        md = {'os-collect-config': {'polling_interval': 10}}
        fake_url.return_value = 'http://ip/heat-api-cfn/v1'
        server = self._server_create_software_config(md=md)

        self.assertEqual({
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': 'http://ip/heat-api-cfn/v1/',
                    'path': 'WebServer.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'software_config_s'
                },
                'collectors': ['ec2', 'cfn', 'local'],
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def _server_create_software_config_poll_heat(self, md=None):
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        stack_name = 'software_config_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        props = tmpl.t['Resources']['WebServer']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        props['software_config_transport'] = 'POLL_SERVER_HEAT'
        if md is not None:
            tmpl.t['Resources']['WebServer']['Metadata'] = md
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        self.patchobject(self.fc.servers, 'create',
                         return_value=return_server)
        scheduler.TaskRunner(server.create)()
        self.assertEqual('1234', server._get_user_id())

        self.assertTrue(stack.access_allowed('1234', 'WebServer'))
        self.assertFalse(stack.access_allowed('45678', 'WebServer'))
        self.assertFalse(stack.access_allowed('4567', 'wWebServer'))
        return stack, server

    def test_server_create_software_config_poll_heat(self):
        stack, server = self._server_create_software_config_poll_heat()

        self.assertEqual({
            'os-collect-config': {
                'heat': {
                    'auth_url': 'http://server.test:5000/v2.0',
                    'password': server.password,
                    'project_id': '8888',
                    'region_name': 'RegionOne',
                    'resource_name': 'WebServer',
                    'stack_id': 'software_config_s/%s' % stack.id,
                    'user_id': '1234'
                },
                'collectors': ['ec2', 'heat', 'local']
            },
            'deployments': []
        }, server.metadata_get())

    def test_server_create_software_config_poll_heat_metadata(self):
        md = {'os-collect-config': {'polling_interval': 10}}
        stack, server = self._server_create_software_config_poll_heat(md=md)

        self.assertEqual({
            'os-collect-config': {
                'heat': {
                    'auth_url': 'http://server.test:5000/v2.0',
                    'password': server.password,
                    'project_id': '8888',
                    'region_name': 'RegionOne',
                    'resource_name': 'WebServer',
                    'stack_id': 'software_config_s/%s' % stack.id,
                    'user_id': '1234'
                },
                'collectors': ['ec2', 'heat', 'local'],
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def _server_create_software_config_poll_temp_url(self, md=None):
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        stack_name = 'software_config_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        props = tmpl.t['Resources']['WebServer']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        props['software_config_transport'] = 'POLL_TEMP_URL'
        if md is not None:
            tmpl.t['Resources']['WebServer']['Metadata'] = md
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        sc = mock.Mock()
        sc.head_account.return_value = {
            'x-account-meta-temp-url-key': 'secrit'
        }
        sc.url = 'http://192.0.2.2'

        self.patchobject(swift.SwiftClientPlugin, '_create',
                         return_value=sc)
        self.patchobject(self.fc.servers, 'create',
                         return_value=return_server)
        scheduler.TaskRunner(server.create)()
        metadata_put_url = server.data().get('metadata_put_url')
        md = server.metadata_get()
        metadata_url = md['os-collect-config']['request']['metadata_url']
        self.assertNotEqual(metadata_url, metadata_put_url)

        container_name = server.physical_resource_name()
        object_name = server.data().get('metadata_object_name')
        self.assertTrue(uuidutils.is_uuid_like(object_name))
        test_path = '/v1/AUTH_test_tenant_id/%s/%s' % (
            server.physical_resource_name(), object_name)
        self.assertEqual(test_path, urlparse.urlparse(metadata_put_url).path)
        self.assertEqual(test_path, urlparse.urlparse(metadata_url).path)
        sc.put_object.assert_called_once_with(
            container_name, object_name, jsonutils.dumps(md))

        sc.head_container.return_value = {'x-container-object-count': '0'}
        server._delete_temp_url()
        sc.delete_object.assert_called_once_with(container_name, object_name)
        sc.head_container.assert_called_once_with(container_name)
        sc.delete_container.assert_called_once_with(container_name)
        return metadata_url, server

    def test_server_create_software_config_poll_temp_url(self):
        metadata_url, server = (
            self._server_create_software_config_poll_temp_url())

        self.assertEqual({
            'os-collect-config': {
                'request': {
                    'metadata_url': metadata_url
                },
                'collectors': ['ec2', 'request', 'local']
            },
            'deployments': []
        }, server.metadata_get())

    def test_server_create_software_config_poll_temp_url_metadata(self):
        md = {'os-collect-config': {'polling_interval': 10}}
        metadata_url, server = (
            self._server_create_software_config_poll_temp_url(md=md))

        self.assertEqual({
            'os-collect-config': {
                'request': {
                    'metadata_url': metadata_url
                },
                'collectors': ['ec2', 'request', 'local'],
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def _prepare_for_server_create(self, md=None):
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        stack_name = 'software_config_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        props = tmpl.t['Resources']['WebServer']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        props['software_config_transport'] = 'ZAQAR_MESSAGE'
        if md is not None:
            tmpl.t['Resources']['WebServer']['Metadata'] = md
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')
        self.patchobject(self.fc.servers, 'create',
                         return_value=return_server)

        return server, stack

    def _server_create_software_config_zaqar(self, md=None):
        server, stack = self._prepare_for_server_create(md)

        zcc = self.patchobject(zaqar.ZaqarClientPlugin, 'create_for_tenant')
        zc = mock.Mock()
        zcc.return_value = zc
        queue = mock.Mock()
        zc.queue.return_value = queue

        scheduler.TaskRunner(server.create)()

        metadata_queue_id = server.data().get('metadata_queue_id')
        md = server.metadata_get()
        queue_id = md['os-collect-config']['zaqar']['queue_id']
        self.assertEqual(queue_id, metadata_queue_id)

        zc.queue.assert_called_once_with(queue_id)
        queue.post.assert_called_once_with(
            {'body': server.metadata_get(), 'ttl': 3600})

        zc.queue.reset_mock()

        server._delete_queue()

        zc.queue.assert_called_once_with(queue_id)
        zc.queue(queue_id).delete.assert_called_once_with()
        return queue_id, server

    def test_server_create_software_config_zaqar(self):
        queue_id, server = self._server_create_software_config_zaqar()
        self.assertEqual({
            'os-collect-config': {
                'zaqar': {
                    'user_id': '1234',
                    'password': server.password,
                    'auth_url': 'http://server.test:5000/v2.0',
                    'project_id': '8888',
                    'queue_id': queue_id,
                    'region_name': 'RegionOne',
                },
                'collectors': ['ec2', 'zaqar', 'local']
            },
            'deployments': []
        }, server.metadata_get())

    def test_create_delete_no_zaqar_service(self):
        zcc = self.patchobject(zaqar.ZaqarClientPlugin, 'create_for_tenant')
        zcc.side_effect = ks_exceptions.EndpointNotFound
        server, stack = self._prepare_for_server_create()
        creator = scheduler.TaskRunner(server.create)
        self.assertRaises(exception.ResourceFailure, creator)
        self.assertEqual((server.CREATE, server.FAILED), server.state)
        self.assertEqual({
            'os-collect-config': {
                'zaqar': {
                    'user_id': '1234',
                    'password': server.password,
                    'auth_url': 'http://server.test:5000/v2.0',
                    'project_id': '8888',
                    'queue_id': mock.ANY,
                    'region_name': 'RegionOne',
                },
                'collectors': ['ec2', 'zaqar', 'local']
            },
            'deployments': []
        }, server.metadata_get())

        scheduler.TaskRunner(server.delete)()
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)

    def test_server_create_software_config_zaqar_metadata(self):
        md = {'os-collect-config': {'polling_interval': 10}}
        queue_id, server = self._server_create_software_config_zaqar(md=md)
        self.assertEqual({
            'os-collect-config': {
                'zaqar': {
                    'user_id': '1234',
                    'password': server.password,
                    'auth_url': 'http://server.test:5000/v2.0',
                    'project_id': '8888',
                    'queue_id': queue_id,
                    'region_name': 'RegionOne',
                },
                'collectors': ['ec2', 'zaqar', 'local'],
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def test_server_create_default_admin_pass(self):
        return_server = self.fc.servers.list()[1]
        return_server.adminPass = 'autogenerated'
        stack_name = 'admin_pass_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        mock_create = self.patchobject(self.fc.servers, 'create',
                                       return_value=return_server)
        scheduler.TaskRunner(server.create)()
        _, kwargs = mock_create.call_args
        self.assertIsNone(kwargs['admin_pass'])
        self.assertEqual({}, kwargs['meta'])

    def test_server_create_custom_admin_pass(self):
        return_server = self.fc.servers.list()[1]
        return_server.adminPass = 'foo'
        stack_name = 'admin_pass_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties']['admin_pass'] = 'foo'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        mock_create = self.patchobject(self.fc.servers, 'create',
                                       return_value=return_server)
        scheduler.TaskRunner(server.create)()
        _, kwargs = mock_create.call_args
        self.assertEqual('foo', kwargs['admin_pass'])
        self.assertEqual({}, kwargs['meta'])

    def test_server_create_with_stack_scheduler_hints(self):
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        sh.cfg.CONF.set_override('stack_scheduler_hints', True)
        # Unroll _create_test_server, to enable check
        # for addition of heat ids (stack id, resource name)
        stack_name = 'test_server_w_stack_sched_hints_s'
        server_name = 'server_w_stack_sched_hints'
        (t, stack) = self._get_test_template(stack_name, server_name)
        self.patchobject(stack, 'path_in_stack',
                         return_value=[('parent', stack.name)])
        resource_defns = t.resource_definitions(stack)
        server = servers.Server(server_name,
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        # server.uuid is only available once the resource has been added.
        stack.add_resource(server)
        self.assertIsNotNone(server.uuid)

        mock_create = self.patchobject(self.fc.servers, 'create',
                                       return_value=return_server)
        shm = sh.SchedulerHintsMixin
        scheduler_hints = {shm.HEAT_ROOT_STACK_ID: stack.root_stack_id(),
                           shm.HEAT_STACK_ID: stack.id,
                           shm.HEAT_STACK_NAME: stack.name,
                           shm.HEAT_PATH_IN_STACK: [','.join(['parent',
                                                             stack.name])],
                           shm.HEAT_RESOURCE_NAME: server.name,
                           shm.HEAT_RESOURCE_UUID: server.uuid}

        scheduler.TaskRunner(server.create)()
        _, kwargs = mock_create.call_args
        self.assertEqual(scheduler_hints, kwargs['scheduler_hints'])
        self.assertEqual({}, kwargs['meta'])
        # this makes sure the auto increment worked on server creation
        self.assertGreater(server.id, 0)

    def test_check_maximum(self):
        msg = 'test_check_maximum'
        self.assertIsNone(servers.Server._check_maximum(1, 1, msg))
        self.assertIsNone(servers.Server._check_maximum(1000, -1, msg))
        error = self.assertRaises(exception.StackValidationFailed,
                                  servers.Server._check_maximum,
                                  2, 1, msg)
        self.assertEqual(msg, six.text_type(error))

    def test_server_validate(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.assertIsNone(server.validate())

    def test_server_validate_with_bootable_vol(self):
        stack_name = 'srv_val_bootvol'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        self.stub_VolumeConstraint_validate()
        # create a server with bootable volume
        web_server = tmpl.t['Resources']['WebServer']
        del web_server['Properties']['image']

        def create_server(device_name):
            web_server['Properties']['block_device_mapping'] = [{
                "device_name": device_name,
                "volume_id": "5d7e27da-6703-4f7e-9f94-1f67abef734c",
                "delete_on_termination": False
            }]
            resource_defns = tmpl.resource_definitions(stack)
            server = servers.Server('server_with_bootable_volume',
                                    resource_defns['WebServer'], stack)
            return server

        server = create_server(u'vda')
        self.assertIsNone(server.validate())
        server = create_server('vda')
        self.assertIsNone(server.validate())
        server = create_server('vdb')
        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertEqual('Neither image nor bootable volume is specified for '
                         'instance server_with_bootable_volume',
                         six.text_type(ex))

        web_server['Properties']['image'] = ''
        server = create_server('vdb')
        self.assertIsNone(server.validate())

    def test_server_validate_with_nova_keypair_resource(self):
        stack_name = 'srv_val_test'
        nova_keypair_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Resources" : {
    "WebServer": {
      "Type": "OS::Nova::Server",
      "Properties": {
        "image" : "F17-x86_64-gold",
        "flavor"   : "m1.large",
        "key_name"        : { "Ref": "SSHKey" },
        "user_data"       : "wordpress"
      }
    },
    "SSHKey": {
      "Type": "OS::Nova::KeyPair",
      "Properties": {
        "name": "my_key"
      }
    }
  }
}
'''
        self.patchobject(nova.NovaClientPlugin, 'has_extension',
                         return_value=True)
        t = template_format.parse(nova_keypair_template)
        templ = template.Template(t)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        stack = parser.Stack(utils.dummy_context(), stack_name, templ,
                             stack_id=uuidutils.generate_uuid())
        resource_defns = templ.resource_definitions(stack)
        server = servers.Server('server_validate_test',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.assertIsNone(server.validate())

    def test_server_validate_with_invalid_ssh_key(self):
        stack_name = 'srv_val_test'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        web_server = tmpl['Resources']['WebServer']
        # Make the ssh key have an invalid name
        web_server['Properties']['key_name'] = 'test2'

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        error = self.assertRaises(exception.StackValidationFailed,
                                  server.validate)
        self.assertEqual(
            "Property error: Resources.WebServer.Properties.key_name: "
            "Error validating value 'test2': The Key (test2) could not "
            "be found.", six.text_type(error))

    def test_server_validate_software_config_invalid_meta(self):
        stack_name = 'srv_val_test'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        web_server = tmpl['Resources']['WebServer']
        web_server['Properties']['user_data_format'] = 'SOFTWARE_CONFIG'
        web_server['Metadata'] = {'deployments': 'notallowed'}

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        error = self.assertRaises(exception.StackValidationFailed,
                                  server.validate)
        self.assertEqual(
            "deployments key not allowed in resource metadata "
            "with user_data_format of SOFTWARE_CONFIG", six.text_type(error))

    def test_server_validate_with_networks(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.stub_KeypairConstraint_validate()

        network_name = 'public'
        # create a server with 'uuid' and 'network' properties
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'uuid': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
              'network': network_name}])

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)
        self.stub_NetworkConstraint_validate()
        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)

        self.assertIn("Cannot define the following properties at "
                      "the same time: networks.network, networks.uuid",
                      six.text_type(ex))

    def test_server_validate_with_network_empty_ref(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'network': ''}])

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id')
        self.assertIsNone(server.validate())

    def test_server_validate_with_only_fixed_ip(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        # create a server with 'uuid' and 'network' properties
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'fixed_ip': '10.0.0.99'}])
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id')
        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertIn(_('One of the properties "network", "port", '
                        '"allocate_network" or "subnet" should be set '
                        'for the specified network of '
                        'server "%s".') % server.name,
                      six.text_type(ex))

    def test_server_validate_with_network_floating_ip(self):
        stack_name = 'srv_net_floating_ip'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        # create a server with 'uuid' and 'network' properties
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'floating_ip': '172.24.4.14',
              'network': '6b1688bb-18a0-4754-ab05-19daaedc5871'}])
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_net_floating_ip',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id')
        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertIn(_('Property "floating_ip" is not supported if '
                        'only "network" is specified, because the '
                        'corresponding port can not be retrieved.'),
                      six.text_type(ex))

    def test_server_validate_with_networks_str_net(self):
        stack_name = 'srv_networks_str_nets'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        # create a server with 'uuid' and 'network' properties
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'network': '6b1688bb-18a0-4754-ab05-19daaedc5871',
              'allocate_network': 'auto'}])
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_net_list_str',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id')
        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertIn(_('Can not specify "allocate_network" with '
                        'other keys of networks at the same time.'),
                      six.text_type(ex))

    def test_server_validate_port_fixed_ip(self):
        stack_name = 'port_with_fixed_ip'
        (tmpl, stack) = self._setup_test_stack(stack_name,
                                               test_templ=with_port_template)

        resource_defns = tmpl.resource_definitions(stack)

        server = servers.Server('validate_port_reference_fixed_ip',
                                resource_defns['server'], stack)

        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)

        error = self.assertRaises(exception.ResourcePropertyConflict,
                                  server.validate)
        self.assertEqual("Cannot define the following properties at the same "
                         "time: networks/fixed_ip, networks/port.",
                         six.text_type(error))
        # test if the 'port' doesn't reference with non-created resource
        tmpl['Resources']['server']['Properties']['networks'] = (
            [{'port': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
              'fixed_ip': '10.0.0.99'}])
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('with_port_fixed_ip',
                                resource_defns['server'], stack)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id')
        error = self.assertRaises(exception.ResourcePropertyConflict,
                                  server.validate)
        self.assertEqual("Cannot define the following properties at the same "
                         "time: networks/fixed_ip, networks/port.",
                         six.text_type(error))

    def test_server_validate_with_uuid_fixed_ip(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'uuid': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
              'fixed_ip': '10.0.0.99'}])
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id')
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.assertIsNone(server.validate())

    def test_server_validate_with_network_fixed_ip(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'network': 'public',
              'fixed_ip': '10.0.0.99'}])
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id')
        self.assertIsNone(server.validate())

    def test_server_validate_net_security_groups(self):
        # Test that if network 'ports' are assigned security groups are
        # not, because they'll be ignored
        stack_name = 'srv_net_secgroups'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl['Resources']['WebServer']['Properties']['networks'] = [
            {'port': ''}]
        tmpl['Resources']['WebServer']['Properties'][
            'security_groups'] = ['my_security_group']
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_net_security_groups',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id')
        error = self.assertRaises(exception.ResourcePropertyConflict,
                                  server.validate)
        self.assertEqual("Cannot define the following properties at the same "
                         "time: security_groups, networks/port.",
                         six.text_type(error))

    def test_server_delete(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete')
        server.resource_id = '1234'

        # this makes sure the auto increment worked on server creation
        self.assertGreater(server.id, 0)

        side_effect = [server, fakes_nova.fake_exception()]
        self.patchobject(self.fc.servers, 'get', side_effect=side_effect)
        scheduler.TaskRunner(server.delete)()
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)

    def test_server_delete_notfound(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete2')
        server.resource_id = '1234'

        # this makes sure the auto increment worked on server creation
        self.assertGreater(server.id, 0)

        self.patchobject(self.fc.client, 'delete_servers_1234',
                         side_effect=fakes_nova.fake_exception())
        scheduler.TaskRunner(server.delete)()
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)

    def test_server_delete_error(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete')
        server.resource_id = '1234'

        # this makes sure the auto increment worked on server creation
        self.assertGreater(server.id, 0)

        def make_error(*args):
            return_server.status = "ERROR"
            return return_server

        self.patchobject(self.fc.servers, 'get',
                         side_effect=[return_server, return_server,
                                      make_error()])
        resf = self.assertRaises(exception.ResourceFailure,
                                 scheduler.TaskRunner(server.delete))
        self.assertIn("Server %s delete failed" % return_server.name,
                      six.text_type(resf))

    def test_server_delete_error_task_in_progress(self):
        # test server in 'ERROR', but task state in nova is 'deleting'
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete')
        server.resource_id = '1234'

        def make_error(*args):
            return_server.status = "ERROR"
            setattr(return_server, 'OS-EXT-STS:task_state', 'deleting')
            return return_server

        def make_error_done(*args):
            return_server.status = "ERROR"
            setattr(return_server, 'OS-EXT-STS:task_state', None)
            return return_server

        self.patchobject(self.fc.servers, 'get',
                         side_effect=[make_error(),
                                      make_error_done()])
        resf = self.assertRaises(exception.ResourceFailure,
                                 scheduler.TaskRunner(server.delete))
        self.assertIn("Server %s delete failed" % return_server.name,
                      six.text_type(resf))

    def test_server_soft_delete(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete')
        server.resource_id = '1234'

        # this makes sure the auto increment worked on server creation
        self.assertGreater(server.id, 0)

        self.patchobject(self.fc.servers, 'get',
                         side_effect=ServerStatus(return_server,
                                                  [return_server.status,
                                                   return_server.status,
                                                   "SOFT_DELETED",
                                                   "DELETED"]))
        scheduler.TaskRunner(server.delete)()
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)

    def test_server_update_metadata(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')
        ud_tmpl = self._get_test_template('update_stack')[0]
        ud_tmpl.t['Resources']['WebServer']['Metadata'] = {'test': 123}
        resource_defns = ud_tmpl.resource_definitions(server.stack)

        scheduler.TaskRunner(server.update, resource_defns['WebServer'])()
        self.assertEqual({'test': 123}, server.metadata_get())

        ud_tmpl.t['Resources']['WebServer']['Metadata'] = {'test': 456}
        server.t = ud_tmpl.resource_definitions(server.stack)['WebServer']

        self.assertEqual({'test': 123}, server.metadata_get())
        server.metadata_update()
        self.assertEqual({'test': 456}, server.metadata_get())

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'url_for')
    def test_server_update_metadata_software_config(self, fake_url):
        fake_url.return_value = 'http://ip:8000/v1'
        server, ud_tmpl = self._server_create_software_config(
            stack_name='update_meta_sc', ret_tmpl=True)

        expected_md = {
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': 'http://ip:8000/v1/',
                    'path': 'WebServer.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'update_meta_sc'
                },
                'collectors': ['ec2', 'cfn', 'local']
            },
            'deployments': []}
        self.assertEqual(expected_md, server.metadata_get())
        ud_tmpl.t['Resources']['WebServer']['Metadata'] = {'test': 123}
        resource_defns = ud_tmpl.resource_definitions(server.stack)
        scheduler.TaskRunner(server.update, resource_defns['WebServer'])()
        expected_md.update({'test': 123})
        self.assertEqual(expected_md, server.metadata_get())
        server.metadata_update()
        self.assertEqual(expected_md, server.metadata_get())

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'url_for')
    def test_server_update_metadata_software_config_merge(self, fake_url):
        md = {'os-collect-config': {'polling_interval': 10}}
        fake_url.return_value = 'http://ip/heat-api-cfn/v1'
        server, ud_tmpl = self._server_create_software_config(
            stack_name='update_meta_sc', ret_tmpl=True,
            md=md)

        expected_md = {
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': 'http://ip/heat-api-cfn/v1/',
                    'path': 'WebServer.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'update_meta_sc'
                },
                'collectors': ['ec2', 'cfn', 'local'],
                'polling_interval': 10
            },
            'deployments': []}
        self.assertEqual(expected_md, server.metadata_get())
        ud_tmpl.t['Resources']['WebServer']['Metadata'] = {'test': 123}
        resource_defns = ud_tmpl.resource_definitions(server.stack)
        scheduler.TaskRunner(server.update, resource_defns['WebServer'])()
        expected_md.update({'test': 123})
        self.assertEqual(expected_md, server.metadata_get())
        server.metadata_update()
        self.assertEqual(expected_md, server.metadata_get())

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'url_for')
    def test_server_update_software_config_transport(self, fake_url):
        md = {'os-collect-config': {'polling_interval': 10}}
        fake_url.return_value = 'http://ip/heat-api-cfn/v1'
        server = self._server_create_software_config(
            stack_name='update_meta_sc', md=md)

        expected_md = {
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': 'http://ip/heat-api-cfn/v1/',
                    'path': 'WebServer.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'update_meta_sc'
                },
                'collectors': ['ec2', 'cfn', 'local'],
                'polling_interval': 10
            },
            'deployments': []}
        self.assertEqual(expected_md, server.metadata_get())
        sc = mock.Mock()
        sc.head_account.return_value = {
            'x-account-meta-temp-url-key': 'secrit'
        }
        sc.url = 'http://192.0.2.2'
        self.patchobject(swift.SwiftClientPlugin, '_create',
                         return_value=sc)
        update_props = self.server_props.copy()
        update_props['software_config_transport'] = 'POLL_TEMP_URL'
        update_template = server.t.freeze(properties=update_props)

        self.rpc_client = mock.MagicMock()
        server._rpc_client = self.rpc_client
        self.rpc_client.create_software_config.return_value = None
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)

        md = server.metadata_get()
        metadata_url = md['os-collect-config']['request']['metadata_url']
        self.assertTrue(metadata_url.startswith(
            'http://192.0.2.2/v1/AUTH_test_tenant_id/'))

        expected_md = {
            'os-collect-config': {
                'cfn': {
                    'access_key_id': None,
                    'metadata_url': None,
                    'path': None,
                    'secret_access_key': None,
                    'stack_name': None,
                },
                'request': {
                    'metadata_url': 'the_url',
                },
                'collectors': ['ec2', 'request', 'local'],
                'polling_interval': 10
            },
            'deployments': []}
        md['os-collect-config']['request']['metadata_url'] = 'the_url'
        self.assertEqual(expected_md, server.metadata_get())

    def test_update_transport_heat_to_zaqar(self):
        stack, server = self._server_create_software_config_poll_heat()
        password = server.password
        self.assertEqual({
            'os-collect-config': {
                'heat': {
                    'auth_url': 'http://server.test:5000/v2.0',
                    'password': password,
                    'project_id': '8888',
                    'region_name': 'RegionOne',
                    'resource_name': 'WebServer',
                    'stack_id': 'software_config_s/%s' % stack.id,
                    'user_id': '1234'
                },
                'collectors': ['ec2', 'heat', 'local'],
            },
            'deployments': []
        }, server.metadata_get())

        update_props = self.server_props.copy()
        update_props['software_config_transport'] = 'ZAQAR_MESSAGE'
        update_template = server.t.freeze(properties=update_props)
        zcc = self.patchobject(zaqar.ZaqarClientPlugin, 'create_for_tenant')
        zc = mock.Mock()
        zcc.return_value = zc
        queue = mock.Mock()
        zc.queue.return_value = queue

        self.rpc_client = mock.MagicMock()
        server._rpc_client = self.rpc_client
        self.rpc_client.create_software_config.return_value = None
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        password_1 = server.password
        self.assertEqual(password, password_1)
        self.assertEqual({
            'os-collect-config': {
                'zaqar': {
                    'user_id': '1234',
                    'password': password_1,
                    'auth_url': 'http://server.test:5000/v2.0',
                    'project_id': '8888',
                    'queue_id': server.data().get('metadata_queue_id'),
                    'region_name': 'RegionOne',
                },
                'heat': {
                    'auth_url': None,
                    'password': None,
                    'project_id': None,
                    'region_name': None,
                    'resource_name': None,
                    'stack_id': None,
                    'user_id': None
                },
                'collectors': ['ec2', 'zaqar', 'local']
            },
            'deployments': []
        }, server.metadata_get())

    def test_server_update_nova_metadata(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')

        new_meta = {'test': 123}
        self.patchobject(self.fc.servers, 'get',
                         return_value=return_server)
        set_meta_mock = self.patchobject(self.fc.servers, 'set_meta')
        update_props = self.server_props.copy()
        update_props['metadata'] = new_meta
        update_template = server.t.freeze(properties=update_props)
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        set_meta_mock.assert_called_with(
            return_server, server.client_plugin().meta_serialize(new_meta))

    def test_server_update_nova_metadata_complex(self):
        """Test that complex metadata values are correctly serialized to JSON.

        Test that complex metadata values are correctly serialized to JSON when
        sent to Nova.
        """
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')
        self.patchobject(self.fc.servers, 'get',
                         return_value=return_server)
        new_meta = {'test': {'testkey': 'testvalue'}}
        set_meta_mock = self.patchobject(self.fc.servers, 'set_meta')

        # If we're going to call set_meta() directly we
        # need to handle the serialization ourselves.
        update_props = self.server_props.copy()
        update_props['metadata'] = new_meta
        update_template = server.t.freeze(properties=update_props)
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        set_meta_mock.assert_called_with(
            return_server, server.client_plugin().meta_serialize(new_meta))

    def test_server_update_nova_metadata_with_delete(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')

        # part one, add some metadata
        new_meta = {'test': '123', 'this': 'that'}
        self.patchobject(self.fc.servers, 'get',
                         return_value=return_server)
        set_meta_mock = self.patchobject(self.fc.servers, 'set_meta')
        update_props = self.server_props.copy()
        update_props['metadata'] = new_meta
        update_template = server.t.freeze(properties=update_props)
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        set_meta_mock.assert_called_with(
            return_server, server.client_plugin().meta_serialize(new_meta))

        # part two change the metadata (test removing the old key)
        new_meta = {'new_key': 'yeah'}
        # new fake with the correct metadata
        server.resource_id = '56789'

        new_return_server = self.fc.servers.list()[5]
        self.patchobject(self.fc.servers, 'get',
                         return_value=new_return_server)
        del_meta_mock = self.patchobject(self.fc.servers, 'delete_meta')
        update_props = self.server_props.copy()
        update_props['metadata'] = new_meta
        update_template = server.t.freeze(properties=update_props)

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        del_meta_mock.assert_called_with(new_return_server,
                                         ['test', 'this'])
        set_meta_mock.assert_called_with(
            new_return_server, server.client_plugin().meta_serialize(new_meta))

    def test_server_update_server_name(self):
        """Server.handle_update supports changing the name."""
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server = self._create_test_server(return_server,
                                          'srv_update')
        new_name = 'new_name'
        update_props = self.server_props.copy()
        update_props['name'] = new_name
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get',
                         return_value=return_server)
        self.patchobject(return_server, 'update')
        return_server.update(new_name).AndReturn(None)
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)

    def test_server_update_server_admin_password(self):
        """Server.handle_update supports changing the admin password."""
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server = self._create_test_server(return_server,
                                          'change_password')
        new_password = 'new_password'
        update_props = self.server_props.copy()
        update_props['admin_pass'] = new_password
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        self.patchobject(return_server, 'change_password')

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        return_server.change_password.assert_called_once_with(new_password)
        self.assertEqual(1, return_server.change_password.call_count)

    def test_server_get_live_state(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        self.patchobject(nova.NovaClientPlugin, 'is_version_supported',
                         return_value=False)
        server = self._create_test_server(return_server,
                                          'get_live_state_stack')

        server.properties.data['networks'] = [{'network': 'public_id',
                                               'fixed_ip': '5.6.9.8'}]

        iface0 = create_fake_iface(port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   net='public',
                                   ip='5.6.9.8',
                                   mac='fa:16:3e:8c:33:aa')
        iface1 = create_fake_iface(port='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                                   net='public',
                                   ip='4.5.6.7',
                                   mac='fa:16:3e:8c:22:aa')
        iface2 = create_fake_iface(port='cccccccc-cccc-cccc-cccc-cccccccccccc',
                                   net='private',
                                   ip='10.13.12.13',
                                   mac='fa:16:3e:8c:44:cc')
        self.patchobject(return_server, 'interface_list',
                         return_value=[iface0, iface1, iface2])

        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         side_effect=['public_id',
                                      'private_id'])
        reality = server.get_live_state(server.properties.data)

        expected = {'flavor': '1',
                    'image': '2',
                    'name': 'sample-server2',
                    'networks': [
                        {'fixed_ip': '4.5.6.7',
                         'network': 'public',
                         'port': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'},
                        {'fixed_ip': '5.6.9.8',
                         'network': 'public',
                         'port': None},
                        {'fixed_ip': '10.13.12.13',
                         'network': 'private',
                         'port': 'cccccccc-cccc-cccc-cccc-cccccccccccc'}],
                    'metadata': {}}
        self.assertEqual(set(expected.keys()), set(reality.keys()))
        expected_nets = expected.pop('networks')
        reality_nets = reality.pop('networks')
        for net in reality_nets:
            for exp_net in expected_nets:
                if net == exp_net:
                    for key in net:
                        self.assertEqual(exp_net[key], net[key])
                    break

        for key in six.iterkeys(reality):
            self.assertEqual(expected[key], reality[key])

    def test_server_update_server_flavor(self):
        """Tests update server changing the flavor.

        Server.handle_update supports changing the flavor, and makes
        the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'srv_update')
        update_props = self.server_props.copy()
        update_props['flavor'] = 'm1.small'
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get',
                         side_effect=ServerStatus(return_server,
                                                  ['ACTIVE',
                                                   'RESIZE',
                                                   'VERIFY_RESIZE',
                                                   'VERIFY_RESIZE',
                                                   'ACTIVE']))
        mock_post = self.patchobject(self.fc.client,
                                     'post_servers_1234_action',
                                     return_value=(202, None))
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        mock_post.assert_has_calls([
            mock.call(body={'resize': {'flavorRef': '2'}}),
            mock.call(body={'confirmResize': None}),
        ])

    def test_server_update_server_flavor_failed(self):
        """Check raising exception due to resize call failing.

        If the status after a resize is not VERIFY_RESIZE, it means the resize
        call failed, so we raise an explicit error.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'srv_update2')
        update_props = self.server_props.copy()
        update_props['flavor'] = 'm1.small'
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get',
                         side_effect=ServerStatus(return_server,
                                                  ['RESIZE', 'ERROR']))
        mock_post = self.patchobject(self.fc.client,
                                     'post_servers_1234_action',
                                     return_value=(202, None))
        updater = scheduler.TaskRunner(server.update, update_template)
        error = self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual(
            "Error: resources.srv_update2: Resizing to '2' failed, "
            "status 'ERROR'", six.text_type(error))
        self.assertEqual((server.UPDATE, server.FAILED), server.state)
        mock_post.assert_called_once_with(body={'resize': {'flavorRef': '2'}})

    def test_server_update_flavor_resize_has_not_started(self):
        """Test update of server flavor if server resize has not started.

        Server resize is asynchronous operation in nova. So when heat is
        requesting resize and polling the server then the server may still be
        in ACTIVE state. So we need to wait some amount of time till the server
        status becomes RESIZE.
        """
        # create the server for resizing
        server = self.fc.servers.list()[1]
        server.id = '1234'
        server_resource = self._create_test_server(server,
                                                   'resize_server')
        # prepare template with resized server
        update_props = self.server_props.copy()
        update_props['flavor'] = 'm1.small'
        update_template = server_resource.t.freeze(properties=update_props)

        # define status transition when server resize
        # ACTIVE(initial) -> ACTIVE -> RESIZE -> VERIFY_RESIZE

        self.patchobject(self.fc.servers, 'get',
                         side_effect=ServerStatus(server,
                                                  ['ACTIVE',
                                                   'ACTIVE',
                                                   'RESIZE',
                                                   'VERIFY_RESIZE',
                                                   'VERIFY_RESIZE',
                                                   'ACTIVE']))

        mock_post = self.patchobject(self.fc.client,
                                     'post_servers_1234_action',
                                     return_value=(202, None))
        # check that server resize has finished correctly
        scheduler.TaskRunner(server_resource.update, update_template)()
        self.assertEqual((server_resource.UPDATE, server_resource.COMPLETE),
                         server_resource.state)
        mock_post.assert_has_calls([
            mock.call(body={'resize': {'flavorRef': '2'}}),
            mock.call(body={'confirmResize': None}),
        ])

    @mock.patch.object(servers.Server, 'prepare_for_replace')
    def test_server_update_server_flavor_replace(self, mock_replace):
        stack_name = 'update_flvrep'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        server_props = tmpl['Resources']['WebServer']['Properties']
        server_props['flavor_update_policy'] = 'REPLACE'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_server_update_flavor_replace',
                                resource_defns['WebServer'], stack)
        update_props = server_props.copy()
        update_props['flavor'] = 'm1.small'
        update_template = server.t.freeze(properties=update_props)
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    @mock.patch.object(servers.Server, 'prepare_for_replace')
    def test_server_update_server_flavor_policy_update(self, mock_replace):
        stack_name = 'update_flvpol'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_server_update_flavor_replace',
                                resource_defns['WebServer'], stack)

        update_props = tmpl.t['Resources']['WebServer']['Properties'].copy()
        # confirm that when flavor_update_policy is changed during
        # the update then the updated policy is followed for a flavor
        # update
        update_props['flavor_update_policy'] = 'REPLACE'
        update_props['flavor'] = 'm1.small'
        update_template = server.t.freeze(properties=update_props)
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    @mock.patch.object(servers.Server, 'prepare_for_replace')
    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_server_update_server_userdata_replace(self, mock_create,
                                                   mock_replace):
        stack_name = 'update_udatrep'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_update_userdata_replace',
                                resource_defns['WebServer'], stack)

        update_props = tmpl.t['Resources']['WebServer']['Properties'].copy()
        update_props['user_data'] = 'changed'
        update_template = server.t.freeze(properties=update_props)
        server.action = server.CREATE
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_update_failed_server_not_replace(self, mock_create):
        stack_name = 'update_failed_server_not_replace'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('failed_not_replace',
                                resource_defns['WebServer'], stack)
        update_props = tmpl.t['Resources']['WebServer']['Properties'].copy()
        update_props['name'] = 'my_server'
        update_template = server.t.freeze(properties=update_props)
        server.action = server.CREATE
        server.status = server.FAILED
        server.resource_id = '6a953104-b874-44d2-a29a-26e7c367dc5c'
        nova_server = self.fc.servers.list()[1]
        nova_server.status = 'ACTIVE'
        server.client = mock.Mock()
        server.client().servers.get.return_value = nova_server
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)

    @mock.patch.object(servers.Server, 'prepare_for_replace')
    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_server_update_server_userdata_ignore(self, mock_create,
                                                  mock_replace):
        stack_name = 'update_udatignore'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(servers.Server, 'check_update_complete',
                         return_value=True)

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_update_userdata_ignore',
                                resource_defns['WebServer'], stack)

        update_props = tmpl.t['Resources']['WebServer']['Properties'].copy()
        update_props['user_data'] = 'changed'
        update_props['user_data_update_policy'] = 'IGNORE'
        update_template = server.t.freeze(properties=update_props)
        server.action = server.CREATE
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)

    @mock.patch.object(servers.Server, 'prepare_for_replace')
    def test_server_update_image_replace(self, mock_replace):
        stack_name = 'update_imgrep'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties'][
            'image_update_policy'] = 'REPLACE'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_update_image_replace',
                                resource_defns['WebServer'], stack)
        image_id = self.getUniqueString()
        update_props = tmpl.t['Resources']['WebServer']['Properties'].copy()
        update_props['image'] = image_id
        update_template = server.t.freeze(properties=update_props)
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def _test_server_update_image_rebuild(self, status, policy='REBUILD',
                                          password=None):
        # Server.handle_update supports changing the image, and makes
        # the change making a rebuild API call against Nova.
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'srv_updimgrbld')

        new_image = 'F17-x86_64-gold'
        # current test demonstrate updating when image_update_policy was not
        # changed, so image_update_policy will be used from self.properties
        before_props = self.server_props.copy()
        before_props['image_update_policy'] = policy
        server.t = server.t.freeze(properties=before_props)
        server.reparse()

        update_props = before_props.copy()
        update_props['image'] = new_image
        if password:
            update_props['admin_pass'] = password
        update_template = server.t.freeze(properties=update_props)

        mock_rebuild = self.patchobject(self.fc.servers, 'rebuild')

        def get_sideeff(stat):
            def sideeff(*args):
                return_server.status = stat
                return return_server
            return sideeff

        for stat in status:
            self.patchobject(self.fc.servers, 'get',
                             side_effect=get_sideeff(stat))

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)

        if 'REBUILD' == policy:
            mock_rebuild.assert_called_once_with(
                return_server, '2', password=password,
                preserve_ephemeral=False,
                meta={}, files={})
        else:
            mock_rebuild.assert_called_once_with(
                return_server, '2', password=password,
                preserve_ephemeral=True,
                meta={}, files={})

    def test_server_update_image_rebuild_status_rebuild(self):
        # Normally we will see 'REBUILD' first and then 'ACTIVE".
        self._test_server_update_image_rebuild(status=('REBUILD', 'ACTIVE'))

    def test_server_update_image_rebuild_status_active(self):
        # It is possible for us to miss the REBUILD status.
        self._test_server_update_image_rebuild(status=('ACTIVE',))

    def test_server_update_image_rebuild_status_rebuild_keep_ephemeral(self):
        # Normally we will see 'REBUILD' first and then 'ACTIVE".
        self._test_server_update_image_rebuild(
            policy='REBUILD_PRESERVE_EPHEMERAL', status=('REBUILD', 'ACTIVE'))

    def test_server_update_image_rebuild_status_active_keep_ephemeral(self):
        # It is possible for us to miss the REBUILD status.
        self._test_server_update_image_rebuild(
            policy='REBUILD_PRESERVE_EPHEMERAL', status=('ACTIVE',))

    def test_server_update_image_rebuild_with_new_password(self):
        # Normally we will see 'REBUILD' first and then 'ACTIVE".

        self._test_server_update_image_rebuild(password='new_admin_password',
                                               status=('REBUILD', 'ACTIVE'))

    def test_server_update_image_rebuild_failed(self):
        # If the status after a rebuild is not REBUILD or ACTIVE, it means the
        # rebuild call failed, so we raise an explicit error.
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'srv_updrbldfail')

        new_image = 'F17-x86_64-gold'
        # current test demonstrate updating when image_update_policy was not
        # changed, so image_update_policy will be used from self.properties
        before_props = self.server_props.copy()
        before_props['image_update_policy'] = 'REBUILD'
        update_props = before_props.copy()
        update_props['image'] = new_image
        update_template = server.t.freeze(properties=update_props)
        server.t = server.t.freeze(properties=before_props)
        server.reparse()
        mock_rebuild = self.patchobject(self.fc.servers, 'rebuild')

        self.patchobject(self.fc.servers, 'get',
                         side_effect=ServerStatus(return_server,
                                                  ['REBUILD', 'ERROR']))
        updater = scheduler.TaskRunner(server.update, update_template)
        error = self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual(
            "Error: resources.srv_updrbldfail: "
            "Rebuilding server failed, status 'ERROR'",
            six.text_type(error))
        self.assertEqual((server.UPDATE, server.FAILED), server.state)
        mock_rebuild.assert_called_once_with(
            return_server, '2', password=None, preserve_ephemeral=False,
            meta={}, files={})

    def test_server_update_properties(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'update_prop')
        update_props = self.server_props.copy()
        update_props['image'] = 'F17-x86_64-gold'
        update_props['image_update_policy'] = 'REPLACE'
        update_template = server.t.freeze(properties=update_props)
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_server_status_build(self):
        return_server = self.fc.servers.list()[0]
        server = self._setup_test_server(return_server,
                                         'sts_build')
        server.resource_id = '1234'

        def status_active(*args):
            return_server.status = 'ACTIVE'
            return return_server

        self.patchobject(self.fc.servers, 'get',
                         return_value=status_active())
        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

    def test_server_status_suspend_no_resource_id(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_sus1')
        server.resource_id = None

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.suspend))
        self.assertEqual('Error: resources.srv_sus1: '
                         'Cannot suspend srv_sus1, '
                         'resource_id not set',
                         six.text_type(ex))
        self.assertEqual((server.SUSPEND, server.FAILED), server.state)

    def test_server_status_suspend_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_sus2')
        server.resource_id = '1234'
        self.patchobject(self.fc.servers, 'get',
                         side_effect=fakes_nova.fake_exception())
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.suspend))
        self.assertEqual('NotFound: resources.srv_sus2: '
                         'Failed to find server 1234',
                         six.text_type(ex))
        self.assertEqual((server.SUSPEND, server.FAILED), server.state)

    def _test_server_status_suspend(self, name, state=('CREATE', 'COMPLETE')):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server, name)

        server.resource_id = '1234'
        server.state_set(state[0], state[1])

        self.patchobject(return_server, 'suspend')
        self.patchobject(self.fc.servers, 'get',
                         side_effect=ServerStatus(return_server,
                                                  ['ACTIVE',
                                                   'ACTIVE',
                                                   'SUSPENDED']))

        scheduler.TaskRunner(server.suspend)()
        self.assertEqual((server.SUSPEND, server.COMPLETE), server.state)

    def test_server_suspend_in_create_complete(self):
        self._test_server_status_suspend('test_suspend_in_create_complete')

    def test_server_suspend_in_suspend_failed(self):
        self._test_server_status_suspend(
            name='test_suspend_in_suspend_failed',
            state=('SUSPEND', 'FAILED'))

    def test_server_suspend_in_suspend_complete(self):
        self._test_server_status_suspend(
            name='test_suspend_in_suspend_complete',
            state=('SUSPEND', 'COMPLETE'))

    def test_server_status_suspend_unknown_status(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_susp_uk')
        server.resource_id = '1234'

        self.patchobject(return_server, 'suspend')
        self.patchobject(self.fc.servers, 'get',
                         side_effect=ServerStatus(return_server,
                                                  ['ACTIVE',
                                                   'ACTIVE',
                                                   'TRANSMOGRIFIED']))
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.suspend))
        self.assertIsInstance(ex.exc, exception.ResourceUnknownStatus)
        self.assertEqual('Suspend of server %s failed - '
                         'Unknown status TRANSMOGRIFIED '
                         'due to "Unknown"' % return_server.name,
                         six.text_type(ex.exc.message))
        self.assertEqual((server.SUSPEND, server.FAILED), server.state)

    def _test_server_status_resume(self, name, state=('SUSPEND', 'COMPLETE')):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server, name)

        server.resource_id = '1234'
        server.state_set(state[0], state[1])

        self.patchobject(return_server, 'resume')
        self.patchobject(self.fc.servers, 'get',
                         side_effect=ServerStatus(return_server,
                                                  ['SUSPENDED',
                                                   'SUSPENDED',
                                                   'ACTIVE']))

        scheduler.TaskRunner(server.resume)()
        self.assertEqual((server.RESUME, server.COMPLETE), server.state)

    def test_server_resume_in_suspend_complete(self):
        self._test_server_status_resume(
            name='test_resume_in_suspend_complete')

    def test_server_resume_in_resume_failed(self):
        self._test_server_status_resume(
            name='test_resume_in_resume_failed',
            state=('RESUME', 'FAILED'))

    def test_server_resume_in_resume_complete(self):
        self._test_server_status_resume(
            name='test_resume_in_resume_complete',
            state=('RESUME', 'COMPLETE'))

    def test_server_status_resume_no_resource_id(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_susp_norid')

        server.resource_id = None
        server.state_set(server.SUSPEND, server.COMPLETE)
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.resume))
        self.assertEqual('Error: resources.srv_susp_norid: '
                         'Cannot resume srv_susp_norid, '
                         'resource_id not set',
                         six.text_type(ex))
        self.assertEqual((server.RESUME, server.FAILED), server.state)

    def test_server_status_resume_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_res_nf')

        server.resource_id = '1234'
        self.patchobject(self.fc.servers, 'get',
                         side_effect=fakes_nova.fake_exception())

        server.state_set(server.SUSPEND, server.COMPLETE)

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.resume))
        self.assertEqual('NotFound: resources.srv_res_nf: '
                         'Failed to find server 1234',
                         six.text_type(ex))
        self.assertEqual((server.RESUME, server.FAILED), server.state)

    def test_server_status_build_spawning(self):
        self._test_server_status_not_build_active('BUILD(SPAWNING)')

    def test_server_status_hard_reboot(self):
        self._test_server_status_not_build_active('HARD_REBOOT')

    def test_server_status_password(self):
        self._test_server_status_not_build_active('PASSWORD')

    def test_server_status_reboot(self):
        self._test_server_status_not_build_active('REBOOT')

    def test_server_status_rescue(self):
        self._test_server_status_not_build_active('RESCUE')

    def test_server_status_resize(self):
        self._test_server_status_not_build_active('RESIZE')

    def test_server_status_revert_resize(self):
        self._test_server_status_not_build_active('REVERT_RESIZE')

    def test_server_status_shutoff(self):
        self._test_server_status_not_build_active('SHUTOFF')

    def test_server_status_suspended(self):
        self._test_server_status_not_build_active('SUSPENDED')

    def test_server_status_verify_resize(self):
        self._test_server_status_not_build_active('VERIFY_RESIZE')

    def _test_server_status_not_build_active(self, uncommon_status):
        return_server = self.fc.servers.list()[0]
        server = self._setup_test_server(return_server,
                                         'srv_sts_bld')
        server.resource_id = '1234'

        self.patchobject(self.fc.servers, 'get',
                         side_effect=ServerStatus(return_server,
                                                  [uncommon_status,
                                                   'ACTIVE']))

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

    def test_build_nics(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_create')
        self.patchobject(neutronclient.Client, 'create_port',
                         return_value={'port': {'id': '4815162342'}})

        self.assertIsNone(server._build_nics([]))
        self.assertIsNone(server._build_nics(None))
        self.assertEqual([
            {'port-id': 'aaaabbbb', 'net-id': None, 'tag': 'nic1'},
            {'v4-fixed-ip': '192.0.2.0', 'net-id': None}],
            server._build_nics([
                {'port': 'aaaabbbb', 'tag': 'nic1'},
                {'fixed_ip': '192.0.2.0'}]))
        self.assertEqual([{'port-id': 'aaaabbbb', 'net-id': None},
                          {'port-id': 'aaaabbbb', 'net-id': None}],
                         server._build_nics([{'port': 'aaaabbbb',
                                              'fixed_ip': '192.0.2.0'},
                                             {'port': 'aaaabbbb',
                                              'fixed_ip': '2002::2'}]))
        self.assertEqual([{'port-id': 'aaaabbbb', 'net-id': None},
                          {'v6-fixed-ip': '2002::2', 'net-id': None}],
                         server._build_nics([{'port': 'aaaabbbb'},
                                             {'fixed_ip': '2002::2'}]))

        self.assertEqual([{'net-id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}],
                         server._build_nics(
                             [{'network':
                               'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}]))

    def test_server_network_errors(self):
        stack_name = 'net_err'
        (tmpl, stack) = self._setup_test_stack(stack_name,
                                               test_templ=ns_template)

        resolver = self.patchobject(neutron.NeutronClientPlugin,
                                    'find_resourceid_by_name_or_id')

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server',
                                resource_defns['server'], stack)

        resolver.side_effect = neutron.exceptions.NotFound()
        server.reparse()
        self.assertRaises(ValueError, server.properties.get, 'networks')
        resolver.side_effect = neutron.exceptions.NeutronClientNoUniqueMatch()
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.create))
        self.assertIn('use an ID to be more specific.', six.text_type(ex))

    def test_server_without_ip_address(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'
        server = self._create_test_server(return_server,
                                          'wo_ipaddr')
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value=None)
        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        self.patchobject(return_server, 'interface_list', return_value=[])
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        self.assertEqual({'empty_net': []}, server.FnGetAtt('addresses'))
        self.assertEqual({'empty_net': []}, server.FnGetAtt('networks'))
        self.assertEqual(0, mock_detach.call_count)
        self.assertEqual(0, mock_attach.call_count)

    def test_build_block_device_mapping(self):
        self.assertIsNone(servers.Server._build_block_device_mapping([]))
        self.assertIsNone(servers.Server._build_block_device_mapping(None))

        self.assertEqual({
            'vda': '1234::',
            'vdb': '1234:snap:',
        }, servers.Server._build_block_device_mapping([
            {'device_name': 'vda', 'volume_id': '1234'},
            {'device_name': 'vdb', 'snapshot_id': '1234'},
        ]))

        self.assertEqual({
            'vdc': '1234::10',
            'vdd': '1234:snap::True'
        }, servers.Server._build_block_device_mapping([
            {
                'device_name': 'vdc',
                'volume_id': '1234',
                'volume_size': 10
            },
            {
                'device_name': 'vdd',
                'snapshot_id': '1234',
                'delete_on_termination': True
            }
        ]))

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_block_device_mapping_volume_size_valid_int(self,
                                                                 mock_create):
        stack_name = 'val_vsize_valid'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': 10}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.stub_VolumeConstraint_validate()
        self.assertIsNone(server.validate())

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_block_device_mapping_volume_size_valid_str(self,
                                                                 mock_create):
        stack_name = 'val_vsize_valid'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': '10'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.stub_VolumeConstraint_validate()
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.assertIsNone(server.validate())

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_bd_mapping_volume_size_invalid_str(self, mock_create):
        stack_name = 'val_vsize_invalid'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': '10a'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.stub_VolumeConstraint_validate()
        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertIn("Value '10a' is not an integer", six.text_type(exc))

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_conflict_block_device_mapping_props(self, mock_create):
        stack_name = 'val_blkdev1'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vdb', 'snapshot_id': '1234',
                'volume_id': '1234'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.stub_VolumeConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.assertRaises(exception.ResourcePropertyConflict, server.validate)

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_insufficient_block_device_mapping_props(self,
                                                              mock_create):
        stack_name = 'val_blkdev2'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vdb', 'volume_size': 1,
                'delete_on_termination': True}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        msg = ("Either volume_id or snapshot_id must be specified "
               "for device mapping vdb")
        self.assertEqual(msg, six.text_type(ex))

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_block_device_mapping_with_empty_ref(self, mock_create):
        stack_name = 'val_blkdev2'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '',
                'volume_size': '10'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.stub_VolumeConstraint_validate()
        self.assertIsNone(server.validate())

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_without_image_or_bootable_volume(self, mock_create):
        stack_name = 'val_imgvol'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        del tmpl['Resources']['WebServer']['Properties']['image']
        bdm = [{'device_name': 'vdb', 'volume_id': '1234'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.stub_VolumeConstraint_validate()
        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        msg = ('Neither image nor bootable volume is specified '
               'for instance %s' % server.name)
        self.assertEqual(msg, six.text_type(ex))

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_invalid_image_status(self, mock_create):
        stack_name = 'test_stack'
        tmpl, stack = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_inactive_image',
                                resource_defns['WebServer'], stack)

        mock_image = mock.Mock(min_ram=2, status='sdfsdf')
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=mock_image)
        error = self.assertRaises(exception.StackValidationFailed,
                                  server.validate)
        self.assertEqual(
            'Image status is required to be active not sdfsdf.',
            six.text_type(error))

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_insufficient_ram_flavor(self, mock_create):
        stack_name = 'test_stack'
        tmpl, stack = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_insufficient_ram_flavor',
                                resource_defns['WebServer'], stack)

        mock_image = mock.Mock(min_ram=100, status='active')
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        error = self.assertRaises(exception.StackValidationFailed,
                                  server.validate)
        self.assertEqual(
            'Image F18-x86_64-gold requires 100 minimum ram. Flavor m1.large '
            'has only 4.',
            six.text_type(error))

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_image_flavor_not_found(self, mock_create):
        stack_name = 'test_stack'
        tmpl, stack = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('image_not_found',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         side_effect=[
                             glance.client_exception.EntityMatchNotFound,
                             self.mock_image])
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         side_effect=nova.exceptions.NotFound(''))
        self.assertIsNone(server.validate())
        self.assertIsNone(server.validate())

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_insufficient_disk_flavor(self, mock_create):
        stack_name = 'test_stack'
        tmpl, stack = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_insufficient_disk_flavor',
                                resource_defns['WebServer'], stack)

        mock_image = mock.Mock(min_ram=1, status='active', min_disk=100)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        error = self.assertRaises(exception.StackValidationFailed,
                                  server.validate)
        self.assertEqual(
            'Image F18-x86_64-gold requires 100 GB minimum disk space. '
            'Flavor m1.large has only 4 GB.',
            six.text_type(error))

    def test_build_block_device_mapping_v2(self):
        self.assertIsNone(servers.Server._build_block_device_mapping_v2([]))
        self.assertIsNone(servers.Server._build_block_device_mapping_v2(None))

        self.assertEqual([{
            'uuid': '1', 'source_type': 'volume',
            'destination_type': 'volume', 'boot_index': 0,
            'delete_on_termination': False}
        ], servers.Server._build_block_device_mapping_v2([
            {'volume_id': '1'}
        ]))

        self.assertEqual([{
            'uuid': '1', 'source_type': 'snapshot',
            'destination_type': 'volume', 'boot_index': 0,
            'delete_on_termination': False}
        ], servers.Server._build_block_device_mapping_v2([
            {'snapshot_id': '1'}
        ]))

        self.assertEqual([{
            'uuid': '1', 'source_type': 'image',
            'destination_type': 'volume', 'boot_index': 0,
            'delete_on_termination': False}
        ], servers.Server._build_block_device_mapping_v2([
            {'image': '1'}
        ]))

        self.assertEqual([{
            'source_type': 'blank', 'destination_type': 'local',
            'boot_index': -1, 'delete_on_termination': True,
            'guest_format': 'swap', 'volume_size': 1}
        ], servers.Server._build_block_device_mapping_v2([
            {'swap_size': 1}
        ]))

        self.assertEqual([], servers.Server._build_block_device_mapping_v2([
            {'device_name': ''}
        ]))

        self.assertEqual([
            {'source_type': 'blank',
             'destination_type': 'local',
             'boot_index': -1,
             'delete_on_termination': True,
             'volume_size': 1,
             'guest_format': 'ext4'}
        ], servers.Server._build_block_device_mapping_v2([
            {'ephemeral_size': 1,
             'ephemeral_format': 'ext4'}
        ]))

    def test_block_device_mapping_v2_image_resolve(self):
        (tmpl, stack) = self._setup_test_stack('mapping',
                                               test_templ=bdm_v2_template)
        resource_defns = tmpl.resource_definitions(stack)
        self.server = servers.Server('server',
                                     resource_defns['server'], stack)
        self.server.translate_properties(self.server.properties)
        self.assertEqual('2',
                         self.server.properties['block_device_mapping_v2'][
                             0]['image'])

    def test_block_device_mapping_v2_image_prop_conflict(self):
        test_templ = bdm_v2_template + "\n          image: F17-x86_64-gold"
        (tmpl, stack) = self._setup_test_stack('mapping',
                                               test_templ=test_templ)
        resource_defns = tmpl.resource_definitions(stack)
        msg = ("Cannot define the following "
               "properties at the same time: block_device_mapping_v2.image, "
               "block_device_mapping_v2.image_id")
        server = servers.Server('server', resource_defns['server'], stack)
        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertIn(msg, six.text_type(exc))

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_with_both_blk_dev_map_and_blk_dev_map_v2(self,
                                                               mock_create):
        stack_name = 'invalid_stack'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': '10'}]
        bdm_v2 = [{'volume_id': '1'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        wsp['block_device_mapping_v2'] = bdm_v2
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.stub_VolumeConstraint_validate()
        exc = self.assertRaises(exception.ResourcePropertyConflict,
                                server.validate)
        msg = ('Cannot define the following properties at the same time: '
               'block_device_mapping, block_device_mapping_v2.')
        self.assertEqual(msg, six.text_type(exc))

    def _test_validate_bdm_v2(self, stack_name, bdm_v2, with_image=True,
                              error_msg=None, raise_exc=None):
        tmpl, stack = self._setup_test_stack(stack_name)
        if not with_image:
            del tmpl['Resources']['WebServer']['Properties']['image']
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping_v2'] = bdm_v2

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.stub_VolumeConstraint_validate()
        if raise_exc:
            ex = self.assertRaises(raise_exc, server.validate)
            self.assertIn(error_msg, six.text_type(ex))
        else:
            self.assertIsNone(server.validate())

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_conflict_block_device_mapping_v2_props(self,
                                                             mock_create):
        stack_name = 'val_blkdev2'
        bdm_v2 = [{'volume_id': '1', 'snapshot_id': 2}]
        error_msg = ('Cannot define the following properties at '
                     'the same time: volume_id, snapshot_id')
        self.stub_SnapshotConstraint_validate()
        self._test_validate_bdm_v2(
            stack_name, bdm_v2,
            raise_exc=exception.ResourcePropertyConflict,
            error_msg=error_msg)

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_bdm_v2_with_empty_mapping(self, mock_create):
        stack_name = 'val_blkdev2'
        bdm_v2 = [{}]
        msg = ('Either volume_id, snapshot_id, image_id, swap_size, '
               'ephemeral_size or ephemeral_format must be specified.')
        self._test_validate_bdm_v2(stack_name, bdm_v2,
                                   raise_exc=exception.StackValidationFailed,
                                   error_msg=msg)

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_bdm_v2_properties_success(self, mock_create):
        stack_name = 'bdm_v2_success'
        bdm_v2 = [{'volume_id': '1', 'boot_index': -1}]
        self._test_validate_bdm_v2(stack_name, bdm_v2)

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_bdm_v2_with_unresolved_volume(self, mock_create):
        stack_name = 'bdm_v2_with_unresolved_vol'
        # empty string indicates that volume is unresolved
        bdm_v2 = [{'volume_id': ''}]
        self._test_validate_bdm_v2(stack_name, bdm_v2, with_image=False)

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_bdm_v2_multiple_bootable_source(self, mock_create):
        stack_name = 'v2_multiple_bootable'
        # with two bootable sources: volume_id and image
        bdm_v2 = [{'volume_id': '1', 'boot_index': 0}]
        msg = ('Multiple bootable sources for instance')
        self._test_validate_bdm_v2(stack_name, bdm_v2,
                                   raise_exc=exception.StackValidationFailed,
                                   error_msg=msg)

    @mock.patch.object(nova.NovaClientPlugin, 'client')
    def test_validate_bdm_v2_properties_no_bootable_vol(self, mock_create):
        stack_name = 'bdm_v2_no_bootable'
        bdm_v2 = [{'swap_size': 10}]
        msg = ('Neither image nor bootable volume is specified for instance '
               'server_create_image_err')
        self._test_validate_bdm_v2(stack_name, bdm_v2,
                                   raise_exc=exception.StackValidationFailed,
                                   error_msg=msg,
                                   with_image=False)

    def test_validate_metadata_too_many(self):
        stack_name = 'srv_val_metadata'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties']['metadata'] = {'a': 1,
                                                                      'b': 2,
                                                                      'c': 3,
                                                                      'd': 4}
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertIn('Instance metadata must not contain greater than 3 '
                      'entries', six.text_type(ex))

    def test_validate_metadata_okay(self):
        stack_name = 'srv_val_metadata'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties']['metadata'] = {'a': 1,
                                                                      'b': 2,
                                                                      'c': 3}
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.assertIsNone(server.validate())

    def test_server_unsupported_microversion_tags(self):
        stack_name = 'srv_val_tags'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        props = tmpl.t['Resources']['WebServer']['Properties']
        props['tags'] = ['a']
        # no need test with key_name
        props.pop('key_name')
        self.patchobject(nova.NovaClientPlugin, 'is_version_supported',
                         return_value=False)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertEqual('Cannot use "tags" property - nova does not support '
                         'required api microversion.',
                         six.text_type(exc))

    def test_server_validate_too_many_personality(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        tmpl.t['Resources']['WebServer']['Properties'][
            'personality'] = {"/fake/path1": "fake contents1",
                              "/fake/path2": "fake_contents2",
                              "/fake/path3": "fake_contents3",
                              "/fake/path4": "fake_contents4",
                              "/fake/path5": "fake_contents5",
                              "/fake/path6": "fake_contents6"}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.patchobject(self.fc.limits, 'get', return_value=self.limits)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertEqual("The personality property may not contain "
                         "greater than 5 entries.", six.text_type(exc))

    def test_server_validate_personality_okay(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        tmpl.t['Resources']['WebServer']['Properties'][
            'personality'] = {"/fake/path1": "fake contents1",
                              "/fake/path2": "fake_contents2",
                              "/fake/path3": "fake_contents3",
                              "/fake/path4": "fake_contents4",
                              "/fake/path5": "fake_contents5"}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.patchobject(self.fc.limits, 'get', return_value=self.limits)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.assertIsNone(server.validate())

    def test_server_validate_personality_file_size_okay(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        tmpl.t['Resources']['WebServer']['Properties'][
            'personality'] = {"/fake/path1": "a" * 10240}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(self.fc.limits, 'get', return_value=self.limits)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.assertIsNone(server.validate())

    def test_server_validate_personality_file_size_too_big(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)

        tmpl.t['Resources']['WebServer']['Properties'][
            'personality'] = {"/fake/path1": "a" * 10241}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.patchobject(self.fc.limits, 'get', return_value=self.limits)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertEqual('The contents of personality file "/fake/path1" '
                         'is larger than the maximum allowed personality '
                         'file size (10240 bytes).', six.text_type(exc))

    def test_server_validate_personality_get_attr_return_none(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(
            stack_name, server_with_sw_config_personality)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['server'], stack)
        self.patchobject(self.fc.limits, 'get', return_value=self.limits)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.assertIsNone(server.validate())

    def test_resolve_attribute_server_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_resolve_attr')

        server.resource_id = '1234'
        self.patchobject(self.fc.servers, 'get',
                         side_effect=fakes_nova.fake_exception())
        self.assertEqual('', server._resolve_any_attribute("accessIPv4"))

    def test_resolve_attribute_console_url(self):
        server = self.fc.servers.list()[0]
        tmpl, stack = self._setup_test_stack('console_url_stack')
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        ws = servers.Server(
            'WebServer', tmpl.resource_definitions(stack)['WebServer'], stack)
        ws.resource_id = server.id
        self.patchobject(self.fc.servers, 'get', return_value=server)
        console_urls = ws._resolve_any_attribute('console_urls')
        self.assertIsInstance(console_urls, collections.Mapping)
        supported_consoles = ('novnc', 'xvpvnc', 'spice-html5', 'rdp-html5',
                              'serial', 'webmks')
        self.assertEqual(set(supported_consoles),
                         set(console_urls))

    def test_resolve_attribute_networks(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_resolve_attr')

        server.resource_id = '1234'
        server.networks = {"fake_net": ["10.0.0.3"]}
        self.patchobject(self.fc.servers, 'get', return_value=server)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='fake_uuid')
        expect_networks = {"fake_uuid": ["10.0.0.3"],
                           "fake_net": ["10.0.0.3"]}
        self.assertEqual(expect_networks,
                         server._resolve_any_attribute("networks"))

    def test_empty_instance_user(self):
        """Test Nova server doesn't set instance_user in build_userdata

        Launching the instance should not pass any user name to
        build_userdata. The default cloud-init user set up for the image
        will be used instead.
        """
        return_server = self.fc.servers.list()[1]
        server = self._setup_test_server(return_server, 'without_user')
        metadata = server.metadata_get()
        build_data = self.patchobject(nova.NovaClientPlugin, 'build_userdata')
        scheduler.TaskRunner(server.create)()
        build_data.assert_called_with(metadata, 'wordpress',
                                      instance_user=None,
                                      user_data_format='HEAT_CFNTOOLS')

    def create_old_net(self, port=None, net=None,
                       ip=None, uuid=None, subnet=None,
                       port_extra_properties=None, floating_ip=None,
                       str_network=None, tag=None):
        return {'port': port, 'network': net, 'fixed_ip': ip, 'uuid': uuid,
                'subnet': subnet, 'floating_ip': floating_ip,
                'port_extra_properties': port_extra_properties,
                'allocate_network': str_network,
                'tag': tag}

    def test_get_network_id_neutron(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        net = {'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}
        net_id = server._get_network_id(net)
        self.assertIsNone(net_id)

        net = {'network': 'f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
               'fixed_ip': '1.2.3.4'}
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032')
        net_id = server._get_network_id(net)
        self.assertEqual('f3ef5d2f-d7ba-4b27-af66-58ca0b81e032', net_id)
        net = {'network': '', 'fixed_ip': '1.2.3.4'}
        net_id = server._get_network_id(net)
        self.assertIsNone(net_id)

    def test_exclude_not_updated_networks_no_matching(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        for new_nets in (
                [],
                [{'port': '952fd4ae-53b9-4b39-9e5f-8929c553b5ae',
                  'network': '450abbc9-9b6d-4d6f-8c3a-c47ac34100dd'}]):

            old_nets = [
                self.create_old_net(
                    port='2a60cbaa-3d33-4af6-a9ce-83594ac546fc'),
                self.create_old_net(
                    net='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032', ip='1.2.3.4'),
                self.create_old_net(
                    net='0da8adbf-a7e2-4c59-a511-96b03d2da0d7')]
            interfaces = [
                create_fake_iface(
                    port='2a60cbaa-3d33-4af6-a9ce-83594ac546fc',
                    net='450abbc9-9b6d-4d6f-8c3a-c47ac34100aa',
                    ip='4.3.2.1',
                    subnet='subnetsu-bnet-subn-etsu-bnetsubnetsu'),
                create_fake_iface(
                    port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                    net='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
                    ip='1.2.3.4',
                    subnet='subnetsu-bnet-subn-etsu-bnetsubnetsu'),
                create_fake_iface(
                    port='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                    net='0da8adbf-a7e2-4c59-a511-96b03d2da0d7',
                    ip='4.2.3.1',
                    subnet='subnetsu-bnet-subn-etsu-bnetsubnetsu')]

            new_nets_cpy = copy.deepcopy(new_nets)
            old_nets_cpy = copy.deepcopy(old_nets)
            # Add values to old_nets_cpy that is populated in old_nets when
            # calling update_networks_matching_iface_port() in
            # _exclude_not_updated_networks()
            old_nets_cpy[0]['fixed_ip'] = '4.3.2.1'
            old_nets_cpy[0]['network'] = '450abbc9-9b6d-4d6f-8c3a-c47ac34100aa'
            old_nets_cpy[0]['subnet'] = 'subnetsu-bnet-subn-etsu-bnetsubnetsu'
            old_nets_cpy[1]['fixed_ip'] = '1.2.3.4'
            old_nets_cpy[1]['port'] = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
            old_nets_cpy[1]['subnet'] = 'subnetsu-bnet-subn-etsu-bnetsubnetsu'
            old_nets_cpy[2]['fixed_ip'] = '4.2.3.1'
            old_nets_cpy[2]['port'] = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
            old_nets_cpy[2]['subnet'] = 'subnetsu-bnet-subn-etsu-bnetsubnetsu'

            for net in new_nets_cpy:
                for key in ('port', 'network', 'fixed_ip', 'uuid', 'subnet',
                            'port_extra_properties', 'floating_ip',
                            'allocate_network', 'tag'):
                    net.setdefault(key)

            server._exclude_not_updated_networks(old_nets, new_nets,
                                                 interfaces)
            self.assertEqual(old_nets_cpy, old_nets)
            self.assertEqual(new_nets_cpy, new_nets)

    def test_exclude_not_updated_networks_success(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        old_nets = [
            self.create_old_net(
                port='2a60cbaa-3d33-4af6-a9ce-83594ac546fc'),
            self.create_old_net(
                net='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
                ip='1.2.3.4'),
            self.create_old_net(
                net='0da8adbf-a7e2-4c59-a511-96b03d2da0d7')]
        new_nets = [
            {'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'},
            {'network': 'f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
             'fixed_ip': '1.2.3.4'},
            {'port': '952fd4ae-53b9-4b39-9e5f-8929c553b5ae'}]
        interfaces = [
            create_fake_iface(port='2a60cbaa-3d33-4af6-a9ce-83594ac546fc',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='3.4.5.6'),
            create_fake_iface(port='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                              net='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
                              ip='1.2.3.4'),
            create_fake_iface(port='cccccccc-cccc-cccc-cccc-cccccccccccc',
                              net='0da8adbf-a7e2-4c59-a511-96b03d2da0d7',
                              ip='2.3.4.5')]

        new_nets_copy = copy.deepcopy(new_nets)
        old_nets_copy = copy.deepcopy(old_nets)
        # Add values to old_nets_copy that is populated in old_nets when
        # calling update_networks_matching_iface_port() in
        # _exclude_not_updated_networks()
        old_nets_copy[2]['fixed_ip'] = '2.3.4.5'
        old_nets_copy[2]['port'] = 'cccccccc-cccc-cccc-cccc-cccccccccccc'

        for net in new_nets_copy:
            for key in ('port', 'network', 'fixed_ip', 'uuid', 'subnet',
                        'port_extra_properties', 'floating_ip',
                        'allocate_network', 'tag'):
                net.setdefault(key)

        server._exclude_not_updated_networks(old_nets, new_nets, interfaces)
        self.assertEqual([old_nets_copy[2]], old_nets)
        self.assertEqual([new_nets_copy[2]], new_nets)

    def test_exclude_not_updated_networks_nothing_for_update(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        old_nets = [
            self.create_old_net(
                net='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
                ip='',
                port='')]
        new_nets = [
            {'network': 'f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
             'fixed_ip': None,
             'port': None,
             'subnet': None,
             'uuid': None,
             'port_extra_properties': None,
             'floating_ip': None,
             'allocate_network': None,
             'tag': None}]
        interfaces = [
            create_fake_iface(port='',
                              net='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
                              ip='')]

        server._exclude_not_updated_networks(old_nets, new_nets, interfaces)
        self.assertEqual([], old_nets)
        self.assertEqual([], new_nets)

    def test_update_networks_matching_iface_port(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        # old order 0 1 2 3 4 5 6
        nets = [
            self.create_old_net(port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
            self.create_old_net(net='gggggggg-1111-1111-1111-gggggggggggg',
                                ip='1.2.3.4'),
            self.create_old_net(net='gggggggg-1111-1111-1111-gggggggggggg'),
            self.create_old_net(port='dddddddd-dddd-dddd-dddd-dddddddddddd'),
            self.create_old_net(net='gggggggg-1111-1111-1111-gggggggggggg',
                                ip='5.6.7.8'),
            self.create_old_net(net='gggggggg-1111-1111-1111-gggggggggggg',
                                subnet='hhhhhhhh-1111-1111-1111-hhhhhhhhhhhh'),
            self.create_old_net(subnet='iiiiiiii-1111-1111-1111-iiiiiiiiiiii')]
        # new order 2 3 0 1 4 6 5
        interfaces = [
            create_fake_iface(port='cccccccc-cccc-cccc-cccc-cccccccccccc',
                              net=nets[2]['network'],
                              ip='10.0.0.11'),
            create_fake_iface(port=nets[3]['port'],
                              net='gggggggg-1111-1111-1111-gggggggggggg',
                              ip='10.0.0.12'),
            create_fake_iface(port=nets[0]['port'],
                              net='gggggggg-1111-1111-1111-gggggggggggg',
                              ip='10.0.0.13'),
            create_fake_iface(port='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                              net=nets[1]['network'],
                              ip=nets[1]['fixed_ip']),
            create_fake_iface(port='eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
                              net=nets[4]['network'],
                              ip=nets[4]['fixed_ip']),
            create_fake_iface(port='gggggggg-gggg-gggg-gggg-gggggggggggg',
                              net='gggggggg-1111-1111-1111-gggggggggggg',
                              ip='10.0.0.14',
                              subnet=nets[6]['subnet']),
            create_fake_iface(port='ffffffff-ffff-ffff-ffff-ffffffffffff',
                              net=nets[5]['network'],
                              ip='10.0.0.15',
                              subnet=nets[5]['subnet'])]

        # all networks should get port id
        expected = [
            {'port': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '10.0.0.13',
             'subnet': None,
             'floating_ip': None,
             'port_extra_properties': None,
             'uuid': None,
             'allocate_network': None,
             'tag': None},
            {'port': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '1.2.3.4',
             'subnet': None,
             'port_extra_properties': None,
             'floating_ip': None,
             'uuid': None,
             'allocate_network': None,
             'tag': None},
            {'port': 'cccccccc-cccc-cccc-cccc-cccccccccccc',
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '10.0.0.11',
             'subnet': None,
             'port_extra_properties': None,
             'floating_ip': None,
             'uuid': None,
             'allocate_network': None,
             'tag': None},
            {'port': 'dddddddd-dddd-dddd-dddd-dddddddddddd',
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '10.0.0.12',
             'subnet': None,
             'port_extra_properties': None,
             'floating_ip': None,
             'uuid': None,
             'allocate_network': None,
             'tag': None},
            {'port': 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
             'uuid': None,
             'fixed_ip': '5.6.7.8',
             'subnet': None,
             'port_extra_properties': None,
             'floating_ip': None,
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'allocate_network': None,
             'tag': None},
            {'port': 'ffffffff-ffff-ffff-ffff-ffffffffffff',
             'uuid': None,
             'fixed_ip': '10.0.0.15',
             'subnet': 'hhhhhhhh-1111-1111-1111-hhhhhhhhhhhh',
             'port_extra_properties': None,
             'floating_ip': None,
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'allocate_network': None,
             'tag': None},
            {'port': 'gggggggg-gggg-gggg-gggg-gggggggggggg',
             'uuid': None,
             'fixed_ip': '10.0.0.14',
             'subnet': 'iiiiiiii-1111-1111-1111-iiiiiiiiiiii',
             'port_extra_properties': None,
             'floating_ip': None,
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'allocate_network': None,
             'tag': None}]

        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='gggggggg-1111-1111-1111-gggggggggggg')
        self.patchobject(neutron.NeutronClientPlugin,
                         'network_id_from_subnet_id',
                         return_value='gggggggg-1111-1111-1111-gggggggggggg')
        server.update_networks_matching_iface_port(nets, interfaces)
        self.assertEqual(expected, nets)

    def test_server_update_None_networks_with_port(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'
        server = self._create_test_server(return_server, 'networks_update')

        new_networks = [{'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        update_props = self.server_props.copy()
        # old_networks is None, and update to new_networks with port
        update_props['networks'] = new_networks
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)

        iface = create_fake_iface(
            port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            net='450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
            ip='1.2.3.4')
        self.patchobject(return_server, 'interface_list', return_value=[iface])
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        mock_attach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_attach',
                                             return_value=True)

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.assertEqual(1, mock_detach.call_count)
        self.assertEqual(1, mock_attach.call_count)
        self.assertEqual(1, mock_detach_check.call_count)
        self.assertEqual(1, mock_attach_check.call_count)

    def test_server_update_None_networks_with_network_id(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'

        self.patchobject(neutronclient.Client, 'create_port',
                         return_value={'port': {'id': 'abcd1234'}})

        server = self._create_test_server(return_server, 'networks_update')
        # old_networks is None, and update to new_networks with port
        new_networks = [{'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                         'fixed_ip': '1.2.3.4'}]
        update_props = self.server_props.copy()
        update_props['networks'] = new_networks
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)

        iface = create_fake_iface(
            port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            net='450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
            ip='1.2.3.4')
        self.patchobject(return_server, 'interface_list', return_value=[iface])
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        mock_attach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_attach',
                                             return_value=True)

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.assertEqual(1, mock_detach.call_count)
        self.assertEqual(1, mock_attach.call_count)
        self.assertEqual(1, mock_detach_check.call_count)
        self.assertEqual(1, mock_attach_check.call_count)

    def test_server_update_subnet_with_security_group(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'

        server = self._create_test_server(return_server, 'update_subnet')
        # set old properties for 'networks' and 'security_groups'
        before_props = self.server_props.copy()
        before_props['networks'] = [
            {'subnet': 'aaa09d50-8c23-4498-a542-aa0deb24f73e'}
        ]
        before_props['security_groups'] = ['the_sg']
        # set new property 'networks'
        new_networks = [{'subnet': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        update_props = self.server_props.copy()
        update_props['networks'] = new_networks
        update_props['security_groups'] = ['the_sg']
        update_template = server.t.freeze(properties=update_props)
        server.t = server.t.freeze(properties=before_props)

        sec_uuids = ['86c0f8ae-23a8-464f-8603-c54113ef5467']

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        self.patchobject(neutron.NeutronClientPlugin,
                         'get_secgroup_uuids', return_value=sec_uuids)
        self.patchobject(neutron.NeutronClientPlugin,
                         'network_id_from_subnet_id',
                         return_value='05d8e681-4b37-4570-bc8d-810089f706b2')
        mock_create_port = self.patchobject(
            neutronclient.Client, 'create_port')

        iface = create_fake_iface(
            port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            net='05d8e681-4b37-4570-bc8d-810089f706b2',
            subnet='aaa09d50-8c23-4498-a542-aa0deb24f73e',
            ip='1.2.3.4')
        self.patchobject(return_server, 'interface_list', return_value=[iface])
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        mock_attach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_attach',
                                             return_value=True)

        scheduler.TaskRunner(server.update, update_template, before=server.t)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.assertEqual(1, mock_detach.call_count)
        self.assertEqual(1, mock_attach.call_count)
        self.assertEqual(1, mock_detach_check.call_count)
        self.assertEqual(1, mock_attach_check.call_count)
        kwargs = {'network_id': '05d8e681-4b37-4570-bc8d-810089f706b2',
                  'fixed_ips': [
                      {'subnet_id': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}],
                  'security_groups': sec_uuids,
                  'name': 'update_subnet-port-0',
                  }
        mock_create_port.assert_called_with({'port': kwargs})

    def test_server_update_subnet_to_network_with_security_group(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'

        server = self._create_test_server(return_server, 'update_subnet')
        # set old properties for 'networks' and 'security_groups'
        before_props = self.server_props.copy()
        before_props['networks'] = [
            {'subnet': 'aaa09d50-8c23-4498-a542-aa0deb24f73e'}
        ]
        before_props['security_groups'] = ['the_sg']
        # set new property 'networks'
        new_networks = [{'network': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        update_props = self.server_props.copy()
        update_props['networks'] = new_networks
        update_props['security_groups'] = ['the_sg']
        update_template = server.t.freeze(properties=update_props)
        server.t = server.t.freeze(properties=before_props)

        sec_uuids = ['86c0f8ae-23a8-464f-8603-c54113ef5467']

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        self.patchobject(neutron.NeutronClientPlugin,
                         'get_secgroup_uuids', return_value=sec_uuids)

        self.patchobject(neutron.NeutronClientPlugin,
                         'network_id_from_subnet_id',
                         return_value='05d8e681-4b37-4570-bc8d-810089f706b2')

        iface = create_fake_iface(
            port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            net='05d8e681-4b37-4570-bc8d-810089f706b2',
            subnet='aaa09d50-8c23-4498-a542-aa0deb24f73e',
            ip='1.2.3.4')
        self.patchobject(return_server, 'interface_list', return_value=[iface])
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')

        def interface_attach_mock(port, net):
            class attachment(object):
                def __init__(self, port_id, net_id):
                    self.port_id = port_id
                    self.net_id = net_id

            return attachment(port, net)

        mock_attach.return_value = interface_attach_mock(
            'ad4a231b-67f7-45fe-aee9-461176b48203',
            '2a60cbaa-3d33-4af6-a9ce-83594ac546fc')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        mock_attach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_attach',
                                             return_value=True)
        mock_update_port = self.patchobject(
            neutronclient.Client, 'update_port')

        scheduler.TaskRunner(server.update, update_template, before=server.t)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.assertEqual(1, mock_detach.call_count)
        self.assertEqual(1, mock_attach.call_count)
        self.assertEqual(1, mock_detach_check.call_count)
        self.assertEqual(1, mock_attach_check.call_count)
        kwargs = {'security_groups': sec_uuids}
        mock_update_port.assert_called_with(
            'ad4a231b-67f7-45fe-aee9-461176b48203',
            {'port': kwargs})

    def test_server_update_empty_networks_with_complex_parameters(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'
        server = self._create_test_server(return_server, 'networks_update')
        new_networks = [{'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                         'fixed_ip': '1.2.3.4',
                         'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        update_props = self.server_props.copy()
        update_props['networks'] = new_networks
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)

        iface = create_fake_iface(
            port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            net='450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
            ip='1.2.3.4')
        self.patchobject(return_server, 'interface_list', return_value=[iface])
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        mock_attach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_attach',
                                             return_value=True)
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.assertEqual(1, mock_detach.call_count)
        self.assertEqual(1, mock_attach.call_count)
        self.assertEqual(1, mock_detach_check.call_count)
        self.assertEqual(1, mock_attach_check.call_count)

    def test_server_update_empty_networks_to_None(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'
        server = self._create_test_server(return_server, 'networks_update',
                                          networks=[])
        update_props = copy.deepcopy(self.server_props)
        update_props.pop('networks')
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)

        iface = create_fake_iface(
            port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            net='450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
            ip='1.2.3.4')
        self.patchobject(return_server, 'interface_list', return_value=[iface])
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        mock_attach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_attach',
                                             return_value=True)
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        # test we detach the old interface and attach a new one
        self.assertEqual(0, mock_detach.call_count)
        self.assertEqual(0, mock_attach.call_count)
        self.assertEqual(0, mock_detach_check.call_count)
        self.assertEqual(0, mock_attach_check.call_count)

    def _test_server_update_to_auto(self, available_multi_nets=None):
        multi_nets = available_multi_nets or []
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'}]
        server = self._create_test_server(return_server, 'networks_update',
                                          networks=old_networks)

        update_props = self.server_props.copy()
        update_props['networks'] = [{'allocate_network': 'auto'}]
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        poor_interfaces = [
            create_fake_iface(port='95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='11.12.13.14')]

        self.patchobject(return_server, 'interface_list',
                         return_value=poor_interfaces)
        self.patchobject(server, '_get_available_networks',
                         return_value=multi_nets)
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        updater = scheduler.TaskRunner(server.update, update_template)
        if not multi_nets:
            self.patchobject(nova.NovaClientPlugin, 'check_interface_detach',
                             return_value=True)
            self.patchobject(nova.NovaClientPlugin,
                             'check_interface_attach',
                             return_value=True)

            auto_allocate_net = '9cfe6c74-c105-4906-9a1f-81d9064e9bca'
            self.patchobject(server, '_auto_allocate_network',
                             return_value=[auto_allocate_net])
            updater()
            self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
            self.assertEqual(1, mock_detach.call_count)
            self.assertEqual(1, mock_attach.call_count)
            mock_attach.assert_called_once_with(None,
                                                [auto_allocate_net],
                                                None)
        else:
            self.assertRaises(exception.ResourceFailure, updater)
            self.assertEqual(0, mock_detach.call_count)
            self.assertEqual(0, mock_attach.call_count)

    def test_server_update_str_networks_auto(self):
        self._test_server_update_to_auto()

    def test_server_update_str_networks_auto_multi_nets(self):
        available_nets = ['net_1', 'net_2']
        self._test_server_update_to_auto(available_nets)

    def test_server_update_str_networks_none(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '31.32.33.34'}]
        server = self._create_test_server(return_server, 'networks_update',
                                          networks=old_networks)

        update_props = self.server_props.copy()
        update_props['networks'] = [{'allocate_network': 'none'}]
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        port_interfaces = [
            create_fake_iface(port='95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='11.12.13.14'),
            create_fake_iface(port='4121f61a-1b2e-4ab0-901e-eade9b1cb09d',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='21.22.23.24'),
            create_fake_iface(port='0907fa82-a024-43c2-9fc5-efa1bccaa74a',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='31.32.33.34')]

        self.patchobject(return_server, 'interface_list',
                         return_value=port_interfaces)
        mock_detach = self.patchobject(return_server, 'interface_detach')
        self.patchobject(nova.NovaClientPlugin,
                         'check_interface_detach',
                         return_value=True)
        mock_attach = self.patchobject(return_server, 'interface_attach')

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.assertEqual(3, mock_detach.call_count)
        self.assertEqual(0, mock_attach.call_count)

    def test_server_update_networks_with_complex_parameters(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '1.2.3.4'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '31.32.33.34'}]
        server = self._create_test_server(return_server, 'networks_update',
                                          networks=old_networks)

        new_networks = [
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '1.2.3.4'},
            {'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]

        update_props = copy.deepcopy(self.server_props)
        update_props['networks'] = new_networks
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)

        poor_interfaces = [
            create_fake_iface(port='95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='11.12.13.14'),
            create_fake_iface(port='450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='1.2.3.4'),
            create_fake_iface(port='4121f61a-1b2e-4ab0-901e-eade9b1cb09d',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='21.22.23.24'),
            create_fake_iface(port='0907fa82-a024-43c2-9fc5-efa1bccaa74a',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='31.32.33.34')]

        self.patchobject(return_server, 'interface_list',
                         return_value=poor_interfaces)
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        mock_attach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_attach',
                                             return_value=True)
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        # we only detach the three old networks, and attach a new one
        self.assertEqual(3, mock_detach.call_count)
        self.assertEqual(1, mock_attach.call_count)
        self.assertEqual(3, mock_detach_check.call_count)
        self.assertEqual(1, mock_attach_check.call_count)

    def test_server_update_networks_with_None(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '31.32.33.34'}]
        server = self._create_test_server(return_server, 'networks_update',
                                          networks=old_networks)
        update_props = self.server_props.copy()
        update_props['networks'] = None
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        poor_interfaces = [
            create_fake_iface(port='95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='11.12.13.14'),
            create_fake_iface(port='4121f61a-1b2e-4ab0-901e-eade9b1cb09d',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='21.22.23.24'),
            create_fake_iface(port='0907fa82-a024-43c2-9fc5-efa1bccaa74a',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='31.32.33.34')]
        self.patchobject(return_server, 'interface_list',
                         return_value=poor_interfaces)
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        mock_attach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_attach',
                                             return_value=True)
        scheduler.TaskRunner(server.update, update_template, before=server.t)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.assertEqual(3, mock_detach.call_count)
        self.assertEqual(1, mock_attach.call_count)
        self.assertEqual(3, mock_detach_check.call_count)
        self.assertEqual(1, mock_attach_check.call_count)

    def test_server_update_old_networks_to_empty_list(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '31.32.33.34'}]
        server = self._create_test_server(return_server, 'networks_update',
                                          networks=old_networks)

        update_props = self.server_props.copy()
        update_props['networks'] = []
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        poor_interfaces = [
            create_fake_iface(port='95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='11.12.13.14'),
            create_fake_iface(port='4121f61a-1b2e-4ab0-901e-eade9b1cb09d',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='21.22.23.24'),
            create_fake_iface(port='0907fa82-a024-43c2-9fc5-efa1bccaa74a',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='31.32.33.34')]

        self.patchobject(return_server, 'interface_list',
                         return_value=poor_interfaces)
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        mock_attach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_attach',
                                             return_value=True)
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.assertEqual(3, mock_detach.call_count)
        self.assertEqual(1, mock_attach.call_count)
        self.assertEqual(3, mock_detach_check.call_count)
        self.assertEqual(1, mock_attach_check.call_count)

    def test_server_update_remove_network_non_empty(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'}]
        new_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'}]

        server = self._create_test_server(return_server, 'networks_update',
                                          networks=old_networks)

        update_props = self.server_props.copy()
        update_props['networks'] = new_networks
        update_template = server.t.freeze(properties=update_props)

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        poor_interfaces = [
            create_fake_iface(port='95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='11.12.13.14'),
            create_fake_iface(port='4121f61a-1b2e-4ab0-901e-eade9b1cb09d',
                              net='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                              ip='21.22.23.24')]

        self.patchobject(return_server, 'interface_list',
                         return_value=poor_interfaces)
        mock_detach = self.patchobject(return_server, 'interface_detach')
        mock_attach = self.patchobject(return_server, 'interface_attach')
        mock_detach_check = self.patchobject(nova.NovaClientPlugin,
                                             'check_interface_detach',
                                             return_value=True)
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.assertEqual(1, mock_detach.call_count)
        self.assertEqual(1, mock_detach_check.call_count)
        self.assertEqual(0, mock_attach.call_count)

    def test_server_properties_validation_create_and_update(self):
        return_server = self.fc.servers.list()[1]

        # create
        # validation calls are already mocked there
        server = self._create_test_server(return_server,
                                          'my_server')

        update_props = self.server_props.copy()
        update_props['image'] = 'F17-x86_64-gold'
        update_props['image_update_policy'] = 'REPLACE'
        update_template = server.t.freeze(properties=update_props)
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_server_properties_validation_create_and_update_fail(self):
        return_server = self.fc.servers.list()[1]

        # create
        # validation calls are already mocked there
        server = self._create_test_server(return_server,
                                          'my_server')

        ex = glance.client_exception.EntityMatchNotFound(entity='image',
                                                         args='Update Image')
        self.patchobject(glance.GlanceClientPlugin,
                         'find_image_by_name_or_id',
                         side_effect=[1, ex])
        update_props = self.server_props.copy()
        update_props['image'] = 'Update Image'
        update_template = server.t.freeze(properties=update_props)

        # update
        updater = scheduler.TaskRunner(server.update, update_template)
        err = self.assertRaises(exception.ResourceFailure,
                                updater)
        self.assertEqual("StackValidationFailed: resources.my_server: "
                         "Property error: Properties.image: Error validating "
                         "value '1': No image matching Update Image.",
                         six.text_type(err))

    def test_server_snapshot(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'test_server_snapshot')
        scheduler.TaskRunner(server.snapshot)()

        self.assertEqual((server.SNAPSHOT, server.COMPLETE), server.state)

        self.assertEqual({'snapshot_image_id': '456'},
                         resource_data_object.ResourceData.get_all(server))

    def test_server_check_snapshot_complete_image_in_deleted(self):
        self._test_server_check_snapshot_complete(image_status='DELETED')

    def test_server_check_snapshot_complete_image_in_error(self):
        self._test_server_check_snapshot_complete()

    def test_server_check_snapshot_complete_fail(self):
        self._test_server_check_snapshot_complete()

    def _test_server_check_snapshot_complete(self, image_status='ERROR'):
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'test_server_snapshot')
        image_in_error = mock.Mock()
        image_in_error.status = image_status

        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=image_in_error)
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(server.snapshot))

        self.assertEqual((server.SNAPSHOT, server.FAILED), server.state)
        # test snapshot_image_id already set to resource data
        self.assertEqual({'snapshot_image_id': '456'},
                         resource_data_object.ResourceData.get_all(server))

    def test_server_dont_validate_personality_if_personality_isnt_set(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        mock_limits = self.patchobject(nova.NovaClientPlugin,
                                       'absolute_limits')
        self.patchobject(nova.NovaClientPlugin, 'client')

        # Assert here checks that server resource validates, but actually
        # this call is Act stage of this test. We calling server.validate()
        # to verify that no excessive calls to Nova are made during validation.
        self.assertIsNone(server.validate())

        # Check nova.NovaClientPlugin.absolute_limits is not called during
        # call to server.validate()
        self.assertFalse(mock_limits.called)

    def test_server_validate_connection_error_retry_successful(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl.t['Resources']['WebServer']['Properties'][
            'personality'] = {"/fake/path1": "a" * 10}
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(self.fc.limits, 'get',
                         side_effect=[requests.ConnectionError(),
                                      self.limits])
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.assertIsNone(server.validate())

    def test_server_validate_connection_error_retry_failure(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl.t['Resources']['WebServer']['Properties'][
            'personality'] = {"/fake/path1": "a" * 10}
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(self.fc.limits, 'get',
                         side_effect=[requests.ConnectionError(),
                                      requests.ConnectionError(),
                                      requests.ConnectionError()])
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.assertRaises(requests.ConnectionError, server.validate)

    def test_server_restore(self):
        t = template_format.parse(ns_template)
        tmpl = template.Template(t, files={'a_file': 'the content'})
        stack = parser.Stack(utils.dummy_context(), "server_restore", tmpl)
        stack.store()
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        self.patchobject(stack['server'], 'store_external_ports')
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        mock_create = self.patchobject(self.fc.servers, 'create',
                                       return_value=return_server)
        self.patchobject(self.fc.servers, 'get',
                         return_value=return_server)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.patchobject(return_server, 'get', return_value=None)

        scheduler.TaskRunner(stack.create)()
        self.assertEqual(1, mock_create.call_count)
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)

        scheduler.TaskRunner(stack.snapshot, None)()

        self.assertEqual((stack.SNAPSHOT, stack.COMPLETE), stack.state)

        data = stack.prepare_abandon()
        resource_data = data['resources']['server']['resource_data']
        resource_data['snapshot_image_id'] = 'CentOS 5.2'
        fake_snapshot = collections.namedtuple(
            'Snapshot', ('data', 'stack_id'))(data, stack.id)

        stack.restore(fake_snapshot)
        self.assertEqual((stack.RESTORE, stack.COMPLETE), stack.state)

    def test_snapshot_policy(self):
        t = template_format.parse(wp_template)
        t['Resources']['WebServer']['DeletionPolicy'] = 'Snapshot'
        tmpl = template.Template(t)
        stack = parser.Stack(
            utils.dummy_context(), 'snapshot_policy', tmpl)
        stack.store()

        self.patchobject(stack['WebServer'], 'store_external_ports')

        mock_plugin = self.patchobject(nova.NovaClientPlugin, 'client')
        mock_plugin.return_value = self.fc

        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'

        mock_create = self.patchobject(self.fc.servers, 'create')
        mock_create.return_value = return_server
        mock_get = self.patchobject(self.fc.servers, 'get')
        mock_get.return_value = return_server

        image = self.fc.servers.create_image('1234', 'name')
        create_image = self.patchobject(self.fc.servers, 'create_image')
        create_image.return_value = image

        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)

        delete_server = self.patchobject(self.fc.servers, 'delete')
        delete_server.side_effect = nova_exceptions.NotFound(404)

        scheduler.TaskRunner(stack.create)()

        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)

        scheduler.TaskRunner(stack.delete)()

        self.assertEqual((stack.DELETE, stack.COMPLETE), stack.state)
        create_image.assert_called_once_with(
            '1234', utils.PhysName('snapshot_policy', 'WebServer'))

        delete_server.assert_called_once_with('1234')

    def test_snapshot_policy_image_failed(self):
        t = template_format.parse(wp_template)
        t['Resources']['WebServer']['DeletionPolicy'] = 'Snapshot'
        tmpl = template.Template(t)
        stack = parser.Stack(
            utils.dummy_context(), 'snapshot_policy', tmpl)
        stack.store()

        self.patchobject(stack['WebServer'], 'store_external_ports')

        mock_plugin = self.patchobject(nova.NovaClientPlugin, 'client')
        mock_plugin.return_value = self.fc
        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=self.mock_image)
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        mock_create = self.patchobject(self.fc.servers, 'create')
        mock_create.return_value = return_server
        mock_get = self.patchobject(self.fc.servers, 'get')
        mock_get.return_value = return_server

        image = self.fc.servers.create_image('1234', 'name')
        create_image = self.patchobject(self.fc.servers, 'create_image')
        create_image.return_value = image

        delete_server = self.patchobject(self.fc.servers, 'delete')
        delete_server.side_effect = nova_exceptions.NotFound(404)

        scheduler.TaskRunner(stack.create)()

        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)

        failed_image = mock.Mock(**{
            'id': 456,
            'name': 'CentOS 5.2',
            'updated': '2010-10-10T12:00:00Z',
            'created': '2010-08-10T12:00:00Z',
            'status': 'ERROR'})

        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         return_value=failed_image)
        return_server = self.fc.servers.list()[1]
        scheduler.TaskRunner(stack.delete)()

        self.assertEqual((stack.DELETE, stack.FAILED), stack.state)
        self.assertEqual(
            'Resource DELETE failed: Error: resources.WebServer: ERROR',
            stack.status_reason)
        create_image.assert_called_once_with(
            '1234', utils.PhysName('snapshot_policy', 'WebServer'))

        delete_server.assert_not_called()

    def test_handle_snapshot_delete(self):
        t = template_format.parse(wp_template)
        t['Resources']['WebServer']['DeletionPolicy'] = 'Snapshot'
        tmpl = template.Template(t)
        stack = parser.Stack(
            utils.dummy_context(), 'snapshot_policy', tmpl)
        stack.store()
        rsrc = stack['WebServer']
        mock_plugin = self.patchobject(nova.NovaClientPlugin, 'client')
        mock_plugin.return_value = self.fc
        delete_server = self.patchobject(self.fc.servers, 'delete')
        delete_server.side_effect = nova_exceptions.NotFound(404)
        create_image = self.patchobject(self.fc.servers, 'create_image')

        # test resource_id is None
        self.patchobject(servers.Server, 'user_data_software_config',
                         return_value=True)
        delete_internal_ports = self.patchobject(servers.Server,
                                                 '_delete_internal_ports')
        delete_queue = self.patchobject(servers.Server, '_delete_queue')
        delete_user = self.patchobject(servers.Server, '_delete_user')
        delete_swift_object = self.patchobject(servers.Server,
                                               '_delete_temp_url')
        rsrc.handle_snapshot_delete((rsrc.CREATE, rsrc.FAILED))

        delete_server.assert_not_called()
        create_image.assert_not_called()
        # attempt to delete queue/user/swift_object/internal_ports
        # if no resource_id
        delete_internal_ports.assert_called_once_with()
        delete_queue.assert_called_once_with()
        delete_user.assert_called_once_with()
        delete_swift_object.assert_called_once_with()

        # test has resource_id but state is CREATE_FAILED
        rsrc.resource_id = '4567'
        rsrc.handle_snapshot_delete((rsrc.CREATE, rsrc.FAILED))
        delete_server.assert_called_once_with('4567')
        create_image.assert_not_called()
        # attempt to delete internal_ports if has resource_id
        self.assertEqual(2, delete_internal_ports.call_count)

    def test_handle_delete_without_resource_id(self):
        t = template_format.parse(wp_template)
        tmpl = template.Template(t)
        stack = parser.Stack(
            utils.dummy_context(), 'without_resource_id', tmpl)
        rsrc = stack['WebServer']

        delete_server = self.patchobject(self.fc.servers, 'delete')

        # test resource_id is None
        self.patchobject(servers.Server, 'user_data_software_config',
                         return_value=True)
        delete_internal_ports = self.patchobject(servers.Server,
                                                 '_delete_internal_ports')
        delete_queue = self.patchobject(servers.Server, '_delete_queue')
        delete_user = self.patchobject(servers.Server, '_delete_user')
        delete_swift_object = self.patchobject(servers.Server,
                                               '_delete_temp_url')
        rsrc.handle_delete()

        delete_server.assert_not_called()
        # attempt to delete queue/user/swift_object/internal_ports
        # if no resource_id
        delete_internal_ports.assert_called_once_with()
        delete_queue.assert_called_once_with()
        delete_user.assert_called_once_with()
        delete_swift_object.assert_called_once_with()


class ServerInternalPortTest(ServersTest):
    def setUp(self):
        super(ServerInternalPortTest, self).setUp()
        self.resolve = self.patchobject(neutron.NeutronClientPlugin,
                                        'find_resourceid_by_name_or_id')
        self.port_create = self.patchobject(neutronclient.Client,
                                            'create_port')
        self.port_delete = self.patchobject(neutronclient.Client,
                                            'delete_port')
        self.port_show = self.patchobject(neutronclient.Client,
                                          'show_port')

        def neutron_side_effect(*args):
            if args[0] == 'subnet':
                return '1234'
            if args[0] == 'network':
                return '4321'
            if args[0] == 'port':
                return '12345'

        self.resolve.side_effect = neutron_side_effect

    def _return_template_stack_and_rsrc_defn(self, stack_name, temp):
        templ = template.Template(template_format.parse(temp),
                                  env=environment.Environment(
                                      {'key_name': 'test'}))
        stack = parser.Stack(utils.dummy_context(), stack_name, templ,
                             stack_id=uuidutils.generate_uuid(),
                             stack_user_project_id='8888')
        resource_defns = templ.resource_definitions(stack)
        server = servers.Server('server', resource_defns['server'],
                                stack)
        return templ, stack, server

    def test_build_nics_without_internal_port(self):
        tmpl = """
        heat_template_version: 2015-10-15
        resources:
          server:
            type: OS::Nova::Server
            properties:
              flavor: m1.small
              image: F17-x86_64-gold
              networks:
                - port: 12345
                  network: 4321
        """
        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)

        create_internal_port = self.patchobject(server,
                                                '_create_internal_port',
                                                return_value='12345')
        networks = [{'port': '12345', 'network': '4321'}]
        nics = server._build_nics(networks)
        self.assertEqual([{'port-id': '12345', 'net-id': '4321'}], nics)
        self.assertEqual(0, create_internal_port.call_count)

    def test_validate_internal_port_subnet_not_this_network(self):
        tmpl = """
        heat_template_version: 2015-10-15
        resources:
          server:
            type: OS::Nova::Server
            properties:
              flavor: m1.small
              image: F17-x86_64-gold
              networks:
                - network: 4321
                  subnet: 1234
        """
        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)
        networks = server.properties['networks']
        for network in networks:
            # validation passes at validate time
            server._validate_network(network)

        self.patchobject(neutron.NeutronClientPlugin,
                         'network_id_from_subnet_id',
                         return_value='not_this_network')
        ex = self.assertRaises(exception.StackValidationFailed,
                               server._build_nics, networks)
        self.assertEqual('Specified subnet 1234 does not belongs to '
                         'network 4321.', six.text_type(ex))

    def test_build_nics_create_internal_port_all_props_without_extras(self):
        tmpl = """
        heat_template_version: 2015-10-15
        resources:
          server:
            type: OS::Nova::Server
            properties:
              flavor: m1.small
              image: F17-x86_64-gold
              security_groups:
                - test_sec
              networks:
                - network: 4321
                  subnet: 1234
                  fixed_ip: 127.0.0.1
        """

        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)
        self.patchobject(server, '_validate_belonging_subnet_to_net')
        self.patchobject(neutron.NeutronClientPlugin,
                         'get_secgroup_uuids', return_value=['5566'])
        self.port_create.return_value = {'port': {'id': '111222'}}
        data_set = self.patchobject(resource.Resource, 'data_set')

        network = [{'network': '4321', 'subnet': '1234',
                    'fixed_ip': '127.0.0.1'}]
        security_groups = ['test_sec']
        server._build_nics(network, security_groups)

        self.port_create.assert_called_once_with(
            {'port': {'name': 'server-port-0',
                      'network_id': '4321',
                      'fixed_ips': [{
                          'ip_address': '127.0.0.1',
                          'subnet_id': '1234'
                      }],
                      'security_groups': ['5566']}})
        data_set.assert_called_once_with('internal_ports',
                                         '[{"id": "111222"}]')

    def test_build_nics_do_not_create_internal_port(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)
        self.port_create.return_value = {'port': {'id': '111222'}}
        data_set = self.patchobject(resource.Resource, 'data_set')

        network = [{'network': '4321'}]
        server._build_nics(network)

        self.assertFalse(self.port_create.called)
        self.assertFalse(data_set.called)

    def test_prepare_port_kwargs_with_extras(self):
        tmpl = """
        heat_template_version: 2015-10-15
        resources:
          server:
            type: OS::Nova::Server
            properties:
              flavor: m1.small
              image: F17-x86_64-gold
              networks:
                - network: 4321
                  subnet: 1234
                  fixed_ip: 127.0.0.1
                  port_extra_properties:
                    mac_address: 00:00:00:00:00:00
                    allowed_address_pairs:
                      - ip_address: 127.0.0.1
                        mac_address: None
                      - mac_address: 00:00:00:00:00:00

        """

        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)
        network = {'network': '4321', 'subnet': '1234',
                   'fixed_ip': '127.0.0.1',
                   'port_extra_properties': {
                       'value_specs': {},
                       'mac_address': '00:00:00:00:00:00',
                       'allowed_address_pairs': [
                           {'ip_address': '127.0.0.1',
                            'mac_address': None},
                           {'mac_address': '00:00:00:00:00:00'}
                       ]
                   }}
        sec_uuids = ['8d94c72093284da88caaef5e985d96f7']
        self.patchobject(neutron.NeutronClientPlugin,
                         'get_secgroup_uuids', return_value=sec_uuids)
        kwargs = server._prepare_internal_port_kwargs(
            network, security_groups=['test_sec'])
        self.assertEqual({'network_id': '4321',
                          'security_groups': sec_uuids,
                          'fixed_ips': [
                              {'ip_address': '127.0.0.1', 'subnet_id': '1234'}
                          ],
                          'mac_address': '00:00:00:00:00:00',
                          'allowed_address_pairs': [
                              {'ip_address': '127.0.0.1'},
                              {'mac_address': '00:00:00:00:00:00'}]},
                         kwargs)

    def test_build_nics_create_internal_port_without_net(self):
        tmpl = """
        heat_template_version: 2015-10-15
        resources:
          server:
            type: OS::Nova::Server
            properties:
              flavor: m1.small
              image: F17-x86_64-gold
              networks:
                - subnet: 1234
        """
        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)
        self.patchobject(neutron.NeutronClientPlugin,
                         'network_id_from_subnet_id',
                         return_value='4321')
        net = {'subnet': '1234'}
        net_id = server._get_network_id(net)

        self.assertEqual('4321', net_id)
        self.assertEqual({'subnet': '1234'}, net)
        self.port_create.return_value = {'port': {'id': '111222'}}
        data_set = self.patchobject(resource.Resource, 'data_set')

        network = [{'subnet': '1234'}]
        server._build_nics(network)

        self.port_create.assert_called_once_with(
            {'port': {'name': 'server-port-0',
                      'network_id': '4321',
                      'fixed_ips': [{
                          'subnet_id': '1234'
                      }]}})
        data_set.assert_called_once_with('internal_ports',
                                         '[{"id": "111222"}]')

    def test_calculate_networks_internal_ports(self):
        tmpl = """
        heat_template_version: 2015-10-15
        resources:
          server:
            type: OS::Nova::Server
            properties:
              flavor: m1.small
              image: F17-x86_64-gold
              networks:
                - network: 4321
                  subnet: 1234
                  fixed_ip: 127.0.0.1
                - port: 3344
        """

        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)
        data_mock = self.patchobject(server, '_data_get_ports')
        data_mock.side_effect = [[{"id": "1122"}], [{"id": "1122"}], []]
        self.port_create.return_value = {'port': {'id': '7788'}}
        data_set = self.patchobject(resource.Resource, 'data_set')

        old_net = [self.create_old_net(net='4321',
                                       subnet='1234',
                                       ip='127.0.0.1'),
                   self.create_old_net(port='3344')]

        new_net = [{'port': '3344'},
                   {'port': '5566'},
                   {'network': '4321',
                    'subnet': '5678',
                    'fixed_ip': '10.0.0.1'}
                   ]

        interfaces = [create_fake_iface(port='1122', net='4321',
                                        ip='127.0.0.1', subnet='1234'),
                      create_fake_iface(port='3344', net='4321', ip='10.0.0.2',
                                        subnet='subnet')]

        server.calculate_networks(old_net, new_net, interfaces)

        # we can only delete the port 1122,
        # port 3344 is external port, cant delete it
        self.port_delete.assert_called_once_with('1122')
        self.port_create.assert_called_once_with(
            {'port': {'name': 'server-port-1',
                      'network_id': '4321',
                      'fixed_ips': [{'subnet_id': '5678',
                                     'ip_address': '10.0.0.1'}]}})

        self.assertEqual(2, data_set.call_count)
        data_set.assert_has_calls((
            mock.call('internal_ports', '[]'),
            mock.call('internal_ports', '[{"id": "7788"}]')))

    def test_calculate_networks_internal_ports_with_fipa(self):
        tmpl = """
        heat_template_version: 2015-10-15
        resources:
          server:
            type: OS::Nova::Server
            properties:
              flavor: m1.small
              image: F17-x86_64-gold
              networks:
                - network: 4321
                  subnet: 1234
                  fixed_ip: 127.0.0.1
                  floating_ip: 1199
                - network: 8765
                  subnet: 5678
                  fixed_ip: 127.0.0.2
                  floating_ip: 9911
        """

        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)

        # NOTE(prazumovsky): this method update old_net and new_net with
        # interfaces' ports. Because of uselessness of checking this method,
        # we can afford to give port as part of calculate_networks args.
        self.patchobject(server, 'update_networks_matching_iface_port')

        server._data = {'internal_ports': '[{"id": "1122"}]'}
        self.port_create.return_value = {'port': {'id': '5566'}}
        self.patchobject(resource.Resource, 'data_set')
        self.resolve.side_effect = ['0912', '9021']

        fipa = self.patchobject(neutronclient.Client, 'update_floatingip',
                                side_effect=[neutronclient.exceptions.NotFound,
                                             '9911',
                                             '11910',
                                             '1199'])

        old_net = [
            self.create_old_net(net='4321', subnet='1234', ip='127.0.0.1',
                                port='1122', floating_ip='1199'),
            self.create_old_net(net='8765', subnet='5678', ip='127.0.0.2',
                                port='3344', floating_ip='9911')
        ]

        interfaces = [create_fake_iface(port='1122', net='4321',
                                        ip='127.0.0.1', subnet='1234'),
                      create_fake_iface(port='3344', net='8765',
                                        ip='127.0.0.2', subnet='5678')]

        new_net = [{'network': '8765',
                    'subnet': '5678',
                    'fixed_ip': '127.0.0.2',
                    'port': '3344',
                    'floating_ip': '11910'},
                   {'network': '0912',
                    'subnet': '9021',
                    'fixed_ip': '127.0.0.1',
                    'floating_ip': '1199',
                    'port': '1122'}]

        server.calculate_networks(old_net, new_net, interfaces)

        fipa.assert_has_calls((
            mock.call('1199', {'floatingip': {'port_id': None}}),
            mock.call('9911', {'floatingip': {'port_id': None}}),
            mock.call('11910',
                      {'floatingip': {'port_id': '3344',
                                      'fixed_ip_address': '127.0.0.2'}}),
            mock.call('1199',
                      {'floatingip': {'port_id': '1122',
                                      'fixed_ip_address': '127.0.0.1'}})
        ))

    def test_delete_fipa_with_exception_not_found_neutron(self):
        tmpl = """
        heat_template_version: 2015-10-15
        resources:
          server:
            type: OS::Nova::Server
            properties:
              flavor: m1.small
              image: F17-x86_64-gold
              networks:
                - network: 4321
                  subnet: 1234
                  fixed_ip: 127.0.0.1
                  floating_ip: 1199
                - network: 8765
                  subnet: 5678
                  fixed_ip: 127.0.0.2
                  floating_ip: 9911
        """

        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)
        delete_flip = mock.MagicMock(
            side_effect=[neutron.exceptions.NotFound(404)])
        server.client('neutron').update_floatingip = delete_flip

        self.assertIsNone(server._floating_ip_disassociate('flip123'))
        self.assertEqual(1, delete_flip.call_count)

    def test_delete_internal_ports(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)

        get_data = [{'internal_ports': '[{"id": "1122"}, {"id": "3344"}, '
                                       '{"id": "5566"}]'},
                    {'internal_ports': '[{"id": "1122"}, {"id": "3344"}, '
                                       '{"id": "5566"}]'},
                    {'internal_ports': '[{"id": "3344"}, '
                                       '{"id": "5566"}]'},
                    {'internal_ports': '[{"id": "5566"}]'}]
        self.patchobject(server, 'data', side_effect=get_data)
        data_set = self.patchobject(server, 'data_set')
        data_delete = self.patchobject(server, 'data_delete')

        server._delete_internal_ports()

        self.assertEqual(3, self.port_delete.call_count)
        self.assertEqual(('1122',), self.port_delete.call_args_list[0][0])
        self.assertEqual(('3344',), self.port_delete.call_args_list[1][0])
        self.assertEqual(('5566',), self.port_delete.call_args_list[2][0])

        self.assertEqual(3, data_set.call_count)
        data_set.assert_has_calls((
            mock.call('internal_ports',
                      '[{"id": "3344"}, {"id": "5566"}]'),
            mock.call('internal_ports', '[{"id": "5566"}]'),
            mock.call('internal_ports', '[]')))

        data_delete.assert_called_once_with('internal_ports')

    def test_get_data_internal_ports(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)

        server._data = {"internal_ports": '[{"id": "1122"}]'}
        data = server._data_get_ports()
        self.assertEqual([{"id": "1122"}], data)

        server._data = {"internal_ports": ''}
        data = server._data_get_ports()
        self.assertEqual([], data)

    def test_store_external_ports(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)

        class Fake(object):
            def interface_list(self):
                return [iface('1122'),
                        iface('1122'),
                        iface('2233'),
                        iface('3344')]

        server.client = mock.Mock()
        server.client().servers.get.return_value = Fake()
        server.client_plugin = mock.Mock()
        server.client_plugin().has_extension.return_value = True
        server._data = {"internal_ports": '[{"id": "1122"}]',
                        "external_ports": '[{"id": "3344"},{"id": "5566"}]'}

        iface = collections.namedtuple('iface', ['port_id'])
        update_data = self.patchobject(server, '_data_update_ports')

        server.store_external_ports()
        self.assertEqual(2, update_data.call_count)
        self.assertEqual(('5566', 'delete',),
                         update_data.call_args_list[0][0])
        self.assertEqual({'port_type': 'external_ports'},
                         update_data.call_args_list[0][1])
        self.assertEqual(('2233', 'add',),
                         update_data.call_args_list[1][0])
        self.assertEqual({'port_type': 'external_ports'},
                         update_data.call_args_list[1][1])

    def test_prepare_ports_for_replace_detach_failed(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)

        class Fake(object):
            def interface_list(self):
                return [iface(1122)]
        iface = collections.namedtuple('iface', ['port_id'])

        server.resource_id = 'ser-11'
        port_ids = [{'id': 1122}]

        server._data = {"internal_ports": jsonutils.dumps(port_ids)}
        self.patchobject(nova.NovaClientPlugin, 'client')
        self.patchobject(nova.NovaClientPlugin, 'interface_detach')
        self.patchobject(nova.NovaClientPlugin, 'fetch_server')
        self.patchobject(nova.NovaClientPlugin.check_interface_detach.retry,
                         'sleep')
        nova.NovaClientPlugin.fetch_server.side_effect = [Fake()] * 10

        exc = self.assertRaises(exception.InterfaceDetachFailed,
                                server.prepare_for_replace)
        self.assertIn('Failed to detach interface (1122) from server '
                      '(ser-11)',
                      six.text_type(exc))

    def test_prepare_ports_for_replace(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)
        server.resource_id = 'test_server'
        port_ids = [{'id': '1122'}, {'id': '3344'}]
        external_port_ids = [{'id': '5566'}]
        server._data = {"internal_ports": jsonutils.dumps(port_ids),
                        "external_ports": jsonutils.dumps(external_port_ids)}

        self.patchobject(nova.NovaClientPlugin, 'client')
        nova_server = self.fc.servers.list()[1]
        server.client().servers.get.return_value = nova_server

        self.patchobject(nova.NovaClientPlugin, 'interface_detach',
                         return_value=True)
        self.patchobject(nova.NovaClientPlugin, 'check_interface_detach',
                         return_value=True)

        server.prepare_for_replace()

        # check, that the ports were detached from server
        nova.NovaClientPlugin.interface_detach.assert_has_calls([
            mock.call('test_server', '1122'),
            mock.call('test_server', '3344'),
            mock.call('test_server', '5566')])

    def test_prepare_ports_for_replace_not_found(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)
        server.resource_id = 'test_server'
        port_ids = [{'id': '1122'}, {'id': '3344'}]
        external_port_ids = [{'id': '5566'}]
        server._data = {"internal_ports": jsonutils.dumps(port_ids),
                        "external_ports": jsonutils.dumps(external_port_ids)}
        self.patchobject(nova.NovaClientPlugin, 'client')
        self.patchobject(nova.NovaClientPlugin, 'fetch_server',
                         side_effect=nova_exceptions.NotFound(404))
        check_detach = self.patchobject(nova.NovaClientPlugin,
                                        'check_interface_detach')

        self.patchobject(nova.NovaClientPlugin, 'client')
        nova_server = self.fc.servers.list()[1]
        nova_server.status = 'DELETED'
        server.client().servers.get.return_value = nova_server

        server.prepare_for_replace()
        check_detach.assert_not_called()
        self.assertEqual(0, self.port_delete.call_count)

    def test_prepare_ports_for_replace_error_state(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)
        server.resource_id = 'test_server'
        port_ids = [{'id': '1122'}, {'id': '3344'}]
        external_port_ids = [{'id': '5566'}]
        server._data = {"internal_ports": jsonutils.dumps(port_ids),
                        "external_ports": jsonutils.dumps(external_port_ids)}

        self.patchobject(nova.NovaClientPlugin, 'client')
        nova_server = self.fc.servers.list()[1]
        nova_server.status = 'ERROR'
        server.client().servers.get.return_value = nova_server

        self.patchobject(nova.NovaClientPlugin, 'interface_detach',
                         return_value=True)
        self.patchobject(nova.NovaClientPlugin, 'check_interface_detach',
                         return_value=True)
        data_set = self.patchobject(server, 'data_set')
        data_delete = self.patchobject(server, 'data_delete')

        server.prepare_for_replace()

        # check, that the internal ports were deleted
        self.assertEqual(2, self.port_delete.call_count)
        self.assertEqual(('1122',), self.port_delete.call_args_list[0][0])
        self.assertEqual(('3344',), self.port_delete.call_args_list[1][0])
        data_set.assert_has_calls((
            mock.call('internal_ports',
                      '[{"id": "3344"}]'),
            mock.call('internal_ports', '[{"id": "1122"}]')))
        data_delete.assert_called_once_with('internal_ports')

    def test_prepare_ports_for_replace_not_created(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)
        prepare_mock = self.patchobject(server,
                                        'prepare_ports_for_replace')
        server.prepare_for_replace()

        self.assertIsNone(server.resource_id)
        self.assertEqual(0, prepare_mock.call_count)

    @mock.patch.object(server_network_mixin.ServerNetworkMixin,
                       'store_external_ports')
    def test_restore_ports_after_rollback(self, store_ports):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)
        server.resource_id = 'existing_server'
        port_ids = [{'id': 1122}, {'id': 3344}]
        external_port_ids = [{'id': 5566}]
        server._data = {"internal_ports": jsonutils.dumps(port_ids),
                        "external_ports": jsonutils.dumps(external_port_ids)}
        self.patchobject(nova.NovaClientPlugin, '_check_active')
        nova.NovaClientPlugin._check_active.side_effect = [False, True]

        # add data to old server in backup stack
        old_server = mock.Mock()
        old_server.resource_id = 'old_server'
        stack._backup_stack = mock.Mock()
        stack._backup_stack().resources.get.return_value = old_server
        old_server._data_get_ports.side_effect = [port_ids, external_port_ids]

        self.patchobject(nova.NovaClientPlugin, 'interface_detach',
                         return_value=True)
        self.patchobject(nova.NovaClientPlugin, 'check_interface_detach',
                         return_value=True)
        self.patchobject(nova.NovaClientPlugin, 'interface_attach')
        self.patchobject(nova.NovaClientPlugin, 'check_interface_attach',
                         return_value=True)

        server.restore_prev_rsrc()

        self.assertEqual(2, nova.NovaClientPlugin._check_active.call_count)

        # check, that ports were detached from new server
        nova.NovaClientPlugin.interface_detach.assert_has_calls([
            mock.call('existing_server', 1122),
            mock.call('existing_server', 3344),
            mock.call('existing_server', 5566)])

        # check, that ports were attached to old server
        nova.NovaClientPlugin.interface_attach.assert_has_calls([
            mock.call('old_server', 1122),
            mock.call('old_server', 3344),
            mock.call('old_server', 5566)])

    @mock.patch.object(server_network_mixin.ServerNetworkMixin,
                       'store_external_ports')
    def test_restore_ports_after_rollback_attach_failed(self, store_ports):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)
        server.resource_id = 'existing_server'
        port_ids = [{'id': 1122}, {'id': 3344}]
        server._data = {"internal_ports": jsonutils.dumps(port_ids)}
        self.patchobject(nova.NovaClientPlugin, '_check_active')
        nova.NovaClientPlugin._check_active.return_value = True

        # add data to old server in backup stack
        old_server = mock.Mock()
        old_server.resource_id = 'old_server'
        stack._backup_stack = mock.Mock()
        stack._backup_stack().resources.get.return_value = old_server
        old_server._data_get_ports.side_effect = [port_ids, []]

        class Fake(object):
            def interface_list(self):
                return [iface(1122)]
        iface = collections.namedtuple('iface', ['port_id'])

        self.patchobject(nova.NovaClientPlugin, 'interface_detach')
        self.patchobject(nova.NovaClientPlugin, 'check_interface_detach',
                         return_value=True)
        self.patchobject(nova.NovaClientPlugin, 'interface_attach')
        self.patchobject(nova.NovaClientPlugin, 'fetch_server')
        self.patchobject(nova.NovaClientPlugin.check_interface_attach.retry,
                         'sleep')
        # need to mock 11 times: 1 for port 1122, 10 for port 3344
        nova.NovaClientPlugin.fetch_server.side_effect = [Fake()] * 11

        exc = self.assertRaises(exception.InterfaceAttachFailed,
                                server.restore_prev_rsrc)
        self.assertIn('Failed to attach interface (3344) to server '
                      '(old_server)',
                      six.text_type(exc))

    @mock.patch.object(server_network_mixin.ServerNetworkMixin,
                       'store_external_ports')
    def test_restore_ports_after_rollback_convergence(self, store_ports):
        t = template_format.parse(tmpl_server_with_network_id)
        stack = utils.parse_stack(t)
        stack.store()
        self.patchobject(nova.NovaClientPlugin, '_check_active')
        nova.NovaClientPlugin._check_active.return_value = True

        # mock resource from previous template
        prev_rsrc = stack['server']
        # store in db
        prev_rsrc.state_set(prev_rsrc.UPDATE, prev_rsrc.COMPLETE)
        prev_rsrc.resource_id = 'prev_rsrc'

        # mock resource from existing template, store in db, and set _data
        resource_defns = stack.t.resource_definitions(stack)
        existing_rsrc = servers.Server('server', resource_defns['server'],
                                       stack)
        existing_rsrc.stack = stack
        existing_rsrc.current_template_id = stack.t.id
        existing_rsrc.resource_id = 'existing_rsrc'
        existing_rsrc.state_set(existing_rsrc.UPDATE, existing_rsrc.COMPLETE)

        port_ids = [{'id': 1122}, {'id': 3344}]
        external_port_ids = [{'id': 5566}]
        existing_rsrc.data_set("internal_ports", jsonutils.dumps(port_ids))
        existing_rsrc.data_set("external_ports",
                               jsonutils.dumps(external_port_ids))

        # mock previous resource was replaced by existing resource
        prev_rsrc.replaced_by = existing_rsrc.id

        self.patchobject(nova.NovaClientPlugin, 'interface_detach',
                         return_value=True)
        self.patchobject(nova.NovaClientPlugin, 'check_interface_detach',
                         return_value=True)
        self.patchobject(nova.NovaClientPlugin, 'interface_attach')
        self.patchobject(nova.NovaClientPlugin, 'check_interface_attach',
                         return_value=True)

        prev_rsrc.restore_prev_rsrc(convergence=True)

        # check, that ports were detached from existing server
        nova.NovaClientPlugin.interface_detach.assert_has_calls([
            mock.call('existing_rsrc', 1122),
            mock.call('existing_rsrc', 3344),
            mock.call('existing_rsrc', 5566)])

        # check, that ports were attached to old server
        nova.NovaClientPlugin.interface_attach.assert_has_calls([
            mock.call('prev_rsrc', 1122),
            mock.call('prev_rsrc', 3344),
            mock.call('prev_rsrc', 5566)])

    def test_store_external_ports_os_interface_not_installed(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)

        class Fake(object):
            def interface_list(self):
                return [iface('1122'),
                        iface('1122'),
                        iface('2233'),
                        iface('3344')]

        server.client = mock.Mock()
        server.client().servers.get.return_value = Fake()
        server.client_plugin = mock.Mock()
        server.client_plugin().has_extension.return_value = False

        server._data = {"internal_ports": '[{"id": "1122"}]',
                        "external_ports": '[{"id": "3344"},{"id": "5566"}]'}

        iface = collections.namedtuple('iface', ['port_id'])
        update_data = self.patchobject(server, '_data_update_ports')

        server.store_external_ports()
        self.assertEqual(0, update_data.call_count)
