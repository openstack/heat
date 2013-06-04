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

import eventlet
import mox
import unittest

from nose.plugins.attrib import attr

from heat.common import context
from heat.common import template_format
from heat.engine import parser
from heat.engine.resources import volume as vol
from heat.engine import clients
from heat.tests.v1_1 import fakes


@attr(tag=['unit', 'resource', 'volume'])
@attr(speed='fast')
class VolumeTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(clients.OpenStackClients, 'cinder')
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        self.m.StubOutWithMock(self.fc.volumes, 'create')
        self.m.StubOutWithMock(self.fc.volumes, 'get')
        self.m.StubOutWithMock(self.fc.volumes, 'delete')
        self.m.StubOutWithMock(self.fc.volumes, 'create_server_volume')
        self.m.StubOutWithMock(self.fc.volumes, 'delete_server_volume')
        self.m.StubOutWithMock(eventlet, 'sleep')

    def tearDown(self):
        self.m.UnsetStubs()
        print "VolumeTest teardown complete"

    def load_template(self):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/WordPress_2_Instances_With_EBS.template" % self.path)
        t = template_format.parse(f.read())
        f.close()
        return t

    def parse_stack(self, t, stack_name):
        ctx = context.RequestContext.from_dict({
            'tenant': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'auth_url': 'http://localhost:5000/v2.0'})
        template = parser.Template(t)
        params = parser.Parameters(stack_name, template, {'KeyName': 'test'})
        stack = parser.Stack(ctx, stack_name, template, params)

        return stack

    def create_volume(self, t, stack, resource_name):
        resource = vol.Volume(resource_name,
                              t['Resources'][resource_name],
                              stack)
        self.assertEqual(resource.validate(), None)
        self.assertEqual(resource.create(), None)
        self.assertEqual(resource.state, vol.Volume.CREATE_COMPLETE)
        return resource

    def create_attachment(self, t, stack, resource_name):
        resource = vol.VolumeAttachment(resource_name,
                                        t['Resources'][resource_name],
                                        stack)
        self.assertEqual(resource.validate(), None)
        self.assertEqual(resource.create(), None)
        self.assertEqual(resource.state, vol.VolumeAttachment.CREATE_COMPLETE)
        return resource

    def test_volume(self):
        fv = FakeVolume('creating', 'available')
        stack_name = 'test_volume_stack'

        # create script
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(self.fc)
        self.fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)

        # delete script
        self.fc.volumes.get('vol-123').AndReturn(fv)
        eventlet.sleep(1).AndReturn(None)

        self.fc.volumes.get('vol-123').AndReturn(fv)
        self.fc.volumes.delete('vol-123').AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        t['Resources']['DataVolume']['Properties']['AvailabilityZone'] = 'nova'
        stack = self.parse_stack(t, stack_name)

        resource = self.create_volume(t, stack, 'DataVolume')
        self.assertEqual(fv.status, 'available')

        self.assertEqual(resource.handle_update({}), vol.Volume.UPDATE_REPLACE)

        fv.status = 'in-use'
        self.assertEqual(resource.delete(), 'Volume in use')
        fv.status = 'available'
        self.assertEqual(resource.delete(), None)

        self.m.VerifyAll()

    def test_volume_create_error(self):
        fv = FakeVolume('creating', 'error')
        stack_name = 'test_volume_create_error_stack'

        # create script
        clients.OpenStackClients.cinder().AndReturn(self.fc)
        self.fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)

        eventlet.sleep(1).AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        t['Resources']['DataVolume']['Properties']['AvailabilityZone'] = 'nova'
        stack = self.parse_stack(t, stack_name)

        resource = vol.Volume('DataVolume',
                              t['Resources']['DataVolume'],
                              stack)
        self.assertEqual(resource.create(), 'error')

        self.m.VerifyAll()

    def test_volume_attachment_error(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'error')
        stack_name = 'test_volume_attach_error_stack'

        # volume create
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(self.fc)
        self.fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)

        # create script
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
#        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(self.fc)

        eventlet.sleep(1).MultipleTimes().AndReturn(None)
        self.fc.volumes.create_server_volume(
            device=u'/dev/vdc',
            server_id=u'WikiDatabase',
            volume_id=u'vol-123').AndReturn(fva)

        self.fc.volumes.get('vol-123').AndReturn(fva)

        self.m.ReplayAll()

        t = self.load_template()
        t['Resources']['DataVolume']['Properties']['AvailabilityZone'] = 'nova'
        stack = self.parse_stack(t, stack_name)

        self.assertEqual(stack['DataVolume'].create(), None)
        self.assertEqual(fv.status, 'available')
        resource = vol.VolumeAttachment('MountPoint',
                                        t['Resources']['MountPoint'],
                                        stack)
        self.assertEqual(resource.create(), 'error')

        self.m.VerifyAll()

    def test_volume_attachment(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        stack_name = 'test_volume_attach_stack'

        # volume create
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(self.fc)
        self.fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)

        # create script
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        #clients.OpenStackClients.cinder().MultipleTimes().AndReturn(self.fc)
        eventlet.sleep(1).MultipleTimes().AndReturn(None)
        self.fc.volumes.create_server_volume(
            device=u'/dev/vdc',
            server_id=u'WikiDatabase',
            volume_id=u'vol-123').AndReturn(fva)

        self.fc.volumes.get('vol-123').AndReturn(fva)

        # delete script
        fva = FakeVolume('in-use', 'available')
        self.fc.volumes.delete_server_volume('WikiDatabase',
                                             'vol-123').AndReturn(None)
        self.fc.volumes.get('vol-123').AndReturn(fva)

        self.m.ReplayAll()

        t = self.load_template()
        t['Resources']['DataVolume']['Properties']['AvailabilityZone'] = 'nova'
        stack = self.parse_stack(t, stack_name)

        self.assertEqual(stack['DataVolume'].create(), None)
        self.assertEqual(fv.status, 'available')
        resource = self.create_attachment(t, stack, 'MountPoint')

        self.assertEqual(resource.handle_update({}), vol.Volume.UPDATE_REPLACE)

        self.assertEqual(resource.delete(), None)

        self.m.VerifyAll()


class FakeVolume:
    status = 'attaching'
    id = 'vol-123'

    def __init__(self, initial_status, final_status):
        self.status = initial_status
        self.final_status = final_status

    def get(self):
        self.status = self.final_status
