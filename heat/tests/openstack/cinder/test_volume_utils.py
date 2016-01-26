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

from cinderclient import exceptions as cinder_exp
from cinderclient.v2 import client as cinderclient
import six

from heat.engine.clients.os import cinder
from heat.engine.clients.os import nova
from heat.engine.resources.aws.ec2 import volume as aws_vol
from heat.engine.resources.openstack.cinder import volume as os_vol
from heat.engine import scheduler
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova


class BaseVolumeTest(common.HeatTestCase):
    def setUp(self):
        super(BaseVolumeTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.cinder_fc = cinderclient.Client('username', 'password')
        self.cinder_fc.volume_api_version = 2
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
        self.cinder_fc.volumes.get(fv.id).AndReturn(
            FakeVolume('available'))
        self.cinder_fc.volumes.delete(fv.id).AndReturn(True)
        self.cinder_fc.volumes.get(fv.id).AndRaise(
            cinder_exp.NotFound('Not found'))

    def _mock_create_server_volume_script(self, fva,
                                          server=u'WikiDatabase',
                                          volume='vol-123',
                                          device=u'/dev/vdc',
                                          final_status='in-use',
                                          update=False):
        if not update:
            nova.NovaClientPlugin._create().MultipleTimes().AndReturn(self.fc)
        self.fc.volumes.create_server_volume(
            device=device, server_id=server, volume_id=volume).AndReturn(fva)
        fv_ready = FakeVolume(final_status, id=fva.id)
        self.cinder_fc.volumes.get(fva.id).AndReturn(fv_ready)
        return fv_ready

    def create_volume(self, t, stack, resource_name):
        if self.use_cinder:
            Volume = os_vol.CinderVolume
        else:
            data = t['Resources'][resource_name]
            data['Properties']['AvailabilityZone'] = 'nova'
            Volume = aws_vol.Volume
        rsrc = Volume(resource_name,
                      stack.t.resource_definitions(stack)[resource_name],
                      stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_attachment(self, t, stack, resource_name):
        if self.use_cinder:
            Attachment = os_vol.CinderVolumeAttachment
        else:
            Attachment = aws_vol.VolumeAttachment
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = Attachment(resource_name,
                          resource_defns[resource_name],
                          stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc


class FakeVolume(object):
    _ID = 'vol-123'

    def __init__(self, status, **attrs):
        self.status = status
        self.to_dict = lambda: {'volume': 'info'}
        for key, value in six.iteritems(attrs):
            setattr(self, key, value)
        if 'id' not in attrs:
            self.id = self._ID


class FakeBackup(FakeVolume):
    _ID = 'backup-123'


class FakeBackupRestore(object):
    def __init__(self, volume_id='vol-123'):
        self.volume_id = volume_id
