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

from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine import scheduler
from heat.engine.resources import volume as vol
from heat.engine import clients
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests.v1_1 import fakes
from heat.tests.utils import setup_dummy_db, skip_if

from cinderclient.v1 import client as cinderclient


volume_backups = try_import('cinderclient.v1.volume_backups')


class VolumeTest(HeatTestCase):
    def setUp(self):
        super(VolumeTest, self).setUp()
        self.fc = fakes.FakeClient()
        self.cinder_fc = cinderclient.Client('username', 'password')
        self.m.StubOutWithMock(clients.OpenStackClients, 'cinder')
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        self.m.StubOutWithMock(self.cinder_fc.volumes, 'create')
        self.m.StubOutWithMock(self.cinder_fc.volumes, 'get')
        self.m.StubOutWithMock(self.cinder_fc.volumes, 'delete')
        self.m.StubOutWithMock(self.fc.volumes, 'create_server_volume')
        self.m.StubOutWithMock(self.fc.volumes, 'delete_server_volume')
        self.m.StubOutWithMock(eventlet, 'sleep')
        setup_dummy_db()

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
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(resource.state, vol.Volume.CREATE_COMPLETE)
        return resource

    def create_attachment(self, t, stack, resource_name):
        resource = vol.VolumeAttachment(resource_name,
                                        t['Resources'][resource_name],
                                        stack)
        self.assertEqual(resource.validate(), None)
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(resource.state, vol.VolumeAttachment.CREATE_COMPLETE)
        return resource

    def test_volume(self):
        fv = FakeVolume('creating', 'available')
        stack_name = 'test_volume_stack'

        # create script
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)

        # delete script
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        eventlet.sleep(1).AndReturn(None)

        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        self.cinder_fc.volumes.delete('vol-123').AndReturn(None)

        self.cinder_fc.volumes.get('vol-123').AndRaise(
            clients.cinder_exceptions.NotFound('Not found'))
        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t, stack_name)

        resource = self.create_volume(t, stack, 'DataVolume')
        self.assertEqual(fv.status, 'available')

        self.assertEqual(resource.handle_update({}), vol.Volume.UPDATE_REPLACE)

        fv.status = 'in-use'
        self.assertRaises(exception.ResourceFailure, resource.destroy)
        fv.status = 'available'
        self.assertEqual(resource.destroy(), None)

        # Test when volume already deleted
        resource.state = resource.CREATE_COMPLETE
        self.assertEqual(resource.destroy(), None)

        self.m.VerifyAll()

    def test_volume_create_error(self):
        fv = FakeVolume('creating', 'error')
        stack_name = 'test_volume_create_error_stack'

        # create script
        clients.OpenStackClients.cinder().AndReturn(self.cinder_fc)
        self.cinder_fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)

        eventlet.sleep(1).AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t, stack_name)

        resource = vol.Volume('DataVolume',
                              t['Resources']['DataVolume'],
                              stack)
        create = scheduler.TaskRunner(resource.create)
        self.assertRaises(exception.ResourceFailure, create)

        self.m.VerifyAll()

    def test_volume_attachment_error(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'error')
        stack_name = 'test_volume_attach_error_stack'

        # volume create
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)

        # create script
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        eventlet.sleep(1).MultipleTimes().AndReturn(None)
        self.fc.volumes.create_server_volume(
            device=u'/dev/vdc',
            server_id=u'WikiDatabase',
            volume_id=u'vol-123').AndReturn(fva)

        self.cinder_fc.volumes.get('vol-123').AndReturn(fva)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t, stack_name)

        scheduler.TaskRunner(stack['DataVolume'].create)()
        self.assertEqual(fv.status, 'available')
        resource = vol.VolumeAttachment('MountPoint',
                                        t['Resources']['MountPoint'],
                                        stack)
        create = scheduler.TaskRunner(resource.create)
        self.assertRaises(exception.ResourceFailure, create)

        self.m.VerifyAll()

    def test_volume_attachment(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        stack_name = 'test_volume_attach_stack'

        # volume create
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
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

        self.cinder_fc.volumes.get('vol-123').AndReturn(fva)

        # delete script
        fva = FakeVolume('in-use', 'available')
        self.fc.volumes.delete_server_volume('WikiDatabase',
                                             'vol-123').AndReturn(None)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fva)

        self.m.ReplayAll()

        t = self.load_template()
        stack = self.parse_stack(t, stack_name)

        scheduler.TaskRunner(stack['DataVolume'].create)()
        self.assertEqual(fv.status, 'available')
        resource = self.create_attachment(t, stack, 'MountPoint')

        self.assertEqual(resource.handle_update({}), vol.Volume.UPDATE_REPLACE)

        self.assertEqual(resource.delete(), None)

        self.m.VerifyAll()

    @skip_if(volume_backups is None, 'unable to import volume_backups')
    def test_snapshot(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolume('creating', 'available')
        fb = FakeBackup('creating', 'available')

        # create script
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)
        eventlet.sleep(1).AndReturn(None)

        # snapshot script
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create('vol-123').AndReturn(fb)
        eventlet.sleep(1).AndReturn(None)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        self.cinder_fc.volumes.delete('vol-123').AndReturn(None)
        self.m.ReplayAll()

        t = self.load_template()
        t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = self.parse_stack(t, stack_name)

        resource = self.create_volume(t, stack, 'DataVolume')

        self.assertEqual(resource.destroy(), None)

        self.m.VerifyAll()

    @skip_if(volume_backups is None, 'unable to import volume_backups')
    def test_snapshot_error(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolume('creating', 'available')
        fb = FakeBackup('creating', 'error')

        # create script
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)
        eventlet.sleep(1).AndReturn(None)

        # snapshot script
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create('vol-123').AndReturn(fb)
        eventlet.sleep(1).AndReturn(None)
        self.m.ReplayAll()

        t = self.load_template()
        t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = self.parse_stack(t, stack_name)

        resource = self.create_volume(t, stack, 'DataVolume')

        self.assertRaises(exception.ResourceFailure, resource.destroy)

        self.m.VerifyAll()

    def test_snapshot_no_volume(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolume('creating', 'error')

        # create script
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            u'1', display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name).AndReturn(fv)
        eventlet.sleep(1).AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = self.parse_stack(t, stack_name)
        resource = vol.Volume('DataVolume',
                              t['Resources']['DataVolume'],
                              stack)

        create = scheduler.TaskRunner(resource.create)
        self.assertRaises(exception.ResourceFailure, create)

        self.assertEqual(resource.destroy(), None)

        self.m.VerifyAll()

    def test_create_from_snapshot(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolume('creating', 'available')

        # create script
        clients.OpenStackClients.cinder().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123').AndReturn(
            {'volume_id': 'vol-123'})
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        self.m.StubOutWithMock(fv, 'update')
        fv.update(
            display_description='%s.DataVolume' % stack_name,
            display_name='%s.DataVolume' % stack_name)
        eventlet.sleep(1).AndReturn(None)

        self.m.ReplayAll()

        t = self.load_template()
        t['Resources']['DataVolume']['Properties']['SnapshotId'] = 'backup-123'
        stack = self.parse_stack(t, stack_name)

        self.create_volume(t, stack, 'DataVolume')
        self.assertEqual(fv.status, 'available')

        self.m.VerifyAll()


class FakeVolume:
    status = 'attaching'
    id = 'vol-123'

    def __init__(self, initial_status, final_status):
        self.status = initial_status
        self.final_status = final_status

    def get(self):
        self.status = self.final_status

    def update(self, **kw):
        pass


class FakeBackup(FakeVolume):
    status = 'creating'
    id = 'backup-123'
