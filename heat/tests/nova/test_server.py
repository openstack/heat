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
import mox
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient
from novaclient import exceptions as nova_exceptions
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
import six
from six.moves.urllib import parse as urlparse

from heat.common import exception
from heat.common.i18n import _
from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import neutron
from heat.engine.clients.os import nova
from heat.engine.clients.os import swift
from heat.engine.clients.os import zaqar
from heat.engine import environment
from heat.engine import resource
from heat.engine.resources.openstack.nova import server as servers
from heat.engine.resources import scheduler_hints as sh
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.objects import resource_data as resource_data_object
from heat.tests import common
from heat.tests.nova import fakes as fakes_nova
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
        "image" : "F17-x86_64-gold",
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

subnet_template = '''
heat_template_version: 2013-05-23
resources:
  server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      networks:
      - { uuid: 12345 }
  subnet:
    type: OS::Neutron::Subnet
    properties:
      network: 12345
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


class ServersTest(common.HeatTestCase):
    def setUp(self):
        super(ServersTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.limits = self.m.CreateMockAnything()
        self.limits.absolute = self._limits_absolute()

    def _limits_absolute(self):
        max_personality = self.m.CreateMockAnything()
        max_personality.name = 'maxPersonality'
        max_personality.value = 5
        max_personality_size = self.m.CreateMockAnything()
        max_personality_size.name = 'maxPersonalitySize'
        max_personality_size.value = 10240
        max_server_meta = self.m.CreateMockAnything()
        max_server_meta.name = 'maxServerMeta'
        max_server_meta.value = 3
        yield max_personality
        yield max_personality_size
        yield max_server_meta

    def _setup_test_stack(self, stack_name, test_templ=wp_template):
        t = template_format.parse(test_templ)
        templ = template.Template(t,
                                  env=environment.Environment(
                                      {'key_name': 'test'}))
        stack = parser.Stack(utils.dummy_context(), stack_name, templ,
                             stack_id=uuidutils.generate_uuid(),
                             stack_user_project_id='8888')
        return (templ, stack)

    def _prepare_server_check(self, status='ACTIVE'):
        templ, self.stack = self._setup_test_stack('server_check')
        server = self.fc.servers.list()[1]
        server.status = status
        res = self.stack['WebServer']
        res.client = mock.Mock()
        res.client().servers.get.return_value = server
        self.patchobject(res, 'store_external_ports')
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
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties'][
            'image'] = image_id or 'CentOS 5.2'
        tmpl.t['Resources']['WebServer']['Properties'][
            'flavor'] = '256 MB Server'

        if server_name is not None:
            tmpl.t['Resources']['WebServer']['Properties'][
                'name'] = server_name

        return tmpl, stack

    def _setup_test_server(self, return_server, name, image_id=None,
                           override_name=False, stub_create=True):
        stack_name = '%s_s' % name
        server_name = str(name) if override_name else None
        tmpl, self.stack = self._get_test_template(stack_name, server_name,
                                                   image_id)
        resource_defns = tmpl.resource_definitions(self.stack)
        server = servers.Server(str(name), resource_defns['WebServer'],
                                self.stack)

        self.patchobject(server, 'store_external_ports')

        self._mock_get_image_id_success(image_id or 'CentOS 5.2', 1)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)

        if stub_create:
            self.m.StubOutWithMock(self.fc.servers, 'create')
            self.fc.servers.create(
                image=1, flavor=1, key_name='test',
                name=override_name and server.name or utils.PhysName(
                    stack_name, server.name),
                security_groups=[],
                userdata=mox.IgnoreArg(), scheduler_hints=None,
                meta=None, nics=None, availability_zone=None,
                block_device_mapping=None, block_device_mapping_v2=None,
                config_drive=None, disk_config=None, reservation_id=None,
                files={}, admin_pass=None).AndReturn(return_server)
            # mock check_create_complete innards
            self.m.StubOutWithMock(self.fc.servers, 'get')
            self.fc.servers.get(return_server.id).AndReturn(return_server)

        return server

    def _create_test_server(self, return_server, name, override_name=False,
                            stub_create=True):
        server = self._setup_test_server(return_server, name,
                                         stub_create=stub_create)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.UnsetStubs()
        return server

    def _stub_glance_for_update(self, image_id=None, rebuild=False):
        if rebuild:
            image = 'F17-x86_64-gold'
            imageId = 744
        else:
            image = image_id or 'CentOS 5.2'
            imageId = 1

        self._mock_get_image_id_success(image, imageId)

    def _create_fake_iface(self, port, mac, ip):
        class fake_interface(object):
            def __init__(self, port_id, mac_addr, fixed_ip):
                self.port_id = port_id
                self.mac_addr = mac_addr
                self.fixed_ips = [{'ip_address': fixed_ip}]

        return fake_interface(port, mac, ip)

    def _mock_get_image_id_success(self, imageId_input, imageId):
        self.m.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
        glance.GlanceClientPlugin.get_image_id(
            imageId_input).MultipleTimes().AndReturn(imageId)

    def _mock_get_image_id_fail(self, image_id, exp):
        self.m.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
        glance.GlanceClientPlugin.get_image_id(image_id).AndRaise(exp)

    def _mock_get_keypair_success(self, keypair_input, keypair):
        self.m.StubOutWithMock(nova.NovaClientPlugin, 'get_keypair')
        nova.NovaClientPlugin.get_keypair(
            keypair_input).MultipleTimes().AndReturn(keypair)

    def _server_validate_mock(self, server):
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_VolumeConstraint_validate()

    def test_subnet_dependency(self):
        template, stack = self._setup_test_stack('subnet-test',
                                                 subnet_template)
        server_rsrc = stack['server']
        subnet_rsrc = stack['subnet']
        deps = []
        server_rsrc.add_dependencies(deps)
        self.assertEqual(4, len(deps))
        self.assertEqual(subnet_rsrc, deps[3])

    def test_subnet_nodeps(self):
        template, stack = self._setup_test_stack('subnet-test',
                                                 no_subnet_template)
        server_rsrc = stack['server']
        subnet_rsrc = stack['subnet']
        deps = []
        server_rsrc.add_dependencies(deps)
        self.assertEqual(2, len(deps))
        self.assertNotIn(subnet_rsrc, deps)

    def test_server_create(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server_name = 'test_server_create'
        stack_name = '%s_s' % server_name
        server = self._create_test_server(return_server, server_name)

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        interfaces = [
            self._create_fake_iface('1234', 'fa:16:3e:8c:22:aa', '4.5.6.7'),
            self._create_fake_iface('5678', 'fa:16:3e:8c:33:bb', '5.6.9.8'),
            self._create_fake_iface(
                '1013', 'fa:16:3e:8c:44:cc', '10.13.12.13')]

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('5678').MultipleTimes().AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'interface_list')
        return_server.interface_list().MultipleTimes().AndReturn(interfaces)
        self.m.ReplayAll()

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
        self.assertIn(
            server.FnGetAtt('first_address'), (private_ip, public_ip))

        self.assertEqual(return_server._info, server.FnGetAtt('show'))
        self.assertEqual('sample-server2', server.FnGetAtt('instance_name'))
        self.assertEqual('192.0.2.0', server.FnGetAtt('accessIPv4'))
        self.assertEqual('::babe:4317:0A83', server.FnGetAtt('accessIPv6'))

        expected_name = utils.PhysName(stack_name, server.name)
        self.assertEqual(expected_name, server.FnGetAtt('name'))

        self.m.VerifyAll()

    def test_server_create_metadata(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'create_metadata_test_stack'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl['Resources']['WebServer']['Properties'][
            'metadata'] = {'a': 1}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('create_metadata_test_server',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        instance_meta = {'a': "1"}
        image_id = mox.IgnoreArg()
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=image_id, flavor=mox.IgnoreArg(), key_name='test',
            name=mox.IgnoreArg(), security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=instance_meta, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(return_server)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', image_id)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_server_create_with_image_id(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server_name = 'test_server_create_image_id'
        server = self._setup_test_server(return_server,
                                         server_name,
                                         image_id='1',
                                         override_name=True)

        interfaces = [
            self._create_fake_iface('1234', 'fa:16:3e:8c:22:aa', '4.5.6.7'),
            self._create_fake_iface('5678', 'fa:16:3e:8c:33:bb', '5.6.9.8'),
            self._create_fake_iface(
                '1013', 'fa:16:3e:8c:44:cc', '10.13.12.13')]

        self.fc.servers.get('5678').MultipleTimes().AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'interface_list')
        return_server.interface_list().MultipleTimes().AndReturn(interfaces)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

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
        self.assertIn(
            server.FnGetAtt('first_address'), (private_ip, public_ip))

        self.assertEqual(server_name, server.FnGetAtt('name'))

        self.m.VerifyAll()

    def test_server_create_image_name_err(self):
        stack_name = 'img_name_err'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image name
        tmpl['Resources']['WebServer']['Properties']['image'] = 'Slackware'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)

        self._mock_get_image_id_fail('Slackware',
                                     exception.EntityNotFound(
                                         entity='Image',
                                         name='Slackware'))
        self.stub_FlavorConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.m.ReplayAll()

        create = scheduler.TaskRunner(server.create)
        error = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual(
            "StackValidationFailed: resources.WebServer: Property error: "
            "WebServer.Properties.image: Error validating value 'Slackware': "
            "The Image (Slackware) could not be found.",
            six.text_type(error))

        self.m.VerifyAll()

    def test_server_create_duplicate_image_name_err(self):
        stack_name = 'img_dup_err'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        # create an server with a non unique image name
        tmpl['Resources']['WebServer']['Properties']['image'] = 'CentOS 5.2'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)

        self._mock_get_image_id_fail('CentOS 5.2',
                                     exception.PhysicalResourceNameAmbiguity(
                                         name='CentOS 5.2'))
        self.stub_FlavorConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.m.ReplayAll()

        create = scheduler.TaskRunner(server.create)
        error = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual(
            'StackValidationFailed: resources.WebServer: Property error: '
            'WebServer.Properties.image: Multiple physical '
            'resources were found with name (CentOS 5.2).',
            six.text_type(error))

        self.m.VerifyAll()

    def test_server_create_image_id_err(self):
        stack_name = 'img_id_err'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        tmpl['Resources']['WebServer']['Properties']['image'] = '1'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)

        self._mock_get_image_id_fail('1',
                                     exception.EntityNotFound(
                                         entity='Image', name='1'))
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()

        create = scheduler.TaskRunner(server.create)
        error = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual(
            "StackValidationFailed: resources.WebServer: Property error: "
            "WebServer.Properties.image: Error validating value '1': "
            "The Image (1) could not be found.",
            six.text_type(error))

        self.m.VerifyAll()

    def test_server_create_unexpected_status(self):
        # NOTE(pshchelo) checking is done only on check_create_complete
        # level so not to mock out all delete/retry logic that kicks in
        # on resource create failure
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'cr_unexp_sts')
        self.m.StubOutWithMock(self.fc.servers, 'get')
        return_server.status = 'BOGUS'
        self.fc.servers.get(server.resource_id).AndReturn(return_server)
        self.m.ReplayAll()

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
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndReturn(return_server)
        self.m.ReplayAll()

        e = self.assertRaises(exception.ResourceInError,
                              server.check_create_complete,
                              server.resource_id)
        self.assertEqual(
            'Went to status ERROR due to "Message: NoValidHost, Code: 500"',
            six.text_type(e))

        self.m.VerifyAll()

    def test_server_create_raw_userdata(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'raw_userdata_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl['Resources']['WebServer']['Properties'][
            'user_data_format'] = 'RAW'

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata='wordpress', scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_server_create_raw_config_userdata(self):
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

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata='wordpress from config', scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_server_create_raw_config_userdata_None(self):
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

        self.rpc_client.show_software_config.side_effect = exception.NotFound

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=sc_id,
            scheduler_hints=None, meta=None,
            nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def _server_create_software_config(self, md=None,
                                       stack_name='software_config_s',
                                       ret_tmpl=False):
        return_server = self.fc.servers.list()[1]
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.stack = stack

        tmpl['Resources']['WebServer']['Properties'][
            'user_data_format'] = 'SOFTWARE_CONFIG'
        if md is not None:
            tmpl['Resources']['WebServer']['Metadata'] = md

        stack.stack_user_project_id = '8888'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        self.m.StubOutWithMock(server, 'heat')

        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()

        self.assertEqual('4567', server.access_key)
        self.assertEqual('8901', server.secret_key)
        self.assertEqual('1234', server._get_user_id())
        self.assertEqual('POLL_SERVER_CFN',
                         server.properties.get('software_config_transport'))

        self.assertTrue(stack.access_allowed('4567', 'WebServer'))
        self.assertFalse(stack.access_allowed('45678', 'WebServer'))
        self.assertFalse(stack.access_allowed('4567', 'wWebServer'))
        self.m.VerifyAll()
        if ret_tmpl:
            return server, tmpl
        else:
            return server

    def test_server_create_software_config(self):
        server = self._server_create_software_config()

        self.assertEqual({
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': '/v1/',
                    'path': 'WebServer.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'software_config_s'
                }
            },
            'deployments': []
        }, server.metadata_get())

    def test_server_create_software_config_metadata(self):
        md = {'os-collect-config': {'polling_interval': 10}}
        server = self._server_create_software_config(md=md)

        self.assertEqual({
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': '/v1/',
                    'path': 'WebServer.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'software_config_s'
                },
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def _server_create_software_config_poll_heat(self, md=None):
        return_server = self.fc.servers.list()[1]
        stack_name = 'software_config_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        props = tmpl.t['Resources']['WebServer']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        props['software_config_transport'] = 'POLL_SERVER_HEAT'
        if md is not None:
            tmpl.t['Resources']['WebServer']['Metadata'] = md

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')

        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()

        self.assertEqual('1234', server._get_user_id())

        self.assertTrue(stack.access_allowed('1234', 'WebServer'))
        self.assertFalse(stack.access_allowed('45678', 'WebServer'))
        self.assertFalse(stack.access_allowed('4567', 'wWebServer'))
        self.m.VerifyAll()
        return stack, server

    def test_server_create_software_config_poll_heat(self):
        stack, server = self._server_create_software_config_poll_heat()

        self.assertEqual({
            'os-collect-config': {
                'heat': {
                    'auth_url': 'http://server.test:5000/v2.0',
                    'password': server.password,
                    'project_id': '8888',
                    'resource_name': 'WebServer',
                    'stack_id': 'software_config_s/%s' % stack.id,
                    'user_id': '1234'
                }
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
                    'resource_name': 'WebServer',
                    'stack_id': 'software_config_s/%s' % stack.id,
                    'user_id': '1234'
                },
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def _server_create_software_config_poll_temp_url(self, md=None):
        return_server = self.fc.servers.list()[1]
        stack_name = 'software_config_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        props = tmpl.t['Resources']['WebServer']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        props['software_config_transport'] = 'POLL_TEMP_URL'
        if md is not None:
            tmpl.t['Resources']['WebServer']['Metadata'] = md

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        self.m.StubOutWithMock(swift.SwiftClientPlugin, '_create')

        sc = mock.Mock()
        sc.head_account.return_value = {
            'x-account-meta-temp-url-key': 'secrit'
        }
        sc.url = 'http://192.0.2.2'

        swift.SwiftClientPlugin._create().AndReturn(sc)
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
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

        sc.head_container.return_value = {'x-container-object-count': '0'}
        server._delete_temp_url()
        sc.delete_object.assert_called_once_with(container_name, object_name)
        sc.head_container.assert_called_once_with(container_name)
        sc.delete_container.assert_called_once_with(container_name)

        self.m.VerifyAll()
        return metadata_url, server

    def test_server_create_software_config_poll_temp_url(self):
        metadata_url, server = \
            self._server_create_software_config_poll_temp_url()

        self.assertEqual({
            'os-collect-config': {
                'request': {
                    'metadata_url': metadata_url
                }
            },
            'deployments': []
        }, server.metadata_get())

    def test_server_create_software_config_poll_temp_url_metadata(self):
        md = {'os-collect-config': {'polling_interval': 10}}
        metadata_url, server = \
            self._server_create_software_config_poll_temp_url(md=md)

        self.assertEqual({
            'os-collect-config': {
                'request': {
                    'metadata_url': metadata_url
                },
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def _server_create_software_config_zaqar(self, md=None):
        return_server = self.fc.servers.list()[1]
        stack_name = 'software_config_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        props = tmpl.t['Resources']['WebServer']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        props['software_config_transport'] = 'ZAQAR_MESSAGE'
        if md is not None:
            tmpl.t['Resources']['WebServer']['Metadata'] = md

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        ncp = self.patchobject(nova.NovaClientPlugin, '_create')
        zcc = self.patchobject(zaqar.ZaqarClientPlugin, 'create_for_tenant')
        zc = mock.Mock()

        ncp.return_value = self.fc
        zcc.return_value = zc
        queue = mock.Mock()
        zc.queue.return_value = queue
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
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

        self.m.VerifyAll()
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
                    'queue_id': queue_id
                }
            },
            'deployments': []
        }, server.metadata_get())

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
                    'queue_id': queue_id
                },
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    @mock.patch.object(nova.NovaClientPlugin, '_create')
    def test_server_create_default_admin_pass(self, mock_client):
        return_server = self.fc.servers.list()[1]
        return_server.adminPass = 'autogenerated'
        stack_name = 'admin_pass_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        mock_client.return_value = self.fc
        self.fc.servers.create = mock.Mock(return_value=return_server)
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        scheduler.TaskRunner(server.create)()
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mock.ANY, scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None)

    @mock.patch.object(nova.NovaClientPlugin, '_create')
    def test_server_create_custom_admin_pass(self, mock_client):
        return_server = self.fc.servers.list()[1]
        return_server.adminPass = 'foo'
        stack_name = 'admin_pass_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties']['admin_pass'] = 'foo'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        mock_client.return_value = self.fc
        self.fc.servers.create = mock.Mock(return_value=return_server)
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        scheduler.TaskRunner(server.create)()
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mock.ANY, scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass='foo')

    def test_server_create_with_stack_scheduler_hints(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        sh.cfg.CONF.set_override('stack_scheduler_hints', True)
        # Unroll _create_test_server, to enable check
        # for addition of heat ids (stack id, resource name)
        stack_name = 'test_server_w_stack_sched_hints_s'
        server_name = 'server_w_stack_sched_hints'
        (t, stack) = self._get_test_template(stack_name, server_name)

        resource_defns = t.resource_definitions(stack)
        server = servers.Server(server_name,
                                resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        # server.uuid is only available once the resource has been added.
        stack.add_resource(server)
        self.assertIsNotNone(server.uuid)

        self._mock_get_image_id_success('CentOS 5.2', 1)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().MultipleTimes().AndReturn(self.fc)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        shm = sh.SchedulerHintsMixin
        self.fc.servers.create(
            image=1, flavor=1, key_name='test',
            name=server_name,
            security_groups=[],
            userdata=mox.IgnoreArg(),
            scheduler_hints={shm.HEAT_ROOT_STACK_ID: stack.root_stack_id(),
                             shm.HEAT_STACK_ID: stack.id,
                             shm.HEAT_STACK_NAME: stack.name,
                             shm.HEAT_PATH_IN_STACK: [(None, stack.name)],
                             shm.HEAT_RESOURCE_NAME: server.name,
                             shm.HEAT_RESOURCE_UUID: server.uuid},
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        self.m.VerifyAll()

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

        tmpl.t['Resources']['WebServer']['Properties']['image'] = '1'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('1', 1)

        self.m.ReplayAll()

        self.assertIsNone(server.validate())

        self.m.VerifyAll()

    def test_server_validate_with_bootable_vol(self):
        stack_name = 'srv_val_bootvol'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        # create an server with bootable volume
        web_server = tmpl.t['Resources']['WebServer']
        del web_server['Properties']['image']

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.stub_VolumeConstraint_validate()
        self.m.ReplayAll()

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
        self.m.VerifyAll()

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
        stack = parser.Stack(utils.dummy_context(), stack_name, templ,
                             stack_id=uuidutils.generate_uuid())

        resource_defns = templ.resource_definitions(stack)
        server = servers.Server('server_validate_test',
                                resource_defns['WebServer'], stack)
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()

        self.m.ReplayAll()

        self.assertIsNone(server.validate())

        self.m.VerifyAll()

    def test_server_validate_with_invalid_ssh_key(self):
        stack_name = 'srv_val_test'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        web_server = tmpl['Resources']['WebServer']

        # Make the ssh key have an invalid name
        web_server['Properties']['key_name'] = 'test2'

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        error = self.assertRaises(exception.StackValidationFailed,
                                  server.validate)
        self.assertEqual(
            "Property error: Resources.WebServer.Properties.key_name: "
            "Error validating value 'test2': The Key (test2) could not "
            "be found.", six.text_type(error))
        self.m.VerifyAll()

    def test_server_validate_software_config_invalid_meta(self):
        stack_name = 'srv_val_test'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        web_server = tmpl['Resources']['WebServer']
        web_server['Properties']['user_data_format'] = 'SOFTWARE_CONFIG'
        web_server['Metadata'] = {'deployments': 'notallowed'}

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('WebServer',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        error = self.assertRaises(exception.StackValidationFailed,
                                  server.validate)
        self.assertEqual(
            "deployments key not allowed in resource metadata "
            "with user_data_format of SOFTWARE_CONFIG", six.text_type(error))
        self.m.VerifyAll()

    def test_server_validate_with_networks(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        network_name = 'public'
        # create an server with 'uuid' and 'network' properties
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'uuid': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
              'network': network_name}])

        resource_defns = tmpl.resource_definitions(stack)
        ex = self.assertRaises(ValueError, servers.Server,
                               'server_validate_with_networks',
                               resource_defns['WebServer'], stack)

        self.assertIn(_('Cannot use network and uuid at the same time.'),
                      six.text_type(ex))

    def test_server_validate_with_network_empty_ref(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'network': ''}])

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_NetworkConstraint_validate()
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_with_only_fixed_ip(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        # create an server with 'uuid' and 'network' properties
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'fixed_ip': '10.0.0.99'}])

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_NetworkConstraint_validate()
        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertIn(_('One of the properties "network", "port", "uuid" or '
                        '"subnet" should be set for the specified network of '
                        'server "%s".') % server.name,
                      six.text_type(ex))
        self.m.VerifyAll()

    def test_server_validate_with_port_fixed_ip(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'port': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
              'fixed_ip': '10.0.0.99'}])

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_NetworkConstraint_validate()
        self.stub_PortConstraint_validate()
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_with_uuid_fixed_ip(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'uuid': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
              'fixed_ip': '10.0.0.99'}])

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_NetworkConstraint_validate()

        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_with_network_fixed_ip(self):
        stack_name = 'srv_net'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        tmpl['Resources']['WebServer']['Properties']['networks'] = (
            [{'network': 'public',
              'fixed_ip': '10.0.0.99'}])

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_with_networks',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_NetworkConstraint_validate()

        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_net_security_groups(self):
        # Test that if network 'ports' are assigned security groups are
        # not, because they'll be ignored
        stack_name = 'srv_net_secgroups'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl['Resources']['WebServer']['Properties']['networks'] = [
            {'port': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}]
        tmpl['Resources']['WebServer']['Properties'][
            'security_groups'] = ['my_security_group']

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_validate_net_security_groups',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)

        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_PortConstraint_validate()
        self.m.ReplayAll()

        error = self.assertRaises(exception.ResourcePropertyConflict,
                                  server.validate)
        self.assertEqual("Cannot define the following properties at the same "
                         "time: security_groups, networks/port.",
                         six.text_type(error))
        self.m.VerifyAll()

    def test_server_delete(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete')
        server.resource_id = '1234'

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndReturn(server)
        self.fc.servers.get(server.resource_id).AndRaise(
            fakes_nova.fake_exception())
        self.m.ReplayAll()

        scheduler.TaskRunner(server.delete)()
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_delete_notfound(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete2')
        server.resource_id = '1234'

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        self.m.StubOutWithMock(self.fc.client, 'delete_servers_1234')
        self.fc.client.delete_servers_1234().AndRaise(
            fakes_nova.fake_exception())
        self.m.ReplayAll()

        scheduler.TaskRunner(server.delete)()
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_delete_error(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete')
        server.resource_id = '1234'

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        def make_error(*args):
            return_server.status = "ERROR"

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndReturn(return_server)
        self.fc.servers.get(server.resource_id).AndReturn(return_server)
        self.fc.servers.get(server.resource_id).WithSideEffects(
            make_error).AndReturn(return_server)
        self.m.ReplayAll()

        resf = self.assertRaises(exception.ResourceFailure,
                                 scheduler.TaskRunner(server.delete))
        self.assertIn("Server %s delete failed" % return_server.name,
                      six.text_type(resf))

        self.m.VerifyAll()

    def test_server_delete_error_task_in_progress(self):
        # test server in 'ERROR', but task state in nova is 'deleting'
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete')
        server.resource_id = '1234'

        def make_error(*args):
            return_server.status = "ERROR"
            setattr(return_server, 'OS-EXT-STS:task_state', 'deleting')

        def make_error_done(*args):
            return_server.status = "ERROR"
            setattr(return_server, 'OS-EXT-STS:task_state', None)

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).WithSideEffects(
            make_error).AndReturn(return_server)
        self.fc.servers.get(server.resource_id).WithSideEffects(
            make_error_done).AndReturn(return_server)
        self.m.ReplayAll()

        resf = self.assertRaises(exception.ResourceFailure,
                                 scheduler.TaskRunner(server.delete))
        self.assertIn("Server %s delete failed" % return_server.name,
                      six.text_type(resf))
        self.m.VerifyAll()

    def test_server_soft_delete(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete')
        server.resource_id = '1234'

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        def make_soft_delete(*args):
            return_server.status = "SOFT_DELETED"

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndReturn(return_server)
        self.fc.servers.get(server.resource_id).AndReturn(return_server)
        self.fc.servers.get(server.resource_id).WithSideEffects(
            make_soft_delete).AndReturn(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.delete)()
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_metadata(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')

        self._stub_glance_for_update()
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

    def test_server_update_metadata_software_config(self):
        server, ud_tmpl = self._server_create_software_config(
            stack_name='update_meta_sc', ret_tmpl=True)

        expected_md = {
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': '/v1/',
                    'path': 'WebServer.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'update_meta_sc'
                }
            },
            'deployments': []}
        self.assertEqual(expected_md, server.metadata_get())

        self.m.UnsetStubs()
        self._stub_glance_for_update()

        ud_tmpl.t['Resources']['WebServer']['Metadata'] = {'test': 123}
        resource_defns = ud_tmpl.resource_definitions(server.stack)
        scheduler.TaskRunner(server.update, resource_defns['WebServer'])()
        expected_md.update({'test': 123})
        self.assertEqual(expected_md, server.metadata_get())
        server.metadata_update()
        self.assertEqual(expected_md, server.metadata_get())

    def test_server_update_metadata_software_config_merge(self):
        md = {'os-collect-config': {'polling_interval': 10}}
        server, ud_tmpl = self._server_create_software_config(
            stack_name='update_meta_sc', ret_tmpl=True,
            md=md)

        expected_md = {
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': '/v1/',
                    'path': 'WebServer.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'update_meta_sc'
                },
                'polling_interval': 10
            },
            'deployments': []}
        self.assertEqual(expected_md, server.metadata_get())

        self.m.UnsetStubs()
        self._stub_glance_for_update()

        ud_tmpl.t['Resources']['WebServer']['Metadata'] = {'test': 123}
        resource_defns = ud_tmpl.resource_definitions(server.stack)
        scheduler.TaskRunner(server.update, resource_defns['WebServer'])()
        expected_md.update({'test': 123})
        self.assertEqual(expected_md, server.metadata_get())
        server.metadata_update()
        self.assertEqual(expected_md, server.metadata_get())

    def test_server_update_nova_metadata(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')

        new_meta = {'test': 123}
        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndReturn(return_server)
        self.m.StubOutWithMock(self.fc.servers, 'set_meta')
        self.fc.servers.set_meta(return_server,
                                 server.client_plugin().meta_serialize(
                                     new_meta)).AndReturn(None)
        self.m.ReplayAll()
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['metadata'] = new_meta
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_nova_metadata_complex(self):
        """Test that complex metadata values are correctly serialized to JSON.

        Test that complex metadata values are correctly serialized to JSON when
        sent to Nova.
        """

        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndReturn(return_server)
        new_meta = {'test': {'testkey': 'testvalue'}}
        self.m.StubOutWithMock(self.fc.servers, 'set_meta')

        # If we're going to call set_meta() directly we
        # need to handle the serialization ourselves.
        self.fc.servers.set_meta(return_server,
                                 server.client_plugin().meta_serialize(
                                     new_meta)).AndReturn(None)
        self.m.ReplayAll()
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['metadata'] = new_meta
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_nova_metadata_with_delete(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')

        # part one, add some metadata
        self._stub_glance_for_update()
        new_meta = {'test': '123', 'this': 'that'}
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndReturn(return_server)
        self.m.StubOutWithMock(self.fc.servers, 'set_meta')
        self.fc.servers.set_meta(return_server,
                                 new_meta).AndReturn(None)
        self.m.ReplayAll()
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['metadata'] = new_meta
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()
        self.m.UnsetStubs()

        # part two change the metadata (test removing the old key)
        self.m.ReplayAll()
        new_meta = {'new_key': 'yeah'}
        # new fake with the correct metadata
        server.resource_id = '56789'

        new_return_server = self.fc.servers.list()[5]
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndReturn(new_return_server)
        self.m.StubOutWithMock(self.fc.servers, 'delete_meta')
        self.fc.servers.delete_meta(new_return_server,
                                    ['test', 'this']).AndReturn(None)

        self.m.StubOutWithMock(self.fc.servers, 'set_meta')
        self.fc.servers.set_meta(new_return_server,
                                 new_meta).AndReturn(None)
        self._mock_get_image_id_success('CentOS 5.2', 1)
        self.m.ReplayAll()
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['metadata'] = new_meta

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_server_name(self):
        """Server.handle_update supports changing the name."""
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server = self._create_test_server(return_server,
                                          'srv_update')
        new_name = 'new_name'
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['name'] = new_name

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('5678').AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'update')
        return_server.update(new_name).AndReturn(None)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_server_admin_password(self):
        """Server.handle_update supports changing the admin password."""
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server = self._create_test_server(return_server,
                                          'change_password')
        self._stub_glance_for_update()
        new_password = 'new_password'
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['admin_pass'] = new_password

        self.patchobject(self.fc.servers, 'get', return_value=return_server)
        self.patchobject(return_server, 'change_password')

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        return_server.change_password.assert_called_once_with(new_password)
        self.assertEqual(1, return_server.change_password.call_count)

    def test_server_update_server_flavor(self):
        """Tests update server changing the flavor.

        Server.handle_update supports changing the flavor, and makes
        the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'srv_update')

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['flavor'] = 'm1.small'

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')

        def status_resize(*args):
            return_server.status = 'RESIZE'

        def status_verify_resize(*args):
            return_server.status = 'VERIFY_RESIZE'

        def status_active(*args):
            return_server.status = 'ACTIVE'

        self.fc.servers.get('1234').WithSideEffects(
            status_active).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_resize).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_verify_resize).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_verify_resize).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_active).AndReturn(return_server)

        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')
        self.fc.client.post_servers_1234_action(
            body={'resize': {'flavorRef': 2}}).AndReturn((202, None))
        self.fc.client.post_servers_1234_action(
            body={'confirmResize': None}).AndReturn((202, None))
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_server_flavor_failed(self):
        """Check raising exception due to resize call failing.

        If the status after a resize is not VERIFY_RESIZE, it means the resize
        call failed, so we raise an explicit error.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'srv_update2')

        self._stub_glance_for_update()
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['flavor'] = 'm1.small'

        self.m.StubOutWithMock(self.fc.servers, 'get')

        def status_resize(*args):
            return_server.status = 'RESIZE'

        def status_error(*args):
            return_server.status = 'ERROR'

        self.fc.servers.get('1234').AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_resize).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_error).AndReturn(return_server)

        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')
        self.fc.client.post_servers_1234_action(
            body={'resize': {'flavorRef': 2}}).AndReturn((202, None))
        self.m.ReplayAll()

        updater = scheduler.TaskRunner(server.update, update_template)
        error = self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual(
            "Error: resources.srv_update2: Resizing to 'm1.small' failed, "
            "status 'ERROR'", six.text_type(error))
        self.assertEqual((server.UPDATE, server.FAILED), server.state)
        self.m.VerifyAll()

    def test_server_update_flavor_resize_has_not_started(self):
        """Test update of server flavour if server resize has not started.

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
        update_template = copy.deepcopy(server_resource.t)
        update_template['Properties']['flavor'] = 'm1.small'

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')

        # define status transition when server resize
        # ACTIVE(initial) -> ACTIVE -> RESIZE -> VERIFY_RESIZE

        def status_resize(*args):
            server.status = 'RESIZE'

        def status_verify_resize(*args):
            server.status = 'VERIFY_RESIZE'

        def status_active(*args):
            server.status = 'ACTIVE'

        self.fc.servers.get('1234').WithSideEffects(
            status_active).AndReturn(server)
        self.fc.servers.get('1234').WithSideEffects(
            status_active).AndReturn(server)
        self.fc.servers.get('1234').WithSideEffects(
            status_resize).AndReturn(server)
        self.fc.servers.get('1234').WithSideEffects(
            status_verify_resize).AndReturn(server)
        self.fc.servers.get('1234').WithSideEffects(
            status_verify_resize).AndReturn(server)
        self.fc.servers.get('1234').WithSideEffects(
            status_active).AndReturn(server)

        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')
        self.fc.client.post_servers_1234_action(
            body={'resize': {'flavorRef': 2}}).AndReturn((202, None))
        self.fc.client.post_servers_1234_action(
            body={'confirmResize': None}).AndReturn((202, None))
        self.m.ReplayAll()
        # check that server resize has finished correctly
        scheduler.TaskRunner(server_resource.update, update_template)()
        self.assertEqual((server_resource.UPDATE, server_resource.COMPLETE),
                         server_resource.state)
        self.m.VerifyAll()

    def test_server_update_server_flavor_replace(self):
        stack_name = 'update_flvrep'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()
        self.patchobject(servers.Server, 'prepare_for_replace')

        tmpl['Resources']['WebServer']['Properties'][
            'flavor_update_policy'] = 'REPLACE'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_server_update_flavor_replace',
                                resource_defns['WebServer'], stack)

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['flavor'] = 'm1.small'
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(exception.UpdateReplace, updater)

    def test_server_update_server_flavor_policy_update(self):
        stack_name = 'update_flvpol'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        self.patchobject(servers.Server, 'prepare_for_replace')
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_server_update_flavor_replace',
                                resource_defns['WebServer'], stack)

        update_template = copy.deepcopy(server.t)
        # confirm that when flavor_update_policy is changed during
        # the update then the updated policy is followed for a flavor
        # update
        update_template['Properties']['flavor_update_policy'] = 'REPLACE'
        update_template['Properties']['flavor'] = 'm1.small'
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(exception.UpdateReplace, updater)

    def test_server_update_image_replace(self):
        stack_name = 'update_imgrep'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        self.patchobject(servers.Server, 'prepare_for_replace')

        tmpl.t['Resources']['WebServer']['Properties'][
            'image_update_policy'] = 'REPLACE'
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_update_image_replace',
                                resource_defns['WebServer'], stack)
        image_id = self.getUniqueString()
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.stub_ImageConstraint_validate()

        self.m.ReplayAll()

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = image_id
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(exception.UpdateReplace, updater)

    def _test_server_update_image_rebuild(self, status, policy='REBUILD',
                                          password=None):
        # Server.handle_update supports changing the image, and makes
        # the change making a rebuild API call against Nova.
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'srv_updimgrbld')

        new_image = 'F17-x86_64-gold'
        self._stub_glance_for_update(rebuild=True)
        # current test demonstrate updating when image_update_policy was not
        # changed, so image_update_policy will be used from self.properties
        server.t['Properties']['image_update_policy'] = policy

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = new_image
        if password:
            update_template['Properties']['admin_pass'] = password

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('1234').AndReturn(return_server)
        self.m.StubOutWithMock(self.fc.servers, 'rebuild')
        # 744 is a static lookup from the fake images list
        if 'REBUILD' == policy:
            self.fc.servers.rebuild(
                return_server, 744, password=password,
                preserve_ephemeral=False)
        else:
            self.fc.servers.rebuild(
                return_server, 744, password=password,
                preserve_ephemeral=True)
        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')

        def get_sideeff(stat):
            def sideeff(*args):
                return_server.status = stat
            return sideeff

        for stat in status:
            self.fc.servers.get('1234').WithSideEffects(
                get_sideeff(stat)).AndReturn(return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

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
        self._stub_glance_for_update(rebuild=True)
        # current test demonstrate updating when image_update_policy was not
        # changed, so image_update_policy will be used from self.properties
        server.t['Properties']['image_update_policy'] = 'REBUILD'
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = new_image

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('1234').AndReturn(return_server)
        self.m.StubOutWithMock(self.fc.servers, 'rebuild')
        # 744 is a static lookup from the fake images list
        self.fc.servers.rebuild(
            return_server, 744, password=None, preserve_ephemeral=False)
        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')

        def status_rebuild(*args):
            return_server.status = 'REBUILD'

        def status_error(*args):
            return_server.status = 'ERROR'

        self.fc.servers.get('1234').WithSideEffects(
            status_rebuild).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_error).AndReturn(return_server)
        self.m.ReplayAll()

        updater = scheduler.TaskRunner(server.update, update_template)
        error = self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual(
            "Error: resources.srv_updrbldfail: "
            "Rebuilding server failed, status 'ERROR'",
            six.text_type(error))
        self.assertEqual((server.UPDATE, server.FAILED), server.state)
        self.m.VerifyAll()

    def test_server_update_properties(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'update_prop')

        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = 'mustreplace'
        update_template['Properties']['image_update_policy'] = 'REPLACE'
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(exception.UpdateReplace, updater)

    def test_server_status_build(self):
        return_server = self.fc.servers.list()[0]
        server = self._setup_test_server(return_server,
                                         'sts_build')
        server.resource_id = '1234'

        def status_active(*args):
            return_server.status = 'ACTIVE'

        self.fc.servers.get(server.resource_id).WithSideEffects(
            status_active).AndReturn(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

    def test_server_status_suspend_no_resource_id(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_sus1')

        server.resource_id = None
        self.m.ReplayAll()

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.suspend))
        self.assertEqual('Error: resources.srv_sus1: '
                         'Cannot suspend srv_sus1, '
                         'resource_id not set',
                         six.text_type(ex))
        self.assertEqual((server.SUSPEND, server.FAILED), server.state)

        self.m.VerifyAll()

    def test_server_status_suspend_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_sus2')

        server.resource_id = '1234'
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndRaise(
            fakes_nova.fake_exception())
        self.m.ReplayAll()

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.suspend))
        self.assertEqual('NotFound: resources.srv_sus2: '
                         'Failed to find server 1234',
                         six.text_type(ex))
        self.assertEqual((server.SUSPEND, server.FAILED), server.state)

        self.m.VerifyAll()

    def _test_server_status_suspend(self, name, state=('CREATE', 'COMPLETE')):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server, name)

        server.resource_id = '1234'
        server.state_set(state[0], state[1])

        def status_suspended(*args):
            return_server.status = 'SUSPENDED'

        def status_active(*args):
            return_server.status = 'ACTIVE'

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).WithSideEffects(
            status_active).AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'suspend')
        return_server.suspend().AndReturn(None)
        self.fc.servers.get(return_server.id).WithSideEffects(
            status_active).AndReturn(return_server)
        self.fc.servers.get(return_server.id).WithSideEffects(
            status_suspended).AndReturn(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.suspend)()
        self.assertEqual((server.SUSPEND, server.COMPLETE), server.state)

        self.m.VerifyAll()

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

        def status_unknown(*args):
            return_server.status = 'TRANSMOGRIFIED'

        def status_active(*args):
            return_server.status = 'ACTIVE'

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).WithSideEffects(
            status_active).AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'suspend')
        return_server.suspend().AndReturn(None)
        self.fc.servers.get(return_server.id).WithSideEffects(
            status_active).AndReturn(return_server)
        self.fc.servers.get(return_server.id).WithSideEffects(
            status_unknown).AndReturn(return_server)
        self.m.ReplayAll()

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.suspend))
        self.assertIsInstance(ex.exc, exception.ResourceUnknownStatus)
        self.assertEqual('Suspend of server %s failed - '
                         'Unknown status TRANSMOGRIFIED '
                         'due to "Unknown"' % return_server.name,
                         six.text_type(ex.exc.message))
        self.assertEqual((server.SUSPEND, server.FAILED), server.state)

        self.m.VerifyAll()

    def _test_server_status_resume(self, name, state=('SUSPEND', 'COMPLETE')):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server, name)

        server.resource_id = '1234'
        server.state_set(state[0], state[1])

        def status_suspended(*args):
            return_server.status = 'SUSPENDED'

        def status_active(*args):
            return_server.status = 'ACTIVE'

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).WithSideEffects(
            status_suspended).AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'resume')
        return_server.resume().AndReturn(None)
        self.fc.servers.get(return_server.id).WithSideEffects(
            status_suspended).AndReturn(return_server)
        self.fc.servers.get(return_server.id).WithSideEffects(
            status_active).AndReturn(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.resume)()
        self.assertEqual((server.RESUME, server.COMPLETE), server.state)

        self.m.VerifyAll()

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
        self.m.ReplayAll()

        server.state_set(server.SUSPEND, server.COMPLETE)
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.resume))
        self.assertEqual('Error: resources.srv_susp_norid: '
                         'Cannot resume srv_susp_norid, '
                         'resource_id not set',
                         six.text_type(ex))
        self.assertEqual((server.RESUME, server.FAILED), server.state)

        self.m.VerifyAll()

    def test_server_status_resume_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_res_nf')

        server.resource_id = '1234'
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndRaise(
            fakes_nova.fake_exception())
        self.m.ReplayAll()

        server.state_set(server.SUSPEND, server.COMPLETE)

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.resume))
        self.assertEqual('NotFound: resources.srv_res_nf: '
                         'Failed to find server 1234',
                         six.text_type(ex))
        self.assertEqual((server.RESUME, server.FAILED), server.state)

        self.m.VerifyAll()

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

        def status_uncommon(*args):
            return_server.status = uncommon_status

        def status_active(*args):
            return_server.status = 'ACTIVE'

        self.fc.servers.get(server.resource_id).WithSideEffects(
            status_uncommon).AndReturn(return_server)
        self.fc.servers.get(server.resource_id).WithSideEffects(
            status_active).AndReturn(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_build_nics(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_create')
        self.patchobject(server, 'is_using_neutron', return_value=True)
        self.patchobject(neutronclient.Client, 'create_port',
                         return_value={'port': {'id': '4815162342'}})

        self.assertIsNone(server._build_nics([]))
        self.assertIsNone(server._build_nics(None))
        self.assertEqual([{'port-id': 'aaaabbbb', 'net-id': None},
                          {'v4-fixed-ip': '192.0.2.0', 'net-id': None}],
                         server._build_nics([{'port': 'aaaabbbb'},
                                             {'fixed_ip': '192.0.2.0'}]))

        self.assertEqual([{'port-id': 'aaaabbbb', 'net-id': None},
                          {'v6-fixed-ip': '2002::2', 'net-id': None}],
                         server._build_nics([{'port': 'aaaabbbb'},
                                             {'fixed_ip': '2002::2'}]))
        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='1234abcd')
        self.assertEqual([{'net-id': '1234abcd'}],
                         server._build_nics([{'uuid': '1234abcd'}]))

        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.assertEqual([{'net-id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}],
                         server._build_nics(
                             [{'network':
                               'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}]))

        self.patchobject(server, 'is_using_neutron', return_value=False)
        self.assertEqual([{'net-id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}],
                         server._build_nics([{'network': 'public'}]))

        expected = ('Multiple physical resources were found with name (foo)')
        exc = self.assertRaises(
            exception.PhysicalResourceNameAmbiguity,
            server._build_nics, ([{'network': 'foo'}]))
        self.assertIn(expected, six.text_type(exc))
        expected = 'The Nova network (bar) could not be found'
        exc = self.assertRaises(
            exception.EntityNotFound,
            server._build_nics, ([{'network': 'bar'}]))
        self.assertIn(expected, six.text_type(exc))

        self.m.VerifyAll()

    def test_server_without_ip_address(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'
        server = self._create_test_server(return_server,
                                          'wo_ipaddr')

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('9102').MultipleTimes().AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'interface_list')
        return_server.interface_list().MultipleTimes().AndReturn([])
        self.m.ReplayAll()

        self.assertEqual({'empty_net': []}, server.FnGetAtt('addresses'))
        self.assertEqual({'empty_net': []}, server.FnGetAtt('networks'))
        self.assertEqual('', server.FnGetAtt('first_address'))
        self.m.VerifyAll()

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

    def test_validate_block_device_mapping_volume_size_valid_int(self):
        stack_name = 'val_vsize_valid'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': 10}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self._server_validate_mock(server)
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_validate_block_device_mapping_volume_size_valid_str(self):
        stack_name = 'val_vsize_valid'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': '10'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self._server_validate_mock(server)

        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_validate_block_device_mapping_volume_size_invalid_str(self):
        stack_name = 'val_vsize_invalid'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': '10a'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.patchobject(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.stub_ImageConstraint_validate()
        self.stub_VolumeConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()
        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertIn("Value '10a' is not an integer", six.text_type(exc))
        self.m.VerifyAll()

    def test_validate_conflict_block_device_mapping_props(self):
        stack_name = 'val_blkdev1'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        bdm = [{'device_name': 'vdb', 'snapshot_id': '1234',
                'volume_id': '1234'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_VolumeConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.m.ReplayAll()

        self.assertRaises(exception.ResourcePropertyConflict, server.validate)
        self.m.VerifyAll()

    def test_validate_insufficient_block_device_mapping_props(self):
        stack_name = 'val_blkdev2'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        bdm = [{'device_name': 'vdb', 'volume_size': 1,
                'delete_on_termination': True}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        msg = ("Either volume_id or snapshot_id must be specified "
               "for device mapping vdb")
        self.assertEqual(msg, six.text_type(ex))

        self.m.VerifyAll()

    def test_validate_block_device_mapping_with_empty_ref(self):
        stack_name = 'val_blkdev2'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '',
                'volume_size': '10'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        self.stub_VolumeConstraint_validate()
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_validate_without_image_or_bootable_volume(self):
        stack_name = 'val_imgvol'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        del tmpl['Resources']['WebServer']['Properties']['image']
        bdm = [{'device_name': 'vdb', 'volume_id': '1234'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.stub_VolumeConstraint_validate()
        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        msg = ('Neither image nor bootable volume is specified '
               'for instance %s' % server.name)
        self.assertEqual(msg, six.text_type(ex))

        self.m.VerifyAll()

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
            {'image_id': '1'}
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

    def test_validate_with_both_blk_dev_map_and_blk_dev_map_v2(self):
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

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_VolumeConstraint_validate()
        self.m.ReplayAll()

        exc = self.assertRaises(exception.ResourcePropertyConflict,
                                server.validate)
        msg = ('Cannot define the following properties at the same time: '
               'block_device_mapping, block_device_mapping_v2.')
        self.assertEqual(msg, six.text_type(exc))

        self.m.VerifyAll()

    def test_validate_conflict_block_device_mapping_v2_props(self):
        stack_name = 'val_blkdev2'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        bdm_v2 = [{'volume_id': '1', 'snapshot_id': 2}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping_v2'] = bdm_v2
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_VolumeConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.m.ReplayAll()

        self.assertRaises(exception.ResourcePropertyConflict, server.validate)
        self.m.VerifyAll()

    def test_validate_without_bootable_source_in_bdm_v2(self):
        stack_name = 'val_blkdev2'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        bdm_v2 = [{}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping_v2'] = bdm_v2
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        msg = ('Either volume_id, snapshot_id, image_id or swap_size must '
               'be specified.')
        self.assertEqual(msg, six.text_type(exc))

        self.m.VerifyAll()

    def test_validate_bdm_v2_properties_success(self):
        stack_name = 'v2_properties'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        bdm_v2 = [{'volume_id': '1'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping_v2'] = bdm_v2
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.stub_VolumeConstraint_validate()
        self.m.ReplayAll()

        self.assertIsNone(server.validate())

        self.m.VerifyAll()

    def test_validate_bdm_v2_properties_no_bootable_vol(self):
        stack_name = 'v2_properties'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        bdm_v2 = [{'swap_size': 10}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['block_device_mapping_v2'] = bdm_v2
        wsp.pop('image')
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.stub_VolumeConstraint_validate()
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        msg = ('Neither image nor bootable volume is specified for instance '
               'server_create_image_err')
        self.assertEqual(msg, six.text_type(exc))

        self.m.VerifyAll()

    def test_validate_metadata_too_many(self):
        stack_name = 'srv_val_metadata'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties']['metadata'] = {'a': 1,
                                                                      'b': 2,
                                                                      'c': 3,
                                                                      'd': 4}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertIn('Instance metadata must not contain greater than 3 '
                      'entries', six.text_type(ex))
        self.m.VerifyAll()

    def test_validate_metadata_okay(self):
        stack_name = 'srv_val_metadata'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties']['metadata'] = {'a': 1,
                                                                      'b': 2,
                                                                      'c': 3}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()
        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_too_many_personality(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)

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

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertEqual("The personality property may not contain "
                         "greater than 5 entries.", six.text_type(exc))
        self.m.VerifyAll()

    def test_server_validate_personality_okay(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties'][
            'personality'] = {"/fake/path1": "fake contents1",
                              "/fake/path2": "fake_contents2",
                              "/fake/path3": "fake_contents3",
                              "/fake/path4": "fake_contents4",
                              "/fake/path5": "fake_contents5"}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_personality_file_size_okay(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties'][
            'personality'] = {"/fake/path1": "a" * 10240}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_personality_file_size_too_big(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties'][
            'personality'] = {"/fake/path1": "a" * 10241}
        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertEqual('The contents of personality file "/fake/path1" '
                         'is larger than the maximum allowed personality '
                         'file size (10240 bytes).', six.text_type(exc))
        self.m.VerifyAll()

    def test_resolve_attribute_server_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_resolve_attr')

        server.resource_id = '1234'
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndRaise(
            fakes_nova.fake_exception())
        self.m.ReplayAll()

        self.assertEqual('', server._resolve_all_attributes("accessIPv4"))
        self.m.VerifyAll()

    def test_resolve_attribute_console_url(self):
        server = self.fc.servers.list()[0]
        tmpl, stack = self._setup_test_stack('console_url_stack')
        ws = servers.Server(
            'WebServer', tmpl.resource_definitions(stack)['WebServer'], stack)
        ws.resource_id = server.id
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.id).AndReturn(server)
        self.m.ReplayAll()

        console_urls = ws._resolve_all_attributes('console_urls')
        self.assertIsInstance(console_urls, collections.Mapping)
        supported_consoles = ('novnc', 'xvpvnc', 'spice-html5', 'rdp-html5',
                              'serial')
        self.assertEqual(set(supported_consoles),
                         set(six.iterkeys(console_urls)))
        self.m.VerifyAll()

    def test_resolve_attribute_networks(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_resolve_attr')

        server.resource_id = '1234'
        server.networks = {"fake_net": ["10.0.0.3"]}
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.resource_id).AndReturn(server)
        self.m.StubOutWithMock(nova.NovaClientPlugin, 'get_net_id_by_label')
        nova.NovaClientPlugin.get_net_id_by_label(
            'fake_net').AndReturn('fake_uuid')
        self.m.ReplayAll()
        expect_networks = {"fake_uuid": ["10.0.0.3"],
                           "fake_net": ["10.0.0.3"]}
        self.assertEqual(expect_networks,
                         server._resolve_all_attributes("networks"))
        self.m.VerifyAll()

    def test_empty_instance_user(self):
        """Test Nova server doesn't set instance_user in build_userdata

        Launching the instance should not pass any user name to
        build_userdata. The default cloud-init user set up for the image
        will be used instead.
        """
        return_server = self.fc.servers.list()[1]
        server = self._setup_test_server(return_server, 'without_user')
        metadata = server.metadata_get()
        self.m.StubOutWithMock(nova.NovaClientPlugin, 'build_userdata')
        nova.NovaClientPlugin.build_userdata(
            metadata,
            'wordpress',
            instance_user=None,
            user_data_format='HEAT_CFNTOOLS')
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def create_old_net(self, port=None, net=None,
                       ip=None, uuid=None, subnet=None,
                       port_extra_properties=None):
        return {'port': port, 'network': net, 'fixed_ip': ip, 'uuid': uuid,
                'subnet': subnet,
                'port_extra_properties': port_extra_properties}

    def create_fake_iface(self, port, net, ip):
        class fake_interface(object):
            def __init__(self, port_id, net_id, fixed_ip):
                self.port_id = port_id
                self.net_id = net_id
                self.fixed_ips = [{'ip_address': fixed_ip}]

        return fake_interface(port, net, ip)

    def test_get_network_id_neutron(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        self.patchobject(server, 'is_using_neutron', return_value=True)

        net = {'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}
        net_id = server._get_network_id(net)
        self.assertIsNone(net_id)

        net = {'network': 'f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
               'fixed_ip': '1.2.3.4'}
        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032')
        net_id = server._get_network_id(net)
        self.assertEqual('f3ef5d2f-d7ba-4b27-af66-58ca0b81e032', net_id)

        net = {'network': 'private_net',
               'fixed_ip': '1.2.3.4'}
        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032')
        net_id = server._get_network_id(net)
        self.assertEqual('f3ef5d2f-d7ba-4b27-af66-58ca0b81e032', net_id)

        net = {'network': '', 'fixed_ip': '1.2.3.4'}
        net_id = server._get_network_id(net)
        self.assertIsNone(net_id)

    def test_get_network_id_nova(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        self.patchobject(server, 'is_using_neutron', return_value=False)

        net = {'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}

        net_id = server._get_network_id(net)
        self.assertIsNone(net_id)

        net = {'network': 'f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
               'fixed_ip': '1.2.3.4'}

        self.patchobject(nova.NovaClientPlugin, 'get_nova_network_id',
                         return_value='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032')
        net_id = server._get_network_id(net)
        self.assertEqual('f3ef5d2f-d7ba-4b27-af66-58ca0b81e032', net_id)

        net = {'network': 'private_net',
               'fixed_ip': '1.2.3.4'}
        self.patchobject(nova.NovaClientPlugin, 'get_nova_network_id',
                         return_value='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032')
        net_id = server._get_network_id(net)
        self.assertEqual('f3ef5d2f-d7ba-4b27-af66-58ca0b81e032', net_id)

    def test_exclude_not_updated_networks_no_matching(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        for new_nets in ([],
                         [{'port': '952fd4ae-53b9-4b39-9e5f-8929c553b5ae'}]):

            old_nets = [
                self.create_old_net(
                    port='2a60cbaa-3d33-4af6-a9ce-83594ac546fc'),
                self.create_old_net(
                    net='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032', ip='1.2.3.4'),
                self.create_old_net(
                    net='0da8adbf-a7e2-4c59-a511-96b03d2da0d7')]

            new_nets_copy = copy.deepcopy(new_nets)
            old_nets_copy = copy.deepcopy(old_nets)
            for net in new_nets_copy:
                for key in ('port', 'network', 'fixed_ip', 'uuid', 'subnet',
                            'port_extra_properties'):
                    net.setdefault(key)

            matched_nets = server._exclude_not_updated_networks(old_nets,
                                                                new_nets)
            self.assertEqual([], matched_nets)
            self.assertEqual(old_nets_copy, old_nets)
            self.assertEqual(new_nets_copy, new_nets)

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

        new_nets_copy = copy.deepcopy(new_nets)
        old_nets_copy = copy.deepcopy(old_nets)
        for net in new_nets_copy:
            for key in ('port', 'network', 'fixed_ip', 'uuid', 'subnet',
                        'port_extra_properties'):
                net.setdefault(key)

        matched_nets = server._exclude_not_updated_networks(old_nets, new_nets)
        self.assertEqual(old_nets_copy[:-1], matched_nets)
        self.assertEqual([old_nets_copy[2]], old_nets)
        self.assertEqual([new_nets_copy[2]], new_nets)

    def test_exclude_not_updated_networks_nothing_for_update(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        old_nets = [
            self.create_old_net(
                net='f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
                ip='',
                port='',
                uuid='')]
        new_nets = [
            {'network': 'f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
             'fixed_ip': None,
             'port': None,
             'uuid': None,
             'subnet': None,
             'port_extra_properties': None}]
        new_nets_copy = copy.deepcopy(new_nets)

        matched_nets = server._exclude_not_updated_networks(old_nets, new_nets)
        self.assertEqual(new_nets_copy, matched_nets)
        self.assertEqual([], old_nets)
        self.assertEqual([], new_nets)

    def test_update_networks_matching_iface_port(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        # old order 0 1 2 3 4
        nets = [
            self.create_old_net(port='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
            self.create_old_net(net='gggggggg-1111-1111-1111-gggggggggggg',
                                ip='1.2.3.4'),
            self.create_old_net(net='gggggggg-1111-1111-1111-gggggggggggg'),
            self.create_old_net(port='dddddddd-dddd-dddd-dddd-dddddddddddd'),
            self.create_old_net(uuid='gggggggg-1111-1111-1111-gggggggggggg',
                                ip='5.6.7.8')]
        # new order 2 3 0 1 4
        interfaces = [
            self.create_fake_iface('cccccccc-cccc-cccc-cccc-cccccccccccc',
                                   nets[2]['network'], '10.0.0.11'),
            self.create_fake_iface(nets[3]['port'],
                                   'gggggggg-1111-1111-1111-gggggggggggg',
                                   '10.0.0.12'),
            self.create_fake_iface(nets[0]['port'],
                                   'gggggggg-1111-1111-1111-gggggggggggg',
                                   '10.0.0.13'),
            self.create_fake_iface('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                                   nets[1]['network'], nets[1]['fixed_ip']),
            self.create_fake_iface('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
                                   nets[4]['uuid'], nets[4]['fixed_ip'])]
        # all networks should get port id
        expected = [
            {'port': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'network': None,
             'fixed_ip': None,
             'uuid': None,
             'subnet': None,
             'port_extra_properties': None,
             'uuid': None},
            {'port': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '1.2.3.4',
             'subnet': None,
             'port_extra_properties': None,
             'uuid': None},
            {'port': 'cccccccc-cccc-cccc-cccc-cccccccccccc',
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': None,
             'subnet': None,
             'port_extra_properties': None,
             'uuid': None},
            {'port': 'dddddddd-dddd-dddd-dddd-dddddddddddd',
             'network': None,
             'fixed_ip': None,
             'subnet': None,
             'port_extra_properties': None,
             'uuid': None},
            {'port': 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
             'uuid': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '5.6.7.8',
             'subnet': None,
             'port_extra_properties': None,
             'network': None}]

        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='gggggggg-1111-1111-1111-gggggggggggg')

        server.update_networks_matching_iface_port(nets, interfaces)
        self.assertEqual(expected, nets)

    def test_server_update_None_networks_with_port(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'
        server = self._create_test_server(return_server, 'networks_update')

        new_networks = [{'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = new_networks

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('9102').MultipleTimes().AndReturn(return_server)
        # to make sure, that old_networks will be None
        self.assertFalse(hasattr(server.t['Properties'], 'networks'))

        iface = self.create_fake_iface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                       '450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
                                       '1.2.3.4')
        self.m.StubOutWithMock(return_server, 'interface_list')
        return_server.interface_list().AndReturn([iface])

        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa').AndReturn(None)

        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach(new_networks[0]['port'],
                                       None, None).AndReturn(None)
        self.stub_PortConstraint_validate()
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_None_networks_with_network_id(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'

        self.patchobject(neutronclient.Client, 'create_port',
                         return_value={'port': {'id': 'abcd1234'}})

        server = self._create_test_server(return_server, 'networks_update')

        new_networks = [{'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                         'fixed_ip': '1.2.3.4'}]
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = new_networks

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('9102').MultipleTimes().AndReturn(return_server)
        # to make sure, that old_networks will be None
        self.assertFalse(hasattr(server.t['Properties'], 'networks'))

        iface = self.create_fake_iface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                       '450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
                                       '1.2.3.4')
        self.m.StubOutWithMock(return_server, 'interface_list')
        return_server.interface_list().AndReturn([iface])

        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa').AndReturn(None)

        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach(None, new_networks[0]['network'],
                                       new_networks[0]['fixed_ip']).AndReturn(
                                           None)
        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.stub_NetworkConstraint_validate()
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_empty_networks_with_complex_parameters(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = '9102'
        server = self._create_test_server(return_server, 'networks_update')

        new_networks = [{'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                         'fixed_ip': '1.2.3.4',
                         'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = new_networks

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('9102').MultipleTimes().AndReturn(return_server)
        # to make sure, that old_networks will be None
        self.assertFalse(hasattr(server.t['Properties'], 'networks'))

        iface = self.create_fake_iface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                       '450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
                                       '1.2.3.4')
        self.m.StubOutWithMock(return_server, 'interface_list')
        return_server.interface_list().AndReturn([iface])

        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa').AndReturn(None)

        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value=None)

        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach(
            new_networks[0]['port'], None, None).AndReturn(None)
        self.stub_NetworkConstraint_validate()
        self.stub_PortConstraint_validate()
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_networks_with_complex_parameters(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server = self._create_test_server(return_server, 'networks_update')

        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '1.2.3.4'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '31.32.33.34'}]

        new_networks = [
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '1.2.3.4'},
            {'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]

        server.t['Properties']['networks'] = old_networks
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = new_networks

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('5678').MultipleTimes().AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'interface_list')

        poor_interfaces = [
            self.create_fake_iface('95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '11.12.13.14'),
            self.create_fake_iface('450abbc9-9b6d-4d6f-8c3a-c47ac34100ef',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '1.2.3.4'),
            self.create_fake_iface('4121f61a-1b2e-4ab0-901e-eade9b1cb09d',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '21.22.23.24'),
            self.create_fake_iface('0907fa82-a024-43c2-9fc5-efa1bccaa74a',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '31.32.33.34')
        ]

        return_server.interface_list().AndReturn(poor_interfaces)

        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            poor_interfaces[0].port_id).InAnyOrder().AndReturn(None)
        return_server.interface_detach(
            poor_interfaces[2].port_id).InAnyOrder().AndReturn(None)
        return_server.interface_detach(
            poor_interfaces[3].port_id).InAnyOrder().AndReturn(None)

        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach(
            new_networks[1]['port'], None, None).AndReturn(None)
        self.stub_NetworkConstraint_validate()
        self.stub_PortConstraint_validate()
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_networks_with_None(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server = self._create_test_server(return_server, 'networks_update')

        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '31.32.33.34'}]

        server.t['Properties']['networks'] = old_networks
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = None

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('5678').MultipleTimes().AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'interface_list')

        poor_interfaces = [
            self.create_fake_iface('95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '11.12.13.14'),
            self.create_fake_iface('4121f61a-1b2e-4ab0-901e-eade9b1cb09d',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '21.22.23.24'),
            self.create_fake_iface('0907fa82-a024-43c2-9fc5-efa1bccaa74a',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '31.32.33.34')
        ]

        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        return_server.interface_list().AndReturn(poor_interfaces)

        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            poor_interfaces[0].port_id).InAnyOrder().AndReturn(None)
        return_server.interface_detach(
            poor_interfaces[1].port_id).InAnyOrder().AndReturn(None)
        return_server.interface_detach(
            poor_interfaces[2].port_id).InAnyOrder().AndReturn(None)

        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach(None, None, None).AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_networks_with_uuid(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'

        self.patchobject(neutronclient.Client, 'create_port',
                         return_value={'port': {'id': 'abcd1234'}})

        server = self._create_test_server(return_server, 'networks_update')

        old_networks = [
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}]
        new_networks = [
            {'uuid': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}]

        server.t['Properties']['networks'] = old_networks
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = new_networks

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('5678').MultipleTimes().AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'interface_list')

        poor_interfaces = [
            self.create_fake_iface('95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '11.12.13.14')
        ]

        return_server.interface_list().AndReturn(poor_interfaces)

        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            poor_interfaces[0].port_id).AndReturn(None)

        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach(None, new_networks[0]['uuid'],
                                       None).AndReturn(None)
        self.stub_NetworkConstraint_validate()
        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_networks_with_empty_list(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '5678'
        server = self._create_test_server(return_server, 'networks_update')

        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '31.32.33.34'}]

        server.t['Properties']['networks'] = old_networks
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = []

        self._stub_glance_for_update()
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('5678').MultipleTimes().AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'interface_list')

        poor_interfaces = [
            self.create_fake_iface('95e25541-d26a-478d-8f36-ae1c8f6b74dc',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '11.12.13.14'),
            self.create_fake_iface('4121f61a-1b2e-4ab0-901e-eade9b1cb09d',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '21.22.23.24'),
            self.create_fake_iface('0907fa82-a024-43c2-9fc5-efa1bccaa74a',
                                   'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                   '31.32.33.34')
        ]

        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')

        return_server.interface_list().AndReturn(poor_interfaces)

        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            poor_interfaces[0].port_id).InAnyOrder().AndReturn(None)
        return_server.interface_detach(
            poor_interfaces[1].port_id).InAnyOrder().AndReturn(None)
        return_server.interface_detach(
            poor_interfaces[2].port_id).InAnyOrder().AndReturn(None)

        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach(None, None, None).AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_properties_validation_create_and_update(self):
        return_server = self.fc.servers.list()[1]

        # create
        # validation calls are already mocked there
        server = self._create_test_server(return_server,
                                          'my_server')

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = 'Update Image'
        update_template['Properties']['image_update_policy'] = 'REPLACE'

        # update
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(exception.UpdateReplace, updater)

        self.m.VerifyAll()

    def test_server_properties_validation_create_and_update_fail(self):
        return_server = self.fc.servers.list()[1]

        # create
        # validation calls are already mocked there
        server = self._create_test_server(return_server,
                                          'my_server')

        self.m.StubOutWithMock(glance.ImageConstraint, "validate")
        # verify that validate gets invoked exactly once for update
        ex = exception.EntityNotFound(entity='Image', name='Update Image')
        glance.ImageConstraint.validate('Update Image',
                                        mox.IgnoreArg()).AndRaise(ex)
        self.m.ReplayAll()

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = 'Update Image'

        # update
        updater = scheduler.TaskRunner(server.update, update_template)
        err = self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual('StackValidationFailed: resources.my_server: '
                         'Property error: '
                         'WebServer.Properties.image: The Image '
                         '(Update Image) could not be found.',
                         six.text_type(err))
        self.m.VerifyAll()

    def test_server_snapshot(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'test_server_snapshot')
        scheduler.TaskRunner(server.snapshot)()

        self.assertEqual((server.SNAPSHOT, server.COMPLETE), server.state)

        self.assertEqual({'snapshot_image_id': '456'},
                         resource_data_object.ResourceData.get_all(server))
        self.m.VerifyAll()

    def test_server_check_snapshot_complete_image_in_deleted(self):
        self.test_server_check_snapshot_complete_fail(image_status='DELETED')

    def test_server_check_snapshot_complete_image_in_error(self):
        self.test_server_check_snapshot_complete_fail()

    def test_server_check_snapshot_complete_fail(self, image_status='ERROR'):
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        server = self._create_test_server(return_server,
                                          'test_server_snapshot')
        image_in_error = mock.Mock()
        image_in_error.status = image_status
        self.fc.images.get = mock.Mock(return_value=image_in_error)
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(server.snapshot))

        self.assertEqual((server.SNAPSHOT, server.FAILED), server.state)
        # test snapshot_image_id already set to resource data
        self.assertEqual({'snapshot_image_id': '456'},
                         resource_data_object.ResourceData.get_all(server))
        self.m.VerifyAll()

    def test_server_dont_validate_personality_if_personality_isnt_set(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = servers.Server('server_create_image_err',
                                resource_defns['WebServer'], stack)

        # We mock out nova.NovaClientPlugin.absolute_limits but we don't
        # specify how this mock should behave, so mox will verify that this
        # mock is NOT called during call to server.validate().
        # This is the way to validate that no excessive calls to Nova
        # are made during validation.
        self.m.StubOutWithMock(nova.NovaClientPlugin, 'absolute_limits')
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 'image_id')
        self.m.ReplayAll()

        # Assert here checks that server resource validates, but actually
        # this call is Act stage of this test. We calling server.validate()
        # to verify that no excessive calls to Nova are made during validation.
        self.assertIsNone(server.validate())

        self.m.VerifyAll()

    def test_server_restore(self):
        t = template_format.parse(ns_template)
        tmpl = template.Template(t, files={'a_file': 'the content'})
        stack = parser.Stack(utils.dummy_context(), "server_restore", tmpl)
        stack.store()

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().MultipleTimes().AndReturn(self.fc)

        self.patchobject(stack['server'], 'store_external_ports')

        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name=None,
            name=utils.PhysName("server_restore", "server"),
            nics=[{'net-id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}],
            security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=None, availability_zone=None,
            block_device_mapping=None, block_device_mapping_v2=None,
            config_drive=None, disk_config=None, reservation_id=None,
            files={}, admin_pass=None).AndReturn(return_server)
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(return_server.id).AndReturn(return_server)

        self.m.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
        glance.GlanceClientPlugin.get_image_id(
            'F17-x86_64-gold').MultipleTimes().AndReturn(744)
        glance.GlanceClientPlugin.get_image_id(
            'CentOS 5.2').MultipleTimes().AndReturn(1)

        self.patchobject(neutron.NeutronClientPlugin, 'resolve_network',
                         return_value='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.stub_NetworkConstraint_validate()
        self.fc.servers.get(return_server.id).AndReturn(return_server)
        self.fc.servers.get(return_server.id).AndReturn(return_server)
        self.patchobject(return_server, 'get', return_value=None)

        self.m.ReplayAll()

        scheduler.TaskRunner(stack.create)()

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

        self.m.VerifyAll()

    def test_snapshot_policy(self):
        t = template_format.parse(wp_template)
        t['Resources']['WebServer']['DeletionPolicy'] = 'Snapshot'
        tmpl = template.Template(t)
        stack = parser.Stack(
            utils.dummy_context(), 'snapshot_policy', tmpl)
        stack.store()

        self.patchobject(stack['WebServer'], 'store_external_ports')

        mock_plugin = self.patchobject(nova.NovaClientPlugin, '_create')
        mock_plugin.return_value = self.fc

        get_image = self.patchobject(glance.GlanceClientPlugin, 'get_image_id')
        get_image.return_value = 744

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

        scheduler.TaskRunner(stack.delete)()

        self.assertEqual((stack.DELETE, stack.COMPLETE), stack.state)

        get_image.assert_called_with('F17-x86_64-gold')
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

        mock_plugin = self.patchobject(nova.NovaClientPlugin, '_create')
        mock_plugin.return_value = self.fc

        get_image = self.patchobject(glance.GlanceClientPlugin, 'get_image_id')
        get_image.return_value = 744

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

        failed_image = {
            'id': 456,
            'name': 'CentOS 5.2',
            'updated': '2010-10-10T12:00:00Z',
            'created': '2010-08-10T12:00:00Z',
            'status': 'ERROR'}
        self.fc.client.get_images_456 = lambda **kw: (
            200, {'image': failed_image})

        scheduler.TaskRunner(stack.delete)()

        self.assertEqual((stack.DELETE, stack.FAILED), stack.state)
        self.assertEqual(
            'Resource DELETE failed: Error: resources.WebServer: ERROR',
            stack.status_reason)

        get_image.assert_called_with('F17-x86_64-gold')
        create_image.assert_called_once_with(
            '1234', utils.PhysName('snapshot_policy', 'WebServer'))

        delete_server.assert_not_called()


class ServerInternalPortTest(common.HeatTestCase):
    def setUp(self):
        super(ServerInternalPortTest, self).setUp()
        self.resolve = self.patchobject(neutronV20,
                                        'find_resourceid_by_name_or_id')
        self.port_create = self.patchobject(neutronclient.Client,
                                            'create_port')
        self.port_delete = self.patchobject(neutronclient.Client,
                                            'delete_port')
        self.port_show = self.patchobject(neutronclient.Client,
                                          'show_port')
        self.port_update = self.patchobject(neutronclient.Client,
                                            'update_port')

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
        self.resolve.return_value = '4321'

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
        self.resolve.return_value = '4321'

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
              networks:
                - network: 4321
                  subnet: 1234
                  fixed_ip: 127.0.0.1
        """

        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)

        self.resolve.side_effect = ['4321', '1234']
        self.patchobject(server, '_validate_belonging_subnet_to_net')
        self.port_create.return_value = {'port': {'id': '111222'}}
        data_set = self.patchobject(resource.Resource, 'data_set')

        network = [{'network': '4321', 'subnet': '1234',
                    'fixed_ip': '127.0.0.1'}]
        server._build_nics(network)

        self.port_create.assert_called_once_with(
            {'port': {'name': 'server-port-0',
                      'network_id': '4321',
                      'fixed_ips': [{
                          'ip_address': '127.0.0.1',
                          'subnet_id': '1234'
                      }]}})
        data_set.assert_called_once_with('internal_ports',
                                         '[{"id": "111222"}]')

    def test_build_nics_do_not_create_internal_port(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)

        self.resolve.side_effect = ['4321', '1234']
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

        self.resolve.side_effect = ['4321', '1234']

        network = {'network': '4321', 'subnet': '1234',
                   'fixed_ip': '127.0.0.1',
                   'port_extra_properties': {
                       'mac_address': '00:00:00:00:00:00',
                       'allowed_address_pairs': [
                           {'ip_address': '127.0.0.1',
                            'mac_address': None},
                           {'mac_address': '00:00:00:00:00:00'}
                       ]
                   }}
        kwargs = server._prepare_internal_port_kwargs(network)

        self.assertEqual({'network_id': '4321',
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
                - subnet: 4321
        """
        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)

        self.patchobject(neutron.NeutronClientPlugin,
                         'network_id_from_subnet_id',
                         return_value='1234')
        self.resolve.return_value = '4321'

        net = {'subnet': '4321'}
        net_id = server._get_network_id(net)

        self.assertEqual('1234', net_id)
        subnet_id = server._get_subnet_id(net)
        self.assertEqual('4321', subnet_id)
        # check that networks doesn't changed in _get_subnet_id method.
        self.assertEqual({'subnet': '4321'}, net)

        self.resolve.return_value = '4321'
        self.port_create.return_value = {'port': {'id': '111222'}}
        data_set = self.patchobject(resource.Resource, 'data_set')

        network = [{'subnet': '1234'}]
        server._build_nics(network)

        self.port_create.assert_called_once_with(
            {'port': {'name': 'server-port-0',
                      'network_id': '1234',
                      'fixed_ips': [{
                          'subnet_id': '4321'
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
                - network: 8765
                  subnet: 5678
                  fixed_ip: 127.0.0.2
        """

        t, stack, server = self._return_template_stack_and_rsrc_defn('test',
                                                                     tmpl)

        # NOTE(prazumovsky): this method update old_net and new_net with
        # interfaces' ports. Because of uselessness of checking this method,
        # we can afford to give port as part of calculate_networks args.
        self.patchobject(server, 'update_networks_matching_iface_port')

        server._data = {'internal_ports': '[{"id": "1122"}]'}
        self.port_create.return_value = {'port': {'id': '5566'}}
        data_set = self.patchobject(resource.Resource, 'data_set')
        self.resolve.side_effect = ['0912', '9021']

        old_net = [{'network': '4321',
                    'subnet': '1234',
                    'fixed_ip': '127.0.0.1',
                    'port': '1122'},
                   {'network': '8765',
                    'subnet': '5678',
                    'fixed_ip': '127.0.0.2',
                    'port': '3344'}]

        new_net = [{'network': '8765',
                    'subnet': '5678',
                    'fixed_ip': '127.0.0.2',
                    'port': '3344'},
                   {'network': '0912',
                    'subnet': '9021',
                    'fixed_ip': '127.0.0.1'}]

        server.calculate_networks(old_net, new_net, [])

        self.port_delete.assert_called_once_with('1122')
        self.port_create.assert_called_once_with(
            {'port': {'name': 'server-port-0',
                      'network_id': '0912',
                      'fixed_ips': [{'subnet_id': '9021',
                                     'ip_address': '127.0.0.1'}]}})

        self.assertEqual(2, data_set.call_count)
        data_set.assert_has_calls((
            mock.call('internal_ports', '[]'),
            mock.call('internal_ports', '[{"id": "1122"}, {"id": "5566"}]')))

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
        server.client_plugin()._has_extension.return_value = True
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

    def test_prepare_ports_for_replace(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)
        port_ids = [{'id': 1122}, {'id': 3344}]
        external_port_ids = [{'id': 5566}]
        server._data = {"internal_ports": jsonutils.dumps(port_ids),
                        "external_ports": jsonutils.dumps(external_port_ids)}
        data_set = self.patchobject(server, 'data_set')

        port1_fixed_ip = {
            'fixed_ips': {
                'subnet_id': 'test_subnet1',
                'ip_address': '41.41.41.41'
            }
        }
        port2_fixed_ip = {
            'fixed_ips': {
                'subnet_id': 'test_subnet2',
                'ip_address': '42.42.42.42'
            }
        }
        port3_fixed_ip = {
            'fixed_ips': {
                'subnet_id': 'test_subnet3',
                'ip_address': '43.43.43.43'
            }
        }
        self.port_show.side_effect = [{'port': port1_fixed_ip},
                                      {'port': port2_fixed_ip},
                                      {'port': port3_fixed_ip}]

        server.prepare_for_replace()

        # check, that data was updated
        port_ids[0].update(port1_fixed_ip)
        port_ids[1].update(port2_fixed_ip)
        external_port_ids[0].update(port3_fixed_ip)

        expected_data = jsonutils.dumps(port_ids)
        expected_external_data = jsonutils.dumps(external_port_ids)
        data_set.assert_has_calls([
            mock.call('internal_ports', expected_data),
            mock.call('external_ports', expected_external_data)])

        # check, that all ip were removed from ports
        empty_fixed_ips = {'port': {'fixed_ips': []}}
        self.port_update.assert_has_calls([
            mock.call(1122, empty_fixed_ips),
            mock.call(3344, empty_fixed_ips),
            mock.call(5566, empty_fixed_ips)])

    def test_restore_ports_after_rollback(self):
        t, stack, server = self._return_template_stack_and_rsrc_defn(
            'test', tmpl_server_with_network_id)
        port_ids = [{'id': 1122}, {'id': 3344}]
        external_port_ids = [{'id': 5566}]
        server._data = {"internal_ports": jsonutils.dumps(port_ids),
                        "external_ports": jsonutils.dumps(external_port_ids)}
        port1_fixed_ip = {
            'fixed_ips': {
                'subnet_id': 'test_subnet1',
                'ip_address': '41.41.41.41'
            }
        }
        port2_fixed_ip = {
            'fixed_ips': {
                'subnet_id': 'test_subnet2',
                'ip_address': '42.42.42.42'
            }
        }
        port3_fixed_ip = {
            'fixed_ips': {
                'subnet_id': 'test_subnet3',
                'ip_address': '43.43.43.43'
            }
        }
        port_ids[0].update(port1_fixed_ip)
        port_ids[1].update(port2_fixed_ip)
        external_port_ids[0].update(port3_fixed_ip)
        # add data to old server in backup stack
        old_server = mock.Mock()
        stack._backup_stack = mock.Mock()
        stack._backup_stack().resources.get.return_value = old_server
        old_server._data_get_ports.side_effect = [port_ids, external_port_ids]

        server.restore_prev_rsrc()

        # check, that all ip were removed from new_ports
        empty_fixed_ips = {'port': {'fixed_ips': []}}
        self.port_update.assert_has_calls([
            mock.call(1122, empty_fixed_ips),
            mock.call(3344, empty_fixed_ips),
            mock.call(5566, empty_fixed_ips)])

        # check, that all ip were restored for old_ports
        self.port_update.assert_has_calls([
            mock.call(1122, {'port': port1_fixed_ip}),
            mock.call(3344, {'port': port2_fixed_ip}),
            mock.call(5566, {'port': port3_fixed_ip})])

    def test_restore_ports_after_rollback_convergence(self):
        t = template_format.parse(tmpl_server_with_network_id)
        stack = utils.parse_stack(t)
        stack.store()

        # mock resource from previous template
        prev_rsrc = stack['server']
        prev_rsrc.resource_id = 'prev-rsrc'
        # store in db
        prev_rsrc.state_set(prev_rsrc.UPDATE, prev_rsrc.COMPLETE)

        # mock resource from existing template, store in db, and set _data
        existing_rsrc = stack['server']
        existing_rsrc.current_template_id = stack.t.id
        existing_rsrc.resource_id = 'existing-rsrc'
        existing_rsrc.state_set(existing_rsrc.UPDATE, existing_rsrc.COMPLETE)

        port_ids = [{'id': 1122}, {'id': 3344}]
        external_port_ids = [{'id': 5566}]
        existing_rsrc.data_set("internal_ports", jsonutils.dumps(port_ids))
        existing_rsrc.data_set("external_ports",
                               jsonutils.dumps(external_port_ids))

        # mock previous resource was replaced by existing resource
        prev_rsrc.replaced_by = existing_rsrc.id

        port1_fixed_ip = {
            'fixed_ips': {
                'subnet_id': 'test_subnet1',
                'ip_address': '41.41.41.41'
            }
        }
        port2_fixed_ip = {
            'fixed_ips': {
                'subnet_id': 'test_subnet2',
                'ip_address': '42.42.42.42'
            }
        }
        port3_fixed_ip = {
            'fixed_ips': {
                'subnet_id': 'test_subnet3',
                'ip_address': '43.43.43.43'
            }
        }
        port_ids[0].update(port1_fixed_ip)
        port_ids[1].update(port2_fixed_ip)
        external_port_ids[0].update(port3_fixed_ip)
        # add data to old server
        prev_rsrc._data = {
            "internal_ports": jsonutils.dumps(port_ids),
            "external_ports": jsonutils.dumps(external_port_ids)
        }

        prev_rsrc.restore_prev_rsrc(convergence=True)

        # check, that all ip were removed from new_ports
        empty_fixed_ips = {'port': {'fixed_ips': []}}
        self.port_update.assert_has_calls([
            mock.call(1122, empty_fixed_ips),
            mock.call(3344, empty_fixed_ips),
            mock.call(5566, empty_fixed_ips)])

        # check, that all ip were restored for old_ports
        self.port_update.assert_has_calls([
            mock.call(1122, {'port': port1_fixed_ip}),
            mock.call(3344, {'port': port2_fixed_ip}),
            mock.call(5566, {'port': port3_fixed_ip})])

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
