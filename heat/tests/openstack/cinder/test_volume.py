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

import collections
import copy
import json

from cinderclient import exceptions as cinder_exp
import mock
from oslo_config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import cinder
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine.resources.openstack.cinder import volume as c_vol
from heat.engine.resources import scheduler_hints as sh
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.objects import resource_data as resource_data_object
from heat.tests.openstack.cinder import test_volume_utils as vt_base
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils

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
  volume3:
    type: OS::Cinder::Volume
    properties:
      availability_zone: nova
      size: 1
      name: test_name
      scheduler_hints: {"hint1": "good_advice"}
  volume4:
    type: OS::Cinder::Volume
    properties:
      availability_zone: nova
      size: 1
      name: test_name
      multiattach: True
  attachment:
    type: OS::Cinder::VolumeAttachment
    properties:
      instance_uuid: WikiDatabase
      volume_id: { get_resource: volume }
      mountpoint: /dev/vdc
'''

single_cinder_volume_template = '''
heat_template_version: 2013-05-23
description: Cinder volume
resources:
  volume:
    type: OS::Cinder::Volume
    properties:
      size: 1
      name: test_name
      description: test_description
'''


class CinderVolumeTest(vt_base.VolumeTestCase):

    def setUp(self):
        super(CinderVolumeTest, self).setUp()
        self.t = template_format.parse(cinder_volume_template)
        self.use_cinder = True

    def create_volume(self, t, stack, resource_name):
        return super(CinderVolumeTest, self).create_volume(
            t, stack, resource_name, validate=False)

    def _mock_create_volume(self, fv, stack_name, size=1,
                            final_status='available', extra_get_mocks=[],
                            extra_create_mocks=[]):
        result = [fv]
        for m in extra_create_mocks:
            result.append(m)
        self.cinder_fc.volumes.create.side_effect = result
        fv_ready = vt_base.FakeVolume(final_status, id=fv.id)
        result = [fv, fv_ready]
        for m in extra_get_mocks:
            result.append(m)
        self.cinder_fc.volumes.get.side_effect = result
        return fv_ready

    def test_cinder_volume_size_constraint(self):
        self.t['resources']['volume']['properties']['size'] = 0
        stack = utils.parse_stack(self.t)
        error = self.assertRaises(exception.StackValidationFailed,
                                  self.create_volume,
                                  self.t, stack, 'volume')
        self.assertEqual(
            "Property error: resources.volume.properties.size: "
            "0 is out of range (min: 1, max: None)", six.text_type(error))

    def test_cinder_create(self):
        fv = vt_base.FakeVolume('creating')
        self.stack_name = 'test_cvolume_stack'

        self.stub_SnapshotConstraint_validate()
        self.stub_VolumeConstraint_validate()
        self.stub_VolumeTypeConstraint_validate()
        self.cinder_fc.volumes.create.return_value = fv
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get.side_effect = [fv, fv_ready]

        self.t['resources']['volume']['properties'].update({
            'volume_type': 'lvm',
        })
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        self.create_volume(self.t, stack, 'volume')

        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, availability_zone='nova',
            description='test_description',
            name='test_name',
            metadata={'key': 'value'},
            volume_type='lvm',
            multiattach=False)
        self.assertEqual(2, self.cinder_fc.volumes.get.call_count)

    def test_cinder_create_from_image(self):
        fv = vt_base.FakeVolume('downloading')
        self.stack_name = 'test_cvolume_create_from_img_stack'
        image_id = '46988116-6703-4623-9dbc-2bc6d284021b'
        self.patchobject(glance.GlanceClientPlugin,
                         'find_image_by_name_or_id', return_value=image_id)

        self.cinder_fc.volumes.create.return_value = fv
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get.side_effect = [fv, fv_ready]

        self.t['resources']['volume']['properties'] = {
            'size': '1',
            'name': 'ImageVolume',
            'description': 'ImageVolumeDescription',
            'availability_zone': 'nova',
            'image': image_id,
        }
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        self.create_volume(self.t, stack, 'volume')

        glance.GlanceClientPlugin.find_image_by_name_or_id.assert_called_with(
            image_id)
        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, availability_zone='nova',
            description='ImageVolumeDescription',
            name='ImageVolume',
            imageRef=image_id,
            multiattach=False,
            metadata={})
        self.assertEqual(2, self.cinder_fc.volumes.get.call_count)

    def test_cinder_create_with_read_only(self):
        fv = vt_base.FakeVolume('with_read_only_access_mode')
        self.stack_name = 'test_create_with_read_only'

        self.cinder_fc.volumes.create.return_value = fv

        update_readonly_mock = self.patchobject(self.cinder_fc.volumes,
                                                'update_readonly_flag',
                                                return_value=None)
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get.return_value = fv_ready

        self.t['resources']['volume']['properties'] = {
            'size': '1',
            'name': 'ImageVolume',
            'description': 'ImageVolumeDescription',
            'availability_zone': 'nova',
            'read_only': False,
        }
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        self.create_volume(self.t, stack, 'volume')

        update_readonly_mock.assert_called_once_with(fv.id, False)

        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, availability_zone='nova',
            description='ImageVolumeDescription',
            name='ImageVolume',
            multiattach=False,
            metadata={})
        self.cinder_fc.volumes.get.assert_called_once_with(fv.id)

    def test_cinder_default(self):
        fv = vt_base.FakeVolume('creating')
        self.stack_name = 'test_cvolume_default_stack'

        vol_name = utils.PhysName(self.stack_name, 'volume')
        self.cinder_fc.volumes.create.return_value = fv
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get.side_effect = [fv, fv_ready]

        self.t['resources']['volume']['properties'] = {
            'size': '1',
            'availability_zone': 'nova',
        }
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        self.create_volume(self.t, stack, 'volume')

        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, availability_zone='nova',
            description=None,
            name=vol_name,
            multiattach=False,
            metadata={}
        )
        self.assertEqual(2, self.cinder_fc.volumes.get.call_count)

    def test_cinder_fn_getatt(self):
        self.stack_name = 'test_cvolume_fngetatt_stack'

        fv = vt_base.FakeVolume(
            'available', availability_zone='zone1',
            size=1, snapshot_id='snap-123', name='name',
            description='desc', volume_type='lvm',
            metadata={'key': 'value'}, source_volid=None,
            bootable=False, created_at='2013-02-25T02:40:21.000000',
            encrypted=False, attachments=[], multiattach=False)

        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name,
                                 extra_get_mocks=[fv for i in range(20)])

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
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
        self.assertEqual(u'False', rsrc.FnGetAtt('encrypted'))
        self.assertEqual(u'[]', rsrc.FnGetAtt('attachments'))
        self.assertEqual([], rsrc.FnGetAtt('attachments_list'))
        self.assertEqual('False', rsrc.FnGetAtt('multiattach'))
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'unknown')
        self.assertEqual(
            'The Referenced Attribute (volume unknown) is incorrect.',
            six.text_type(error))

        self.cinder_fc.volumes.get.assert_called_with('vol-123')

    def test_cinder_attachment(self):
        self.stack_name = 'test_cvolume_attach_stack'
        fva = vt_base.FakeVolume('in-use')

        m_v = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name,
                                 extra_get_mocks=[
                                     m_v, fva,
                                     vt_base.FakeVolume('available')])
        self.stub_VolumeConstraint_validate()

        # delete script
        self.fc.volumes.get_server_volume.side_effect = [
            fva, fva, fakes_nova.fake_exception()]

        self.fc.volumes.delete_server_volume.return_value = None

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        self.create_volume(self.t, stack, 'volume')
        rsrc = self.create_attachment(self.t, stack, 'attachment')
        scheduler.TaskRunner(rsrc.delete)()

        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.fc.volumes.delete_server_volume.assert_called_with(
            'WikiDatabase', 'vol-123')

    def test_cinder_attachment_no_mountpoint(self):
        self.stack_name = 'test_cvolume_attach_stack'

        fva = vt_base.FakeVolume('in-use')
        m_v = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name,
                                 extra_get_mocks=[
                                     m_v, fva,
                                     vt_base.FakeVolume('available')])
        self.stub_VolumeConstraint_validate()

        self.t['resources']['attachment']['properties']['mountpoint'] = ''
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        self.create_volume(self.t, stack, 'volume')
        rsrc = self.create_attachment(self.t, stack, 'attachment')

        # delete script
        self.fc.volumes.get_server_volume.side_effect = [
            fva, fva, fakes_nova.fake_exception()]
        self.fc.volumes.delete_server_volume.return_value = None

        scheduler.TaskRunner(rsrc.delete)()

        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.fc.volumes.delete_server_volume.assert_called_with(
            'WikiDatabase', 'vol-123')

    def test_cinder_volume_shrink_fails(self):
        self.stack_name = 'test_cvolume_shrink_fail_stack'

        fv = vt_base.FakeVolume('available', size=2)
        # create script
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name, size=2, extra_get_mocks=[fv])

        self.t['resources']['volume']['properties']['size'] = 2
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 1
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertEqual('NotSupported: resources.volume: '
                         'Shrinking volume is not supported.',
                         six.text_type(ex))

        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)

    def test_cinder_volume_extend_detached(self):
        self.stack_name = 'test_cvolume_extend_det_stack'
        fv = vt_base.FakeVolume('available',
                                size=1, attachments=[])

        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name,
                                 extra_get_mocks=[
                                     fv, vt_base.FakeVolume('extending'),
                                     vt_base.FakeVolume('extending'),
                                     vt_base.FakeVolume('available')])

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        self.assertIsNone(update_task())

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.cinder_fc.volumes.extend.assert_called_once_with(fv.id, 2)

    def test_cinder_volume_extend_fails_to_start(self):
        self.stack_name = 'test_cvolume_extend_fail_start_stack'

        fv = vt_base.FakeVolume('available',
                                size=1, attachments=[])
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name,
                                 extra_get_mocks=[fv])
        self.cinder_fc.volumes.extend.side_effect = cinder_exp.OverLimit(413)

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertIn('Over limit', six.text_type(ex))

        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.cinder_fc.volumes.extend.assert_called_once_with(fv.id, 2)

    def test_cinder_volume_extend_fails_to_complete(self):
        self.stack_name = 'test_cvolume_extend_fail_compl_stack'

        fv = vt_base.FakeVolume('available',
                                size=1, attachments=[])
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name,
                                 extra_get_mocks=[
                                     fv, vt_base.FakeVolume('extending'),
                                     vt_base.FakeVolume('extending'),
                                     vt_base.FakeVolume('error_extending')])

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertIn("Volume resize failed - Unknown status error_extending",
                      six.text_type(ex))

        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.cinder_fc.volumes.extend.assert_called_once_with(fv.id, 2)

    def test_cinder_volume_extend_attached(self):
        self.stack_name = 'test_cvolume_extend_att_stack'
        self._update_if_attached(self.stack_name)

    def test_cinder_volume_extend_created_from_backup_with_same_size(self):
        self.stack_name = 'test_cvolume_extend_snapsht_stack'

        fv = vt_base.FakeVolume('available', size=2)
        self.stub_VolumeBackupConstraint_validate()
        fvbr = vt_base.FakeBackupRestore('vol-123')
        self.patchobject(self.cinder_fc.restores, 'restore', return_value=fvbr)
        self.cinder_fc.volumes.get.side_effect = [
            vt_base.FakeVolume('restoring-backup'),
            vt_base.FakeVolume('available'), fv]
        vol_name = utils.PhysName(self.stack_name, 'volume')
        self.cinder_fc.volumes.update.return_value = None

        self.t['resources']['volume']['properties'] = {
            'availability_zone': 'nova',
            'backup_id': 'backup-123'
        }
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('available', fv.status)

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        self.assertIsNone(update_task())

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.cinder_fc.restores.restore.assert_called_once_with('backup-123')
        self.cinder_fc.volumes.update.assert_called_once_with(
            'vol-123', description=None, name=vol_name)
        self.assertEqual(3, self.cinder_fc.volumes.get.call_count)

    def test_cinder_volume_retype(self):
        fv = vt_base.FakeVolume('available',
                                size=1, name='my_vol',
                                description='test')
        self.stack_name = 'test_cvolume_retype'
        new_vol_type = 'new_type'
        self.patchobject(cinder.CinderClientPlugin, '_create',
                         return_value=self.cinder_fc)
        self.cinder_fc.volumes.create.return_value = fv
        self.cinder_fc.volumes.get.return_value = fv
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        rsrc = self.create_volume(self.t, stack, 'volume2')

        props = copy.deepcopy(rsrc.properties.data)
        props['volume_type'] = new_vol_type
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        self.patchobject(cinder.CinderClientPlugin, 'get_volume_type',
                         return_value=new_vol_type)
        self.patchobject(self.cinder_fc.volumes, 'retype')
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(1, self.cinder_fc.volumes.retype.call_count)

    def test_cinder_volume_update_name_and_metadata(self):
        # update the name, description and metadata
        fv = vt_base.FakeVolume('creating',
                                size=1, name='my_vol',
                                description='test')
        self.stack_name = 'test_cvolume_updname_stack'
        update_name = 'update_name'
        meta = {'Key': 'New Value'}
        update_description = 'update_description'
        kwargs = {
            'name': update_name,
            'description': update_description
        }

        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self._mock_create_volume(fv, self.stack_name,
                                 extra_get_mocks=[fv_ready])
        self.cinder_fc.volumes.update.return_value = None
        self.cinder_fc.volumes.update_all_metadata.return_value = None

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['name'] = update_name
        props['description'] = update_description
        props['metadata'] = meta
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.cinder_fc.volumes.update.assert_called_once_with(fv_ready,
                                                              **kwargs)
        self.cinder_fc.volumes.update_all_metadata.assert_called_once_with(
            fv_ready, meta)

    def test_cinder_volume_update_read_only(self):
        # update read only access mode
        fv = vt_base.FakeVolume('update_read_only_access_mode')
        self.stack_name = 'test_update_read_only'

        self.cinder_fc.volumes.create.return_value = fv

        update_readonly_mock = self.patchobject(self.cinder_fc.volumes,
                                                'update_readonly_flag',
                                                return_value=None)
        fv_ready = vt_base.FakeVolume('available', id=fv.id, attachments=[])
        self.cinder_fc.volumes.get.return_value = fv_ready

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['read_only'] = True
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        update_readonly_mock.assert_called_once_with(fv.id, True)
        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, availability_zone='nova',
            description='test_description',
            name='test_name',
            multiattach=False,
            metadata={u'key': u'value'})
        self.cinder_fc.volumes.get.assert_called_with(fv.id)

    def test_cinder_volume_update_no_need_replace(self):
        # update read only access mode
        fv = vt_base.FakeVolume('creating')
        self.stack_name = 'test_update_no_need_replace'

        self.cinder_fc.volumes.create.return_value = fv

        vol_name = utils.PhysName(self.stack_name, 'volume2')

        fv_ready = vt_base.FakeVolume('available', id=fv.id, size=2,
                                      attachments=[])
        self.cinder_fc.volumes.get.return_value = fv_ready

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume2')

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 1
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.assertIn("NotSupported: resources.volume2: Shrinking volume is "
                      "not supported", six.text_type(ex))

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 3
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.cinder_fc.volumes.create.assert_called_once_with(
            size=2, availability_zone='nova',
            description=None,
            name=vol_name,
            multiattach=False,
            metadata={}
        )
        self.cinder_fc.volumes.extend.assert_called_once_with(fv.id, 3)
        self.cinder_fc.volumes.get.assert_called_with(fv.id)

    def _update_if_attached(self, stack_name, update_type='resize'):
        # create script
        self.stub_VolumeConstraint_validate()
        fv3 = vt_base.FakeVolume('attaching')
        fv3_ready = vt_base.FakeVolume('in-use', id=fv3.id)
        fv1 = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'),
            extra_create_server_volume_mocks=[fv3])
        attachments = [{'id': 'vol-123',
                        'device': '/dev/vdc',
                        'server_id': u'WikiDatabase'}]
        fv2 = vt_base.FakeVolume('in-use',
                                 attachments=attachments, size=1)
        fvd = vt_base.FakeVolume('in-use')
        resize_m_get = [
            vt_base.FakeVolume('extending'),
            vt_base.FakeVolume('extending'),
            vt_base.FakeVolume('available')
        ]
        extra_get_mocks = [fv1, fv2, fvd, vt_base.FakeVolume('available')]
        if update_type == 'resize':
            extra_get_mocks += resize_m_get
        extra_get_mocks.append(fv3_ready)
        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name,
                                 extra_get_mocks=extra_get_mocks
                                 )
        # detach script
        self.fc.volumes.get_server_volume.side_effect = [
            fvd, fvd, fakes_nova.fake_exception()]

        if update_type == 'access_mode':
            # update access mode script
            update_readonly_mock = self.patchobject(self.cinder_fc.volumes,
                                                    'update_readonly_flag',
                                                    return_value=None)

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')
        self.create_attachment(self.t, stack, 'attachment')

        props = copy.deepcopy(rsrc.properties.data)
        if update_type == 'access_mode':
            props['read_only'] = True
        if update_type == 'resize':
            props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        self.assertIsNone(update_task())

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        if update_type == 'access_mode':
            update_readonly_mock.assert_called_once_with(fvd.id, True)

        if update_type == 'resize':
            self.cinder_fc.volumes.extend.assert_called_once_with(fvd.id, 2)
        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.fc.volumes.delete_server_volume.assert_called_with(
            'WikiDatabase', 'vol-123')

    def test_cinder_volume_update_read_only_attached(self):
        self.stack_name = 'test_cvolume_update_read_only_att_stack'
        self._update_if_attached(self.stack_name, update_type='access_mode')

    def test_cinder_snapshot(self):
        self.stack_name = 'test_cvolume_snpsht_stack'

        self.cinder_fc.volumes.create.return_value = vt_base.FakeVolume(
            'creating')
        fv = vt_base.FakeVolume('available')
        self.cinder_fc.volumes.get.return_value = fv

        fb = vt_base.FakeBackup('creating')
        self.patchobject(self.cinder_fc.backups, 'create', return_value=fb)
        self.patchobject(self.cinder_fc.backups, 'get',
                         return_value=vt_base.FakeBackup('available'))

        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=self.stack_name)

        rsrc = stack['volume']
        self.patchobject(rsrc, '_store_config_default_properties')
        scheduler.TaskRunner(rsrc.create)()

        scheduler.TaskRunner(rsrc.snapshot)()

        self.assertEqual((rsrc.SNAPSHOT, rsrc.COMPLETE), rsrc.state)

        self.assertEqual({'backup_id': 'backup-123'},
                         resource_data_object.ResourceData.get_all(rsrc))
        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, availability_zone=None,
            description='test_description',
            name='test_name',
            multiattach=False,
            metadata={}
        )
        self.cinder_fc.backups.create.assert_called_once_with(fv.id,
                                                              force=True)
        self.cinder_fc.backups.get.assert_called_once_with(fb.id)
        self.cinder_fc.volumes.get.assert_called_with(fv.id)

    def test_cinder_snapshot_error(self):
        self.stack_name = 'test_cvolume_snpsht_err_stack'

        self.cinder_fc.volumes.create.return_value = vt_base.FakeVolume(
            'creating')
        fv = vt_base.FakeVolume('available')
        self.cinder_fc.volumes.get.return_value = fv

        fb = vt_base.FakeBackup('creating')
        self.patchobject(self.cinder_fc.backups, 'create',
                         return_value=fb)
        fail_reason = 'Could not determine which Swift endpoint to use'
        self.patchobject(self.cinder_fc.backups, 'get',
                         return_value=vt_base.FakeBackup(
                             'error', fail_reason=fail_reason))

        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=self.stack_name)

        rsrc = stack['volume']
        self.patchobject(rsrc, '_store_config_default_properties')
        scheduler.TaskRunner(rsrc.create)()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.snapshot))

        self.assertEqual((rsrc.SNAPSHOT, rsrc.FAILED), rsrc.state)
        self.assertIn(fail_reason, rsrc.status_reason)

        self.assertEqual({u'backup_id': u'backup-123'},
                         resource_data_object.ResourceData.get_all(rsrc))
        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, availability_zone=None,
            description='test_description',
            name='test_name',
            multiattach=False,
            metadata={}
        )
        self.cinder_fc.backups.create.assert_called_once_with(
            fv.id, force=True)
        self.cinder_fc.volumes.get.assert_called_once_with(fv.id)

    def test_cinder_volume_attachment_update_device(self):
        self.stack_name = 'test_cvolume_attach_udev_stack'

        m_v = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        # attach script
        m_v2 = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'), update=True)

        fva = vt_base.FakeVolume('in-use')
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name,
                                 extra_get_mocks=[
                                     m_v, fva,
                                     vt_base.FakeVolume('available'),
                                     m_v2])
        self.stub_VolumeConstraint_validate()

        # delete script
        self.fc.volumes.get_server_volume.side_effect = [
            fva, fva, fakes_nova.fake_exception()]
        self.fc.volumes.delete_server_volume.return_value = None

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        self.create_volume(self.t, stack, 'volume')
        rsrc = self.create_attachment(self.t, stack, 'attachment')

        props = copy.deepcopy(rsrc.properties.data)
        props['mountpoint'] = ''
        props['volume_id'] = 'vol-123'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.fc.volumes.delete_server_volume.assert_called_with(
            'WikiDatabase', 'vol-123')

    def test_cinder_volume_attachment_update_volume(self):

        self.stack_name = 'test_cvolume_attach_uvol_stack'
        fv2 = vt_base.FakeVolume('creating', id='vol-456')
        vol2_name = utils.PhysName(self.stack_name, 'volume2')
        fv3 = vt_base.FakeVolume('available', id=fv2.id)
        fv4 = vt_base.FakeVolume('attaching')
        fv_4ready = vt_base.FakeVolume('in-use', id=fv4.id)
        fv5 = vt_base.FakeVolume('in-use')
        fv6 = vt_base.FakeVolume('available')
        fv7 = vt_base.FakeVolume('attaching', id='vol-456')
        fv7ready = vt_base.FakeVolume('in-use', id=fv7.id)

        self.stub_VolumeConstraint_validate()
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name,
                                 extra_get_mocks=[fv2, fv3, fv_4ready, fv5,
                                                  fv6, fv7ready,
                                                  ],
                                 extra_create_mocks=[fv2])
        self.fc.volumes.create_server_volume.side_effect = [fv4, fv7]
        self.fc.volumes.get_server_volume.side_effect = [
            fv5, fv5, fakes_nova.fake_exception()]
        self.fc.volumes.delete_server_volume.return_value = None

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        self.create_volume(self.t, stack, 'volume')
        self.create_volume(self.t, stack, 'volume2')

        self.fc.volumes.create_server_volume.return_value = fv7

        rsrc = self.create_attachment(self.t, stack, 'attachment')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        props = copy.deepcopy(rsrc.properties.data)
        props['volume_id'] = 'vol-456'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(fv7.id, rsrc.resource_id)

        self.cinder_fc.volumes.create.assert_called_with(
            size=2, availability_zone='nova',
            description=None,
            name=vol2_name,
            multiattach=False,
            metadata={}
        )
        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.fc.volumes.delete_server_volume.assert_called_with(
            'WikiDatabase', 'vol-123')

    def test_cinder_volume_attachment_update_server(self):
        self.stack_name = 'test_cvolume_attach_usrv_stack'

        fv1 = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'))
        fva = vt_base.FakeVolume('in-use')
        fv2 = self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'), update=True)
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 self.stack_name,
                                 extra_get_mocks=[
                                     fv1, fva,
                                     vt_base.FakeVolume('available'), fv2])
        self.stub_VolumeConstraint_validate()

        # delete script
        self.fc.volumes.get_server_volume.side_effect = [
            fva, fva, fakes_nova.fake_exception()]
        self.fc.volumes.delete_server_volume.return_value = None

        stack = utils.parse_stack(self.t, stack_name=self.stack_name)

        self.create_volume(self.t, stack, 'volume')

        rsrc = self.create_attachment(self.t, stack, 'attachment')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        props = copy.deepcopy(rsrc.properties.data)
        props['instance_uuid'] = 'AnotherServer'
        props['volume_id'] = 'vol-123'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.fc.volumes.get_server_volume.assert_called_with(
            u'WikiDatabase', 'vol-123')
        self.fc.volumes.delete_server_volume.assert_called_with(
            'WikiDatabase', 'vol-123')

    def test_delete_attachment_has_not_been_created(self):
        self.stack_name = 'test_delete_attachment_has_not_been_created'
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        resource_defn = stack.t.resource_definitions(stack)

        att_rsrc = c_vol.CinderVolumeAttachment(
            'test_attachment',
            resource_defn['attachment'],
            stack)
        att_rsrc.state_set(att_rsrc.UPDATE, att_rsrc.COMPLETE)
        self.assertIsNone(att_rsrc.resource_id)
        # assert even not to create the novaclient instance
        nc = self.patchobject(nova.NovaClientPlugin, '_create')

        scheduler.TaskRunner(att_rsrc.delete)()
        self.assertEqual(0, nc.call_count)
        self.assertEqual((att_rsrc.DELETE, att_rsrc.COMPLETE), att_rsrc.state)

    def test_cinder_create_with_scheduler_hints(self):
        fv = vt_base.FakeVolume('creating')

        self.cinder_fc.volumes.create.return_value = fv
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get.side_effect = [fv, fv_ready]

        self.stack_name = 'test_cvolume_scheduler_hints_stack'
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        self.patchobject(stack['volume3'], '_store_config_default_properties')
        self.create_volume(self.t, stack, 'volume3')

        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, name='test_name', description=None,
            availability_zone='nova',
            scheduler_hints={'hint1': 'good_advice'},
            multiattach=False,
            metadata={}
        )
        self.assertEqual(2, self.cinder_fc.volumes.get.call_count)

    def test_cinder_create_with_multiattach(self):
        fv = vt_base.FakeVolume('creating')

        self.cinder_fc.volumes.create.return_value = fv
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get.side_effect = [fv, fv_ready]

        self.stack_name = 'test_cvolume_multiattach_stack'
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        self.create_volume(self.t, stack, 'volume4')

        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, name='test_name', description=None,
            availability_zone='nova',
            multiattach=True,
            metadata={})
        self.assertEqual(2, self.cinder_fc.volumes.get.call_count)

    def test_cinder_create_with_stack_scheduler_hints(self):
        fv = vt_base.FakeVolume('creating')
        sh.cfg.CONF.set_override('stack_scheduler_hints', True)

        self.stack_name = 'test_cvolume_stack_scheduler_hints_stack'
        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=self.stack_name)

        rsrc = stack['volume']

        # rsrc.uuid is only available once the resource has been added.
        stack.add_resource(rsrc)
        self.assertIsNotNone(rsrc.uuid)

        shm = sh.SchedulerHintsMixin
        self.cinder_fc.volumes.create.return_value = fv
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get.side_effect = [fv, fv_ready]

        self.patchobject(rsrc, '_store_config_default_properties')
        scheduler.TaskRunner(rsrc.create)()
        # this makes sure the auto increment worked on volume creation
        self.assertGreater(rsrc.id, 0)

        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, name='test_name', description='test_description',
            availability_zone=None,
            metadata={},
            multiattach=False,
            scheduler_hints={shm.HEAT_ROOT_STACK_ID: stack.root_stack_id(),
                             shm.HEAT_STACK_ID: stack.id,
                             shm.HEAT_STACK_NAME: stack.name,
                             shm.HEAT_PATH_IN_STACK: [stack.name],
                             shm.HEAT_RESOURCE_NAME: rsrc.name,
                             shm.HEAT_RESOURCE_UUID: rsrc.uuid})
        self.assertEqual(2, self.cinder_fc.volumes.get.call_count)

    def _test_cinder_create_invalid_property_combinations(
            self, stack_name, combinations, err_msg, exc):
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        vp = stack.t['Resources']['volume2']['Properties']
        vp.pop('size')
        vp.update(combinations)
        rsrc = stack['volume2']
        ex = self.assertRaises(exc, rsrc.validate)
        self.assertEqual(err_msg, six.text_type(ex))

    def test_cinder_create_with_image_and_imageRef(self):
        self.stack_name = 'test_create_with_image_and_imageRef'
        combinations = {'imageRef': 'image-456', 'image': 'image-123'}
        err_msg = ("Cannot define the following properties at the same time: "
                   "image, imageRef")
        self.stub_ImageConstraint_validate()
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        vp = stack.t['Resources']['volume2']['Properties']
        vp.pop('size')
        vp.update(combinations)
        rsrc = stack.get('volume2')
        ex = self.assertRaises(exception.StackValidationFailed, rsrc.validate)
        self.assertIn(err_msg, six.text_type(ex))

    def test_cinder_create_with_image_and_size(self):
        self.stack_name = 'test_create_with_image_and_size'
        combinations = {'image': 'image-123'}
        err_msg = ('If neither "backup_id" nor "size" is provided, one and '
                   'only one of "source_volid", "snapshot_id" must be '
                   'specified, but currently '
                   'specified options: [\'image\'].')
        self.stub_ImageConstraint_validate()
        self._test_cinder_create_invalid_property_combinations(
            self.stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_with_size_snapshot_and_image(self):
        self.stack_name = 'test_create_with_size_snapshot_and_image'
        combinations = {
            'size': 1,
            'image': 'image-123',
            'snapshot_id': 'snapshot-123'}
        self.stub_ImageConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        err_msg = ('If "size" is provided, only one of "image", "imageRef", '
                   '"source_volid", "snapshot_id" can be specified, but '
                   'currently specified options: '
                   '[\'snapshot_id\', \'image\'].')
        self._test_cinder_create_invalid_property_combinations(
            self.stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_with_size_snapshot_and_imageRef(self):
        self.stack_name = 'test_create_with_size_snapshot_and_imageRef'
        combinations = {
            'size': 1,
            'imageRef': 'image-123',
            'snapshot_id': 'snapshot-123'}
        self.stub_ImageConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        # image appears there because of translation rule
        err_msg = ('If "size" is provided, only one of "image", "imageRef", '
                   '"source_volid", "snapshot_id" can be specified, but '
                   'currently specified options: '
                   '[\'snapshot_id\', \'image\'].')
        self._test_cinder_create_invalid_property_combinations(
            self.stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_with_size_snapshot_and_sourcevol(self):
        self.stack_name = 'test_create_with_size_snapshot_and_sourcevol'
        combinations = {
            'size': 1,
            'source_volid': 'volume-123',
            'snapshot_id': 'snapshot-123'}
        self.stub_VolumeConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        err_msg = ('If "size" is provided, only one of "image", "imageRef", '
                   '"source_volid", "snapshot_id" can be specified, but '
                   'currently specified options: '
                   '[\'snapshot_id\', \'source_volid\'].')
        self._test_cinder_create_invalid_property_combinations(
            self.stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_with_snapshot_and_source_volume(self):
        self.stack_name = 'test_create_with_snapshot_and_source_volume'
        combinations = {
            'source_volid': 'source_volume-123',
            'snapshot_id': 'snapshot-123'}
        err_msg = ('If neither "backup_id" nor "size" is provided, one and '
                   'only one of "source_volid", "snapshot_id" must be '
                   'specified, but currently '
                   'specified options: [\'snapshot_id\', \'source_volid\'].')
        self.stub_VolumeConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self._test_cinder_create_invalid_property_combinations(
            self.stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_with_image_and_source_volume(self):
        self.stack_name = 'test_create_with_image_and_source_volume'
        combinations = {
            'source_volid': 'source_volume-123',
            'image': 'image-123'}
        err_msg = ('If neither "backup_id" nor "size" is provided, one and '
                   'only one of "source_volid", "snapshot_id" must be '
                   'specified, but currently '
                   'specified options: [\'source_volid\', \'image\'].')
        self.stub_VolumeConstraint_validate()
        self.stub_ImageConstraint_validate()
        self._test_cinder_create_invalid_property_combinations(
            self.stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_no_size_no_combinations(self):
        self.stack_name = 'test_create_no_size_no_options'
        combinations = {}
        err_msg = ('If neither "backup_id" nor "size" is provided, one and '
                   'only one of "source_volid", "snapshot_id" must be '
                   'specified, but currently specified options: [].')
        self._test_cinder_create_invalid_property_combinations(
            self.stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def _test_volume_restore(self, stack_name, final_status='available',
                             stack_final_status=('RESTORE', 'COMPLETE')):
        # create script
        self.cinder_fc.volumes.create.return_value = vt_base.FakeVolume(
            'creating')
        fv = vt_base.FakeVolume('available')
        fv_restoring = vt_base.FakeVolume(
            'restoring-backup', id=fv.id, attachments=[])
        fv_final = vt_base.FakeVolume(final_status, id=fv.id)
        self.cinder_fc.volumes.get.side_effect = [fv, fv_restoring, fv_final]
        self.stub_VolumeBackupConstraint_validate()

        # snapshot script
        fb = vt_base.FakeBackup('creating')
        self.patchobject(self.cinder_fc, 'backups')
        self.cinder_fc.backups.create.return_value = fb
        self.cinder_fc.backups.get.return_value = vt_base.FakeBackup(
            'available')

        # restore script
        fvbr = vt_base.FakeBackupRestore('vol-123')
        self.patchobject(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore.return_value = fvbr

        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)
        self.patchobject(stack['volume'], '_store_config_default_properties')

        scheduler.TaskRunner(stack.create)()

        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)

        scheduler.TaskRunner(stack.snapshot, None)()

        self.assertEqual((stack.SNAPSHOT, stack.COMPLETE), stack.state)

        data = stack.prepare_abandon()
        fake_snapshot = collections.namedtuple(
            'Snapshot', ('data', 'stack_id'))(data, stack.id)

        stack.restore(fake_snapshot)

        self.assertEqual(stack_final_status, stack.state)

        self.cinder_fc.volumes.create.assert_called_once_with(
            size=1, availability_zone=None,
            description='test_description',
            name='test_name',
            multiattach=False,
            metadata={}
        )
        self.cinder_fc.backups.create.assert_called_once_with(
            fv.id, force=True)
        self.cinder_fc.backups.get.assert_called_once_with(fb.id)
        self.cinder_fc.restores.restore.assert_called_once_with(
            'backup-123', 'vol-123')
        self.assertEqual(3, self.cinder_fc.volumes.get.call_count)

    def test_volume_restore_success(self):
        self._test_volume_restore(stack_name='test_volume_restore_success')

    def test_volume_restore_failed(self):
        self._test_volume_restore(stack_name='test_volume_restore_failed',
                                  final_status='error',
                                  stack_final_status=('RESTORE', 'FAILED'))

    def test_handle_delete_snapshot_no_backup(self):
        self.stack_name = 'test_handle_delete_snapshot_no_backup'
        mock_vs = {
            'resource_data': {}
        }
        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=self.stack_name)
        rsrc = c_vol.CinderVolume(
            'volume',
            stack.t.resource_definitions(stack)['volume'],
            stack)
        self.assertIsNone(rsrc.handle_delete_snapshot(mock_vs))

    def test_vaildate_deletion_policy(self):
        cfg.CONF.set_override('backups_enabled', False, group='volumes')
        self.stack_name = 'test_volume_validate_deletion_policy'
        self.t['resources']['volume']['deletion_policy'] = 'Snapshot'
        stack = utils.parse_stack(self.t, stack_name=self.stack_name)
        rsrc = self.get_volume(self.t, stack, 'volume')
        self.assertRaisesRegex(
            exception.StackValidationFailed,
            'volume backup service is not enabled',
            rsrc.validate)

    def test_volume_get_live_state(self):
        tmpl = """
        heat_template_version: 2013-05-23
        description: Cinder volume
        resources:
          volume:
            type: OS::Cinder::Volume
            properties:
              size: 1
              name: test_name
              description: test_description
              image: 1234
              scheduler_hints:
                'consistencygroup_id': 4444
        """
        t = template_format.parse(tmpl)
        stack = utils.parse_stack(t, stack_name='get_live_state')
        rsrc = stack['volume']
        rsrc._availability_zone = 'nova'
        rsrc.resource_id = '1234'

        vol_resp = {
            'attachments': [],
            'availability_zone': 'nova',
            'snapshot_id': None,
            'size': 1,
            'metadata': {'test': 'test_value', 'readonly': False},
            'consistencygroup_id': '4444',
            'volume_image_metadata': {'image_id': '1234',
                                      'image_name': 'test'},
            'description': None,
            'multiattach': False,
            'source_volid': None,
            'name': 'test-volume-jbdbgdsy3vyg',
            'volume_type': 'lvmdriver-1'
        }
        vol = mock.MagicMock()
        vol.to_dict.return_value = vol_resp
        rsrc.client().volumes = mock.MagicMock()
        rsrc.client().volumes.get = mock.MagicMock(return_value=vol)
        rsrc.client().volume_api_version = 2
        rsrc.data = mock.MagicMock(return_value={'volume_type': 'lvmdriver-1'})

        reality = rsrc.get_live_state(rsrc.properties)
        expected = {
            'size': 1,
            'metadata': {'test': 'test_value'},
            'description': None,
            'name': 'test-volume-jbdbgdsy3vyg',
            'backup_id': None,
            'read_only': False,
        }

        self.assertEqual(expected, reality)
