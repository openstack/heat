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
from heat.tests.openstack.cinder import test_volume_utils as vt_base
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


class VolumeTest(vt_base.VolumeTestCase):

    def setUp(self):
        super(VolumeTest, self).setUp()
        self.t = template_format.parse(volume_template)
        self.use_cinder = False

    def _mock_create_volume(self, fv, stack_name, final_status='available',
                            mock_attachment=None):
        self.vol_name = utils.PhysName(stack_name, 'DataVolume')
        self.stack_name = stack_name
        self.cinder_fc.volumes.create.return_value = vt_base.FakeVolume(fv)
        fv_ready = vt_base.FakeVolume(final_status, id=fv.id)
        if mock_attachment is not None:
            results = [fv, fv_ready, mock_attachment]
        else:
            results = [fv, fv_ready, vt_base.FakeVolume('in-use')]
        self.cinder_fc.volumes.get.side_effect = results
        return fv_ready

    def test_volume(self):
        stack_name = 'test_volume_create_stack'

        # create script
        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name)
        # delete script
        self._mock_delete_volume(fv)

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        # delete script
        self._mock_delete_volume(fv)
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(rsrc.destroy))
        self.assertIn("Volume in use", six.text_type(ex))
        self.cinder_fc.volumes.get.side_effect = [
            vt_base.FakeVolume('available'), cinder_exp.NotFound('Not found')]

        scheduler.TaskRunner(rsrc.destroy)()

    def test_volume_default_az(self):
        fv = vt_base.FakeVolume('creating')
        stack_name = 'test_volume_defaultaz_stack'

        # create script
        self.patchobject(instance.Instance, 'handle_create')
        self.patchobject(instance.Instance, 'check_create_complete',
                         return_value=True)
        self.patchobject(instance.Instance, '_resolve_attribute',
                         return_value=None)
        self.patchobject(aws_vol.VolumeAttachment, 'handle_create')
        self.patchobject(aws_vol.VolumeAttachment,
                         'check_create_complete',
                         return_value=True)

        cinder.CinderClientPlugin._create.return_value = self.cinder_fc
        self.stub_ImageConstraint_validate()
        self.stub_ServerConstraint_validate()
        self.stub_VolumeConstraint_validate()
        vol_name = utils.PhysName(stack_name, 'DataVolume')
        self.cinder_fc.volumes.create.return_value = fv
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get.side_effect = [
            fv, fv_ready, cinder_exp.NotFound('Not found')]

        # delete script
        cookie = object()
        self.patchobject(instance.Instance, 'handle_delete')
        self.patchobject(aws_vol.VolumeAttachment, 'handle_delete',
                         return_value=cookie)
        self.patchobject(aws_vol.VolumeAttachment, 'check_delete_complete',
                         return_value=True)

        stack = utils.parse_stack(self.t, stack_name=stack_name)
        stack._update_all_resource_data(True, False)

        rsrc = stack['DataVolume']
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(stack.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        scheduler.TaskRunner(stack.delete)()

        instance.Instance._resolve_attribute.assert_called_with(
            'AvailabilityZone')
        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, availability_zone=None,
            description=vol_name,
            name=vol_name,
            metadata={u'Usage': u'Wiki Data Volume'})
        self.cinder_fc.volumes.get.assert_called_with('vol-123')
        aws_vol.VolumeAttachment.check_delete_complete.assert_called_once_with(
            cookie)

    def test_volume_create_error(self):
        fv = vt_base.FakeVolume('creating')
        stack_name = 'test_volume_create_error_stack'
        cfg.CONF.set_override('action_retry_limit', 0)

        self._mock_create_volume(fv, stack_name, final_status='error')

        stack = utils.parse_stack(self.t, stack_name=stack_name)
        ex = self.assertRaises(exception.ResourceFailure,
                               self.create_volume, self.t, stack, 'DataVolume')
        self.assertIn('Went to status error due to "Unknown"',
                      six.text_type(ex))

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

    def test_volume_attachment_error(self):
        stack_name = 'test_volume_attach_error_stack'

        mock_attachment = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'), final_status='error')
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name,
                                 mock_attachment=mock_attachment
                                 )
        self.stub_VolumeConstraint_validate()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        ex = self.assertRaises(exception.ResourceFailure,
                               self.create_attachment,
                               self.t, stack, 'MountPoint')
        self.assertIn("Volume attachment failed - Unknown status error",
                      six.text_type(ex))
        self.validate_mock_create_server_volume_script()

    def test_volume_attachment(self):
        stack_name = 'test_volume_attach_stack'

        fva = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name, mock_attachment=fva)
        self.stub_VolumeConstraint_validate()
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        # delete script
        fva = vt_base.FakeVolume('in-use')
        self.cinder_fc.volumes.get.side_effect = [
            fva, vt_base.FakeVolume('detaching', id=fva.id),
            vt_base.FakeVolume('available', id=fva.id)
        ]
        self.fc.volumes.delete_server_volume.return_value = None
        self.fc.volumes.get_server_volume.side_effect = [
            fva, fva, fakes_nova.fake_exception()]

        scheduler.TaskRunner(rsrc.delete)()
        self.fc.volumes.get_server_volume.assert_called_with(u'WikiDatabase',
                                                             'vol-123')
        self.fc.volumes.delete_server_volume.assert_called_with(
            'WikiDatabase', 'vol-123')
        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.validate_mock_create_server_volume_script()

    def test_volume_detachment_err(self):
        stack_name = 'test_volume_detach_err_stack'

        fva = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name, mock_attachment=fva)
        self.stub_VolumeConstraint_validate()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        # delete script
        fva = vt_base.FakeVolume('in-use')
        self.fc.volumes.get_server_volume.side_effect = [
            fva, fva, fakes_nova.fake_exception()]
        self.cinder_fc.volumes.get.side_effect = [
            fva, vt_base.FakeVolume('available', id=fva.id)]

        exc = fakes_nova.fake_exception(400)
        self.fc.volumes.delete_server_volume.side_effect = exc

        scheduler.TaskRunner(rsrc.delete)()
        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.fc.volumes.delete_server_volume.assert_called_once_with(
            'WikiDatabase', 'vol-123')
        self.validate_mock_create_server_volume_script()

    def test_volume_detach_non_exist(self):
        fv = vt_base.FakeVolume('creating')
        fva = vt_base.FakeVolume('in-use')
        stack_name = 'test_volume_detach_nonexist_stack'

        mock_attachment = self._mock_create_server_volume_script(fva)
        self._mock_create_volume(fv, stack_name,
                                 mock_attachment=mock_attachment)
        self.stub_VolumeConstraint_validate()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        # delete script
        self.fc.volumes.delete_server_volume.return_value = None
        self.cinder_fc.volumes.get.side_effect = cinder_exp.NotFound(
            'Not found')

        exc = fakes_nova.fake_exception()
        self.fc.volumes.get_server_volume.side_effect = exc

        scheduler.TaskRunner(rsrc.delete)()

        self.fc.volumes.delete_server_volume.assert_called_once_with(
            u'WikiDatabase', 'vol-123')
        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.validate_mock_create_server_volume_script()

    def test_volume_detach_deleting_volume(self):
        fv = vt_base.FakeVolume('creating')
        fva = vt_base.FakeVolume('deleting')
        stack_name = 'test_volume_detach_deleting_volume_stack'

        mock_attachment = self._mock_create_server_volume_script(fva)
        self._mock_create_volume(fv, stack_name,
                                 mock_attachment=mock_attachment)
        self.stub_VolumeConstraint_validate()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        # delete script
        self.cinder_fc.volumes.get.side_effect = [fva]
        exc = fakes_nova.fake_exception()
        self.fc.volumes.get_server_volume.side_effect = exc

        scheduler.TaskRunner(rsrc.delete)()

        self.fc.volumes.delete_server_volume.assert_called_once_with(
            u'WikiDatabase', 'vol-123')
        self.validate_mock_create_server_volume_script()

    def test_volume_detach_with_latency(self):
        stack_name = 'test_volume_detach_latency_stack'

        fva = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name, mock_attachment=fva)
        self.stub_VolumeConstraint_validate()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        # delete script
        self.fc.volumes.get_server_volume.side_effect = [
            fva, fva, fakes_nova.fake_exception()]
        self.cinder_fc.volumes.get.side_effect = [
            fva, vt_base.FakeVolume('in-use', id=fva.id),
            vt_base.FakeVolume('detaching', id=fva.id),
            vt_base.FakeVolume('available', id=fva.id)]

        scheduler.TaskRunner(rsrc.delete)()

        self.fc.volumes.delete_server_volume.assert_called_once_with(
            u'WikiDatabase', 'vol-123')
        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.validate_mock_create_server_volume_script()

    def test_volume_detach_with_error(self):
        stack_name = 'test_volume_detach_werr_stack'

        fva = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name, mock_attachment=fva)
        self.stub_VolumeConstraint_validate()
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume')
        rsrc = self.create_attachment(self.t, stack, 'MountPoint')

        # delete script
        self.fc.volumes.delete_server_volume.return_value = None
        fva = vt_base.FakeVolume('in-use')
        self.cinder_fc.volumes.get.side_effect = [
            vt_base.FakeVolume('error', id=fva.id)]

        detach_task = scheduler.TaskRunner(rsrc.delete)
        ex = self.assertRaises(exception.ResourceFailure, detach_task)
        self.assertIn('Volume detachment failed - Unknown status error',
                      six.text_type(ex))

        self.fc.volumes.delete_server_volume.assert_called_once_with(
            u'WikiDatabase', 'vol-123')
        self.validate_mock_create_server_volume_script()

    def test_volume_delete(self):
        stack_name = 'test_volume_delete_stack'
        fv = vt_base.FakeVolume('creating')

        self._mock_create_volume(fv, stack_name)

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Delete'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        m_hd = mock.Mock(return_value=None)
        rsrc.handle_delete = m_hd
        m_cdc = mock.Mock(return_value=True)
        rsrc.check_delete_complete = m_cdc
        scheduler.TaskRunner(rsrc.destroy)()
        m_cdc.assert_called_with(None)
        m_hd.assert_called_once_with()

    def test_volume_deleting_delete(self):
        vt_base.FakeVolume('creating')
        stack_name = 'test_volume_deleting_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name)

        stack = utils.parse_stack(self.t, stack_name=stack_name)
        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        self.assertEqual(2, self.cinder_fc.volumes.get.call_count)
        # delete script
        self.cinder_fc.volumes.get.side_effect = [
            vt_base.FakeVolume('deleting'),
            vt_base.FakeVolume('deleting'),
            cinder_exp.NotFound('NotFound')]

        scheduler.TaskRunner(rsrc.destroy)()
        self.assertEqual(5, self.cinder_fc.volumes.get.call_count)

    def test_volume_delete_error(self):
        fv = vt_base.FakeVolume('creating')
        stack_name = 'test_volume_deleting_stack'

        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name)

        stack = utils.parse_stack(self.t, stack_name=stack_name)
        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        self.assertEqual(2, self.cinder_fc.volumes.get.call_count)
        self.cinder_fc.volumes.get.side_effect = [
            fv,
            vt_base.FakeVolume('deleting'),
            vt_base.FakeVolume('error_deleting')]
        self.cinder_fc.volumes.delete.return_value = True

        deleter = scheduler.TaskRunner(rsrc.destroy)
        self.assertRaisesRegex(exception.ResourceFailure,
                               ".*ResourceInError.*error_deleting.*delete",
                               deleter)

        self.cinder_fc.volumes.delete.assert_called_once_with(fv.id)
        self.assertEqual(5, self.cinder_fc.volumes.get.call_count)

    def test_volume_update_not_supported(self):
        stack_name = 'test_volume_updnotsup_stack'
        fv = vt_base.FakeVolume('creating')

        self._mock_create_volume(fv, stack_name)

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
        res.state_set(res.CREATE, res.COMPLETE)
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
        res.state_set(res.CREATE, res.COMPLETE)
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
        res.state_set(res.CREATE, res.COMPLETE)
        cinder = mock.Mock()
        cinder.volumes.get.side_effect = Exception('boom')
        self.patchobject(res, 'client', return_value=cinder)

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.check))
        self.assertEqual((res.CHECK, res.FAILED), res.state)
        self.assertIn('boom', res.status_reason)

    def test_snapshot(self):
        stack_name = 'test_volume_snapshot_stack'
        fv = vt_base.FakeVolume('creating')
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        fv = self._mock_create_volume(fv,
                                      stack_name, mock_attachment=fv_ready)

        # snapshot script
        fb = vt_base.FakeBackup('available')
        self.m_backups.create.return_value = fb
        self.m_backups.get.return_value = fb
        self._mock_delete_volume(fv)

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        self.cinder_fc.volumes.get.side_effect = [
            fv,
            vt_base.FakeVolume('available'),
            cinder_exp.NotFound('Not found')
        ]
        scheduler.TaskRunner(rsrc.destroy)()

        self.m_backups.create.assert_called_once_with(fv.id)
        self.m_backups.get.assert_called_once_with(fb.id)

    def test_snapshot_error(self):
        stack_name = 'test_volume_snapshot_err_stack'
        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name)

        # snapshot script
        fb = vt_base.FakeBackup('error')
        self.m_backups.create.return_value = fb
        self.m_backups.get.return_value = fb

        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'DataVolume')

        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(rsrc.destroy))
        self.assertIn('Unknown status error', six.text_type(ex))

        self.m_backups.create.assert_called_once_with(fv.id)
        self.m_backups.get.assert_called_once_with(fb.id)

    def test_snapshot_no_volume(self):
        """Test that backup does not start for failed resource."""
        stack_name = 'test_volume_snapshot_novol_stack'
        cfg.CONF.set_override('action_retry_limit', 0)
        fva = vt_base.FakeVolume('error')
        fv = self._mock_create_volume(vt_base.FakeVolume('creating'),
                                      stack_name,
                                      final_status='error',
                                      mock_attachment=fva)

        self._mock_delete_volume(fv)

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

        self.cinder_fc.volumes.get.side_effect = [
            fva,
            cinder_exp.NotFound('Not found')
        ]

        scheduler.TaskRunner(rsrc.destroy)()

    def test_create_from_snapshot(self):
        stack_name = 'test_volume_create_from_snapshot_stack'
        fv = vt_base.FakeVolume('restoring-backup')
        fvbr = vt_base.FakeBackupRestore('vol-123')

        # create script
        cinder.CinderClientPlugin._create.return_value = self.cinder_fc
        self.m_restore.return_value = fvbr
        fv2 = vt_base.FakeVolume('available')
        self.cinder_fc.volumes.get.side_effect = [fv, fv2]
        vol_name = utils.PhysName(stack_name, 'DataVolume')

        self.t['Resources']['DataVolume']['Properties'][
            'SnapshotId'] = 'backup-123'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'DataVolume', no_create=True)

        cinder.CinderClientPlugin._create.assert_called_once_with()
        self.m_restore.assert_called_once_with('backup-123')
        self.cinder_fc.volumes.get.assert_called_with('vol-123')
        self.cinder_fc.volumes.update.assert_called_once_with(
            'vol-123', description=vol_name, name=vol_name)

    def test_create_from_snapshot_error(self):
        stack_name = 'test_volume_create_from_snap_err_stack'
        cfg.CONF.set_override('action_retry_limit', 0)
        fv = vt_base.FakeVolume('restoring-backup')
        fv2 = vt_base.FakeVolume('error')
        fvbr = vt_base.FakeBackupRestore('vol-123')

        # create script
        cinder.CinderClientPlugin._create.return_value = self.cinder_fc
        self.m_restore.return_value = fvbr
        self.cinder_fc.volumes.get.side_effect = [fv, fv2]
        vol_name = utils.PhysName(stack_name, 'DataVolume')

        self.t['Resources']['DataVolume']['Properties'][
            'SnapshotId'] = 'backup-123'
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        ex = self.assertRaises(exception.ResourceFailure,
                               self.create_volume, self.t, stack, 'DataVolume')
        self.assertIn('Went to status error due to "Unknown"',
                      six.text_type(ex))

        cinder.CinderClientPlugin._create.assert_called_once_with()
        self.m_restore.assert_called_once_with('backup-123')
        self.cinder_fc.volumes.update.assert_called_once_with(
            fv.id, description=vol_name, name=vol_name)

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
        self.patchobject(nova.NovaClientPlugin, 'get_server')
        fv = vt_base.FakeVolume('creating')
        fva = vt_base.FakeVolume('attaching')
        stack_name = 'test_volume_attach_updnotsup_stack'

        mock_create_server_volume = self._mock_create_server_volume_script(fva)
        self._mock_create_volume(fv, stack_name,
                                 mock_attachment=mock_create_server_volume)
        self.stub_VolumeConstraint_validate()

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
        self.validate_mock_create_server_volume_script()

    def test_validate_deletion_policy(self):
        cfg.CONF.set_override('backups_enabled', False, group='volumes')
        stack_name = 'test_volume_validate_deletion_policy'
        self.t['Resources']['DataVolume']['DeletionPolicy'] = 'Snapshot'
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        rsrc = self.get_volume(self.t, stack, 'DataVolume')
        self.assertRaisesRegex(
            exception.StackValidationFailed,
            'volume backup service is not enabled',
            rsrc.validate)
