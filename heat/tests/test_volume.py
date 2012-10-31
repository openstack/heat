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


import sys
import os

import eventlet
import json
import nose
import mox
import unittest

from nose.plugins.attrib import attr

from heat.engine import parser
from heat.engine.resources import volume as vol
from heat.tests.v1_1 import fakes


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class VolumeTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(vol.Volume, 'nova')
        self.m.StubOutWithMock(vol.VolumeAttachment, 'nova')
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
        t = json.loads(f.read())
        f.close()
        return t

    def parse_stack(self, t):
        class DummyContext():
            tenant = 'test_tenant'
            username = 'test_username'
            password = 'password'
            auth_url = 'http://localhost:5000/v2.0'
        template = parser.Template(t)
        params = parser.Parameters('test_stack', template, {'KeyName': 'test'})
        stack = parser.Stack(DummyContext(), 'test_stack', template,
                             params, stack_id=-1)

        return stack

    def create_volume(self, t, stack, resource_name):
        resource = vol.Volume(resource_name,
                                      t['Resources'][resource_name],
                                      stack)
        self.assertEqual(None, resource.validate())
        self.assertEqual(None, resource.create())
        self.assertEqual(vol.Volume.CREATE_COMPLETE, resource.state)
        return resource

    def create_attachment(self, t, stack, resource_name):
        resource = vol.VolumeAttachment(resource_name,
                                      t['Resources'][resource_name],
                                      stack)
        self.assertEqual(None, resource.validate())
        self.assertEqual(None, resource.create())
        self.assertEqual(vol.VolumeAttachment.CREATE_COMPLETE,
                         resource.state)
        return resource

    def test_volume(self):

        fv = FakeVolume('creating', 'available')

        # create script
        vol.Volume.nova('volume').AndReturn(self.fc)
        self.fc.volumes.create(u'1',
                        display_description='test_stack.DataVolume',
                        display_name='test_stack.DataVolume').AndReturn(fv)

        # delete script
        vol.Volume.nova('volume').AndReturn(self.fc)
        self.fc.volumes.get('vol-123').AndReturn(fv)
        eventlet.sleep(1).AndReturn(None)

        vol.Volume.nova('volume').AndReturn(self.fc)
        self.fc.volumes.get('vol-123').AndReturn(fv)
        vol.Volume.nova('volume').AndReturn(self.fc)
        self.fc.volumes.delete('vol-123').AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t)

        resource = self.create_volume(t, stack, 'DataVolume')
        self.assertEqual('available', fv.status)

        self.assertEqual(vol.Volume.UPDATE_REPLACE,
                          resource.handle_update())

        fv.status = 'in-use'
        self.assertEqual('Volume in use', resource.delete())
        fv.status = 'available'
        self.assertEqual(None, resource.delete())

        self.m.VerifyAll()

    def test_volume_create_error(self):

        fv = FakeVolume('creating', 'error')

        # create script
        vol.Volume.nova('volume').AndReturn(self.fc)
        self.fc.volumes.create(u'1',
                        display_description='test_stack.DataVolume',
                        display_name='test_stack.DataVolume').AndReturn(fv)

        eventlet.sleep(1).AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t)

        resource = vol.Volume('DataVolume',
                                      t['Resources']['DataVolume'],
                                      stack)
        self.assertEqual('error', resource.create())

        self.m.VerifyAll()

    def test_volume_attachment_error(self):

        fv = FakeVolume('attaching', 'error')

        # create script
        vol.VolumeAttachment.nova().AndReturn(self.fc)
        self.fc.volumes.create_server_volume(device=u'/dev/vdc',
                        server_id=u'WikiDatabase',
                        volume_id=u'vol-123').AndReturn(fv)

        vol.VolumeAttachment.nova('volume').AndReturn(self.fc)
        self.fc.volumes.get('vol-123').AndReturn(fv)
        eventlet.sleep(1).AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t)

        resource = vol.VolumeAttachment('MountPoint',
                                      t['Resources']['MountPoint'],
                                      stack)
        self.assertEqual('error', resource.create())

        self.m.VerifyAll()

    def test_volume_attachment(self):

        fv = FakeVolume('attaching', 'in-use')

        # create script
        vol.VolumeAttachment.nova().AndReturn(self.fc)
        self.fc.volumes.create_server_volume(device=u'/dev/vdc',
                        server_id=u'WikiDatabase',
                        volume_id=u'vol-123').AndReturn(fv)

        vol.VolumeAttachment.nova('volume').AndReturn(self.fc)
        self.fc.volumes.get('vol-123').AndReturn(fv)
        eventlet.sleep(1).AndReturn(None)

        # delete script

        fv = FakeVolume('in-use', 'available')
        vol.VolumeAttachment.nova().AndReturn(self.fc)
        self.fc.volumes.delete_server_volume('WikiDatabase',
                                             'vol-123').AndReturn(None)
        vol.VolumeAttachment.nova('volume').AndReturn(self.fc)
        self.fc.volumes.get('vol-123').AndReturn(fv)
        eventlet.sleep(1).AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t)

        resource = self.create_attachment(t, stack, 'MountPoint')

        self.assertEqual(vol.Volume.UPDATE_REPLACE,
                  resource.handle_update())

        self.assertEqual(None, resource.delete())

        self.m.VerifyAll()

    # allows testing of the test directly, shown below
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()


class FakeVolume:
    status = 'attaching'
    id = 'vol-123'

    def __init__(self, initial_status, final_status):
        self.status = initial_status
        self.final_status = final_status

    def get(self):
        self.status = self.final_status
