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

import mox

from heat.engine import environment
from heat.tests.v1_1 import fakes
from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.engine.resources import server as servers
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
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
                             stack_id=uuidutils.generate_uuid())
        return (t, stack)

    def _setup_test_server(self, return_server, name, image_id=None):
        stack_name = '%s_stack' % name
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['image'] = \
            image_id or 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['flavor'] = \
            '256 MB Server'
        server = servers.Server('%s_name' % name,
                                t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)

        server.t = server.stack.resolve_runtime_data(server.t)

        # need to resolve the template functions
        #server_userdata = nova_utils.build_userdata(
        #    server,
        #    server.t['Properties']['user_data'])
        #server.mime_string = server_userdata
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=1, key_name='test',
            name=utils.PhysName(stack_name, server.name),
            security_groups=None,
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None).AndReturn(
                return_server)

        return server

    def _create_test_server(self, return_server, name):
        server = self._setup_test_server(return_server, name)
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
        self.assertEqual(
            server.FnGetAtt('addresses')['public'][0]['addr'], public_ip)
        self.assertEqual(
            server.FnGetAtt('networks')['public'][0], public_ip)
        self.assertEqual(
            server.FnGetAtt('first_public_address'), public_ip)

        private_ip = return_server.networks['private'][0]
        self.assertEqual(
            server.FnGetAtt('addresses')['private'][0]['addr'], private_ip)
        self.assertEqual(
            server.FnGetAtt('networks')['private'][0], private_ip)
        self.assertEqual(
            server.FnGetAtt('first_private_address'), private_ip)

        self.assertEqual(return_server._info, server.FnGetAtt('show'))
        self.assertEqual('sample-server2', server.FnGetAtt('instance_name'))
        self.assertEqual('192.0.2.0', server.FnGetAtt('accessIPv4'))
        self.assertEqual('::babe:4317:0A83', server.FnGetAtt('accessIPv6'))
        self.m.VerifyAll()

    def test_server_create_with_image_id(self):
        return_server = self.fc.servers.list()[1]
        server = self._setup_test_server(return_server,
                                         'test_server_create_image_id',
                                         image_id='1')
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
        self.assertEqual(
            server.FnGetAtt('first_public_address'), public_ip)

        private_ip = return_server.networks['private'][0]
        self.assertEqual(
            server.FnGetAtt('addresses')['private'][0]['addr'], private_ip)
        self.assertEqual(
            server.FnGetAtt('networks')['private'][0], private_ip)
        self.assertEqual(
            server.FnGetAtt('first_private_address'), private_ip)

        self.m.VerifyAll()

    def test_server_create_image_name_err(self):
        stack_name = 'test_server_create_image_name_err_stack'
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
        stack_name = 'test_server_create_image_name_err_stack'
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

        self.assertRaises(exception.NoUniqueImageFound, server.handle_create)

        self.m.VerifyAll()

    def test_server_create_image_id_err(self):
        stack_name = 'test_server_create_image_id_err_stack'
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
                                          'test_server_create')
        return_server.get = lambda: None
        return_server.status = 'BOGUS'
        self.assertRaises(exception.Error,
                          server.check_create_complete,
                          return_server)

    def test_server_create_error_status(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_create')
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

    def test_server_validate(self):
        stack_name = 'test_server_validate_stack'
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

        self.assertEqual(server.validate(), None)

        self.m.VerifyAll()

    def test_server_validate_delete_policy(self):
        stack_name = 'test_server_validate_stack'
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

    def test_server_delete(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_create_delete')
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
        self.assertTrue(server.resource_id is None)
        self.assertEqual(server.state, (server.DELETE, server.COMPLETE))
        self.m.VerifyAll()

    def test_server_delete_notfound(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_create_delete')
        server.resource_id = 1234

        # this makes sure the auto increment worked on server creation
        self.assertTrue(server.id > 0)

        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndRaise(servers.clients.novaclient.exceptions.NotFound(404))
        mox.Replay(get)

        scheduler.TaskRunner(server.delete)()
        self.assertTrue(server.resource_id is None)
        self.assertEqual(server.state, (server.DELETE, server.COMPLETE))
        self.m.VerifyAll()

        server.state_set(server.CREATE, server.COMPLETE, 'to delete again')
        scheduler.TaskRunner(server.delete)()
        self.assertEqual(server.state, (server.DELETE, server.COMPLETE))
        self.m.VerifyAll()

    def test_server_update_metadata(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_update')

        update_template = copy.deepcopy(server.t)
        update_template['Metadata'] = {'test': 123}
        scheduler.TaskRunner(server.update, update_template)()
        self.assertEqual(server.metadata, {'test': 123})

        server.t['Metadata'] = {'test': 456}
        server.metadata_update()
        self.assertEqual(server.metadata, {'test': 456})

    def test_server_update_server_flavor(self):
        """
        Server.handle_update supports changing the flavor, and makes
        the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = 1234
        server = self._create_test_server(return_server,
                                          'test_server_update')

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
        self.assertEqual(server.state, (server.UPDATE, server.COMPLETE))
        self.m.VerifyAll()

    def test_server_update_server_flavor_failed(self):
        """
        If the status after a resize is not VERIFY_RESIZE, it means the resize
        call failed, so we raise an explicit error.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = 1234
        server = self._create_test_server(return_server,
                                          'test_server_update')

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
        self.assertEqual(server.state, (server.UPDATE, server.FAILED))
        self.m.VerifyAll()

    def test_server_update_server_flavor_replace(self):
        stack_name = 'test_server_update_flavor_replace'
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
        stack_name = 'test_server_update_flavor_replace'
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

    def test_server_update_replace(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_update')

        update_template = copy.deepcopy(server.t)
        update_template['Notallowed'] = {'test': 123}
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_server_update_properties(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_update')

        update_template = copy.deepcopy(server.t)
        update_template['Properties']['key_name'] = 'mustreplace'
        updater = scheduler.TaskRunner(server.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_server_status_build(self):
        return_server = self.fc.servers.list()[0]
        server = self._setup_test_server(return_server,
                                         'test_server_status_build')
        server.resource_id = 1234

        # Bind fake get method which Server.check_create_complete will call
        def activate_status(server):
            server.status = 'ACTIVE'
        return_server.get = activate_status.__get__(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual(server.state, (server.CREATE, server.COMPLETE))

    def test_server_status_suspend_no_resource_id(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_suspend')

        server.resource_id = None
        self.m.ReplayAll()

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.suspend))
        self.assertEqual('Error: Cannot suspend test_server_suspend_name, '
                         'resource_id not set',
                         str(ex))
        self.assertEqual(server.state, (server.SUSPEND, server.FAILED))

        self.m.VerifyAll()

    def test_server_status_suspend_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_suspend')

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
        self.assertEqual(server.state, (server.SUSPEND, server.FAILED))

        self.m.VerifyAll()

    def test_server_status_suspend_immediate(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_suspend')

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
        self.assertEqual(server.state, (server.SUSPEND, server.COMPLETE))

        self.m.VerifyAll()

    def test_server_status_resume_immediate(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_resume')

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
        self.assertEqual(server.state, (server.RESUME, server.COMPLETE))

        self.m.VerifyAll()

    def test_server_status_suspend_wait(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_suspend')

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
        self.assertEqual(server.state, (server.SUSPEND, server.COMPLETE))

        self.m.VerifyAll()

    def test_server_status_suspend_unknown_status(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_suspend')

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
        self.assertEqual(server.state, (server.SUSPEND, server.FAILED))

        self.m.VerifyAll()

    def test_server_status_resume_wait(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_resume')

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
        self.assertEqual(server.state, (server.RESUME, server.COMPLETE))

        self.m.VerifyAll()

    def test_server_status_resume_no_resource_id(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_suspend')

        server.resource_id = None
        self.m.ReplayAll()

        server.state_set(server.SUSPEND, server.COMPLETE)
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(server.resume))
        self.assertEqual('Error: Cannot resume test_server_suspend_name, '
                         'resource_id not set',
                         str(ex))
        self.assertEqual(server.state, (server.RESUME, server.FAILED))

        self.m.VerifyAll()

    def test_server_status_resume_not_found(self):
        return_server = self.fc.servers.list()[1]
        server = self._create_test_server(return_server,
                                          'test_server_resume')

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
        self.assertEqual(server.state, (server.RESUME, server.FAILED))

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
                                         'test_server_status_build')
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
        self.assertEqual(server.state, (server.CREATE, server.COMPLETE))

        self.m.VerifyAll()

    def test_build_nics(self):
        self.assertEqual(None, servers.Server._build_nics([]))
        self.assertEqual(None, servers.Server._build_nics(None))
        self.assertEqual([
            {'net-id': '1234abcd'},
            {'v4-fixed-ip': '192.0.2.0'},
            {'port-id': 'aaaabbbb'}
        ], servers.Server._build_nics([
            {'uuid': '1234abcd'},
            {'fixed_ip': '192.0.2.0'},
            {'port': 'aaaabbbb'}
        ]))

    def test_server_without_ip_address(self):
        return_server = self.fc.servers.list()[3]
        server = self._create_test_server(return_server,
                                          'test_without_ip_address')

        self.assertEqual(server.FnGetAtt('addresses'), {'empty_net': []})
        self.assertEqual(server.FnGetAtt('networks'), {'empty_net': []})
        self.assertEqual(server.FnGetAtt('first_private_address'), '')
        self.assertEqual(server.FnGetAtt('first_public_address'), '')

    def test_build_block_device_mapping(self):
        self.assertEqual(
            None, servers.Server._build_block_device_mapping([]))
        self.assertEqual(
            None, servers.Server._build_block_device_mapping(None))

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
                'volume_size': '10'
            },
            {
                'device_name': 'vdd',
                'snapshot_id': '1234',
                'delete_on_termination': True
            }
        ]))
