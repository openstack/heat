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

import unittest
import mox

from nose.plugins.attrib import attr

from heat.tests.v1_1 import fakes
from heat.engine.resources import instance as instances
from heat.common import template_format
from heat.engine import parser
from heat.openstack.common import uuidutils


@attr(tag=['unit', 'resource', 'instance'])
@attr(speed='fast')
class instancesTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')

    def tearDown(self):
        self.m.UnsetStubs()
        print "instancesTest teardown complete"

    def test_instance_create(self):
        f = open("%s/WordPress_Single_Instance_gold.template" % self.path)
        t = template_format.parse(f.read())
        f.close()

        stack_name = 'instance_create_test_stack'
        template = parser.Template(t)
        params = parser.Parameters(stack_name, template, {'KeyName': 'test'})
        stack = parser.Stack(None, stack_name, template, params,
                             stack_id=uuidutils.generate_uuid())

        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['InstanceType'] = \
            '256 MB Server'
        instance = instances.Instance('create_instance_name',
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
            meta=None, nics=None).AndReturn(self.fc.servers.list()[1])
        self.m.ReplayAll()

        self.assertEqual(instance.create(), None)

        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)
        self.m.VerifyAll()

    def test_instance_create_delete(self):
        f = open("%s/WordPress_Single_Instance_gold.template" % self.path)
        t = template_format.parse(f.read())
        f.close()

        stack_name = 'instance_create_delete_test_stack'
        template = parser.Template(t)
        params = parser.Parameters(stack_name, template, {'KeyName': 'test'})
        stack = parser.Stack(None, stack_name, template, params,
                             stack_id=uuidutils.generate_uuid())

        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['InstanceType'] = \
            '256 MB Server'
        instance = instances.Instance('create_delete_instance_name',
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
            meta=None, nics=None).AndReturn(self.fc.servers.list()[1])
        self.m.ReplayAll()

        self.assertEqual(instance.create(), None)
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

        AZ = instance.FnGetAtt('AvailabilityZone')
        self.assertEqual(AZ, 'nova')
        private_ip = instance.FnGetAtt('PublicIp')
        self.assertEqual(private_ip, '4.5.6.7')
        private_ip = instance.FnGetAtt('PrivateIp')
        self.assertEqual(private_ip, '4.5.6.7')
        private_ip = instance.FnGetAtt('PrivateDnsName')
        self.assertEqual(private_ip, '4.5.6.7')
        private_ip = instance.FnGetAtt('PrivateDnsName')
        self.assertEqual(private_ip, '4.5.6.7')

    def test_instance_update_metadata(self):
        f = open("%s/WordPress_Single_Instance_gold.template" % self.path)
        t = template_format.parse(f.read())
        f.close()

        stack_name = 'instance_update_test_stack'
        template = parser.Template(t)
        params = parser.Parameters(stack_name, template, {'KeyName': 'test'})
        stack = parser.Stack(None, stack_name, template, params,
                             stack_id=uuidutils.generate_uuid())

        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['InstanceType'] = \
            '256 MB Server'
        instance = instances.Instance('create_instance_name',
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
            meta=None, nics=None).AndReturn(self.fc.servers.list()[1])
        self.m.ReplayAll()

        self.assertEqual(instance.create(), None)

        update_template = copy.deepcopy(instance.t)
        update_template['Metadata'] = {'test': 123}
        self.assertEqual(instance.update(update_template),
                         instance.UPDATE_COMPLETE)
        self.assertEqual(instance.metadata, {'test': 123})
