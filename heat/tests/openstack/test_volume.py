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
from heat.db import api as db_api
from heat.engine.clients.os import cinder
from heat.engine.clients.os import glance
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import test_volume_utils as vt_base
from heat.tests import utils
from heat.tests.v1_1 import fakes as fakes_v1_1

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

    def _mock_create_volume(self, fv, stack_name, size=1):
        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=size, availability_zone='nova',
            description='test_description',
            name='test_name',
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
        fv = vt_base.FakeVolume('creating', 'available')
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
        fv = vt_base.FakeVolumeWithStateTransition('downloading', 'available')
        stack_name = 'test_cvolume_create_from_img_stack'
        image_id = '46988116-6703-4623-9dbc-2bc6d284021b'
        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        self.m.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
        glance.GlanceClientPlugin.get_image_id(
            image_id).MultipleTimes().AndReturn(image_id)

        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            description='ImageVolumeDescription',
            name='ImageVolume',
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
        fv = vt_base.FakeVolume('creating', 'available')
        stack_name = 'test_cvolume_default_stack'

        cinder.CinderClientPlugin._create().AndReturn(
            self.cinder_fc)
        vol_name = utils.PhysName(stack_name, 'volume')
        self.cinder_fc.volumes.create(
            size=1, availability_zone='nova',
            description=None,
            name=vol_name).AndReturn(fv)

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
        fv = vt_base.FakeVolume(
            'creating', 'available', availability_zone='zone1',
            size=1, snapshot_id='snap-123', name='name',
            description='desc', volume_type='lvm',
            metadata={'key': 'value'}, source_volid=None,
            status='available', bootable=False,
            created_at='2013-02-25T02:40:21.000000',
            encrypted=False, attachments=[])
        stack_name = 'test_cvolume_fngetatt_stack'

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
        self.assertEqual(u'False', rsrc.FnGetAtt('encrypted'))
        self.assertEqual(u'[]', rsrc.FnGetAtt('attachments'))
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'unknown')
        self.assertEqual(
            'The Referenced Attribute (volume unknown) is incorrect.',
            six.text_type(error))

        self.m.VerifyAll()

    def test_cinder_attachment(self):
        fv = vt_base.FakeVolume('creating', 'available')
        fva = vt_base.FakeVolume('attaching', 'in-use')
        stack_name = 'test_cvolume_attach_stack'

        self._mock_create_volume(fv, stack_name)
        self._mock_create_server_volume_script(fva)
        self.stub_VolumeConstraint_validate()

        # delete script
        fva = vt_base.FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_v1_1.fake_exception())

        self.m.ReplayAll()

        stack = utils.parse_stack(self.t, stack_name=stack_name)

        self.create_volume(self.t, stack, 'volume')
        self.assertEqual('available', fv.status)
        rsrc = self.create_attachment(self.t, stack, 'attachment')
        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_cinder_volume_shrink_fails(self):
        fv = vt_base.FakeVolume('creating', 'available', size=2)
        stack_name = 'test_cvolume_shrink_fail_stack'

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
        fv = vt_base.FakeVolume('creating', 'available',
                                size=1, attachments=[])
        stack_name = 'test_cvolume_extend_det_stack'

        # create script
        self._mock_create_volume(fv, stack_name)
        # update script
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv2 = vt_base.FakeLatencyVolume(life_cycle=('extending', 'extending',
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
        fv = vt_base.FakeVolume('creating', 'available',
                                size=1, attachments=[])
        stack_name = 'test_cvolume_extend_fail_start_stack'

        # create script
        self._mock_create_volume(fv, stack_name)
        # update script
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv2 = vt_base.FakeVolume('extending', 'extending')
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
        fv = vt_base.FakeVolume('creating', 'available',
                                size=1, attachments=[])
        stack_name = 'test_cvolume_extend_fail_compl_stack'

        # create script
        self._mock_create_volume(fv, stack_name)
        # update script
        self.cinder_fc.volumes.get(fv.id).AndReturn(fv)
        fv2 = vt_base.FakeLatencyVolume(life_cycle=('extending', 'extending',
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
        fv = vt_base.FakeVolume('creating', 'available')
        stack_name = 'test_cvolume_extend_att_stack'
        self.stub_VolumeConstraint_validate()
        self._mock_create_volume(fv, stack_name)

        fva = vt_base.FakeVolume('attaching', 'in-use')
        self._mock_create_server_volume_script(fva)

        # update script
        attachments = [{'id': 'vol-123',
                        'device': '/dev/vdc',
                        'server_id': u'WikiDatabase'}]
        fv2 = vt_base.FakeVolume('available', 'available',
                                 attachments=attachments, size=1)
        self.cinder_fc.volumes.get(fv2.id).AndReturn(fv2)

        # detach script
        fvd = vt_base.FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fvd)
        self.cinder_fc.volumes.get(fvd.id).AndReturn(fvd)
        self.fc.volumes.delete_server_volume('WikiDatabase', 'vol-123')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fvd)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_v1_1.fake_exception())

        # resize script
        fvr = vt_base.FakeLatencyVolume(life_cycle=('extending', 'extending',
                                                    'available'))
        self.cinder_fc.volumes.get(fvr.id).AndReturn(fvr)

        self.cinder_fc.volumes.extend(fvr.id, 2)

        # attach script
        fva2 = vt_base.FakeVolume('attaching', 'in-use')
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
        stack_name = 'test_cvolume_extend_snapsht_stack'
        fv = vt_base.FakeVolumeWithStateTransition('restoring-backup',
                                                   'available',
                                                   size=2)
        fvbr = vt_base.FakeBackupRestore('vol-123')

        # create script
        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123').AndReturn(fvbr)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)
        self.m.StubOutWithMock(fv, 'update')
        vol_name = utils.PhysName(stack_name, 'volume')
        fv.update(description=None, name=vol_name)

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

    def test_cinder_volume_retype(self):
        fv = vt_base.FakeVolume('creating', 'available',
                                size=1, name='my_vol',
                                description='test')
        stack_name = 'test_cvolume_retype'
        new_vol_type = 'new_type'
        self.patchobject(cinder.CinderClientPlugin, '_create',
                         return_value=self.cinder_fc)
        self.patchobject(self.cinder_fc.volumes, 'create', return_value=fv)
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
        self.assertEqual('NotSupported: Using Cinder API V1, '
                         'volume_type update is not supported.',
                         six.text_type(ex))
        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)
        self.assertEqual(1, self.cinder_fc.volumes.retype.call_count)

    def test_cinder_volume_update_name_and_metadata(self):
        # update the name, description and metadata
        fv = vt_base.FakeVolume('creating', 'available',
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
        fv = vt_base.FakeVolume('creating', 'available')
        fb = vt_base.FakeBackup('creating', 'available')
        stack_name = 'test_cvolume_snpsht_stack'

        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone=None,
            description='test_description',
            name='test_name'
        ).AndReturn(fv)

        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create('vol-123').AndReturn(fb)

        self.m.ReplayAll()

        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        rsrc = stack['volume']
        scheduler.TaskRunner(rsrc.create)()

        scheduler.TaskRunner(rsrc.snapshot)()

        self.assertEqual((rsrc.SNAPSHOT, rsrc.COMPLETE), rsrc.state)

        self.assertEqual({'backup_id': 'backup-123'},
                         db_api.resource_data_get_all(rsrc))

        self.m.VerifyAll()

    def test_cinder_snapshot_error(self):
        fv = vt_base.FakeVolume('creating', 'available')
        fb = vt_base.FakeBackup('creating', 'error')
        stack_name = 'test_cvolume_snpsht_err_stack'

        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone=None, name='test_name',
            description='test_description').AndReturn(fv)

        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create('vol-123').AndReturn(fb)

        self.m.ReplayAll()

        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        rsrc = stack['volume']
        scheduler.TaskRunner(rsrc.create)()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.snapshot))

        self.assertEqual((rsrc.SNAPSHOT, rsrc.FAILED), rsrc.state)
        self.assertEqual("Error: error", rsrc.status_reason)

        self.assertEqual({}, db_api.resource_data_get_all(rsrc))

        self.m.VerifyAll()

    def test_cinder_volume_attachment_update_device(self):
        fv = vt_base.FakeVolume('creating', 'available')
        fva = vt_base.FakeVolume('attaching', 'in-use')
        fva2 = vt_base.FakeVolume('attaching', 'in-use')
        stack_name = 'test_cvolume_attach_udev_stack'

        self._mock_create_volume(fv, stack_name)
        self._mock_create_server_volume_script(fva)
        self.stub_VolumeConstraint_validate()

        # delete script
        fva = vt_base.FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_v1_1.fake_exception())

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
        fv = vt_base.FakeVolume('creating', 'available')
        fva = vt_base.FakeVolume('attaching', 'in-use')
        fv2 = vt_base.FakeVolume('creating', 'available')
        fv2.id = 'vol-456'
        fv2a = vt_base.FakeVolume('attaching', 'in-use')
        fv2a.id = 'vol-456'
        stack_name = 'test_cvolume_attach_uvol_stack'

        self.stub_VolumeConstraint_validate()
        self._mock_create_volume(fv, stack_name)

        vol2_name = utils.PhysName(stack_name, 'volume2')
        self.cinder_fc.volumes.create(
            size=2, availability_zone='nova',
            description=None,
            name=vol2_name).AndReturn(fv2)

        self._mock_create_server_volume_script(fva)

        # delete script
        fva = vt_base.FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_v1_1.fake_exception())

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
        fv = vt_base.FakeVolume('creating', 'available')
        fva = vt_base.FakeVolume('attaching', 'in-use')
        fva2 = vt_base.FakeVolume('attaching', 'in-use')
        stack_name = 'test_cvolume_attach_usrv_stack'

        self._mock_create_volume(fv, stack_name)
        self._mock_create_server_volume_script(fva)
        self.stub_VolumeConstraint_validate()

        # delete script
        fva = vt_base.FakeVolume('in-use', 'available')
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fva)
        self.fc.volumes.delete_server_volume(
            'WikiDatabase', 'vol-123').MultipleTimes().AndReturn(None)
        self.fc.volumes.get_server_volume(u'WikiDatabase',
                                          'vol-123').AndReturn(fva)
        self.fc.volumes.get_server_volume(
            u'WikiDatabase', 'vol-123').AndRaise(fakes_v1_1.fake_exception())

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

    def test_cinder_create_with_scheduler_hints(self):
        fv = vt_base.FakeVolume('creating', 'available')

        cinder.CinderClientPlugin._create().AndReturn(self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, name='test_name', description=None,
            availability_zone='nova',
            scheduler_hints={'hint1': 'good_advice'}).AndReturn(fv)

        self.m.ReplayAll()

        stack_name = 'test_cvolume_scheduler_hints_stack'
        stack = utils.parse_stack(self.t, stack_name=stack_name)
        self.create_volume(self.t, stack, 'volume3')
        self.assertEqual('available', fv.status)

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

    def test_volume_restore(self):
        stack_name = 'test_cvolume_restore_stack'
        t = template_format.parse(single_cinder_volume_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        fv = vt_base.FakeVolume('creating', 'available')
        fb = vt_base.FakeBackup('creating', 'available')
        fvbr = vt_base.FakeBackupRestore('vol-123')

        cinder.CinderClientPlugin._create().MultipleTimes().AndReturn(
            self.cinder_fc)
        self.cinder_fc.volumes.create(
            size=1, availability_zone=None, description='test_description',
            name='test_name'
        ).AndReturn(fv)
        self.m.StubOutWithMock(self.cinder_fc.backups, 'create')
        self.cinder_fc.backups.create('vol-123').AndReturn(fb)
        self.m.StubOutWithMock(self.cinder_fc.restores, 'restore')
        self.cinder_fc.restores.restore('backup-123').AndReturn(fvbr)
        self.cinder_fc.volumes.get('vol-123').AndReturn(fv)

        self.m.ReplayAll()

        scheduler.TaskRunner(stack.create)()

        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)

        scheduler.TaskRunner(stack.snapshot)()

        self.assertEqual((stack.SNAPSHOT, stack.COMPLETE), stack.state)

        data = stack.prepare_abandon()
        fake_snapshot = collections.namedtuple(
            'Snapshot', ('data', 'stack_id'))(data, stack.id)

        stack.restore(fake_snapshot)

        self.assertEqual((stack.RESTORE, stack.COMPLETE), stack.state)

        self.m.VerifyAll()
