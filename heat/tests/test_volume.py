#
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
import json

from cinderclient import exceptions as cinder_exp
from cinderclient.v1 import client as cinderclient
import mox
from oslo.config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.db import api as db_api
from heat.engine.clients.os import cinder
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine.resources import instance
from heat.engine.resources import volume as vol
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes


volume_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Volume Test",
  "Parameters" : {},
  "Resources" : {
    "WikiDatabase": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "foo",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "some data"
      }
    },
    "DataVolume" : {
      "Type" : "AWS::EC2::Volume",
      "Properties" : {
        "Size" : "1",
        "AvailabilityZone" : {"Fn::GetAtt": ["WikiDatabase",
                                             "AvailabilityZone"]},
        "Tags" : [{ "Key" : "Usage", "Value" : "Wiki Data Volume" }]
      }
    },
    "MountPoint" : {
      "Type" : "AWS::EC2::VolumeAttachment",
      "Properties" : {
        "InstanceId" : { "Ref" : "WikiDatabase" },
        "VolumeId"  : { "Ref" : "DataVolume" },
        "Device" : "/dev/vdc"
      }
    }
  }
}
'''

cinder_volume_template = '''
heat_template_version: 2013-05-23
description: Cinder volumes and attachments.
resources:
  volume:
    type: OS::Cinder::Volume
    properties:
      availability_zone: nova
      size: 1
      name: test_name
      description: test_description
      metadata:
        key: value
  volume2:
    type: OS::Cinder::Volume
    properties:
      availability_zone: nova
      size: 2
  attachment:
    type: OS::Cinder::VolumeAttachment
    properties:
      instance_uuid: WikiDatabase
      volume_id: { get_resource: volume }
      mountpoint: /dev/vdc
'''


class BaseVolumeTest(HeatTestCase):
    def setUp(self):
        super(BaseVolumeTest, self).setUp()
        self.fc = fakes.FakeClient()
        self.cinder_fc = cinderclient.Client('username', 'password')
        self.m.StubOutWithMock(cinder.CinderClientPlugin, '_create')
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        self.m.StubOutWithMock(self.cinder_fc.volumes, 'create')
        self.m.StubOutWithMock(self.cinder_fc.volumes, 'get')
        self.m.StubOutWithMock(self.cinder_fc.volumes, 'delete')
        self.m.StubOutWithMock(self.cinder_fc.volumes, 'extend')
        self.m.StubOutWithMock(self.cinder_fc.volumes, 'update')
        self.m.StubOutWithMock(self.cinder_fc.volumes, 'update_all_metadata')
        self.m.StubOutWithMock(self.fc.volumes, 'create_server_volume')
        self.m.StubOutWithMock(self.fc.volumes, 'delete_server_volume')
        self.m.StubOutWithMock(self.fc.volumes, 'get_server_volume')
        self.use_cinder = False

    def _mock_delete_volume(self, fv):
        self.m.StubOutWithMock(fv, 'delete')
        fv.delete().AndReturn(True)
        self.m.StubOutWithMock(fv, 'get')
        fv.get().AndReturn(None)
        fv.get().AndRaise(cinder_exp.NotFound('Not found'))
        self.m.ReplayAll()

    def _mock_create_server_volume_script(self, fva,
                                          server=u'WikiDatabase',
                                          volume='vol-123',
                                          device=u'/dev/vdc',
                                          update=False):
        if not update:
            nova.NovaClientPlugin._create().MultipleTimes().AndReturn(self.fc)
        self.fc.volumes.create_server_volume(
            device=device, server_id=server, volume_id=volume).AndReturn(fva)
        self.cinder_fc.volumes.get(volume).AndReturn(fva)

    def create_volume(self, t, stack, resource_name):
        if self.use_cinder:
            Volume = vol.CinderVolume
        else:
            data = t['Resources'][resource_name]
            data['Properties']['AvailabilityZone'] = 'nova'
            Volume = vol.Volume
        rsrc = Volume(resource_name,
                      stack.t.resource_definitions(stack)[resource_name],
                      stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_attachment(self, t, stack, resource_name):
        if self.use_cinder:
            Attachment = vol.CinderVolumeAttachment
        else:
            Attachment = vol.VolumeAttachment
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = Attachment(resource_name,
                          resource_defns[resource_name],
                          stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc


class VolumeTest(BaseVolumeTest):

    def setUp(self):
        super(VolumeTest, self).setUp()
        self.t = template_format.parse(volume_template)
        self.use_cinder = False

    def _mock_create_volume(self, fv, stack_name):
        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        vol_name = utils.PhysName(stack_name, 'DataVolume')
        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            display_description=vol_name,
            display_name=vol_name,
            metadata={u'Usage': u'Wiki Data Volume'}).AndReturn(fv)

    def test_volume(self):
        fv = FakeVolume('creating', 'available')
        stack_name = 'test_volume_stack'

        # create script
        self._mock_create_volume(fv, stack_name)

        # delete script
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)

        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')
        self.assertEqual('available', fv.status)

        fv.status = 'in-use'
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(rsrc.destroy))
        self.assertIn("Volume in use", six.text_type(ex))

        self._mock_delete_volume(fv)
        fv.status = 'available'
        scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_volume_default_az(self):
        fv = FakeVolume('creating', 'available')
        stack_name = 'test_volume_stack'

        # create script
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        self.m.StubOutWithMock(instance.Instance, '_resolve_attribute')
        self.m.StubOutWithMock(vol.VolumeAttachment, 'handle_create')
        self.m.StubOutWithMock(vol.VolumeAttachment, 'check_create_complete')

        instance.Instance.handle_create().AndReturn(None)
        instance.Instance.check_create_complete(None).AndReturn(True)
        instance.Instance._resolve_attribute(
            'AvailabilityZone').MultipleTimes().AndReturn(None)
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.stub_ImageConstraint_validate()
        vol_name = utils.PhysName(stack_name, 'DataVolume')
        self.cinder_fc.volumes.create(
            size=1, availability_zone=None,
            display_description=vol_name,
            display_name=vol_name,
            metadata={u'Usage': u'Wiki Data Volume'}).AndReturn(fv)
        vol.VolumeAttachment.handle_create().AndReturn(None)
        vol.VolumeAttachment.check_create_complete(None).AndReturn(True)

        # delete script
        self.m.StubOutWithMock(instance.Instance, 'handle_delete')
        self.m.StubOutWithMock(vol.VolumeAttachment, 'handle_delete')
        instance.Instance.handle_delete().AndReturn(None)
        self.cinder_fc.volumes.get('vol-123').AndRaise(
            cinder_exp.NotFound('Not found'))
        vol.VolumeAttachment.handle_delete().AndReturn(None)
        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = stack['DataVolume']
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(stack.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        scheduler.TaskRunner(stack.delete)()

        self.m.VerifyAll()

    def test_volume_create_error(self):
        fv = FakeVolume('creating', 'error')
        stack_name = 'test_volume_create_error_stack'
        cfg.CONF.set_override('action_retry_limit', 0)

        self._mock_create_volume(fv, stack_name)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)
        ex = self.assertRaises(exception.ResourceFailure,
                               self.create_volume, self.t, stack, 'DataVolume')
        self.assertIn('Went to status error due to "Unknown"',
                      six.text_type(ex))

        self.m.VerifyAll()

    def test_volume_bad_tags(self):
        stack_name = 'test_volume_bad_tags_stack'
        self.t['Resources']['DataVolume']['Properties'][
            'Tags'] = [{'Foo': 'bar'}]
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.create_volume, self.t, stack, 'DataVolume')
        self.assertIn('Tags Property error', six.text_type(ex))

        self.m.VerifyAll()

    def test_volume_attachment_error(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'error')
        stack_name = 'test_volume_attach_error_stack'

        self._mock_create_volume(fv, stack_name)

        self._mock_create_server_volume_script(fva)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        self.assertEqual('available', fv.status)
        ex = self.assertRaises(exception.ResourceFailure,
                               self.create_attachment,
                               self.t, stack, 'MountPoint')
        self.assertIn("Volume attachment failed - Unknown status error",
                      six.text_type(ex))

        self.m.VerifyAll()

    def test_volume_attachment(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        stack_name = 'test_volume_attach_stack'

        self._mock_create_volume(fv, stack_name)

        self._mock_create_server_volume_script(fva)

        # delete script
        fva = FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes.fake_exception())

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        self.assertEqual('available', fv.status)
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_volume_detachment_err(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('in-use', 'available')
        stack_name = 'test_volume_detach_stack'

        self._mock_create_volume(fv, stack_name)

        self._mock_create_server_volume_script(fva)

        # delete script
        fva = FakeVolume('in-use', 'available')

        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)

        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').AndRaise(fakes.fake_exception(400))

        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes.fake_exception())
        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        self.assertEqual('available', fv.status)
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_volume_detach_non_exist(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('in-use', 'available')
        stack_name = 'test_volume_detach_stack'

        self._mock_create_volume(fv, stack_name)

        self._mock_create_server_volume_script(fva)

        # delete script
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndRaise(
            cinder_exp.NotFound('Not found'))

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_volume_detach_with_latency(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        stack_name = 'test_volume_attach_stack'

        self._mock_create_volume(fv, stack_name)

        self._mock_create_server_volume_script(fva)

        # delete script
        volume_detach_cycle = 'in-use', 'detaching', 'available'
        fva = FakeLatencyVolume(life_cycle=volume_detach_cycle)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes.fake_exception())

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        self.assertEqual('available', fv.status)
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_volume_detach_with_error(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        stack_name = 'test_volume_attach_stack'

        self._mock_create_volume(fv, stack_name)

        self._mock_create_server_volume_script(fva)

        # delete script
        fva = FakeVolume('in-use', 'error')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume('WikiDatabase',
                                             'vol-123').AndReturn(None)
        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        self.assertEqual('available', fv.status)
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')
        detach_task = scheduler.TaskRunner(rsrc.delete)

        ex = self.assertRaises(exception.ResourceFailure, detach_task)
        self.assertIn('Volume detachment failed - Unknown status error',
                      six.text_type(ex))

        self.m.VerifyAll()

    def test_volume_delete(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolume('creating', 'available')

        self._mock_create_volume(fv, stack_name)
        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Delete'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        self.m.StubOutWithMock(rsrc, "handle_delete")
        rsrc.handle_delete().AndReturn(None)
        self.m.StubOutWithMock(rsrc, "check_delete_complete")
        rsrc.check_delete_complete(mox.IgnoreArg()).AndReturn(True)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_volume_update_not_supported(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolume('creating', 'available')

        self._mock_create_volume(fv, stack_name)
        self.m.ReplayAll()

        t = template_format.parse(volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        rsrc = self.create_volume(t, stack, 'DataVolume')

        props = copy.deepcopy(rsrc.properties.data)
        props['Size'] = 2
        props['Tags'] = None
        props['AvailabilityZone'] = 'other'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        updater = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, updater)
        self.assertIn("NotSupported: Update to properties "
                      "AvailabilityZone, Size, Tags of DataVolume "
                      "(AWS::EC2::Volume) is not supported",
                      six.text_type(ex))
        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)

    def test_snapshot(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolume('creating', 'available')
        fb = FakeBackup('creating', 'available')

        self._mock_create_volume(fv, stack_name)

        # snapshot script
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create('vol-123').AndReturn(fb)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)

        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        self._mock_delete_volume(fv)
        scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_snapshot_error(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolume('creating', 'available')
        fb = FakeBackup('creating', 'error')

        self._mock_create_volume(fv, stack_name)

        # snapshot script
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create('vol-123').AndReturn(fb)
        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(rsrc.destroy))
        self.assertIn('Unknown status error', six.text_type(ex))

        self.m.VerifyAll()

    def test_snapshot_no_volume(self):
        stack_name = 'test_volume_stack'

        cfg.CONF.set_override('action_retry_limit', 0)
        fv = FakeVolume('creating', 'error')

        self._mock_create_volume(fv, stack_name)

        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)

        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        self.t['Resources']['DataVolume']['Properties'][
            'AvailabilityZone'] = 'nova'
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = vol.Volume('DataVolume',
                          resource_defns['DataVolume'],
                          stack)

        create = scheduler.TaskRunner(rsrc.create)
        ex = self.assertRaises(exception.ResourceFailure, create)
        self.assertIn('Went to status error due to "Unknown"',
                      six.text_type(ex))

        self._mock_delete_volume(fv)
        scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_create_from_snapshot(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolumeWithStateTransition('restoring-backup', 'available')
        fvbr = FakeBackupRestore('vol-123')

        # create script
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123').AndReturn(fvbr)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        self.m.StubOutWithMock(fv, 'update')
        vol_name = utils.PhysName(stack_name, 'DataVolume')
        fv.update(
            display_description=vol_name,
            display_name=vol_name)

        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['Properties'][
            'SnapshotId'] = 'backup-123'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        self.assertEqual('available', fv.status)

        self.m.VerifyAll()

    def test_create_from_snapshot_error(self):
        stack_name = 'test_volume_stack'
        cfg.CONF.set_override('action_retry_limit', 0)
        fv = FakeVolumeWithStateTransition('restoring-backup', 'error')
        fvbr = FakeBackupRestore('vol-123')

        # create script
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123').AndReturn(fvbr)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        self.m.StubOutWithMock(fv, 'update')
        vol_name = utils.PhysName(stack_name, 'DataVolume')
        fv.update(
            display_description=vol_name,
            display_name=vol_name)

        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['Properties'][
            'SnapshotId'] = 'backup-123'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        ex = self.assertRaises(exception.ResourceFailure,
                               self.create_volume, self.t, stack, 'DataVolume')
        self.assertIn('Went to status error due to "Unknown"',
                      six.text_type(ex))

        self.m.VerifyAll()

    def test_volume_size_constraint(self):
        self.t['Resources']['DataVolume']['Properties']['Size'] = '0'
        stack = utils.parse_stack(self.t)
        error = self.assertRaises(exception.StackValidationFailed,
                                  self.create_volume,
                                  self.t, stack, 'DataVolume')
        self.assertEqual(
            "Property error : DataVolume: Size 0 is out of "
            "range (min: 1, max: None)", six.text_type(error))

    def test_volume_attachment_updates_not_supported(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        stack_name = 'test_volume_attach_stack'

        self._mock_create_volume(fv, stack_name)
        self._mock_create_server_volume_script(fva)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        self.assertEqual('available', fv.status)
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        props = copy.deepcopy(rsrc.properties.data)
        props['InstanceId'] = 'some_other_instance_id'
        props['VolumeId'] = 'some_other_volume_id'
        props['Device'] = '/dev/vdz'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertIn('NotSupported: Update to properties Device, InstanceId, '
                      'VolumeId of MountPoint (AWS::EC2::VolumeAttachment)',
                      six.text_type(ex))
        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()


class CinderVolumeTest(BaseVolumeTest):

    def setUp(self):
        super(CinderVolumeTest, self).setUp()
        self.t = template_format.parse(cinder_volume_template)
        self.use_cinder = True

    def _mock_create_volume(self, fv, stack_name, size=1):
        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=size, availability_zone='nova',
            display_description='test_description',
            display_name='test_name',
            metadata={'key': 'value'}).AndReturn(fv)

    def test_cinder_volume_size_constraint(self):
        self.t['resources']['volume']['properties']['size'] = 0
        stack = utils.parse_stack(self.t)
        error = self.assertRaises(exception.StackValidationFailed,
                                  self.create_volume,
                                  self.t, stack, 'volume')
        self.assertEqual(
            "Property error : volume: size 0 is out of "
            "range (min: 1, max: None)", six.text_type(error))

    def test_cinder_create(self):
        fv = FakeVolume('creating', 'available')
        stack_name = 'test_volume_stack'

        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            display_description='test_description',
            display_name='test_name',
            imageRef='46988116-6703-4623-9dbc-2bc6d284021b',
            snapshot_id='snap-123',
            metadata={'key': 'value'},
            source_volid='vol-012',
            volume_type='lvm').AndReturn(fv)

        self.m.ReplayAll()

        self.t['resources']['volume']['properties'].update({
            'volume_type': 'lvm',
            # Note that specifying all these arguments doesn't work in
            # practice, as they are conflicting, but we just want to check they
            # are sent to the backend.
            'imageRef': '46988116-6703-4623-9dbc-2bc6d284021b',
            'snapshot_id': 'snap-123',
            'source_volid': 'vol-012',
        })
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)

        self.m.VerifyAll()

    def test_cinder_create_from_image(self):
        fv = FakeVolumeWithStateTransition('downloading', 'available')
        stack_name = 'test_volume_stack'
        image_id = '46988116-6703-4623-9dbc-2bc6d284021b'
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.m.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
        glance.GlanceClientPlugin.get_image_id(
            image_id).MultipleTimes().AndReturn(image_id)

        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            display_description='ImageVolumeDescription',
            display_name='ImageVolume',
            imageRef=image_id).AndReturn(fv)

        self.m.ReplayAll()

        self.t['resources']['volume']['properties'] = {
            'size': '1',
            'name': 'ImageVolume',
            'description': 'ImageVolumeDescription',
            'availability_zone': 'nova',
            'image': image_id,
        }
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)

        self.m.VerifyAll()

    def test_cinder_default(self):
        fv = FakeVolume('creating', 'available')
        stack_name = 'test_volume_stack'

        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        vol_name = utils.PhysName(stack_name, 'volume')
        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            display_description=None,
            display_name=vol_name).AndReturn(fv)

        self.m.ReplayAll()

        self.t['resources']['volume']['properties'] = {
            'size': '1',
            'availability_zone': 'nova',
        }
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)

        self.m.VerifyAll()

    def test_cinder_fn_getatt(self):
        fv = FakeVolume('creating', 'available', availability_zone='zone1',
                        size=1, snapshot_id='snap-123', display_name='name',
                        display_description='desc', volume_type='lvm',
                        metadata={'key': 'value'}, source_volid=None,
                        status='available', bootable=False,
                        created_at='2013-02-25T02:40:21.000000')
        stack_name = 'test_volume_stack'

        self._mock_create_volume(fv, stack_name)
        self.cinder_fc.volumes.get('vol-123').MultipleTimes().AndReturn(fv)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)
        rsrc = self.create_volume(self.t, stack, 'volume')

        self.assertEqual(u'zone1', rsrc.FnGetAtt('availability_zone'))
        self.assertEqual(u'1', rsrc.FnGetAtt('size'))
        self.assertEqual(u'snap-123', rsrc.FnGetAtt('snapshot_id'))
        self.assertEqual(u'name', rsrc.FnGetAtt('display_name'))
        self.assertEqual(u'desc', rsrc.FnGetAtt('display_description'))
        self.assertEqual(u'lvm', rsrc.FnGetAtt('volume_type'))
        self.assertEqual(json.dumps({'key': 'value'}),
                         rsrc.FnGetAtt('metadata'))
        self.assertEqual({'key': 'value'},
                         rsrc.FnGetAtt('metadata_values'))
        self.assertEqual(u'None', rsrc.FnGetAtt('source_volid'))
        self.assertEqual(u'available', rsrc.FnGetAtt('status'))
        self.assertEqual(u'2013-02-25T02:40:21.000000',
                         rsrc.FnGetAtt('created_at'))
        self.assertEqual(u'False', rsrc.FnGetAtt('bootable'))
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'unknown')
        self.assertEqual(
            'The Referenced Attribute (volume unknown) is incorrect.',
            six.text_type(error))

        self.m.VerifyAll()

    def test_cinder_attachment(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        stack_name = 'test_volume_attach_stack'

        self._mock_create_volume(fv, stack_name)

        self._mock_create_server_volume_script(fva)

        # delete script
        fva = FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes.fake_exception())

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)
        rsrc = self.create_attachment(self.t, stack, 'attachment')
        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_cinder_volume_shrink_fails(self):
        fv = FakeVolume('creating', 'available', size=2)
        stack_name = 'test_volume_stack'

        # create script
        self._mock_create_volume(fv, stack_name, size=2)
        # update script
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)

        self.m.ReplayAll()

        self.t['resources']['volume']['properties']['size'] = 2
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 1
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertEqual('NotSupported: Shrinking volume is not supported.',
                         six.text_type(ex))

        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_extend_detached(self):
        fv = FakeVolume('creating', 'available', size=1, attachments=[])
        stack_name = 'test_volume_stack'

        # create script
        self._mock_create_volume(fv, stack_name)
        # update script
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv2 = FakeLatencyVolume(life_cycle=('extending', 'extending',
                                            'available'))
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv2)

        self.cinder_fc.volumes.extend(fv.id, 2)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        self.assertIsNone(update_task())

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_extend_fails_to_start(self):
        fv = FakeVolume('creating', 'available', size=1, attachments=[])
        stack_name = 'test_volume_stack'

        # create script
        self._mock_create_volume(fv, stack_name)
        # update script
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv2 = FakeVolume('extending', 'extending')
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv2)

        self.cinder_fc.volumes.extend(fv.id, 2).AndRaise(
            cinder_exp.OverLimit(413))

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertIn('Over limit', six.text_type(ex))

        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_extend_fails_to_complete(self):
        fv = FakeVolume('creating', 'available', size=1, attachments=[])
        stack_name = 'test_volume_stack'

        # create script
        self._mock_create_volume(fv, stack_name)
        # update script
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv2 = FakeLatencyVolume(life_cycle=('extending', 'extending',
                                            'error_extending'))
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv2)

        self.cinder_fc.volumes.extend(fv.id, 2)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertIn("Volume resize failed - Unknown status error_extending",
                      six.text_type(ex))

        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_extend_attached(self):
        # create script
        fv = FakeVolume('creating', 'available')
        stack_name = 'test_volume_stack'
        self._mock_create_volume(fv, stack_name)

        fva = FakeVolume('attaching', 'in-use')
        self._mock_create_server_volume_script(fva)

        # update script
        attachments = [{'id': 'vol-123',
                        'device': '/dev/vdc',
                        'server_id': u'WikiDatabase'}]
        fv2 = FakeVolume('available', 'available', attachments=attachments,
                         size=1)
        self.cinder_fc.volumes.get(fv2.id).AndReturn(fv2)

        # detach script
        fvd = FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fvd)
        self.cinder_fc.volumes.get(fvd.id).AndReturn(fvd)
        self.fc.volumes.delete_server_volume('WikiDatabase', 'vol-123')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fvd)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes.fake_exception())

        # resize script
        fvr = FakeLatencyVolume(life_cycle=('extending', 'extending',
                                            'available'))
        self.cinder_fc.volumes.get(fvr.id).AndReturn(fvr)

        self.cinder_fc.volumes.extend(fvr.id, 2)

        # attach script
        fva2 = FakeVolume('attaching', 'in-use')
        self._mock_create_server_volume_script(fva2, update=True)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)
        self.create_attachment(self.t, stack, 'attachment')

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        self.assertIsNone(update_task())

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_extend_created_from_backup_with_same_size(self):
        stack_name = 'test_volume_stack'
        fv = FakeVolumeWithStateTransition('restoring-backup', 'available',
                                           size=2)
        fvbr = FakeBackupRestore('vol-123')

        # create script
        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123').AndReturn(fvbr)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        self.m.StubOutWithMock(fv, 'update')
        vol_name = utils.PhysName(stack_name, 'volume')
        fv.update(
            display_description=None,
            display_name=vol_name)

        # update script
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        self.m.ReplayAll()

        self.t['resources']['volume']['properties'] = {
            'availability_zone': 'nova',
            'backup_id': 'backup-123'
        }
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('available', fv.status)

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        self.assertIsNone(update_task())

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_update_name_and_metadata(self):
        # update the name, description and metadata
        fv = FakeVolume('creating', 'available', size=1, name='my_vol',
                        description='test')
        stack_name = 'test_volume_stack'
        update_name = 'update_name'
        meta = {'Key': 'New Value'}
        update_description = 'update_description'
        kwargs = {
            'display_name': update_name,
            'display_description': update_description
        }

        self._mock_create_volume(fv, stack_name)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        self.cinder_fc.volumes.update(fv, **kwargs).AndReturn(None)
        self.cinder_fc.volumes.update_all_metadata(fv, meta).AndReturn(None)
        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['name'] = update_name
        props['description'] = update_description
        props['metadata'] = meta
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

    def test_cinder_snapshot(self):
        fv = FakeVolume('creating', 'available')
        fb = FakeBackup('creating', 'available')
        stack_name = 'test_volume_stack'

        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova', display_name='CustomName',
            display_description='CustomDescription').AndReturn(fv)

        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create('vol-123').AndReturn(fb)

        self.m.ReplayAll()

        t = template_format.parse(volume_template)
        t['Resources']['DataVolume']['Properties'] = {
            'size': '1',
            'availability_zone': 'nova',
            'description': 'CustomDescription',
            'name': 'CustomName'
        }
        stack = utils.parse_stack(t, stack_name=stack_name)

        resource_defns = stack.t.resource_definitions(stack)
        rsrc = vol.CinderVolume('DataVolume',
                                resource_defns['DataVolume'],
                                stack)
        scheduler.TaskRunner(rsrc.create)()

        scheduler.TaskRunner(rsrc.snapshot)()

        self.assertEqual((rsrc.SNAPSHOT, rsrc.COMPLETE), rsrc.state)

        self.assertEqual({'backup_id': 'backup-123'},
                         db_api.resource_data_get_all(rsrc))

        self.m.VerifyAll()

    def test_cinder_snapshot_error(self):
        fv = FakeVolume('creating', 'available')
        fb = FakeBackup('creating', 'error')
        stack_name = 'test_volume_stack'

        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova', display_name='CustomName',
            display_description='CustomDescription').AndReturn(fv)

        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create('vol-123').AndReturn(fb)

        self.m.ReplayAll()

        t = template_format.parse(volume_template)
        t['Resources']['DataVolume']['Properties'] = {
            'size': '1',
            'availability_zone': 'nova',
            'description': 'CustomDescription',
            'name': 'CustomName'
        }
        stack = utils.parse_stack(t, stack_name=stack_name)

        resource_defns = stack.t.resource_definitions(stack)
        rsrc = vol.CinderVolume('DataVolume',
                                resource_defns['DataVolume'],
                                stack)
        scheduler.TaskRunner(rsrc.create)()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.snapshot))

        self.assertEqual((rsrc.SNAPSHOT, rsrc.FAILED), rsrc.state)
        self.assertEqual("Error: error", rsrc.status_reason)

        self.assertEqual({}, db_api.resource_data_get_all(rsrc))

        self.m.VerifyAll()

    def test_cinder_volume_attachment_update_device(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        fva2 = FakeVolume('attaching', 'in-use')
        stack_name = 'test_volume_attach_stack'

        self._mock_create_volume(fv, stack_name)

        self._mock_create_server_volume_script(fva)

        # delete script
        fva = FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes.fake_exception())

        # attach script
        self._mock_create_server_volume_script(fva2, device=u'/dev/vdd',
                                               update=True)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)

        rsrc = self.create_attachment(self.t, stack, 'attachment')

        props = copy.deepcopy(rsrc.properties.data)
        props['mountpoint'] = '/dev/vdd'
        props['volume_id'] = 'vol-123'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_attachment_update_volume(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        fv2 = FakeVolume('creating', 'available')
        fv2.id = 'vol-456'
        fv2a = FakeVolume('attaching', 'in-use')
        fv2a.id = 'vol-456'
        stack_name = 'test_volume_attach_stack'

        self._mock_create_volume(fv, stack_name)

        vol2_name = utils.PhysName(stack_name, 'volume2')
        self.cinder_fc.volumes.create(
            size=2, availability_zone='nova',
            display_description=None,
            display_name=vol2_name).AndReturn(fv2)

        self._mock_create_server_volume_script(fva)

        # delete script
        fva = FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes.fake_exception())

        # attach script
        self._mock_create_server_volume_script(fv2a, volume='vol-456',
                                               update=True)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)
        self.create_volume(self.t, stack, 'volume2')
        self.assertEqual('available', fv2.status)

        rsrc = self.create_attachment(self.t, stack, 'attachment')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        props = copy.deepcopy(rsrc.properties.data)
        props['volume_id'] = 'vol-456'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(fv2a.id, rsrc.resource_id)
        self.m.VerifyAll()

    def test_cinder_volume_attachment_update_server(self):
        fv = FakeVolume('creating', 'available')
        fva = FakeVolume('attaching', 'in-use')
        fva2 = FakeVolume('attaching', 'in-use')
        stack_name = 'test_volume_attach_stack'

        self._mock_create_volume(fv, stack_name)

        self._mock_create_server_volume_script(fva)

        # delete script
        fva = FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes.fake_exception())

        # attach script
        self._mock_create_server_volume_script(fva2, server=u'AnotherServer',
                                               update=True)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)

        rsrc = self.create_attachment(self.t, stack, 'attachment')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        props = copy.deepcopy(rsrc.properties.data)
        props['instance_uuid'] = 'AnotherServer'
        props['volume_id'] = 'vol-123'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()


class FakeVolume(object):
    status = 'attaching'
    id = 'vol-123'

    def __init__(self, initial_status, final_status, **attrs):
        self.status = initial_status
        self.final_status = final_status
        for key, value in six.iteritems(attrs):
            setattr(self, key, value)

    def get(self):
        self.status = self.final_status

    def update(self, **kw):
        pass

    def delete(self):
        pass


class FakeLatencyVolume(object):
    status = 'attaching'
    id = 'vol-123'

    def __init__(self, life_cycle=('creating', 'available'), **attrs):
        if not isinstance(life_cycle, tuple):
            raise exception.Error('life_cycle need to be a tuple.')
        if not len(life_cycle):
            raise exception.Error('life_cycle should not be an empty tuple.')
        self.life_cycle = iter(life_cycle)
        self.status = next(self.life_cycle)
        for key, value in six.iteritems(attrs):
            setattr(self, key, value)

    def get(self):
        self.status = next(self.life_cycle)

    def update(self, **kw):
        pass


class FakeBackup(FakeVolume):
    status = 'creating'
    id = 'backup-123'


class FakeBackupRestore(object):
    volume_id = 'vol-123'

    def __init__(self, volume_id):
        self.volume_id = volume_id


class FakeVolumeWithStateTransition(FakeVolume):
    status = 'restoring-backup'
    get_call_count = 0

    def get(self):
        # Allow get to be called once without changing the status
        # This is to allow the check_create_complete method to
        # check the initial status.
        if self.get_call_count < 1:
            self.get_call_count += 1
        else:
            self.status = self.final_status
