# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import copy
import uuid
import mox

from heat.engine import environment
from heat.tests.v1_1 import fakes
from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.engine.resources import nova_utils
from heat.engine.resources import server as servers
from heat.openstack.common import uuidutils
from heat.openstack.common.gettextutils import _
from heat.tests.common import HeatTestCase
from heat.tests import utils
from novaclient import exceptions


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
        self.fc = fakes.FakeClient()
        utils.setup_dummy_db()

    def _setup_test_stack(self, stack_name):
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             environment.Environment({'key_name': 'test'}),
                             stack_id=str(uuid.uuid4()))
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
                disk_config=None, reservation_id=None).AndReturn(
                    return_server)

        return server

    def _create_test_server(self, return_server, name, override_name=False,
                            stub_create=True):
        server = self._setup_test_server(return_server, name,
                                         stub_create=stub_create)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        return server

    def test_server_create(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_create')
        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        public_ip = return_server.networks['public'][0]
        self.assertEqual(public_ip,
                         server.FnGetAtt('addresses')['public'][0]['addr'])
        self.assertEqual(public_ip,
                         server.FnGetAtt('networks')['public'][0])

        private_ip = return_server.networks['private'][0]
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
            disk_config=None, reservation_id=None).AndReturn(
                return_server)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_server_create_with_image_id(self):
        return_server = self.fc.servers.list()[1]
        server = self._setup_test_server(return_server,
                                         'test_server_create_image_id',
                                         image_id='1',
                                         override_name=True)
        self.m.StubOutWithMock(uuidutils, "is_uuid_like")
        uuidutils.is_uuid_like('1').AndReturn(True)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        public_ip = return_server.networks['public'][0]
        self.assertEqual(
            server.FnGetAtt('addresses')['public'][0]['addr'], public_ip)
        self.assertEqual(
            server.FnGetAtt('networks')['public'][0], public_ip)

        private_ip = return_server.networks['private'][0]
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

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        self.assertRaises(exception.ImageNotFound, server.handle_create)

        self.m.VerifyAll()

    def test_server_create_duplicate_image_name_err(self):
        stack_name = 'img_dup_err'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with a non unique image name
        t['Resources']['WebServer']['Properties']['image'] = 'CentOS 5.2'
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc.client, "get_images_detail")
        self.fc.client.get_images_detail().AndReturn((
            200, {'images': [{'id': 1, 'name': 'CentOS 5.2'},
                             {'id': 4, 'name': 'CentOS 5.2'}]}))
        self.m.ReplayAll()

        self.assertRaises(exception.PhysicalResourceNameAmbiguity,
                          server.handle_create)

        self.m.VerifyAll()

    def test_server_create_image_id_err(self):
        stack_name = 'img_id_err'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        t['Resources']['WebServer']['Properties']['image'] = '1'
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(uuidutils, "is_uuid_like")
        uuidutils.is_uuid_like('1').AndReturn(True)
        self.m.StubOutWithMock(self.fc.client, "get_images_1")
        self.fc.client.get_images_1().AndRaise(
            servers.clients.novaclient.exceptions.NotFound(404))
        self.m.ReplayAll()

        self.assertRaises(exception.ImageNotFound, server.handle_create)

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

        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=744, flavor=3, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata='wordpress', scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None).AndReturn(
                return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_server_validate(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        t['Resources']['WebServer']['Properties']['image'] = '1'
        server = servers.Server('server_create_image_err',
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)

        self.m.StubOutWithMock(uuidutils, "is_uuid_like")
        uuidutils.is_uuid_like('1').AndReturn(True)
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
            web_server['Properties']['block_device_mapping'] = [{
                "device_name": device_name,
                "volume_id": "5d7e27da-6703-4f7e-9f94-1f67abef734c",
                "delete_on_termination": False
            }]
            server = servers.Server('server_with_bootable_volume',
                                    web_server, stack)
            self.m.StubOutWithMock(server, 'nova')
            server.nova().MultipleTimes().AndReturn(self.fc)
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

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
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

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['image'] = self.getUniqueString()
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

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['key_name'] = 'mustreplace'
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
        server = self._create_test_server(return_server,
                                          'wo_ipaddr')

        self.assertEqual({'empty_net': []}, server.FnGetAtt('addresses'))
        self.assertEqual({'empty_net': []}, server.FnGetAtt('networks'))
        self.assertEqual('', server.FnGetAtt('first_address'))

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

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
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

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
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
        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
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
        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
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
        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
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

        limits = self.m.CreateMockAnything()
        max_server_meta = self.m.CreateMockAnything()
        max_server_meta.name = 'maxServerMeta'
        max_server_meta.value = 3
        limits.absolute = [max_server_meta]
        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().AndReturn(limits)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
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

        limits = self.m.CreateMockAnything()
        max_server_meta = self.m.CreateMockAnything()
        max_server_meta.name = 'maxServerMeta'
        max_server_meta.value = 3
        limits.absolute = [max_server_meta]
        self.m.StubOutWithMock(self.fc.limits, 'get')
        self.fc.limits.get().AndReturn(limits)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        self.assertIsNone(server.validate())
        self.m.VerifyAll()
