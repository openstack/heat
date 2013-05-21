# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import json

from heat.openstack.common import log as logging
from heat.openstack.common.importutils import try_import

from heat.common import exception
from heat.engine import clients
from heat.engine import resource
from heat.engine import scheduler

volume_backups = try_import('cinderclient.v1.volume_backups')

logger = logging.getLogger(__name__)


class Volume(resource.Resource):

    properties_schema = {'AvailabilityZone': {'Type': 'String',
                                              'Required': True},
                         'Size': {'Type': 'Number'},
                         'SnapshotId': {'Type': 'String'},
                         'Tags': {'Type': 'List'}}

    _restore_property = 'SnapshotId'

    def _display_name(self):
        return self.physical_resource_name()

    def _display_description(self):
        return self.physical_resource_name()

    def _create_arguments(self):
        return {'size': self.properties['Size'],
                'availability_zone': self.properties['AvailabilityZone']}

    def handle_create(self):
        backup_id = self.properties.get(self._restore_property)
        cinder = self.cinder()
        if backup_id is not None:
            if volume_backups is None:
                raise exception.Error(
                    '%s not supported' % self._restore_property)
            vol_id = cinder.restores.restore(backup_id)['volume_id']

            vol = cinder.volumes.get(vol_id)
            vol.update(
                display_name=self._display_name(),
                display_description=self._display_description())
        else:
            vol = cinder.volumes.create(
                display_name=self._display_name(),
                display_description=self._display_description(),
                **self._create_arguments())
        self.resource_id_set(vol.id)

        return vol

    def check_create_complete(self, vol):
        vol.get()

        if vol.status == 'available':
            return True
        elif vol.status == 'creating':
            return False
        else:
            raise exception.Error(vol.status)

    def handle_update(self, json_snippet):
        return self.UPDATE_REPLACE

    def _backup(self):
        backup = self.cinder().backups.create(self.resource_id)
        while backup.status == 'creating':
            yield
            backup.get()
        if backup.status != 'available':
            raise exception.Error(backup.status)

    def _delete(self, backup=False):
        if self.resource_id is not None:
            try:
                vol = self.cinder().volumes.get(self.resource_id)

                if backup:
                    scheduler.TaskRunner(self._backup)()
                    vol.get()

                if vol.status == 'in-use':
                    logger.warn('cant delete volume when in-use')
                    raise exception.Error('Volume in use')

                self.cinder().volumes.delete(self.resource_id)
            except clients.cinderclient.exceptions.NotFound:
                pass

    if volume_backups is not None:
        def handle_snapshot_delete(self, state):
            backup = state not in (self.CREATE_FAILED,
                                   self.UPDATE_FAILED)
            return self._delete(backup=backup)

    def handle_delete(self):
        return self._delete()


class VolumeAttachment(resource.Resource):
    properties_schema = {'InstanceId': {'Type': 'String',
                                        'Required': True},
                         'VolumeId': {'Type': 'String',
                                      'Required': True},
                         'Device': {'Type': 'String',
                                    'Required': True,
                                    'AllowedPattern': '/dev/vd[b-z]'}}

    _instance_property = 'InstanceId'
    _volume_property = 'VolumeId'
    _device_property = 'Device'

    def handle_create(self):
        server_id = self.properties[self._instance_property]
        volume_id = self.properties[self._volume_property]
        dev = self.properties[self._device_property]
        inst = self.stack.clients.attach_volume_to_instance(server_id,
                                                            volume_id,
                                                            dev)
        self.resource_id_set(inst)

    def handle_update(self, json_snippet):
        return self.UPDATE_REPLACE

    def handle_delete(self):
        server_id = self.properties[self._instance_property]
        volume_id = self.properties[self._volume_property]
        self.stack.clients.detach_volume_from_instance(server_id, volume_id)


class CinderVolume(Volume):

    properties_schema = {'availability_zone': {'Type': 'String',
                                               'Required': True},
                         'size': {'Type': 'Number'},
                         'snapshot_id': {'Type': 'String'},
                         'backup_id': {'Type': 'String'},
                         'name': {'Type': 'String'},
                         'description': {'Type': 'String'},
                         'volume_type': {'Type': 'String'},
                         'metadata': {'Type': 'Map'},
                         'imageRef': {'Type': 'String'},
                         'source_volid': {'Type': 'String'}}

    _restore_property = 'backup_id'

    def _display_name(self):
        name = self.properties['name']
        if name:
            return name
        return super(CinderVolume, self)._display_name()

    def _display_description(self):
        return self.properties['description']

    def _create_arguments(self):
        arguments = {
            'size': self.properties['size'],
            'availability_zone': self.properties['availability_zone']
        }
        optionals = ['snapshot_id', 'volume_type', 'imageRef', 'source_volid',
                     'metadata']
        arguments.update((prop, self.properties[prop]) for prop in optionals
                         if self.properties[prop])
        return arguments

    def FnGetAtt(self, key):
        if key == 'id':
            return self.resource_id
        attributes = ['availability_zone', 'size', 'snapshot_id',
                      'display_name', 'display_description', 'volume_type',
                      'metadata', 'source_volid', 'status', 'created_at',
                      'bootable']
        if key not in attributes:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)
        vol = self.cinder().volumes.get(self.resource_id)
        if key == 'metadata':
            return unicode(json.dumps(vol.metadata))
        return unicode(getattr(vol, key))


class CinderVolumeAttachment(VolumeAttachment):

    properties_schema = {'instance_uuid': {'Type': 'String',
                                           'Required': True},
                         'volume_id': {'Type': 'String',
                                       'Required': True},
                         'mountpoint': {'Type': 'String',
                                        'Required': True}}

    _instance_property = 'instance_uuid'
    _volume_property = 'volume_id'
    _device_property = 'mountpoint'


def resource_mapping():
    return {
        'AWS::EC2::Volume': Volume,
        'AWS::EC2::VolumeAttachment': VolumeAttachment,
        'OS::Cinder::Volume': CinderVolume,
        'OS::Cinder::VolumeAttachment': CinderVolumeAttachment,
    }
