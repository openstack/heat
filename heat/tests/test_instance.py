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


import os
import copy

import mox

from heat.tests.v1_1 import fakes
from heat.engine.resources import instance as instances
from heat.common import template_format
from heat.engine import parser
from heat.engine import scheduler
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db


class instancesTest(HeatTestCase):
    def setUp(self):
        super(instancesTest, self).setUp()
        self.fc = fakes.FakeClient()
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        setup_dummy_db()

    def _create_test_instance(self, return_server, name):
        f = open("%s/WordPress_Single_Instance_gold.template" % self.path)
        t = template_format.parse(f.read())
        f.close()

        stack_name = '%s_stack' % name
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
            name='%s.%s' % (stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None,
            meta=None, nics=None, availability_zone=None).AndReturn(
                return_server)
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
        self.assertEqual(instance.update(update_template),
                         instance.UPDATE_COMPLETE)
        self.assertEqual(instance.metadata, {'test': 123})

    def test_build_nics(self):
        self.assertEqual(None, instances.Instance._build_nics([]))
        self.assertEqual(None, instances.Instance._build_nics(None))
        self.assertEqual([
            {'port-id': 'id3'}, {'port-id': 'id1'}, {'port-id': 'id2'}],
            instances.Instance._build_nics([
                'id3', 'id1', 'id2']))
        self.assertEqual([
            {'port-id': 'id1'},
            {'port-id': 'id2'},
            {'port-id': 'id3'}], instances.Instance._build_nics([
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
        ], instances.Instance._build_nics([
            {'NetworkInterfaceId': 'id3', 'DeviceIndex': '3'},
            {'NetworkInterfaceId': 'id1', 'DeviceIndex': '1'},
            {'NetworkInterfaceId': 'id2', 'DeviceIndex': 2},
            'id4',
            'id5'
        ]))
