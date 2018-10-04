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

from cinderclient.v2 import client as cinderclient
import mock
import six

from heat.engine.clients.os import cinder
from heat.engine.clients.os import nova
from heat.engine.resources.aws.ec2 import volume as aws_vol
from heat.engine.resources.openstack.cinder import volume as os_vol
from heat.engine import scheduler
from heat.engine import stk_defn
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


class VolumeTestCase(common.HeatTestCase):
    def setUp(self):
        super(VolumeTestCase, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.cinder_fc = cinderclient.Client('username', 'password')
        self.cinder_fc.volume_api_version = 2
        self.patchobject(cinder.CinderClientPlugin, '_create',
                         return_value=self.cinder_fc)
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        self.cinder_fc.volumes = mock.Mock(spec=self.cinder_fc.volumes)
        self.fc.volumes = mock.Mock()
        self.use_cinder = False
        self.m_backups = mock.Mock(spec=self.cinder_fc.backups)
        self.m_restore = mock.Mock(spec=self.cinder_fc.restores.restore)
        self.cinder_fc.backups = self.m_backups
        self.cinder_fc.restores.restore = self.m_restore

    def _mock_delete_volume(self, fv):
        self.cinder_fc.volumes.delete.return_value = True

    def validate_mock_create_server_volume_script(self):
        self.fc.volumes.create_server_volume.assert_called_once_with(
            device=u'/dev/vdc', server_id=u'WikiDatabase', volume_id='vol-123')

    def _mock_create_server_volume_script(self, fva,
                                          final_status='in-use',
                                          update=False,
                                          extra_create_server_volume_mocks=[]):
        if not update:
            nova.NovaClientPlugin.client.return_value = self.fc

        result = [fva]
        for m in extra_create_server_volume_mocks:
            result.append(m)
        prev = self.fc.volumes.create_server_volume.side_effect or []
        self.fc.volumes.create_server_volume.side_effect = list(prev) + result
        fv_ready = FakeVolume(final_status, id=fva.id)
        return fv_ready

    def get_volume(self, t, stack, resource_name):
        if self.use_cinder:
            Volume = os_vol.CinderVolume
        else:
            data = t['Resources'][resource_name]
            data['Properties']['AvailabilityZone'] = 'nova'
            Volume = aws_vol.Volume
        vol = Volume(resource_name,
                     stack.defn.resource_definition(resource_name),
                     stack)
        return vol

    def create_volume(self, t, stack, resource_name, az='nova',
                      validate=True, no_create=False):
        rsrc = self.get_volume(t, stack, resource_name)
        if isinstance(rsrc, os_vol.CinderVolume):
            self.patchobject(rsrc, '_store_config_default_properties')

        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        stk_defn.update_resource_data(stack.defn, resource_name,
                                      rsrc.node_data())
        if validate:
            if no_create:
                self.cinder_fc.volumes.create.assert_not_called()
            else:
                self.vol_name = utils.PhysName(self.stack_name, 'DataVolume')
                self.cinder_fc.volumes.create.assert_called_once_with(
                    size=1, availability_zone=az,
                    description=self.vol_name,
                    name=self.vol_name,
                    metadata={u'Usage': u'Wiki Data Volume'})
        return rsrc

    def create_attachment(self, t, stack, resource_name):
        if self.use_cinder:
            Attachment = os_vol.CinderVolumeAttachment
        else:
            Attachment = aws_vol.VolumeAttachment
        rsrc = Attachment(resource_name,
                          stack.defn.resource_definition(resource_name),
                          stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        stk_defn.update_resource_data(stack.defn, resource_name,
                                      rsrc.node_data())
        return rsrc


class FakeVolume(object):
    _ID = 'vol-123'

    def __init__(self, status, **attrs):
        self.status = status
        for key, value in six.iteritems(attrs):
            setattr(self, key, value)
        if 'id' not in attrs:
            self.id = self._ID
        if 'attachments' not in attrs:
            self.attachments = [{'server_id': 'WikiDatabase'}]


class FakeBackup(FakeVolume):
    _ID = 'backup-123'


class FakeBackupRestore(object):
    def __init__(self, volume_id='vol-123'):
        self.volume_id = volume_id
