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


class CinderVolumeTest(vt_base.BaseVolumeTest):

    def setUp(self):
        super(CinderVolumeTest, self).setUp()
        self.t = template_format.parse(cinder_volume_template)
        self.use_cinder = True

    def _mock_create_volume(self, fv, stack_name, size=1,
                            final_status='available'):
        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=size, availability_zone='nova',
            description='test_description',
            name='test_name',
            metadata={'key': 'value'}).AndReturn(fv)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv_ready = vt_base.FakeVolume(final_status, id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)
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
        stack_name = 'test_cvolume_stack'

        self.stub_SnapshotConstraint_validate()
        self.stub_VolumeConstraint_validate()
        self.stub_VolumeTypeConstraint_validate()
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            description='test_description',
            name='test_name',
            metadata={'key': 'value'},
            volume_type='lvm').AndReturn(fv)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)

        self.m.ReplayAll()

        self.t['resources']['volume']['properties'].update({
            'volume_type': 'lvm',
        })
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        self.create_volume(self.t, stack, 'volume')

        self.m.VerifyAll()

    def test_cinder_create_from_image(self):
        fv = vt_base.FakeVolume('downloading')
        stack_name = 'test_cvolume_create_from_img_stack'
        image_id = '46988116-6703-4623-9dbc-2bc6d284021b'
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.m.StubOutWithMock(glance.GlanceClientPlugin,
                               'find_image_by_name_or_id')
        glance.GlanceClientPlugin.find_image_by_name_or_id(
            image_id).MultipleTimes().AndReturn(image_id)

        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            description='ImageVolumeDescription',
            name='ImageVolume',
            imageRef=image_id).AndReturn(fv)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)

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

        self.m.VerifyAll()

    def test_cinder_create_with_read_only(self):
        fv = vt_base.FakeVolume('with_read_only_access_mode')
        stack_name = 'test_create_with_read_only'
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)

        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            description='ImageVolumeDescription',
            name='ImageVolume').AndReturn(fv)

        update_readonly_mock = self.patchobject(self.cinder_fc.volumes,
                                                'update_readonly_flag')
        update_readonly_mock.return_value = None
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)

        self.m.ReplayAll()

        self.t['resources']['volume']['properties'] = {
            'size': '1',
            'name': 'ImageVolume',
            'description': 'ImageVolumeDescription',
            'availability_zone': 'nova',
            'read_only': False,
        }
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        self.create_volume(self.t, stack, 'volume')

        update_readonly_mock.assert_called_once_with(fv.id, False)

        self.m.VerifyAll()

    def test_cinder_default(self):
        fv = vt_base.FakeVolume('creating')
        stack_name = 'test_cvolume_default_stack'

        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        vol_name = utils.PhysName(stack_name, 'volume')
        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            description=None,
            name=vol_name).AndReturn(fv)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)

        self.m.ReplayAll()

        self.t['resources']['volume']['properties'] = {
            'size': '1',
            'availability_zone': 'nova',
        }
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        self.create_volume(self.t, stack, 'volume')

        self.m.VerifyAll()

    def test_cinder_fn_getatt(self):
        stack_name = 'test_cvolume_fngetatt_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)
        fv = vt_base.FakeVolume(
            'available', availability_zone='zone1',
            size=1, snapshot_id='snap-123', name='name',
            description='desc', volume_type='lvm',
            metadata={'key': 'value'}, source_volid=None,
            bootable=False, created_at='2013-02-25T02:40:21.000000',
            encrypted=False, attachments=[], multiattach=False)
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
        self.assertEqual(u'False', rsrc.FnGetAtt('encrypted'))
        self.assertEqual(u'[]', rsrc.FnGetAtt('attachments'))
        self.assertEqual({'volume': 'info'}, rsrc.FnGetAtt('show'))
        self.assertEqual('False', rsrc.FnGetAtt('multiattach'))
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'unknown')
        self.assertEqual(
            'The Referenced Attribute (volume unknown) is incorrect.',
            six.text_type(error))

        self.m.VerifyAll()

    def test_cinder_attachment(self):
        stack_name = 'test_cvolume_attach_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)
        self._mock_create_server_volume_script(vt_base.FakeVolume('attaching'))
        self.stub_VolumeConstraint_validate()

        # delete script
        fva = vt_base.FakeVolume('in-use')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('available'))
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception())

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')
        rsrc = self.create_attachment(self.t, stack, 'attachment')
        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_cinder_attachment_no_mountpoint(self):
        stack_name = 'test_cvolume_attach_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)
        self._mock_create_server_volume_script(vt_base.FakeVolume('attaching'),
                                               device=None)
        self.stub_VolumeConstraint_validate()

        # delete script
        fva = vt_base.FakeVolume('in-use')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('available'))
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception())

        self.m.ReplayAll()

        self.t['resources']['attachment']['properties']['mountpoint'] = ''
        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')
        rsrc = self.create_attachment(self.t, stack, 'attachment')

        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_cinder_volume_shrink_fails(self):
        stack_name = 'test_cvolume_shrink_fail_stack'

        # create script
        self._mock_create_volume(vt_base.FakeVolume('creating'),
                                 stack_name, size=2)
        # update script
        fv = vt_base.FakeVolume('available', size=2)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)

        self.m.ReplayAll()

        self.t['resources']['volume']['properties']['size'] = 2
        stack = utils.parse_stack(self.t, stack_name=stack_name)

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
        self.m.VerifyAll()

    def test_cinder_volume_extend_detached(self):
        stack_name = 'test_cvolume_extend_det_stack'

        # create script
        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)
        # update script
        fv = vt_base.FakeVolume('available',
                                size=1, attachments=[])
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        self.cinder_fc.volumes.extend(fv.id, 2)
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('extending'))
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('extending'))
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('available'))

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        self.assertIsNone(update_task())

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_extend_fails_to_start(self):
        stack_name = 'test_cvolume_extend_fail_start_stack'

        # create script
        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)
        # update script
        fv = vt_base.FakeVolume('available',
                                size=1, attachments=[])
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        self.cinder_fc.volumes.extend(fv.id, 2).AndRaise(
            cinder_exp.OverLimit(413))
        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertIn('Over limit', six.text_type(ex))

        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_extend_fails_to_complete(self):
        stack_name = 'test_cvolume_extend_fail_compl_stack'

        # create script
        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)
        # update script
        fv = vt_base.FakeVolume('available',
                                size=1, attachments=[])
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        self.cinder_fc.volumes.extend(fv.id, 2)
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('extending'))
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('extending'))
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            vt_base.FakeVolume('error_extending'))
        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

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
        stack_name = 'test_cvolume_extend_att_stack'
        self._update_if_attached(stack_name)

    def test_cinder_volume_extend_created_from_backup_with_same_size(self):
        stack_name = 'test_cvolume_extend_snapsht_stack'

        # create script
        self.stub_VolumeBackupConstraint_validate()
        fvbr = vt_base.FakeBackupRestore('vol-123')
        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123').AndReturn(fvbr)
        self.cinder_fc.volumes.get('vol-123').AndReturn(
            vt_base.FakeVolume('restoring-backup'))
        vol_name = utils.PhysName(stack_name, 'volume')
        self.cinder_fc.volumes.update('vol-123', description=None,
                                      name=vol_name).AndReturn(None)
        self.cinder_fc.volumes.get('vol-123').AndReturn(
            vt_base.FakeVolume('available'))

        # update script
        fv = vt_base.FakeVolume('available', size=2)
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

    def test_cinder_volume_retype(self):
        fv = vt_base.FakeVolume('available',
                                size=1, name='my_vol',
                                description='test')
        stack_name = 'test_cvolume_retype'
        new_vol_type = 'new_type'
        self.patchobject(cinder.CinderClientPlugin, '_create',
                         return_value=self.cinder_fc)
        self.patchobject(self.cinder_fc.volumes, 'create', return_value=fv)
        self.patchobject(self.cinder_fc.volumes, 'get', return_value=fv)
        stack = utils.parse_stack(self.t, stack_name=stack_name)
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

        self.cinder_fc.volume_api_version = 1
        new_vol_type_1 = 'new_type_1'
        props = copy.deepcopy(rsrc.properties.data)
        props['volume_type'] = new_vol_type_1
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        # if the volume api is v1, not support to retype
        update_task = scheduler.TaskRunner(rsrc.update, after)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        self.assertEqual('NotSupported: resources.volume2: '
                         'Using Cinder API V1, '
                         'volume_type update is not supported.',
                         six.text_type(ex))
        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.assertEqual(1, self.cinder_fc.volumes.retype.call_count)

    def test_cinder_volume_update_name_and_metadata(self):
        # update the name, description and metadata
        fv = vt_base.FakeVolume('creating',
                                size=1, name='my_vol',
                                description='test')
        stack_name = 'test_cvolume_updname_stack'
        update_name = 'update_name'
        meta = {'Key': 'New Value'}
        update_description = 'update_description'
        kwargs = {
            'name': update_name,
            'description': update_description
        }

        fv = self._mock_create_volume(fv, stack_name)
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

    def test_cinder_volume_update_read_only(self):
        # update read only access mode
        fv = vt_base.FakeVolume('update_read_only_access_mode')
        stack_name = 'test_update_read_only'
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)

        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            description='test_description',
            name='test_name',
            metadata={u'key': u'value'}).AndReturn(fv)

        update_readonly_mock = self.patchobject(self.cinder_fc.volumes,
                                                'update_readonly_flag')

        update_readonly_mock.return_value = None
        fv_ready = vt_base.FakeVolume('available', id=fv.id, attachments=[])
        self.cinder_fc.volumes.get(fv.id).MultipleTimes().AndReturn(fv_ready)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')

        props = copy.deepcopy(rsrc.properties.data)
        props['read_only'] = True
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        update_readonly_mock.assert_called_once_with(fv.id, True)

    def _update_if_attached(self, stack_name, update_type='resize'):
        # create script
        self.stub_VolumeConstraint_validate()
        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)

        self._mock_create_server_volume_script(vt_base.FakeVolume('attaching'))

        # update script
        attachments = [{'id': 'vol-123',
                        'device': '/dev/vdc',
                        'server_id': u'WikiDatabase'}]
        fv2 = vt_base.FakeVolume('in-use',
                                 attachments=attachments, size=1)
        self.cinder_fc.volumes.get(fv2.id).AndReturn(fv2)

        # detach script
        fvd = vt_base.FakeVolume('in-use')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fvd)
        self.cinder_fc.volumes.get(fvd.id).AndReturn(fvd)
        self.fc.volumes.delete_server_volume('WikiDatabase', 'vol-123')
        self.cinder_fc.volumes.get(fvd.id).AndReturn(
            vt_base.FakeVolume('available'))
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fvd)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception())

        if update_type is 'access_mode':
            # update access mode script
            update_readonly_mock = self.patchobject(self.cinder_fc.volumes,
                                                    'update_readonly_flag')
            update_readonly_mock.return_value = None
        if update_type is 'resize':
            # resize script
            self.cinder_fc.volumes.extend(fvd.id, 2)
            self.cinder_fc.volumes.get(fvd.id).AndReturn(
                vt_base.FakeVolume('extending'))
            self.cinder_fc.volumes.get(fvd.id).AndReturn(
                vt_base.FakeVolume('extending'))
            self.cinder_fc.volumes.get(fvd.id).AndReturn(
                vt_base.FakeVolume('available'))
        # attach script
        self._mock_create_server_volume_script(vt_base.FakeVolume('attaching'),
                                               update=True)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        rsrc = self.create_volume(self.t, stack, 'volume')
        self.create_attachment(self.t, stack, 'attachment')

        props = copy.deepcopy(rsrc.properties.data)
        if update_type is 'access_mode':
            props['read_only'] = True
        if update_type is 'resize':
            props['size'] = 2
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        update_task = scheduler.TaskRunner(rsrc.update, after)
        self.assertIsNone(update_task())

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        if update_type is 'access_mode':
            update_readonly_mock.assert_called_once_with(fvd.id, True)

        self.m.VerifyAll()

    def test_cinder_volume_update_read_only_attached(self):
        stack_name = 'test_cvolume_update_read_only_att_stack'
        self._update_if_attached(stack_name, update_type='access_mode')

    def test_cinder_snapshot(self):
        stack_name = 'test_cvolume_snpsht_stack'

        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone=None,
            description='test_description',
            name='test_name'
        ).AndReturn(vt_base.FakeVolume('creating'))
        fv = vt_base.FakeVolume('available')
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)

        fb = vt_base.FakeBackup('creating')
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create(fv.id).AndReturn(fb)
        self.m.StubOutWithMock(self.cinder_fc.backups, 'get')
        self.cinder_fc.backups.get(fb.id).AndReturn(
            vt_base.FakeBackup('available'))

        self.m.ReplayAll()

        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        rsrc = stack['volume']
        scheduler.TaskRunner(rsrc.create)()

        scheduler.TaskRunner(rsrc.snapshot)()

        self.assertEqual((rsrc.SNAPSHOT, rsrc.COMPLETE), rsrc.state)

        self.assertEqual({'backup_id': 'backup-123'},
                         resource_data_object.ResourceData.get_all(rsrc))

        self.m.VerifyAll()

    def test_cinder_snapshot_error(self):
        stack_name = 'test_cvolume_snpsht_err_stack'

        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone=None,
            description='test_description',
            name='test_name'
        ).AndReturn(vt_base.FakeVolume('creating'))
        fv = vt_base.FakeVolume('available')
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)

        fb = vt_base.FakeBackup('creating')
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create(fv.id).AndReturn(fb)
        self.m.StubOutWithMock(self.cinder_fc.backups, 'get')
        fail_reason = 'Could not determine which Swift endpoint to use'
        self.cinder_fc.backups.get(fb.id).AndReturn(
            vt_base.FakeBackup('error', fail_reason=fail_reason))

        self.m.ReplayAll()

        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        rsrc = stack['volume']
        scheduler.TaskRunner(rsrc.create)()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.snapshot))

        self.assertEqual((rsrc.SNAPSHOT, rsrc.FAILED), rsrc.state)
        self.assertIn(fail_reason, rsrc.status_reason)

        self.assertEqual({u'backup_id': u'backup-123'},
                         resource_data_object.ResourceData.get_all(rsrc))

        self.m.VerifyAll()

    def test_cinder_volume_attachment_update_device(self):
        stack_name = 'test_cvolume_attach_udev_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)
        self._mock_create_server_volume_script(
            vt_base.FakeVolume('attaching'),
            device=u'/dev/vdc')
        self.stub_VolumeConstraint_validate()

        # delete script
        fva = vt_base.FakeVolume('in-use')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('available'))
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception())

        # attach script
        self._mock_create_server_volume_script(vt_base.FakeVolume('attaching'),
                                               device=None,
                                               update=True)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')
        rsrc = self.create_attachment(self.t, stack, 'attachment')

        props = copy.deepcopy(rsrc.properties.data)
        props['mountpoint'] = ''
        props['volume_id'] = 'vol-123'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_cinder_volume_attachment_update_volume(self):
        stack_name = 'test_cvolume_attach_uvol_stack'

        self.stub_VolumeConstraint_validate()
        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)

        fv2 = vt_base.FakeVolume('creating', id='vol-456')
        vol2_name = utils.PhysName(stack_name, 'volume2')
        self.cinder_fc.volumes.create(
            size=2, availability_zone='nova',
            description=None,
            name=vol2_name).AndReturn(fv2)
        self.cinder_fc.volumes.get(fv2.id).AndReturn(fv2)
        fv2 = vt_base.FakeVolume('available', id=fv2.id)
        self.cinder_fc.volumes.get(fv2.id).AndReturn(fv2)

        self._mock_create_server_volume_script(vt_base.FakeVolume('attaching'))

        # delete script
        fva = vt_base.FakeVolume('in-use')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.cinder_fc.volumes.get(fva.id).AndReturn(
            vt_base.FakeVolume('available'))
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception())

        # attach script
        fv2a = vt_base.FakeVolume('attaching', id='vol-456')
        self._mock_create_server_volume_script(fv2a, volume='vol-456',
                                               update=True)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')
        self.create_volume(self.t, stack, 'volume2')

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
        stack_name = 'test_cvolume_attach_usrv_stack'

        self._mock_create_volume(vt_base.FakeVolume('creating'), stack_name)
        self._mock_create_server_volume_script(
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
            vt_base.FakeVolume('available'))
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_nova.fake_exception())

        # attach script
        self._mock_create_server_volume_script(vt_base.FakeVolume('attaching'),
                                               server=u'AnotherServer',
                                               update=True)

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')

        rsrc = self.create_attachment(self.t, stack, 'attachment')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        props = copy.deepcopy(rsrc.properties.data)
        props['instance_uuid'] = 'AnotherServer'
        props['volume_id'] = 'vol-123'
        after = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)
        scheduler.TaskRunner(rsrc.update, after)()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_attachment_has_not_been_created(self):
        stack_name = 'test_delete_attachment_has_not_been_created'
        stack = utils.parse_stack(self.t, stack_name=stack_name)
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

        cinder.CinderClientPlugin._create().AndReturn(self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, name='test_name', description=None,
            availability_zone='nova',
            scheduler_hints={'hint1': 'good_advice'}).AndReturn(fv)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)

        self.m.ReplayAll()

        stack_name = 'test_cvolume_scheduler_hints_stack'
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        self.create_volume(self.t, stack, 'volume3')

        self.m.VerifyAll()

    def test_cinder_create_with_multiattach(self):
        fv = vt_base.FakeVolume('creating')

        cinder.CinderClientPlugin._create().AndReturn(self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, name='test_name', description=None,
            availability_zone='nova',
            multiattach=True).AndReturn(fv)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)

        self.m.ReplayAll()

        stack_name = 'test_cvolume_multiattach_stack'
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        self.create_volume(self.t, stack, 'volume4')

        self.m.VerifyAll()

    def test_cinder_create_with_scheduler_hints_and_cinder_api_v1(self):
        cinder.CinderClientPlugin._create().AndReturn(self.cinder_fc)
        self.cinder_fc.volume_api_version = 1

        self.m.ReplayAll()

        stack_name = 'test_cvolume_scheduler_hints_api_v1_stack'
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.create_volume, self.t, stack, 'volume3')
        self.assertIn('Scheduler hints are not supported by the current '
                      'volume API.', six.text_type(ex))
        self.m.VerifyAll()

    def test_cinder_create_with_stack_scheduler_hints(self):
        fv = vt_base.FakeVolume('creating')
        sh.cfg.CONF.set_override('stack_scheduler_hints', True)

        stack_name = 'test_cvolume_stack_scheduler_hints_stack'
        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        rsrc = stack['volume']

        # rsrc.uuid is only available once the resource has been added.
        stack.add_resource(rsrc)
        self.assertIsNotNone(rsrc.uuid)

        cinder.CinderClientPlugin._create().AndReturn(self.cinder_fc)
        shm = sh.SchedulerHintsMixin
        self.cinder_fc.volumes.create(
            size=1, name='test_name', description='test_description',
            availability_zone=None,
            scheduler_hints={shm.HEAT_ROOT_STACK_ID: stack.root_stack_id(),
                             shm.HEAT_STACK_ID: stack.id,
                             shm.HEAT_STACK_NAME: stack.name,
                             shm.HEAT_PATH_IN_STACK: [(None, stack.name)],
                             shm.HEAT_RESOURCE_NAME: rsrc.name,
                             shm.HEAT_RESOURCE_UUID: rsrc.uuid}).AndReturn(fv)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv_ready = vt_base.FakeVolume('available', id=fv.id)
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv_ready)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        # this makes sure the auto increment worked on volume creation
        self.assertTrue(rsrc.id > 0)

        self.m.VerifyAll()

    def test_cinder_create_with_multiattach_and_cinder_api_v1(self):
        cinder.CinderClientPlugin._create().AndReturn(self.cinder_fc)
        self.cinder_fc.volume_api_version = 1

        self.m.ReplayAll()

        stack_name = 'test_cvolume_multiattach_api_v1_stack'
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.create_volume, self.t, stack, 'volume4')
        self.assertIn('Multiple attach is not supported by the current '
                      'volume API. Use this property since '
                      'Cinder API v2.', six.text_type(ex))

        self.m.VerifyAll()

    def _test_cinder_create_invalid_property_combinations(
            self, stack_name, combinations, err_msg, exc):
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        vp = stack.t['Resources']['volume2']['Properties']
        vp.pop('size')
        vp.update(combinations)
        rsrc = stack['volume2']
        ex = self.assertRaises(exc, rsrc.validate)
        self.assertEqual(err_msg, six.text_type(ex))

    def test_cinder_create_with_image_and_imageRef(self):
        stack_name = 'test_create_with_image_and_imageRef'
        combinations = {'imageRef': 'image-456', 'image': 'image-123'}
        err_msg = "Cannot use image and imageRef at the same time."
        self.stub_ImageConstraint_validate()
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        vp = stack.t['Resources']['volume2']['Properties']
        vp.pop('size')
        vp.update(combinations)
        ex = self.assertRaises(ValueError, stack.get, 'volume2')
        self.assertEqual(err_msg, six.text_type(ex))

    def test_cinder_create_with_size_snapshot_and_image(self):
        stack_name = 'test_create_with_size_snapshot_and_image'
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
            stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_with_size_snapshot_and_imageRef(self):
        stack_name = 'test_create_with_size_snapshot_and_imageRef'
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
            stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_with_size_snapshot_and_sourcevol(self):
        stack_name = 'test_create_with_size_snapshot_and_sourcevol'
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
            stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_with_snapshot_and_source_volume(self):
        stack_name = 'test_create_with_snapshot_and_source_volume'
        combinations = {
            'source_volid': 'source_volume-123',
            'snapshot_id': 'snapshot-123'}
        err_msg = ('If neither "backup_id" nor "size" is provided, one and '
                   'only one of "image", "imageRef", "source_volid", '
                   '"snapshot_id" must be specified, but currently '
                   'specified options: [\'snapshot_id\', \'source_volid\'].')
        self.stub_VolumeConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self._test_cinder_create_invalid_property_combinations(
            stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_with_image_and_source_volume(self):
        stack_name = 'test_create_with_image_and_source_volume'
        combinations = {
            'source_volid': 'source_volume-123',
            'image': 'image-123'}
        err_msg = ('If neither "backup_id" nor "size" is provided, one and '
                   'only one of "image", "imageRef", "source_volid", '
                   '"snapshot_id" must be specified, but currently '
                   'specified options: [\'source_volid\', \'image\'].')
        self.stub_VolumeConstraint_validate()
        self.stub_ImageConstraint_validate()
        self._test_cinder_create_invalid_property_combinations(
            stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def test_cinder_create_no_size_no_combinations(self):
        stack_name = 'test_create_no_size_no_options'
        combinations = {}
        err_msg = ('If neither "backup_id" nor "size" is provided, one and '
                   'only one of "image", "imageRef", "source_volid", '
                   '"snapshot_id" must be specified, but currently '
                   'specified options: [].')
        self._test_cinder_create_invalid_property_combinations(
            stack_name, combinations,
            err_msg, exception.StackValidationFailed)

    def _test_volume_restore(self, stack_name, final_status='available',
                             stack_final_status=('RESTORE', 'COMPLETE')):
        # create script
        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone=None,
            description='test_description',
            name='test_name'
        ).AndReturn(vt_base.FakeVolume('creating'))
        fv = vt_base.FakeVolume('available')
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        self.stub_VolumeBackupConstraint_validate()

        # snapshot script
        fb = vt_base.FakeBackup('creating')
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create(fv.id).AndReturn(fb)
        self.m.StubOutWithMock(self.cinder_fc.backups, 'get')
        self.cinder_fc.backups.get(fb.id).AndReturn(
            vt_base.FakeBackup('available'))

        # restore script
        fvbr = vt_base.FakeBackupRestore('vol-123')
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123',
                                        'vol-123').AndReturn(fvbr)
        fv_restoring = vt_base.FakeVolume('restoring-backup', id=fv.id)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv_restoring)
        fv_final = vt_base.FakeVolume(final_status, id=fv.id)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv_final)

        self.m.ReplayAll()

        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)
        scheduler.TaskRunner(stack.create)()

        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)

        scheduler.TaskRunner(stack.snapshot, None)()

        self.assertEqual((stack.SNAPSHOT, stack.COMPLETE), stack.state)

        data = stack.prepare_abandon()
        fake_snapshot = collections.namedtuple(
            'Snapshot', ('data', 'stack_id'))(data, stack.id)

        stack.restore(fake_snapshot)

        self.assertEqual(stack_final_status, stack.state)

        self.m.VerifyAll()

    def test_volume_restore_success(self):
        self._test_volume_restore(stack_name='test_volume_restore_success')

    def test_volume_restore_failed(self):
        self._test_volume_restore(stack_name='test_volume_restore_failed',
                                  final_status='error',
                                  stack_final_status=('RESTORE', 'FAILED'))

    def test_handle_delete_snapshot_no_backup(self):
        stack_name = 'test_handle_delete_snapshot_no_backup'
        mock_vs = {
            'resource_data': {}
        }
        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)
        rsrc = c_vol.CinderVolume(
            'volume',
            stack.t.resource_definitions(stack)['volume'],
            stack)
        self.assertIsNone(rsrc.handle_delete_snapshot(mock_vs))
