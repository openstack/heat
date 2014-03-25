
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
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources import image
from heat.engine.resources import instance as instances
from heat.engine.resources import network_interface
from heat.engine.resources import nova_utils
from heat.engine import scheduler
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes


wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''


class InstancesTest(HeatTestCase):
    def setUp(self):
        super(InstancesTest, self).setUp()
        self.fc = fakes.FakeClient()
        utils.setup_dummy_db()

    def _setup_test_stack(self, stack_name):
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             environment.Environment({'KeyName': 'test'}),
                             stack_id=str(uuid.uuid4()))
        return (t, stack)

    def _setup_test_instance(self, return_server, name, image_id=None,
                             stub_create=True):
        stack_name = '%s_s' % name
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['ImageId'] = \
            image_id or 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['InstanceType'] = \
            '256 MB Server'
        instance = instances.Instance(name, t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(instance, 'nova')
        instance.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        instance.t = instance.stack.resolve_runtime_data(instance.t)

        if stub_create:
            self.m.StubOutWithMock(self.fc.servers, 'create')
            self.fc.servers.create(
                image=1, flavor=1, key_name='test',
                name=utils.PhysName(
                    stack_name,
                    instance.name,
                    limit=instance.physical_resource_name_limit),
                security_groups=None,
                userdata=mox.IgnoreArg(), scheduler_hints=None,
                meta=None, nics=None, availability_zone=None).AndReturn(
                    return_server)

        return instance

    def _create_test_instance(self, return_server, name, stub_create=True):
        instance = self._setup_test_instance(return_server, name,
                                             stub_create=stub_create)
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        return instance

    def test_instance_create(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_create')
        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        expected_ip = return_server.networks['public'][0]
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))

        self.m.VerifyAll()

    def test_instance_create_with_image_id(self):
        return_server = self.fc.servers.list()[1]
        instance = self._setup_test_instance(return_server,
                                             'in_create_imgid',
                                             image_id='1')
        self.m.StubOutWithMock(uuidutils, "is_uuid_like")
        uuidutils.is_uuid_like('1').MultipleTimes().AndReturn(True)

        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()

        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        expected_ip = return_server.networks['public'][0]
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicDnsName'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))

        self.m.VerifyAll()

    def test_instance_create_image_name_err(self):
        stack_name = 'test_instance_create_image_name_err_stack'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an instance with non exist image name
        t['Resources']['WebServer']['Properties']['ImageId'] = 'Slackware'
        instance = instances.Instance('instance_create_image_err',
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        self.assertRaises(ValueError, instance.handle_create)

        self.m.VerifyAll()

    def test_instance_create_duplicate_image_name_err(self):
        stack_name = 'test_instance_create_image_name_err_stack'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an instance with a non unique image name
        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'
        instance = instances.Instance('instance_create_image_err',
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc.client, "get_images_detail")
        self.fc.client.get_images_detail().AndReturn((
            200, {'images': [{'id': 1, 'name': 'CentOS 5.2'},
                             {'id': 4, 'name': 'CentOS 5.2'}]}))
        self.m.ReplayAll()

        self.assertRaises(ValueError, instance.handle_create)

        self.m.VerifyAll()

    def test_instance_create_image_id_err(self):
        stack_name = 'test_instance_create_image_id_err_stack'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an instance with non exist image Id
        t['Resources']['WebServer']['Properties']['ImageId'] = '1'
        instance = instances.Instance('instance_create_image_err',
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(uuidutils, "is_uuid_like")
        uuidutils.is_uuid_like('1').AndReturn(True)
        self.m.StubOutWithMock(self.fc.client, "get_images_1")
        self.fc.client.get_images_1().AndRaise(
            instances.clients.novaclient.exceptions.NotFound(404))
        self.m.ReplayAll()

        self.assertRaises(ValueError, instance.handle_create)

        self.m.VerifyAll()

    class FakeVolumeAttach:
        def started(self):
            return False

    def test_instance_create_unexpected_status(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_instance_create')
        return_server.get = lambda: None
        return_server.status = 'BOGUS'
        self.assertRaises(exception.Error,
                          instance.check_create_complete,
                          (return_server, self.FakeVolumeAttach()))

    def test_instance_create_error_status(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_instance_create')
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
                          instance.check_create_complete,
                          (return_server, self.FakeVolumeAttach()))

        self.m.VerifyAll()

    def test_instance_create_error_no_fault(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_create')
        return_server.status = 'ERROR'

        self.m.StubOutWithMock(return_server, 'get')
        return_server.get()
        self.m.ReplayAll()

        e = self.assertRaises(
            exception.Error, instance.check_create_complete,
            (return_server, self.FakeVolumeAttach()))
        self.assertEqual(
            'Creation of server sample-server2 failed: Unknown (500)',
            str(e))

        self.m.VerifyAll()

    def test_instance_validate(self):
        stack_name = 'test_instance_validate_stack'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an instance with non exist image Id
        t['Resources']['WebServer']['Properties']['ImageId'] = '1'
        instance = instances.Instance('instance_create_image_err',
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        self.m.StubOutWithMock(uuidutils, "is_uuid_like")
        uuidutils.is_uuid_like('1').MultipleTimes().AndReturn(True)
        self.m.ReplayAll()

        self.assertIsNone(instance.validate())

        self.m.VerifyAll()

    def test_instance_create_delete(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_cr_del')
        instance.resource_id = 1234

        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndRaise(instances.clients.novaclient.exceptions.NotFound(404))
        mox.Replay(get)

        scheduler.TaskRunner(instance.delete)()
        self.assertIsNone(instance.resource_id)
        self.assertEqual((instance.DELETE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_instance_update_metadata(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'ud_md')

        update_template = copy.deepcopy(instance.t)
        update_template['Metadata'] = {'test': 123}
        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual({'test': 123}, instance.metadata)

    def test_instance_update_instance_type(self):
        """
        Instance.handle_update supports changing the InstanceType, and makes
        the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = 1234
        instance = self._create_test_instance(return_server,
                                              'ud_type')

        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['InstanceType'] = 'm1.small'

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

        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_instance_update_instance_type_failed(self):
        """
        If the status after a resize is not VERIFY_RESIZE, it means the resize
        call failed, so we raise an explicit error.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = 1234
        instance = self._create_test_instance(return_server,
                                              'ud_type_f')

        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['InstanceType'] = 'm1.small'

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(1234).AndReturn(return_server)

        def activate_status(server):
            server.status = 'ACTIVE'
        return_server.get = activate_status.__get__(return_server)

        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')
        self.fc.client.post_servers_1234_action(
            body={'resize': {'flavorRef': 2}}).AndReturn((202, None))
        self.m.ReplayAll()

        updater = scheduler.TaskRunner(instance.update, update_template)
        error = self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual(
            "Error: Resizing to 'm1.small' failed, status 'ACTIVE'",
            str(error))
        self.assertEqual((instance.UPDATE, instance.FAILED), instance.state)
        self.m.VerifyAll()

    def test_instance_update_replace(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_update1')

        update_template = copy.deepcopy(instance.t)
        update_template['Notallowed'] = {'test': 123}
        updater = scheduler.TaskRunner(instance.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_instance_update_properties(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_update2')

        self.m.StubOutWithMock(image.ImageConstraint, "validate")
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.ReplayAll()

        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['ImageId'] = 'mustreplace'
        updater = scheduler.TaskRunner(instance.update, update_template)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_instance_status_build(self):
        return_server = self.fc.servers.list()[0]
        instance = self._setup_test_instance(return_server,
                                             'in_sts_build')
        instance.resource_id = 1234

        # Bind fake get method which Instance.check_create_complete will call
        def activate_status(server):
            server.status = 'ACTIVE'
        return_server.get = activate_status.__get__(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)

    def test_instance_status_suspend_immediate(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_suspend')

        instance.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to SUSPENDED
        d = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d['server']['status'] = 'SUSPENDED'
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d))
        mox.Replay(get)

        scheduler.TaskRunner(instance.suspend)()
        self.assertEqual((instance.SUSPEND, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_instance_status_resume_immediate(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_resume')

        instance.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to SUSPENDED
        d = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d['server']['status'] = 'ACTIVE'
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d))
        mox.Replay(get)
        instance.state_set(instance.SUSPEND, instance.COMPLETE)

        scheduler.TaskRunner(instance.resume)()
        self.assertEqual((instance.RESUME, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_instance_status_suspend_wait(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_suspend_wait')

        instance.resource_id = 1234
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

        scheduler.TaskRunner(instance.suspend)()
        self.assertEqual((instance.SUSPEND, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_instance_status_resume_wait(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_resume_wait')

        instance.resource_id = 1234
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

        instance.state_set(instance.SUSPEND, instance.COMPLETE)

        scheduler.TaskRunner(instance.resume)()
        self.assertEqual((instance.RESUME, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_instance_suspend_volumes_step(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_suspend_vol')

        instance.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to SUSPENDED
        d = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d['server']['status'] = 'SUSPENDED'

        # Return a dummy PollingTaskGroup to make check_suspend_complete step
        def dummy_detach():
            yield
        dummy_tg = scheduler.PollingTaskGroup([dummy_detach, dummy_detach])
        self.m.StubOutWithMock(instance, '_detach_volumes_task')
        instance._detach_volumes_task().AndReturn(dummy_tg)

        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d))
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.suspend)()
        self.assertEqual((instance.SUSPEND, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_instance_resume_volumes_step(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_resume_vol')

        instance.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to ACTIVE
        d = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d['server']['status'] = 'ACTIVE'

        # Return a dummy PollingTaskGroup to make check_resume_complete step
        def dummy_attach():
            yield
        dummy_tg = scheduler.PollingTaskGroup([dummy_attach, dummy_attach])
        self.m.StubOutWithMock(instance, '_attach_volumes_task')
        instance._attach_volumes_task().AndReturn(dummy_tg)

        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d))

        self.m.ReplayAll()

        instance.state_set(instance.SUSPEND, instance.COMPLETE)

        scheduler.TaskRunner(instance.resume)()
        self.assertEqual((instance.RESUME, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_instance_suspend_volumes_wait(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_suspend_vol')

        instance.resource_id = 1234
        self.m.ReplayAll()

        # Override the get_servers_1234 handler status to SUSPENDED, but keep
        # it ACTIVE for the first two iterations of check_suspend_complete.
        d1 = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d2 = copy.deepcopy(d1)
        d1['server']['status'] = 'ACTIVE'
        d2['server']['status'] = 'SUSPENDED'

        # Return a dummy PollingTaskGroup to make check_suspend_complete step
        def dummy_detach():
            yield
        dummy_tg = scheduler.PollingTaskGroup([dummy_detach, dummy_detach])
        self.m.StubOutWithMock(instance, '_detach_volumes_task')
        instance._detach_volumes_task().AndReturn(dummy_tg)

        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d1))
        get().AndReturn((200, d1))
        get().AndReturn((200, d2))
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.suspend)()
        self.assertEqual((instance.SUSPEND, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_instance_status_build_spawning(self):
        self._test_instance_status_not_build_active('BUILD(SPAWNING)')

    def test_instance_status_hard_reboot(self):
        self._test_instance_status_not_build_active('HARD_REBOOT')

    def test_instance_status_password(self):
        self._test_instance_status_not_build_active('PASSWORD')

    def test_instance_status_reboot(self):
        self._test_instance_status_not_build_active('REBOOT')

    def test_instance_status_rescue(self):
        self._test_instance_status_not_build_active('RESCUE')

    def test_instance_status_resize(self):
        self._test_instance_status_not_build_active('RESIZE')

    def test_instance_status_revert_resize(self):
        self._test_instance_status_not_build_active('REVERT_RESIZE')

    def test_instance_status_shutoff(self):
        self._test_instance_status_not_build_active('SHUTOFF')

    def test_instance_status_suspended(self):
        self._test_instance_status_not_build_active('SUSPENDED')

    def test_instance_status_verify_resize(self):
        self._test_instance_status_not_build_active('VERIFY_RESIZE')

    def _test_instance_status_not_build_active(self, uncommon_status):
        return_server = self.fc.servers.list()[0]
        instance = self._setup_test_instance(return_server,
                                             'in_sts_bld')
        instance.resource_id = 1234

        # Bind fake get method which Instance.check_create_complete will call
        def activate_status(server):
            if hasattr(server, '_test_check_iterations'):
                server._test_check_iterations += 1
            else:
                server._test_check_iterations = 1
            if server._test_check_iterations == 1:
                server.status = uncommon_status
            if server._test_check_iterations > 2:
                server.status = 'ACTIVE'
        return_server.get = activate_status.__get__(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_build_nics(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'build_nics')

        self.assertIsNone(instance._build_nics([]))
        self.assertIsNone(instance._build_nics(None))
        self.assertEqual([
            {'port-id': 'id3'}, {'port-id': 'id1'}, {'port-id': 'id2'}],
            instance._build_nics([
                'id3', 'id1', 'id2']))
        self.assertEqual(
            [{'port-id': 'id1'},
             {'port-id': 'id2'},
             {'port-id': 'id3'}],
            instance._build_nics([
                {'NetworkInterfaceId': 'id3', 'DeviceIndex': '3'},
                {'NetworkInterfaceId': 'id1', 'DeviceIndex': '1'},
                {'NetworkInterfaceId': 'id2', 'DeviceIndex': 2},
            ]))
        self.assertEqual(
            [{'port-id': 'id1'},
             {'port-id': 'id2'},
             {'port-id': 'id3'},
             {'port-id': 'id4'},
             {'port-id': 'id5'}],
            instance._build_nics([
                {'NetworkInterfaceId': 'id3', 'DeviceIndex': '3'},
                {'NetworkInterfaceId': 'id1', 'DeviceIndex': '1'},
                {'NetworkInterfaceId': 'id2', 'DeviceIndex': 2},
                'id4',
                'id5']
            ))

    def test_build_nics_with_security_groups(self):
        """
        Test the security groups defined in heat template can be associated
        to a new created port.
        """
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'build_nics2')

        security_groups = ['security_group_1']
        self._test_security_groups(instance, security_groups)

        security_groups = ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        self._test_security_groups(instance, security_groups, all_uuids=True)

        security_groups = ['0389f747-7785-4757-b7bb-2ab07e4b09c3',
                           '384ccd91-447c-4d83-832c-06974a7d3d05']
        self._test_security_groups(instance, security_groups,
                                   sg='two', all_uuids=True)

        security_groups = ['security_group_1',
                           '384ccd91-447c-4d83-832c-06974a7d3d05']
        self._test_security_groups(instance, security_groups, sg='two')

        security_groups = ['wrong_group_name']
        self._test_security_groups(
            instance,
            security_groups,
            sg='zero',
            get_secgroup_raises=exception.PhysicalResourceNotFound)

        security_groups = ['wrong_group_name',
                           '0389f747-7785-4757-b7bb-2ab07e4b09c3']
        self._test_security_groups(
            instance,
            security_groups,
            get_secgroup_raises=exception.PhysicalResourceNotFound)

        security_groups = ['wrong_group_name', 'security_group_1']
        self._test_security_groups(
            instance,
            security_groups,
            get_secgroup_raises=exception.PhysicalResourceNotFound)

        security_groups = ['duplicate_group_name', 'security_group_1']
        self._test_security_groups(
            instance,
            security_groups,
            get_secgroup_raises=exception.PhysicalResourceNameAmbiguity)

    def _test_security_groups(self, instance, security_groups, sg='one',
                              all_uuids=False, get_secgroup_raises=None):
        fake_groups_list, props = self._get_fake_properties(sg)

        nclient = neutronclient.Client()
        self.m.StubOutWithMock(instance, 'neutron')
        instance.neutron().MultipleTimes().AndReturn(nclient)

        if not all_uuids:
            # list_security_groups only gets called when none of the requested
            # groups look like UUIDs.
            self.m.StubOutWithMock(
                neutronclient.Client, 'list_security_groups')
            neutronclient.Client.list_security_groups().AndReturn(
                fake_groups_list)

        net_interface = network_interface.NetworkInterface
        self.m.StubOutWithMock(net_interface, 'network_id_from_subnet_id')
        net_interface.network_id_from_subnet_id(
            nclient,
            'fake_subnet_id').MultipleTimes().AndReturn('fake_network_id')

        if not get_secgroup_raises:
            self.m.StubOutWithMock(neutronclient.Client, 'create_port')
            neutronclient.Client.create_port(
                {'port': props}).MultipleTimes().AndReturn(
                    {'port': {'id': 'fake_port_id'}})

        self.m.ReplayAll()

        if get_secgroup_raises:
            self.assertRaises(get_secgroup_raises, instance._build_nics, None,
                              security_groups=security_groups,
                              subnet_id='fake_subnet_id')
        else:
            self.assertEqual(
                [{'port-id': 'fake_port_id'}],
                instance._build_nics(None,
                                     security_groups=security_groups,
                                     subnet_id='fake_subnet_id'))

        self.m.VerifyAll()
        self.m.UnsetStubs()

    def _get_fake_properties(self, sg='one'):
        fake_groups_list = {
            'security_groups': [
                {
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'id': '384ccd91-447c-4d83-832c-06974a7d3d05',
                    'name': 'security_group_2',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'id': 'e91a0007-06a6-4a4a-8edb-1d91315eb0ef',
                    'name': 'duplicate_group_name',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'id': '8be37f3c-176d-4826-aa17-77d1d9df7b2e',
                    'name': 'duplicate_group_name',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }

        fixed_ip = {'subnet_id': 'fake_subnet_id'}
        props = {
            'admin_state_up': True,
            'network_id': 'fake_network_id',
            'fixed_ips': [fixed_ip],
            'security_groups': ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        }

        if sg == 'zero':
            props['security_groups'] = []
        elif sg == 'one':
            props['security_groups'] = ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        elif sg == 'two':
            props['security_groups'] = ['0389f747-7785-4757-b7bb-2ab07e4b09c3',
                                        '384ccd91-447c-4d83-832c-06974a7d3d05']

        return fake_groups_list, props

    def test_instance_without_ip_address(self):
        return_server = self.fc.servers.list()[3]
        instance = self._create_test_instance(return_server,
                                              'wo_ipaddr')

        self.assertEqual('0.0.0.0', instance.FnGetAtt('PrivateIp'))

    def test_default_instance_user(self):
        """The default value for instance_user in heat.conf is ec2-user."""
        return_server = self.fc.servers.list()[1]
        instance = self._setup_test_instance(return_server, 'default_user')
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(instance, 'wordpress', 'ec2-user')
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        self.m.VerifyAll()

    def test_custom_instance_user(self):
        """Test instance_user in heat.conf being set to a custom value.

        Launching the instance should call build_userdata with the custom user
        name.

        This option is deprecated and will be removed in Juno.
        """
        return_server = self.fc.servers.list()[1]
        instance = self._setup_test_instance(return_server, 'custom_user')
        self.m.StubOutWithMock(instances.cfg.CONF, 'instance_user')
        instances.cfg.CONF.instance_user = 'custom_user'
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(instance, 'wordpress', 'custom_user')
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        self.m.VerifyAll()

    def test_empty_instance_user(self):
        """Test instance_user in heat.conf being empty.

        Launching the instance should call build_userdata with
        "ec2-user".

        This behaviour is compatible with CloudFormation and will be
        the default in Juno once the instance_user option gets removed.
        """
        return_server = self.fc.servers.list()[1]
        instance = self._setup_test_instance(return_server, 'empty_user')
        self.m.StubOutWithMock(instances.cfg.CONF, 'instance_user')
        instances.cfg.CONF.instance_user = ''
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(instance, 'wordpress', 'ec2-user')
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        self.m.VerifyAll()
