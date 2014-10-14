
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
import uuid

import mock
import mox
from novaclient import exceptions

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources import image
from heat.engine.resources import nova_utils
from heat.engine.resources import server as servers
from heat.engine.resources.software_config import software_config as sc
from heat.engine import scheduler
from heat.openstack.common.gettextutils import _
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils
from heat.tests.v1_1 import fakes as fakes_v1_1


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


class ServersTest(HeatTestCase):
    def setUp(self):
        super(ServersTest, self).setUp()
        self.fc = fakes_v1_1.FakeClient()
        self.fkc = fakes.FakeKeystoneClient()

        utils.setup_dummy_db()
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

    def _setup_test_stack(self, stack_name):
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             environment.Environment({'key_name': 'test'}),
                             stack_id=str(uuid.uuid4()),
                             stack_user_project_id='8888')
        return (t, stack)

    def _setup_test_server(self, return_server, name, image_id=None,
                           override_name=False, stub_create=True):
        stack_name = '%s_s' % name
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['image'] = \
            image_id or 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['flavor'] = \
            '256 MB Server'

        server_name = '%s' % name
        if override_name:
            t['Resources']['WebServer']['Properties']['name'] = \
                server_name

        server = servers.Server(server_name,
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server.t = server.stack.resolve_runtime_data(server.t)

        if stub_create:
            self.m.StubOutWithMock(self.fc.servers, 'create')
            self.fc.servers.create(
                image=1, flavor=1, key_name='test',
                name=override_name and server.name or utils.PhysName(
                    stack_name, server.name),
                security_groups=[],
                userdata=mox.IgnoreArg(), scheduler_hints=None,
                meta=None, nics=None, availability_zone=None,
                block_device_mapping=None, config_drive=None,
                disk_config=None, reservation_id=None, files={},
                admin_pass=None).AndReturn(return_server)

        return server

    def _create_test_server(self, return_server, name, override_name=False,
                            stub_create=True):
        server = self._setup_test_server(return_server, name,
                                         stub_create=stub_create)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        return server

    def _create_fake_iface(self, port, mac, ip):
        class fake_interface():
            def __init__(self, port_id, mac_addr, fixed_ip):
                self.port_id = port_id
                self.mac_addr = mac_addr
                self.fixed_ips = [{'ip_address': fixed_ip}]

        return fake_interface(port, mac, ip)

    def test_server_create(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = 5678
        server = self._create_test_server(return_server,
                                          'test_server_create')
        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        interfaces = [
            self._create_fake_iface('1234', 'fa:16:3e:8c:22:aa', '4.5.6.7'),
            self._create_fake_iface('5678', 'fa:16:3e:8c:33:bb', '5.6.9.8'),
            self._create_fake_iface(
                '1013', 'fa:16:3e:8c:44:cc', '10.13.12.13')]

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(5678).MultipleTimes().AndReturn(return_server)

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
        self.m.VerifyAll()

    def test_server_create_metadata(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'create_metadata_test_stack'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['metadata'] = \
            {'a': 1}
        server = servers.Server('create_metadata_test_server',
                                t['Resources']['WebServer'], stack)
        server.t = server.stack.resolve_runtime_data(server.t)

        instance_meta = {'a': "1"}
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=mox.IgnoreArg(), flavor=mox.IgnoreArg(), key_name='test',
            name=mox.IgnoreArg(), security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=instance_meta, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None, files={},
            admin_pass=None).AndReturn(return_server)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_server_create_with_image_id(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = 5678
        server = self._setup_test_server(return_server,
                                         'test_server_create_image_id',
                                         image_id='1',
                                         override_name=True)
        self.m.StubOutWithMock(uuidutils, "is_uuid_like")
        uuidutils.is_uuid_like('1').MultipleTimes().AndReturn(True)

        interfaces = [
            self._create_fake_iface('1234', 'fa:16:3e:8c:22:aa', '4.5.6.7'),
            self._create_fake_iface('5678', 'fa:16:3e:8c:33:bb', '5.6.9.8'),
            self._create_fake_iface(
                '1013', 'fa:16:3e:8c:44:cc', '10.13.12.13')]

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(5678).MultipleTimes().AndReturn(return_server)

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
        self.assertEqual(
            server.FnGetAtt('addresses')['public'][0]['addr'], public_ip)
        self.assertEqual(
            server.FnGetAtt('networks')['public'][0], public_ip)

        private_ip = return_server.networks['private'][0]
        self.assertEqual('1013',
                         server.FnGetAtt('addresses')['private'][0]['port'])
        self.assertEqual(
            server.FnGetAtt('addresses')['private'][0]['addr'], private_ip)
        self.assertEqual(
            server.FnGetAtt('networks')['private'][0], private_ip)
        self.assertIn(
            server.FnGetAtt('first_address'), (private_ip, public_ip))

        self.m.VerifyAll()

    def test_server_create_image_name_err(self):
        stack_name = 'img_name_err'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image name
        t['Resources']['WebServer']['Properties']['image'] = 'Slackware'
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        error = self.assertRaises(ValueError, server.handle_create)
        self.assertEqual(
            'server_create_image_err: image "Slackware" does not '
            'validate glance.image',
            str(error))

        self.m.VerifyAll()

    def test_server_create_duplicate_image_name_err(self):
        stack_name = 'img_dup_err'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with a non unique image name
        t['Resources']['WebServer']['Properties']['image'] = 'CentOS 5.2'
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc.client, "get_images_detail")
        self.fc.client.get_images_detail().AndReturn((
            200, {'images': [{'id': 1, 'name': 'CentOS 5.2'},
                             {'id': 4, 'name': 'CentOS 5.2'}]}))
        self.m.ReplayAll()

        error = self.assertRaises(ValueError, server.handle_create)
        self.assertEqual(
            'server_create_image_err: image Multiple physical resources were '
            'found with name (CentOS 5.2).',
            str(error))

        self.m.VerifyAll()

    def test_server_create_image_id_err(self):
        stack_name = 'img_id_err'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        t['Resources']['WebServer']['Properties']['image'] = '1'
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(uuidutils, "is_uuid_like")
        uuidutils.is_uuid_like('1').AndReturn(True)
        self.m.StubOutWithMock(self.fc.client, "get_images_1")
        self.fc.client.get_images_1().AndRaise(
            servers.clients.novaclient.exceptions.NotFound(404))
        self.m.ReplayAll()

        error = self.assertRaises(ValueError, server.handle_create)
        self.assertEqual(
            'server_create_image_err: image "1" does not '
            'validate glance.image',
            str(error))

        self.m.VerifyAll()

    def test_server_create_unexpected_status(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'cr_unexp_sts')
        return_server.get = lambda: None
        return_server.status = 'BOGUS'
        self.assertRaises(exception.Error,
                          server.check_create_complete,
                          return_server)

    def test_server_create_error_status(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'cr_err_sts')
        return_server.status = 'ERROR'
        return_server.fault = {
            'message': 'NoValidHost',
            'code': 500,
            'created': '2013-08-14T03:12:10Z'
        }
        self.m.StubOutWithMock(return_server, 'get')
        return_server.get()
        self.m.ReplayAll()

        self.assertRaises(exception.Error,
                          server.check_create_complete,
                          return_server)

        self.m.VerifyAll()

    def test_server_create_raw_userdata(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'raw_userdata_s'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['user_data_format'] = \
            'RAW'

        server = servers.Server('WebServer',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata='wordpress', scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None, files={},
            admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_server_create_raw_config_userdata(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'raw_userdata_s'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['user_data_format'] = \
            'RAW'
        t['Resources']['WebServer']['Properties']['user_data'] = \
            '8c813873-f6ee-4809-8eec-959ef39acb55'

        server = servers.Server('WebServer',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        self.m.StubOutWithMock(server, 'heat')
        self.m.StubOutWithMock(sc.SoftwareConfig, 'get_software_config')
        server.heat().AndReturn(None)
        sc.SoftwareConfig.get_software_config(
            None, '8c813873-f6ee-4809-8eec-959ef39acb55').AndReturn(
                'wordpress from config')

        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata='wordpress from config', scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None, files={},
            admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_server_create_raw_config_userdata_None(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'raw_userdata_s'
        (t, stack) = self._setup_test_stack(stack_name)

        sc_id = '8c813873-f6ee-4809-8eec-959ef39acb55'
        t['Resources']['WebServer']['Properties']['user_data_format'] = \
            'RAW'
        t['Resources']['WebServer']['Properties']['user_data'] = sc_id

        server = servers.Server('WebServer',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        self.m.StubOutWithMock(server, 'heat')
        self.m.StubOutWithMock(sc.SoftwareConfig, 'get_software_config')
        server.heat().AndReturn(None)
        sc.SoftwareConfig.get_software_config(
            None, sc_id).AndRaise(exception.SoftwareConfigMissing(
                software_config_id=sc_id))

        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=sc_id,
            scheduler_hints=None, meta=None,
            nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None, files={},
            admin_pass=None).AndReturn(return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_server_create_software_config(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'software_config_s'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['user_data_format'] = \
            'SOFTWARE_CONFIG'

        stack.stack_user_project_id = '8888'
        server = servers.Server('WebServer',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        self.m.StubOutWithMock(server, 'keystone')
        self.m.StubOutWithMock(server, 'heat')
        self.m.StubOutWithMock(server, '_get_deployments_metadata')

        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server.keystone().MultipleTimes().AndReturn(self.fkc)
        server.heat().MultipleTimes().AndReturn(self.fc)
        server._get_deployments_metadata(
            self.fc, 5678).AndReturn({'foo': 'bar'})

        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None, files={},
            admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()

        self.assertEqual('4567', server.access_key)
        self.assertEqual('8901', server.secret_key)
        self.assertEqual('1234', server._get_user_id())

        self.assertTrue(stack.access_allowed('4567', 'WebServer'))
        self.assertFalse(stack.access_allowed('45678', 'WebServer'))
        self.assertFalse(stack.access_allowed('4567', 'wWebServer'))

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
            'deployments': {'foo': 'bar'}
        }, server.metadata)

        created_server = servers.Server('WebServer',
                                        t['Resources']['WebServer'], stack)
        self.assertEqual('4567', created_server.access_key)
        self.assertTrue(stack.access_allowed('4567', 'WebServer'))

        self.m.VerifyAll()

    def test_server_create_software_config_poll_heat(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'software_config_s'
        (t, stack) = self._setup_test_stack(stack_name)

        props = t['Resources']['WebServer']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        props['software_config_transport'] = 'POLL_SERVER_HEAT'

        server = servers.Server('WebServer',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        self.m.StubOutWithMock(server, 'keystone')
        self.m.StubOutWithMock(server, 'heat')
        self.m.StubOutWithMock(server, '_get_deployments_metadata')

        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server.keystone().MultipleTimes().AndReturn(self.fkc)
        server.heat().MultipleTimes().AndReturn(self.fc)
        server._get_deployments_metadata(
            self.fc, 5678).AndReturn({'foo': 'bar'})

        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None, files={},
            admin_pass=None).AndReturn(
                return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()

        #self.assertEqual('4567', server.access_key)
        #self.assertEqual('8901', server.secret_key)
        self.assertEqual('1234', server._get_user_id())

        self.assertTrue(stack.access_allowed('1234', 'WebServer'))
        self.assertFalse(stack.access_allowed('45678', 'WebServer'))
        self.assertFalse(stack.access_allowed('4567', 'wWebServer'))

        self.assertEqual({
            'os-collect-config': {
                'heat': {
                    'auth_url': 'http://server.test:5000/v2.0',
                    'password': None,
                    'project_id': '8888',
                    'resource_name': 'WebServer',
                    'stack_id': 'software_config_s/%s' % stack.id,
                    'user_id': '1234'
                }
            },
            'deployments': {'foo': 'bar'}
        }, server.metadata)

        created_server = servers.Server('WebServer',
                                        t['Resources']['WebServer'], stack)
        self.assertEqual('1234', created_server._get_user_id())
        self.assertTrue(stack.access_allowed('1234', 'WebServer'))

        self.m.VerifyAll()

    def test_server_metadata_with_empty_deploy(self):
        stack_name = 'software_config_s'
        (t, stack) = self._setup_test_stack(stack_name)
        props = t['Resources']['WebServer']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        server = servers.Server('WebServer',
                                t['Resources']['WebServer'], stack)
        self.m.StubOutWithMock(server, 'keystone')
        server.t = server.stack.resolve_runtime_data(server.t)
        self.m.ReplayAll()
        deployments = server.metadata['deployments']
        self.assertEqual([], deployments)
        self.m.VerifyAll()

    @mock.patch.object(clients.OpenStackClients, 'nova')
    def test_server_create_default_admin_pass(self, mock_nova):
        return_server = self.fc.servers.list()[1]
        return_server.adminPass = 'autogenerated'
        stack_name = 'admin_pass_s'
        (t, stack) = self._setup_test_stack(stack_name)

        server = servers.Server('WebServer',
                                t['Resources']['WebServer'], stack)

        mock_nova.return_value = self.fc
        server.t = server.stack.resolve_runtime_data(server.t)
        self.fc.servers.create = mock.Mock(return_value=return_server)

        scheduler.TaskRunner(server.create)()
        self.fc.servers.create.assert_called_once_with(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mock.ANY, scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None,
            files={}, admin_pass=None)

    @mock.patch.object(clients.OpenStackClients, 'nova')
    def test_server_create_custom_admin_pass(self, mock_nova):
        return_server = self.fc.servers.list()[1]
        return_server.adminPass = 'foo'
        stack_name = 'admin_pass_s'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['admin_pass'] = 'foo'
        server = servers.Server('WebServer',
                                t['Resources']['WebServer'], stack)

        mock_nova.return_value = self.fc
        server.t = server.stack.resolve_runtime_data(server.t)
        self.fc.servers.create = mock.Mock(return_value=return_server)

        scheduler.TaskRunner(server.create)()
        self.fc.servers.create.assert_called_once_with(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mock.ANY, scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None,
            files={}, admin_pass='foo')

    def test_check_maximum(self):
        msg = 'test_check_maximum'
        self.assertIsNone(servers.Server._check_maximum(1, 1, msg))
        self.assertIsNone(servers.Server._check_maximum(1000, -1, msg))
        error = self.assertRaises(exception.StackValidationFailed,
                                  servers.Server._check_maximum,
                                  2, 1, msg)
        self.assertEqual(msg, str(error))

    def test_server_validate(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        t['Resources']['WebServer']['Properties']['image'] = '1'
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(image.ImageConstraint, "validate")
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)

        self.m.ReplayAll()

        self.assertIsNone(server.validate())

        self.m.VerifyAll()

    def test_server_validate_with_bootable_vol(self):
        stack_name = 'srv_val_bootvol'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with bootable volume
        web_server = t['Resources']['WebServer']
        del web_server['Properties']['image']

        def create_server(device_name):
            self.m.UnsetStubs()
            web_server['Properties']['block_device_mapping'] = [{
                "device_name": device_name,
                "volume_id": "5d7e27da-6703-4f7e-9f94-1f67abef734c",
                "delete_on_termination": False
            }]
            server = servers.Server('server_with_bootable_volume',
                                    web_server, stack)
            self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
            clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
            self.m.ReplayAll()
            return server

        server = create_server(u'vda')
        self.assertIsNone(server.validate())
        server = create_server('vda')
        self.assertIsNone(server.validate())
        server = create_server('vdb')
        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertEqual('Neither image nor bootable volume is specified for '
                         'instance server_with_bootable_volume', str(ex))
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
        t = template_format.parse(nova_keypair_template)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             stack_id=str(uuid.uuid4()))

        server = servers.Server('server_validate_test',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        self.m.StubOutWithMock(image.ImageConstraint, "validate")
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.ReplayAll()
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_with_invalid_ssh_key(self):
        stack_name = 'srv_val_test'
        (t, stack) = self._setup_test_stack(stack_name)

        web_server = t['Resources']['WebServer']

        # Make the ssh key have an invalid name
        web_server['Properties']['key_name'] = 'test2'

        server = servers.Server('server_validate_test',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        error = self.assertRaises(exception.StackValidationFailed,
                                  server.validate)
        self.assertEqual(
            'Property error : server_validate_test: key_name "test2" does '
            'not validate nova.keypair',
            str(error))
        self.m.VerifyAll()

    def test_server_validate_delete_policy(self):
        stack_name = 'srv_val_delpol'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        t['Resources']['WebServer']['DeletionPolicy'] = 'SelfDestruct'
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertEqual('Invalid DeletionPolicy SelfDestruct',
                         str(ex))

        self.m.VerifyAll()

    def test_server_validate_with_networks(self):
        stack_name = 'srv_net'
        (t, stack) = self._setup_test_stack(stack_name)

        network_name = 'public'
        # create an server with 'uuid' and 'network' properties
        t['Resources']['WebServer']['Properties']['networks'] = (
            [{'uuid': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
              'network': network_name}])

        server = servers.Server('server_validate_with_networks',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertIn(_('Properties "uuid" and "network" are both set to '
                        'the network "%(network)s" for the server '
                        '"%(server)s". The "uuid" property is deprecated. '
                        'Use only "network" property.'
                        '') % dict(network=network_name, server=server.name),
                      str(ex))
        self.m.VerifyAll()

    def test_server_validate_net_security_groups(self):
        # Test that if network 'ports' are assigned security groups are
        # not, because they'll be ignored
        stack_name = 'srv_net_secgroups'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['networks'] = [
            {'port': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}]
        t['Resources']['WebServer']['Properties']['security_groups'] = \
            ['my_security_group']

        server = servers.Server('server_validate_net_security_groups',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        error = self.assertRaises(exception.ResourcePropertyConflict,
                                  server.validate)
        self.assertEqual("Cannot define the following properties at the same "
                         "time: security_groups, networks/port.",
                         str(error))
        self.m.VerifyAll()

    def test_server_delete(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete')
        server.resource_id = 1234

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        server_get = self.fc.client.get_servers_1234()
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn(server_get)
        get().AndRaise(servers.clients.novaclient.exceptions.NotFound(404))
        mox.Replay(get)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.delete)()
        self.assertIsNone(server.resource_id)
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_delete_notfound(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'create_delete2')
        server.resource_id = 1234

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndRaise(servers.clients.novaclient.exceptions.NotFound(404))
        mox.Replay(get)

        scheduler.TaskRunner(server.delete)()
        self.assertIsNone(server.resource_id)
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)
        self.m.VerifyAll()

        server.state_set(server.CREATE, server.COMPLETE, 'to delete again')
        scheduler.TaskRunner(server.delete)()
        self.assertEqual((server.DELETE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_metadata(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')

        update_template = copy.deepcopy(server.t)
        update_template['Metadata'] = {'test': 123}
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual({'test': 123}, server.metadata)

        server.t['Metadata'] = {'test': 456}
        server.metadata_update()
        self.assertEqual({'test': 456}, server.metadata)

    def test_server_update_nova_metadata(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')

        new_meta = {'test': 123}
        self.m.StubOutWithMock(self.fc.servers, 'set_meta')
        self.fc.servers.set_meta(return_server,
                                 nova_utils.meta_serialize(
                                     new_meta)).AndReturn(None)
        self.m.ReplayAll()
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['metadata'] = new_meta
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_nova_metadata_complex(self):
        """
        Test that complex metadata values are correctly serialized
        to JSON when sent to Nova.
        """

        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'md_update')

        new_meta = {'test': {'testkey': 'testvalue'}}
        self.m.StubOutWithMock(self.fc.servers, 'set_meta')

        # If we're going to call set_meta() directly we
        # need to handle the serialization ourselves.
        self.fc.servers.set_meta(return_server,
                                 nova_utils.meta_serialize(
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
        new_meta = {'test': '123', 'this': 'that'}
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
        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()
        new_meta = {'new_key': 'yeah'}

        self.m.StubOutWithMock(self.fc.servers, 'delete_meta')
        new_return_server = self.fc.servers.list()[5]
        self.fc.servers.delete_meta(new_return_server,
                                    ['test', 'this']).AndReturn(None)

        self.m.StubOutWithMock(self.fc.servers, 'set_meta')
        self.fc.servers.set_meta(new_return_server,
                                 new_meta).AndReturn(None)
        self.m.ReplayAll()
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['metadata'] = new_meta

        # new fake with the correct metadata
        server.resource_id = '56789'

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_server_name(self):
        """
        Server.handle_update supports changing the name.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = 5678
        server = self._create_test_server(return_server,
                                          'srv_update')
        new_name = 'new_name'
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['name'] = new_name

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(5678).AndReturn(return_server)

        self.m.StubOutWithMock(return_server, 'update')
        return_server.update(new_name).AndReturn(None)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_server_flavor(self):
        """
        Server.handle_update supports changing the flavor, and makes
        the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = 1234
        server = self._create_test_server(return_server,
                                          'srv_update')

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['flavor'] = 'm1.small'

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(1234).AndReturn(return_server)

        def activate_status(server):
            server.status = 'VERIFY_RESIZE'
        return_server.get = activate_status.__get__(return_server)

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
        """
        If the status after a resize is not VERIFY_RESIZE, it means the resize
        call failed, so we raise an explicit error.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = 1234
        server = self._create_test_server(return_server,
                                          'srv_update2')

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['flavor'] = 'm1.small'

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(1234).AndReturn(return_server)

        def activate_status(server):
            server.status = 'ACTIVE'
        return_server.get = activate_status.__get__(return_server)

        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')
        self.fc.client.post_servers_1234_action(
            body={'resize': {'flavorRef': 2}}).AndReturn((202, None))
        self.m.ReplayAll()

        updater = scheduler.TaskRunner(server.update, update_template)
        error = self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual(
            "Error: Resizing to 'm1.small' failed, status 'ACTIVE'",
            str(error))
        self.assertEqual((server.UPDATE, server.FAILED), server.state)
        self.m.VerifyAll()

    def test_server_update_server_flavor_replace(self):
        stack_name = 'update_flvrep'
        (t, stack) = self._setup_test_stack(stack_name)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        t['Resources']['WebServer']['Properties'][
            'flavor_update_policy'] = 'REPLACE'
        server = servers.Server('server_server_update_flavor_replace',
                                t['Resources']['WebServer'], stack)

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['flavor'] = 'm1.smigish'
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_server_update_server_flavor_policy_update(self):
        stack_name = 'update_flvpol'
        (t, stack) = self._setup_test_stack(stack_name)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        server = servers.Server('server_server_update_flavor_replace',
                                t['Resources']['WebServer'], stack)

        update_template = copy.deepcopy(server.t)
        # confirm that when flavor_update_policy is changed during
        # the update then the updated policy is followed for a flavor
        # update
        update_template['Properties']['flavor_update_policy'] = 'REPLACE'
        update_template['Properties']['flavor'] = 'm1.smigish'
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_server_update_image_replace(self):
        stack_name = 'update_imgrep'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties'][
            'image_update_policy'] = 'REPLACE'
        server = servers.Server('server_update_image_replace',
                                t['Resources']['WebServer'], stack)
        image_id = self.getUniqueString()
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(image.ImageConstraint, "validate")
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.ReplayAll()

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = image_id
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def _test_server_update_image_rebuild(self, status, policy='REBUILD'):
        # Server.handle_update supports changing the image, and makes
        # the change making a rebuild API call against Nova.
        return_server = self.fc.servers.list()[1]
        return_server.id = 1234
        server = self._create_test_server(return_server,
                                          'srv_updimgrbld')

        new_image = 'F17-x86_64-gold'
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = new_image
        server.t['Properties']['image_update_policy'] = policy

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(1234).MultipleTimes().AndReturn(return_server)
        self.m.StubOutWithMock(self.fc.servers, 'rebuild')
        # 744 is a static lookup from the fake images list
        if 'REBUILD' == policy:
            self.fc.servers.rebuild(
                return_server, 744, password=None, preserve_ephemeral=False)
        else:
            self.fc.servers.rebuild(
                return_server, 744, password=None, preserve_ephemeral=True)
        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')
        for stat in status:
            def activate_status(serv):
                serv.status = stat
            return_server.get = activate_status.__get__(return_server)

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
            policy='REBUILD_PRESERVE_EPHEMERAL', status=('ACTIVE'))

    def test_server_update_image_rebuild_failed(self):
        # If the status after a rebuild is not REBUILD or ACTIVE, it means the
        # rebuild call failed, so we raise an explicit error.
        return_server = self.fc.servers.list()[1]
        return_server.id = 1234
        server = self._create_test_server(return_server,
                                          'srv_updrbldfail')

        new_image = 'F17-x86_64-gold'
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = new_image
        server.t['Properties']['image_update_policy'] = 'REBUILD'

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(1234).MultipleTimes().AndReturn(return_server)
        self.m.StubOutWithMock(self.fc.servers, 'rebuild')
        # 744 is a static lookup from the fake images list
        self.fc.servers.rebuild(
            return_server, 744, password=None, preserve_ephemeral=False)
        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')

        def activate_status(server):
            server.status = 'REBUILD'
        return_server.get = activate_status.__get__(return_server)

        def activate_status2(server):
            server.status = 'ERROR'
        return_server.get = activate_status2.__get__(return_server)
        self.m.ReplayAll()
        updater = scheduler.TaskRunner(server.update, update_template)
        error = self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual(
            "Error: Rebuilding server failed, status 'ERROR'",
            str(error))
        self.assertEqual((server.UPDATE, server.FAILED), server.state)
        self.m.VerifyAll()

    def test_server_update_attr_replace(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'update_rep')

        update_template = copy.deepcopy(server.t)
        update_template['UpdatePolicy'] = {'test': 123}
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_server_update_properties(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'update_prop')

        self.m.StubOutWithMock(image.ImageConstraint, "validate")
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.ReplayAll()

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = 'mustreplace'
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_server_status_build(self):
        return_server = self.fc.servers.list()[0]
        server = self._setup_test_server(return_server,
                                         'sts_build')
        server.resource_id = 1234

        # Bind fake get method which Server.check_create_complete will call
        def activate_status(server):
            server.status = 'ACTIVE'
        return_server.get = activate_status.__get__(return_server)
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
        self.assertEqual('Error: Cannot suspend srv_sus1, '
                         'resource_id not set',
                         str(ex))
        self.assertEqual((server.SUSPEND, server.FAILED), server.state)

        self.m.VerifyAll()

    def test_server_status_suspend_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_sus2')

        server.resource_id = 1234
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndRaise(servers.clients.novaclient.exceptions.NotFound(404))
        mox.Replay(get)
        self.m.ReplayAll()

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.suspend))
        self.assertEqual('NotFound: Failed to find server 1234',
                         str(ex))
        self.assertEqual((server.SUSPEND, server.FAILED), server.state)

        self.m.VerifyAll()

    def test_server_status_suspend_immediate(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_suspend3')

        server.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to SUSPENDED
        d = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d['server']['status'] = 'SUSPENDED'
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d))
        mox.Replay(get)

        scheduler.TaskRunner(server.suspend)()
        self.assertEqual((server.SUSPEND, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_server_status_resume_immediate(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_resume1')

        server.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to SUSPENDED
        d = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d['server']['status'] = 'ACTIVE'
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d))
        mox.Replay(get)
        server.state_set(server.SUSPEND, server.COMPLETE)

        scheduler.TaskRunner(server.resume)()
        self.assertEqual((server.RESUME, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_server_status_suspend_wait(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_susp_w')

        server.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to SUSPENDED, but
        # return the ACTIVE state first (twice, so we sleep)
        d1 = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d2 = copy.deepcopy(d1)
        d1['server']['status'] = 'ACTIVE'
        d2['server']['status'] = 'SUSPENDED'
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d1))
        get().AndReturn((200, d1))
        get().AndReturn((200, d2))
        self.m.ReplayAll()

        scheduler.TaskRunner(server.suspend)()
        self.assertEqual((server.SUSPEND, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_server_status_suspend_unknown_status(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_susp_uk')

        server.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to SUSPENDED, but
        # return the ACTIVE state first (twice, so we sleep)
        d1 = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d2 = copy.deepcopy(d1)
        d1['server']['status'] = 'ACTIVE'
        d2['server']['status'] = 'TRANSMOGRIFIED'
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d1))
        get().AndReturn((200, d1))
        get().AndReturn((200, d2))
        self.m.ReplayAll()

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.suspend))
        self.assertEqual('Error: Suspend of server sample-server failed '
                         'with unknown status: TRANSMOGRIFIED',
                         str(ex))
        self.assertEqual((server.SUSPEND, server.FAILED), server.state)

        self.m.VerifyAll()

    def test_server_status_resume_wait(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_res_w')

        server.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to ACTIVE, but
        # return the SUSPENDED state first (twice, so we sleep)
        d1 = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d2 = copy.deepcopy(d1)
        d1['server']['status'] = 'SUSPENDED'
        d2['server']['status'] = 'ACTIVE'
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d1))
        get().AndReturn((200, d1))
        get().AndReturn((200, d2))
        self.m.ReplayAll()

        server.state_set(server.SUSPEND, server.COMPLETE)

        scheduler.TaskRunner(server.resume)()
        self.assertEqual((server.RESUME, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_server_status_resume_no_resource_id(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_susp_norid')

        server.resource_id = None
        self.m.ReplayAll()

        server.state_set(server.SUSPEND, server.COMPLETE)
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.resume))
        self.assertEqual('Error: Cannot resume srv_susp_norid, '
                         'resource_id not set',
                         str(ex))
        self.assertEqual((server.RESUME, server.FAILED), server.state)

        self.m.VerifyAll()

    def test_server_status_resume_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_res_nf')

        server.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to ACTIVE, but
        # return the SUSPENDED state first (twice, so we sleep)
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndRaise(servers.clients.novaclient.exceptions.NotFound(404))
        self.m.ReplayAll()

        server.state_set(server.SUSPEND, server.COMPLETE)

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.resume))
        self.assertEqual('NotFound: Failed to find server 1234',
                         str(ex))
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
        server.resource_id = 1234

        check_iterations = [0]

        # Bind fake get method which Server.check_create_complete will call
        def activate_status(server):
            check_iterations[0] += 1
            if check_iterations[0] == 1:
                server.status = uncommon_status
            if check_iterations[0] > 2:
                server.status = 'ACTIVE'
        return_server.get = activate_status.__get__(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_build_nics(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_create')
        self.assertIsNone(server._build_nics([]))
        self.assertIsNone(server._build_nics(None))
        self.assertEqual([{'port-id': 'aaaabbbb'},
                          {'v4-fixed-ip': '192.0.2.0'}],
                         server._build_nics([{'port': 'aaaabbbb'},
                                             {'fixed_ip': '192.0.2.0'}]))

        self.assertEqual([{'net-id': '1234abcd'}],
                         server._build_nics([{'uuid': '1234abcd'}]))

        self.assertEqual([{'net-id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}],
                         server._build_nics(
                             [{'network':
                               'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}]
                         ))

        self.assertEqual([{'net-id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}],
                         server._build_nics([{'network': 'public'}]))

        self.assertRaises(exceptions.NoUniqueMatch, server._build_nics,
                          ([{'network': 'foo'}]))

        self.assertRaises(exceptions.NotFound, server._build_nics,
                          ([{'network': 'bar'}]))

    def test_server_without_ip_address(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = 9102
        server = self._create_test_server(return_server,
                                          'wo_ipaddr')

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(9102).MultipleTimes().AndReturn(return_server)

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
            'vda': '1234:',
            'vdb': '1234:snap',
        }, servers.Server._build_block_device_mapping([
            {'device_name': 'vda', 'volume_id': '1234'},
            {'device_name': 'vdb', 'snapshot_id': '1234'},
        ]))

        self.assertEqual({
            'vdc': '1234::10',
            'vdd': '1234:snap:0:True'
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
        t, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': 10}]
        t['Resources']['WebServer']['Properties']['block_device_mapping'] = bdm
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_validate_block_device_mapping_volume_size_valid_str(self):
        stack_name = 'val_vsize_valid'
        t, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': '10'}]
        t['Resources']['WebServer']['Properties']['block_device_mapping'] = bdm
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_validate_block_device_mapping_volume_size_invalid_str(self):
        stack_name = 'val_vsize_invalid'
        t, stack = self._setup_test_stack(stack_name)
        bdm = [{'device_name': 'vda', 'volume_id': '1234',
                'volume_size': '10a'}]
        t['Resources']['WebServer']['Properties']['block_device_mapping'] = bdm
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertIn("Value '10a' is not an integer", str(exc))

    def test_validate_conflict_block_device_mapping_props(self):
        stack_name = 'val_blkdev1'
        (t, stack) = self._setup_test_stack(stack_name)

        bdm = [{'device_name': 'vdb', 'snapshot_id': '1234',
                'volume_id': '1234'}]
        t['Resources']['WebServer']['Properties']['block_device_mapping'] = bdm
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        self.assertRaises(exception.ResourcePropertyConflict, server.validate)
        self.m.VerifyAll()

    def test_validate_insufficient_block_device_mapping_props(self):
        stack_name = 'val_blkdev2'
        (t, stack) = self._setup_test_stack(stack_name)

        bdm = [{'device_name': 'vdb', 'volume_size': 1,
                'delete_on_termination': True}]
        t['Resources']['WebServer']['Properties']['block_device_mapping'] = bdm
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        msg = 'Either volume_id or snapshot_id must be specified for device' +\
              ' mapping vdb'
        self.assertEqual(msg, str(ex))

        self.m.VerifyAll()

    def test_validate_without_image_or_bootable_volume(self):
        stack_name = 'val_imgvol'
        (t, stack) = self._setup_test_stack(stack_name)

        del t['Resources']['WebServer']['Properties']['image']
        bdm = [{'device_name': 'vdb', 'volume_id': '1234'}]
        t['Resources']['WebServer']['Properties']['block_device_mapping'] = bdm
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        msg = 'Neither image nor bootable volume is specified for instance %s'\
            % server.name
        self.assertEqual(msg, str(ex))

        self.m.VerifyAll()

    def test_validate_metadata_too_many(self):
        stack_name = 'srv_val_metadata'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['metadata'] = {'a': 1,
                                                                 'b': 2,
                                                                 'c': 3,
                                                                 'd': 4}
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               server.validate)
        self.assertIn('Instance metadata must not contain greater than 3 '
                      'entries', str(ex))
        self.m.VerifyAll()

    def test_validate_metadata_okay(self):
        stack_name = 'srv_val_metadata'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['metadata'] = {'a': 1,
                                                                 'b': 2,
                                                                 'c': 3}
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()
        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_too_many_personality(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['personality'] = \
            {"/fake/path1": "fake contents1",
             "/fake/path2": "fake_contents2",
             "/fake/path3": "fake_contents3",
             "/fake/path4": "fake_contents4",
             "/fake/path5": "fake_contents5",
             "/fake/path6": "fake_contents6"}
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertEqual("The personality property may not contain "
                         "greater than 5 entries.", str(exc))
        self.m.VerifyAll()

    def test_server_validate_personality_okay(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['personality'] = \
            {"/fake/path1": "fake contents1",
             "/fake/path2": "fake_contents2",
             "/fake/path3": "fake_contents3",
             "/fake/path4": "fake_contents4",
             "/fake/path5": "fake_contents5"}
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_personality_file_size_okay(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['personality'] = \
            {"/fake/path1": "a" * 10240}
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()

    def test_server_validate_personality_file_size_too_big(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['personality'] = \
            {"/fake/path1": "a" * 10241}
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().MultipleTimes().AndReturn(self.limits)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertEqual("The contents of personality file \"/fake/path1\" "
                         "is larger than the maximum allowed personality "
                         "file size (10240 bytes).", str(exc))
        self.m.VerifyAll()

    def test_resolve_attribute_server_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'srv_resolve_attr')

        server.resource_id = 1234
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndRaise(servers.clients.novaclient.exceptions.NotFound(404))
        mox.Replay(get)
        self.m.ReplayAll()

        self.assertEqual(server._resolve_attribute("accessIPv4"), '')
        self.m.VerifyAll()

    def test_default_instance_user(self):
        """The default value for instance_user in heat.conf is ec2-user."""
        return_server = self.fc.servers.list()[1]
        server = self._setup_test_server(return_server, 'default_user')
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(server,
                                  'wordpress',
                                  instance_user='ec2-user',
                                  user_data_format='HEAT_CFNTOOLS')
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_admin_user_property(self):
        """Test the admin_user property on the server overrides instance_user.

        Launching the instance should call build_userdata with the
        custom user name. This property is deprecated and will be
        removed in Juno.
        """
        return_server = self.fc.servers.list()[1]
        stack_name = 'stack_with_custom_admin_user_server'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['admin_user'] = 'custom_user'
        server = servers.Server('create_metadata_test_server',
                                t['Resources']['WebServer'], stack)
        server.t = server.stack.resolve_runtime_data(server.t)
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=mox.IgnoreArg(), flavor=mox.IgnoreArg(), key_name='test',
            name=mox.IgnoreArg(), security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=mox.IgnoreArg(), nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None, files={},
            admin_pass=None).AndReturn(return_server)
        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(server,
                                  'wordpress',
                                  instance_user='custom_user',
                                  user_data_format='HEAT_CFNTOOLS')
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_custom_instance_user(self):
        """Test instance_user in heat.conf being set to a custom value.

        Launching the instance should call build_userdata with the
        custom user name.

        This option is deprecated and will be removed in Juno.
        """
        return_server = self.fc.servers.list()[1]
        server = self._setup_test_server(return_server, 'custom_user')
        self.m.StubOutWithMock(servers.cfg.CONF, 'instance_user')
        servers.cfg.CONF.instance_user = 'custom_user'
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(server,
                                  'wordpress',
                                  instance_user='custom_user',
                                  user_data_format='HEAT_CFNTOOLS')
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_empty_instance_user(self):
        """Test instance_user in heat.conf being empty.

        Launching the instance should not pass any user to
        build_userdata. The default cloud-init user set up for the image
        will be used instead.

        This will the default behaviour in Juno once we remove the
        instance_user option.
        """
        return_server = self.fc.servers.list()[1]
        server = self._setup_test_server(return_server, 'custom_user')
        self.m.StubOutWithMock(servers.cfg.CONF, 'instance_user')
        servers.cfg.CONF.instance_user = ''
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(server,
                                  'wordpress',
                                  instance_user=None,
                                  user_data_format='HEAT_CFNTOOLS')
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def create_old_net(self, port=None, net=None, ip=None):
        return {'port': port, 'network': net, 'fixed_ip': ip, 'uuid': None}

    def create_fake_iface(self, port, net, ip):
        class fake_interface():
            def __init__(self, port_id, net_id, fixed_ip):
                self.port_id = port_id
                self.net_id = net_id
                self.fixed_ips = [{'ip_address': fixed_ip}]

        return fake_interface(port, net, ip)

    def test_get_network_matches_no_matching(self):
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
            for net in old_nets_copy:
                net.pop('uuid')
            for net in new_nets_copy:
                for key in ('port', 'network', 'fixed_ip'):
                    net[key] = net.get(key)

            matched_nets = server._get_network_matches(old_nets, new_nets)
            self.assertEqual([], matched_nets)
            self.assertEqual(old_nets_copy, old_nets)
            self.assertEqual(new_nets_copy, new_nets)

    def test_get_network_matches_success(self):
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
        for net in old_nets_copy:
            net.pop('uuid')
        for net in new_nets_copy:
            for key in ('port', 'network', 'fixed_ip'):
                net[key] = net.get(key)

        matched_nets = server._get_network_matches(old_nets, new_nets)
        self.assertEqual(old_nets_copy[:-1], matched_nets)
        self.assertEqual([old_nets_copy[2]], old_nets)
        self.assertEqual([new_nets_copy[2]], new_nets)

    def test_update_networks_matching_iface_port(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server, 'networks_update')

        # old order 0 1 2 3 4 5
        nets = [
            {'port': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'network': None, 'fixed_ip': None},
            {'port': None, 'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '1.2.3.4', },
            {'port': None, 'network': 'f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
             'fixed_ip': None},
            {'port': 'dddddddd-dddd-dddd-dddd-dddddddddddd',
             'network': None, 'fixed_ip': None},
            {'port': None, 'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '5.6.7.8'},
            {'port': None, 'network': '0da8adbf-a7e2-4c59-a511-96b03d2da0d7',
             'fixed_ip': None}]
        # new order 5 2 3 0 1 4
        interfaces = [
            self.create_fake_iface('ffffffff-ffff-ffff-ffff-ffffffffffff',
                                   nets[5]['network'], '10.0.0.10'),
            self.create_fake_iface('cccccccc-cccc-cccc-cccc-cccccccccccc',
                                   nets[2]['network'], '10.0.0.11'),
            self.create_fake_iface(nets[3]['port'],
                                   'f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
                                   '10.0.0.12'),
            self.create_fake_iface(nets[0]['port'],
                                   'gggggggg-1111-1111-1111-gggggggggggg',
                                   '10.0.0.13'),
            self.create_fake_iface('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                                   nets[1]['network'], nets[1]['fixed_ip']),
            self.create_fake_iface('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
                                   nets[4]['network'], nets[4]['fixed_ip'])]
        # all networks should get port id
        expected = [
            {'port': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'network': None, 'fixed_ip': None},
            {'port': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '1.2.3.4'},
            {'port': 'cccccccc-cccc-cccc-cccc-cccccccccccc',
             'network': 'f3ef5d2f-d7ba-4b27-af66-58ca0b81e032',
             'fixed_ip': None},
            {'port': 'dddddddd-dddd-dddd-dddd-dddddddddddd',
             'network': None, 'fixed_ip': None},
            {'port': 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
             'network': 'gggggggg-1111-1111-1111-gggggggggggg',
             'fixed_ip': '5.6.7.8'},
            {'port': 'ffffffff-ffff-ffff-ffff-ffffffffffff',
             'network': '0da8adbf-a7e2-4c59-a511-96b03d2da0d7',
             'fixed_ip': None}]

        server.update_networks_matching_iface_port(nets, interfaces)
        self.assertEqual(expected, nets)

    def test_server_update_None_networks_with_port(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = 9102
        server = self._create_test_server(return_server, 'networks_update')

        new_networks = [{'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = new_networks

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(9102).MultipleTimes().AndReturn(return_server)
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
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_None_networks_with_network_id(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = 9102
        server = self._create_test_server(return_server, 'networks_update')

        new_networks = [{'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                         'fixed_ip': '1.2.3.4'}]
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = new_networks

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(9102).MultipleTimes().AndReturn(return_server)
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
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_empty_networks_with_complex_parameters(self):
        return_server = self.fc.servers.list()[3]
        return_server.id = 9102
        server = self._create_test_server(return_server, 'networks_update')

        new_networks = [{'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                         'fixed_ip': '1.2.3.4',
                         'port': '2a60cbaa-3d33-4af6-a9ce-83594ac546fc'}]
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = new_networks

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(9102).MultipleTimes().AndReturn(return_server)
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
        return_server.interface_attach(
            new_networks[0]['port'], None, None).AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_networks_with_complex_parameters(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = 5678
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

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(5678).MultipleTimes().AndReturn(return_server)

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

        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach(
            new_networks[1]['port'], None, None).AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual((server.UPDATE, server.COMPLETE), server.state)
        self.m.VerifyAll()

    def test_server_update_networks_with_None(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = 5678
        server = self._create_test_server(return_server, 'networks_update')

        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '31.32.33.34'}]

        server.t['Properties']['networks'] = old_networks
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = None

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(5678).MultipleTimes().AndReturn(return_server)

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

    def test_server_update_networks_with_empty_list(self):
        return_server = self.fc.servers.list()[1]
        return_server.id = 5678
        server = self._create_test_server(return_server, 'networks_update')

        old_networks = [
            {'port': '95e25541-d26a-478d-8f36-ae1c8f6b74dc'},
            {'port': '4121f61a-1b2e-4ab0-901e-eade9b1cb09d'},
            {'network': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'fixed_ip': '31.32.33.34'}]

        server.t['Properties']['networks'] = old_networks
        update_template = copy.deepcopy(server.t)
        update_template['Properties']['networks'] = []

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(5678).MultipleTimes().AndReturn(return_server)

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

    def test_server_dont_validate_personality_if_personality_isnt_set(self):
        stack_name = 'srv_val'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        server = servers.Server('server_create_image_err',
                                tmpl['Resources']['WebServer'], stack)

        # We mock out nova_utils.absolute_limits but we don't specify
        # how this mock should behave, so mox will verify that this mock
        # is NOT called during call to server.validate().
        # This is the way to validate that no excessive calls to Nova
        # are made during validation.
        self.m.StubOutWithMock(nova_utils, 'absolute_limits')
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        # Assert here checks that server resource validates, but actually
        # this call is Act stage of this test. We calling server.validate()
        # to verify that no excessive calls to Nova are made during validation.
        self.assertIsNone(server.validate())
        self.m.VerifyAll()


class FlavorConstraintTest(HeatTestCase):

    def test_validate(self):
        client = fakes.FakeClient()
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(client)
        client.flavors = self.m.CreateMockAnything()

        flavor = collections.namedtuple("Flavor", ["id", "name"])
        flavor.id = "1234"
        flavor.name = "foo"
        client.flavors.list().MultipleTimes().AndReturn([flavor])
        self.m.ReplayAll()

        constraint = servers.FlavorConstraint()
        self.assertFalse(constraint.validate("bar", None))
        self.assertTrue(constraint.validate("foo", None))
        self.assertTrue(constraint.validate("1234", None))

        self.m.VerifyAll()
