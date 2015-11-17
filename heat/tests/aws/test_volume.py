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

from cinderclient import exceptions as cinder_exp
import mock
import mox
from oslo_config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import cinder
from heat.engine.clients.os import nova
from heat.engine.resources.aws.ec2 import instance
from heat.engine.resources.aws.ec2 import volume as aws_vol
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.cinder import test_volume_utils as vt_base
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


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


class VolumeTest(vt_base.BaseVolumeTest):

    def setUp(self):
        super(VolumeTest, self).setUp()
        self.t = template_format.parse(volume_template)
        self.use_cinder = False

    def _mock_create_volume(self, fv, stack_name, final_status='available'):
        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        vol_name = utils.PhysName(stack_name, 'DataVolume')
        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            description=vol_name,
            name=vol_name,
            metadata={u'Usage': u'Wiki Data Volume'}).AndReturn(
                vt_base.FakeVolume(fv))
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv_ready = vt_base.FakeVolume(final_status, id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)
        return fv_ready

    def test_volume(self):
        stack_name = 'test_volume_create_stack'

        # create script
        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name)
        # failed delete due to in-use script
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('in-use'))
        # delete script
        self._mock_delete_volume(fv)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(rsrc.destroy))
        self.assertIn("Volume in use", six.text_type(ex))

        scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_volume_default_az(self):
        fv = vt_base.FakeVolume('creating')
        stack_name = 'test_volume_defaultaz_stack'

        # create script
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        self.m.StubOutWithMock(instance.Instance, '_resolve_attribute')
        self.m.StubOutWithMock(aws_vol.VolumeAttachment,
                               'handle_create')
        self.m.StubOutWithMock(aws_vol.VolumeAttachment,
                               'check_create_complete')

        instance.Instance.handle_create().AndReturn(None)
        instance.Instance.check_create_complete(None).AndReturn(True)
        instance.Instance._resolve_attribute(
            'AvailabilityZone').MultipleTimes().AndReturn(None)
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.stub_ImageConstraint_validate()
        self.stub_ServerConstraint_validate()
        self.stub_VolumeConstraint_validate()
        vol_name = utils.PhysName(stack_name, 'DataVolume')
        self.cinder_fc.volumes.create(
            size=1, availability_zone=None,
            description=vol_name,
            name=vol_name,
            metadata={u'Usage': u'Wiki Data Volume'}).AndReturn(fv)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)
        aws_vol.VolumeAttachment.handle_create().AndReturn(None)
        aws_vol.VolumeAttachment.check_create_complete(
            None).AndReturn(True)

        # delete script
        self.m.StubOutWithMock(instance.Instance, 'handle_delete')
        self.m.StubOutWithMock(aws_vol.VolumeAttachment, 'handle_delete')
        self.m.StubOutWithMock(aws_vol.VolumeAttachment,
                               'check_delete_complete')
        instance.Instance.handle_delete().AndReturn(None)
        self.cinder_fc.volumes.get('vol-123').AndRaise(
            cinder_exp.NotFound('Not found'))
        cookie = object()
        aws_vol.VolumeAttachment.handle_delete().AndReturn(cookie)
        aws_vol.VolumeAttachment.check_delete_complete(cookie).AndReturn(True)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = stack['DataVolume']
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(stack.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        scheduler.TaskRunner(stack.delete)()

        self.m.VerifyAll()

    def test_volume_create_error(self):
        fv = vt_base.FakeVolume('creating')
        stack_name = 'test_volume_create_error_stack'
        cfg.CONF.set_override('action_retry_limit', 0)

        self._mock_create_volume(fv, stack_name, final_status='error')

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
        self.assertEqual("Property error: "
                         "Resources.DataVolume.Properties.Tags[0]: "
                         "Unknown Property Foo", six.text_type(ex))

        self.m.VerifyAll()

    def test_volume_attachment_error(self):
        stack_name = 'test_volume_attach_error_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name)
        self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'), final_status='error')
        self.stub_VolumeConstraint_validate()

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        ex = self.assertRaises(exception.ResourceFailure,
                               self.create_attachment,
                               self.t, stack, 'MountPoint')
        self.assertIn("Volume attachment failed - Unknown status error",
                      six.text_type(ex))

        self.m.VerifyAll()

    def test_volume_attachment(self):
        stack_name = 'test_volume_attach_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name)
        fva = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self.stub_VolumeConstraint_validate()
        # delete script
        fva = vt_base.FakeVolume('in-use')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('detaching', id=fva.id))
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('available', id=fva.id))
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception())

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_volume_detachment_err(self):
        stack_name = 'test_volume_detach_err_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name)
        fva = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self.stub_VolumeConstraint_validate()
        # delete script
        fva = vt_base.FakeVolume('in-use')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)

        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception(400))
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('available', id=fva.id))
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception())
        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_volume_detach_non_exist(self):
        fv = vt_base.FakeVolume('creating')
        fva = vt_base.FakeVolume('in-use')
        stack_name = 'test_volume_detach_nonexist_stack'

        self._mock_create_volume(fv, stack_name)
        self._mock_create_server_volume_script(fva)
        self.stub_VolumeConstraint_validate()
        # delete script
        self.fc.volumes.delete_server_volume(u'WikiDatabase',
                                             'vol-123').AndReturn(None)
        self.cinder_fc.volumes.get(fva.id).AndRaise(
            cinder_exp.NotFound('Not found'))
        self.fc.volumes.get_server_volume(u'WikiDatabase', 'vol-123'
                                          ).AndRaise(
                                              fakes_nova.fake_exception())

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_volume_detach_deleting_volume(self):
        fv = vt_base.FakeVolume('creating')
        fva = vt_base.FakeVolume('deleting')
        stack_name = 'test_volume_detach_deleting_volume_stack'

        self._mock_create_volume(fv, stack_name)
        self._mock_create_server_volume_script(fva)
        self.stub_VolumeConstraint_validate()
        # delete script
        self.fc.volumes.delete_server_volume(u'WikiDatabase',
                                             'vol-123').AndReturn(None)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.get_server_volume(u'WikiDatabase', 'vol-123'
                                          ).AndRaise(
                                              fakes_nova.fake_exception())

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_volume_detach_with_latency(self):
        stack_name = 'test_volume_detach_latency_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name)
        fva = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self.stub_VolumeConstraint_validate()

        # delete script
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('in-use', id=fva.id))
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('detaching', id=fva.id))
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('available', id=fva.id))
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception())

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_volume_detach_with_error(self):
        stack_name = 'test_volume_detach_werr_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name)
        fva = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self.stub_VolumeConstraint_validate()
        # delete script
        fva = vt_base.FakeVolume('in-use')
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').AndReturn(None)
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('error', id=fva.id))
        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')
        detach_task = scheduler.TaskRunner(rsrc.delete)

        ex = self.assertRaises(exception.ResourceFailure, detach_task)
        self.assertIn('Volume detachment failed - Unknown status error',
                      six.text_type(ex))

        self.m.VerifyAll()

    def test_volume_delete(self):
        stack_name = 'test_volume_delete_stack'
        fv = vt_base.FakeVolume('creating')

        self._mock_create_volume(fv, stack_name)
        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Delete'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        self.m.StubOutWithMock(rsrc, "handle_delete")
        rsrc.handle_delete().AndReturn(None)
        self.m.StubOutWithMock(rsrc, "check_delete_complete")
        rsrc.check_delete_complete(None).AndReturn(True)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_volume_deleting_delete(self):
        fv = vt_base.FakeVolume('creating')
        stack_name = 'test_volume_deleting_stack'

        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name)

        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('deleting'))
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('deleting'))
        self.cinder_fc.volumes.get(fv.id).AndRaise(
            cinder_exp.NotFound('NotFound'))

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)
        rsrc = self.create_volume(self.t, stack, 'DataVolume')
        scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_volume_delete_error(self):
        fv = vt_base.FakeVolume('creating')
        stack_name = 'test_volume_deleting_stack'

        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name)

        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        self.cinder_fc.volumes.delete(fv.id).AndReturn(True)
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('deleting'))
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('error_deleting'))

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)
        rsrc = self.create_volume(self.t, stack, 'DataVolume')
        deleter = scheduler.TaskRunner(rsrc.destroy)
        self.assertRaisesRegexp(exception.ResourceFailure,
                                ".*ResourceInError.*error_deleting.*delete",
                                deleter)

        self.m.VerifyAll()

    def test_volume_update_not_supported(self):
        stack_name = 'test_volume_updnotsup_stack'
        fv = vt_base.FakeVolume('creating')

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
        self.assertIn("NotSupported: resources.DataVolume: "
                      "Update to properties "
                      "AvailabilityZone, Size, Tags of DataVolume "
                      "(AWS::EC2::Volume) is not supported",
                      six.text_type(ex))
        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)

    def test_volume_check(self):
        stack = utils.parse_stack(self.t, stack_name='volume_check')
        res = stack['DataVolume']
        fake_volume = vt_base.FakeVolume('available')
        cinder = mock.Mock()
        cinder.volumes.get.return_value = fake_volume
        self.patchobject(res, 'client', return_value=cinder)

        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

        fake_volume = vt_base.FakeVolume('in-use')
        res.client().volumes.get.return_value = fake_volume
        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

    def test_volume_check_not_available(self):
        stack = utils.parse_stack(self.t, stack_name='volume_check_na')
        res = stack['DataVolume']
        cinder = mock.Mock()
        fake_volume = vt_base.FakeVolume('foobar')
        cinder.volumes.get.return_value = fake_volume
        self.patchobject(res, 'client', return_value=cinder)

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.check))
        self.assertEqual((res.CHECK, res.FAILED), res.state)
        self.assertIn('foobar', res.status_reason)

    def test_volume_check_fail(self):
        stack = utils.parse_stack(self.t, stack_name='volume_check_fail')
        res = stack['DataVolume']
        cinder = mock.Mock()
        cinder.volumes.get.side_effect = Exception('boom')
        self.patchobject(res, 'client', return_value=cinder)

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.check))
        self.assertEqual((res.CHECK, res.FAILED), res.state)
        self.assertIn('boom', res.status_reason)

    def test_snapshot(self):
        stack_name = 'test_volume_snapshot_stack'
        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name)

        # snapshot script
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.m.StubOutWithMock(self.cinder_fc.backups, 'get')
        fb = vt_base.FakeBackup('available')
        self.cinder_fc.backups.create(fv.id).AndReturn(fb)
        self.cinder_fc.backups.get(fb.id).AndReturn(fb)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        self._mock_delete_volume(fv)

        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_snapshot_error(self):
        stack_name = 'test_volume_snapshot_err_stack'
        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name)

        # snapshot script
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.m.StubOutWithMock(self.cinder_fc.backups, 'get')
        fb = vt_base.FakeBackup('error')
        self.cinder_fc.backups.create(fv.id).AndReturn(fb)
        self.cinder_fc.backups.get(fb.id).AndReturn(fb)
        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(rsrc.destroy))
        self.assertIn('Unknown status error', six.text_type(ex))

        self.m.VerifyAll()

    def test_snapshot_no_volume(self):
        """Test that backup does not start for failed resource."""
        stack_name = 'test_volume_snapshot_novol_stack'
        cfg.CONF.set_override('action_retry_limit', 0)
        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name,
                                      final_status='error')

        self._mock_delete_volume(fv)
        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        self.t['Resources']['DataVolume']['Properties'][
            'AvailabilityZone'] = 'nova'
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = aws_vol.Volume('DataVolume',
                              resource_defns['DataVolume'],
                              stack)

        create = scheduler.TaskRunner(rsrc.create)
        ex = self.assertRaises(exception.ResourceFailure, create)
        self.assertIn('Went to status error due to "Unknown"',
                      six.text_type(ex))

        scheduler.TaskRunner(rsrc.destroy)()

        self.m.VerifyAll()

    def test_create_from_snapshot(self):
        stack_name = 'test_volume_create_from_snapshot_stack'
        fv = vt_base.FakeVolume('restoring-backup')
        fvbr = vt_base.FakeBackupRestore('vol-123')

        # create script
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.patchobject(self.cinder_fc.backups, 'get')
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123').AndReturn(fvbr)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        vol_name = utils.PhysName(stack_name, 'DataVolume')
        self.cinder_fc.volumes.update('vol-123',
                                      description=vol_name, name=vol_name)
        fv.status = 'available'
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)

        self.m.ReplayAll()

        self.t['Resources']['DataVolume']['Properties'][
            'SnapshotId'] = 'backup-123'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')

        self.m.VerifyAll()

    def test_create_from_snapshot_error(self):
        stack_name = 'test_volume_create_from_snap_err_stack'
        cfg.CONF.set_override('action_retry_limit', 0)
        fv = vt_base.FakeVolume('restoring-backup')
        fvbr = vt_base.FakeBackupRestore('vol-123')

        # create script
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.patchobject(self.cinder_fc.backups, 'get')
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123').AndReturn(fvbr)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        vol_name = utils.PhysName(stack_name, 'DataVolume')
        self.cinder_fc.volumes.update(fv.id,
                                      description=vol_name, name=vol_name)
        fv.status = 'error'
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)

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
            "Property error: Resources.DataVolume.Properties.Size: "
            "0 is out of range (min: 1, max: None)", six.text_type(error))

    def test_volume_attachment_updates_not_supported(self):
        self.m.StubOutWithMock(nova.NovaClientPlugin, 'get_server')
        nova.NovaClientPlugin.get_server(mox.IgnoreArg()).AndReturn(
            mox.MockAnything())
        fv = vt_base.FakeVolume('creating')
        fva = vt_base.FakeVolume('attaching')
        stack_name = 'test_volume_attach_updnotsup_stack'

        self._mock_create_volume(fv, stack_name)
        self._mock_create_server_volume_script(fva)
        self.stub_VolumeConstraint_validate()

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        props = copy.deepcopy(rsrc.properties.data)
        props['InstanceId'] = 'some_other_instance_id'
        props['VolumeId'] = 'some_other_volume_id'
        props['Device'] = '/dev/vdz'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertIn('NotSupported: resources.MountPoint: '
                      'Update to properties Device, InstanceId, '
                      'VolumeId of MountPoint (AWS::EC2::VolumeAttachment)',
                      six.text_type(ex))
        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()
