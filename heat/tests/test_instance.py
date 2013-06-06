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

from heat.tests.v1_1 import fakes
from heat.engine.resources import instance as instances
from heat.common import template_format
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.utils import setup_dummy_db


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


class instancesTest(HeatTestCase):
    def setUp(self):
        super(instancesTest, self).setUp()
        self.fc = fakes.FakeClient()
        setup_dummy_db()

    def _setup_test_instance(self, return_server, name):
        stack_name = '%s_stack' % name
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        params = parser.Parameters(stack_name, template, {'KeyName': 'test'})
        stack = parser.Stack(None, stack_name, template, params,
                             stack_id=uuidutils.generate_uuid())

        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['InstanceType'] = \
            '256 MB Server'
        instance = instances.Instance('%s_name' % name,
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(instance, 'nova')
        instance.nova().MultipleTimes().AndReturn(self.fc)

        instance.t = instance.stack.resolve_runtime_data(instance.t)

        # need to resolve the template functions
        server_userdata = instance._build_userdata(
            instance.t['Properties']['UserData'])
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=1, key_name='test',
            name=utils.PhysName(stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None,
            meta=None, nics=None, availability_zone=None).AndReturn(
                return_server)

        return instance

    def _create_test_instance(self, return_server, name):
        instance = self._setup_test_instance(return_server, name)
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        return instance

    def test_instance_create(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_instance_create')
        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        expected_ip = return_server.networks['public'][0]
        self.assertEqual(instance.FnGetAtt('PublicIp'), expected_ip)
        self.assertEqual(instance.FnGetAtt('PrivateIp'), expected_ip)
        self.assertEqual(instance.FnGetAtt('PrivateDnsName'), expected_ip)
        self.assertEqual(instance.FnGetAtt('PrivateDnsName'), expected_ip)

        self.m.VerifyAll()

    def test_instance_create_delete(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_instance_create_delete')
        instance.resource_id = 1234

        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndRaise(instances.clients.novaclient.exceptions.NotFound(404))
        mox.Replay(get)

        instance.delete()
        self.assertTrue(instance.resource_id is None)
        self.assertEqual(instance.state, instance.DELETE_COMPLETE)
        self.m.VerifyAll()

    def test_instance_update_metadata(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_instance_update')

        update_template = copy.deepcopy(instance.t)
        update_template['Metadata'] = {'test': 123}
        self.assertEqual(None, instance.update(update_template))
        self.assertEqual(instance.metadata, {'test': 123})

    def test_instance_update_replace(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_instance_update')

        update_template = copy.deepcopy(instance.t)
        update_template['Notallowed'] = {'test': 123}
        self.assertRaises(resource.UpdateReplace,
                          instance.update, update_template)

    def test_instance_update_properties(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_instance_update')

        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['KeyName'] = 'mustreplace'
        self.assertRaises(resource.UpdateReplace,
                          instance.update, update_template)

    def test_instance_status_build(self):
        return_server = self.fc.servers.list()[0]
        instance = self._setup_test_instance(return_server,
                                             'test_instance_status_build')
        instance.resource_id = 1234

        # Bind fake get method which Instance.check_create_complete will call
        def activate_status(server):
            server.status = 'ACTIVE'
        return_server.get = activate_status.__get__(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual(instance.state, instance.CREATE_COMPLETE)

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
                                             'test_instance_status_build')
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
        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual(instance.state, instance.CREATE_COMPLETE)

        self.m.VerifyAll()

    def test_build_nics(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_build_nics')

        self.assertEqual(None, instance._build_nics([]))
        self.assertEqual(None, instance._build_nics(None))
        self.assertEqual([
            {'port-id': 'id3'}, {'port-id': 'id1'}, {'port-id': 'id2'}],
            instance._build_nics([
                'id3', 'id1', 'id2']))
        self.assertEqual([
            {'port-id': 'id1'},
            {'port-id': 'id2'},
            {'port-id': 'id3'}], instance._build_nics([
                {'NetworkInterfaceId': 'id3', 'DeviceIndex': '3'},
                {'NetworkInterfaceId': 'id1', 'DeviceIndex': '1'},
                {'NetworkInterfaceId': 'id2', 'DeviceIndex': 2},
            ]))
        self.assertEqual([
            {'port-id': 'id1'},
            {'port-id': 'id2'},
            {'port-id': 'id3'},
            {'port-id': 'id4'},
            {'port-id': 'id5'}
        ], instance._build_nics([
            {'NetworkInterfaceId': 'id3', 'DeviceIndex': '3'},
            {'NetworkInterfaceId': 'id1', 'DeviceIndex': '1'},
            {'NetworkInterfaceId': 'id2', 'DeviceIndex': 2},
            'id4',
            'id5'
        ]))

    def test_instance_without_ip_address(self):
        return_server = self.fc.servers.list()[3]
        instance = self._create_test_instance(return_server,
                                              'test_without_ip_address')

        self.assertEqual(instance.FnGetAtt('PrivateIp'), '0.0.0.0')
