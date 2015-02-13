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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import volume_tasks as vol_task


class Volume(resource.Resource):

    PROPERTIES = (
        AVAILABILITY_ZONE, SIZE, BACKUP_ID, TAGS,
    ) = (
        'AvailabilityZone', 'Size', 'SnapshotId', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('The availability zone in which the volume will be created.'),
            required=True,
            immutable=True
        ),
        SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('The size of the volume in GB.'),
            immutable=True,
            constraints=[
                constraints.Range(min=1),
            ]
        ),
        BACKUP_ID: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the backup used as the source to create the '
              'volume.'),
            immutable=True
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('The list of tags to associate with the volume.'),
            immutable=True,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    TAG_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    TAG_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
            )
        ),
    }

    _volume_creating_status = ['creating', 'restoring-backup']

    default_client_name = 'cinder'

    def _name(self):
        return self.physical_resource_name()

    def _description(self):
        return self.physical_resource_name()

    def _create_arguments(self):
        if self.properties[self.TAGS]:
            tags = dict((tm[self.TAG_KEY], tm[self.TAG_VALUE])
                        for tm in self.properties[self.TAGS])
        else:
            tags = None

        return {
            'size': self.properties[self.SIZE],
            'availability_zone': (self.properties[self.AVAILABILITY_ZONE] or
                                  None),
            'metadata': tags
        }

    def _fetch_name_and_description(self, api_version, name=None,
                                    description=None):
        if api_version == 1:
            return {'display_name': name or self._name(),
                    'display_description': description or self._description()}
        else:
            return {'name': name or self._name(),
                    'description': description or self._description()}

    def handle_create(self):
        backup_id = self.properties.get(self.BACKUP_ID)
        cinder = self.client()
        if backup_id is not None:
            vol_id = cinder.restores.restore(backup_id).volume_id

            vol = cinder.volumes.get(vol_id)
            kwargs = self._fetch_name_and_description(
                cinder.volume_api_version)
            cinder.volumes.update(vol_id, **kwargs)
        else:
            kwargs = self._create_arguments()
            kwargs.update(self._fetch_name_and_description(
                cinder.volume_api_version))
            vol = cinder.volumes.create(**kwargs)
        self.resource_id_set(vol.id)

        return vol.id

    def check_create_complete(self, vol_id):
        vol = self.client().volumes.get(vol_id)

        if vol.status == 'available':
            return True
        if vol.status in self._volume_creating_status:
            return False
        if vol.status == 'error':
            raise resource.ResourceInError(
                resource_status=vol.status)
        else:
            raise resource.ResourceUnknownStatus(
                resource_status=vol.status,
                result=_('Volume create failed'))

    def handle_check(self):
        vol = self.client().volumes.get(self.resource_id)
        statuses = ['available', 'in-use']
        checks = [
            {'attr': 'status', 'expected': statuses, 'current': vol.status},
        ]
        self._verify_check_conditions(checks)

    def _backup(self):
        cinder = self.client()
        backup = cinder.backups.create(self.resource_id)
        while backup.status == 'creating':
            yield
            backup = cinder.backups.get(backup.id)
        if backup.status != 'available':
            raise resource.ResourceUnknownStatus(
                resource_status=backup.status,
                result=_('Volume backup failed'))

    @scheduler.wrappertask
    def _delete(self, backup=False):
        if self.resource_id is not None:
            cinder = self.client()
            try:
                vol = cinder.volumes.get(self.resource_id)

                if backup:
                    yield self._backup()
                    vol = cinder.volumes.get(self.resource_id)

                if vol.status == 'in-use':
                    raise exception.Error(_('Volume in use'))
                # if the volume is already in deleting status,
                # just wait for the deletion to complete
                if vol.status != 'deleting':
                    cinder.volumes.delete(self.resource_id)
                while True:
                    yield
                    vol = cinder.volumes.get(self.resource_id)
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)

    def handle_snapshot_delete(self, state):
        backup = state not in ((self.CREATE, self.FAILED),
                               (self.UPDATE, self.FAILED))

        delete_task = scheduler.TaskRunner(self._delete, backup=backup)
        delete_task.start()
        return delete_task

    def handle_delete(self):
        delete_task = scheduler.TaskRunner(self._delete)
        delete_task.start()
        return delete_task

    def check_delete_complete(self, delete_task):
        return delete_task.step()


class VolumeAttachment(resource.Resource):
    PROPERTIES = (
        INSTANCE_ID, VOLUME_ID, DEVICE,
    ) = (
        'InstanceId', 'VolumeId', 'Device',
    )

    properties_schema = {
        INSTANCE_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the instance to which the volume attaches.'),
            immutable=True,
            required=True,
            constraints=[
                constraints.CustomConstraint('nova.server')
            ]
        ),
        VOLUME_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the volume to be attached.'),
            immutable=True,
            required=True,
            constraints=[
                constraints.CustomConstraint('cinder.volume')
            ]
        ),
        DEVICE: properties.Schema(
            properties.Schema.STRING,
            _('The device where the volume is exposed on the instance. This '
              'assignment may not be honored and it is advised that the path '
              '/dev/disk/by-id/virtio-<VolumeId> be used instead.'),
            immutable=True,
            required=True,
            constraints=[
                constraints.AllowedPattern('/dev/vd[b-z]'),
            ]
        ),
    }

    def handle_create(self):
        server_id = self.properties[self.INSTANCE_ID]
        volume_id = self.properties[self.VOLUME_ID]
        dev = self.properties[self.DEVICE]

        attach_task = vol_task.VolumeAttachTask(
            self.stack, server_id, volume_id, dev)
        attach_runner = scheduler.TaskRunner(attach_task)

        attach_runner.start()

        self.resource_id_set(attach_task.attachment_id)

        return attach_runner

    def check_create_complete(self, attach_runner):
        return attach_runner.step()

    def handle_delete(self):
        server_id = self.properties[self.INSTANCE_ID]
        detach_task = vol_task.VolumeDetachTask(
            self.stack, server_id, self.resource_id)
        detach_runner = scheduler.TaskRunner(detach_task)
        detach_runner.start()
        return detach_runner

    def check_delete_complete(self, detach_runner):
        return detach_runner.step()


def resource_mapping():
    return {
        'AWS::EC2::Volume': Volume,
        'AWS::EC2::VolumeAttachment': VolumeAttachment,
    }
