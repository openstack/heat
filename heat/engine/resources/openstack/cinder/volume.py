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

from oslo_log import log as logging
from oslo_serialization import jsonutils
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LI
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.aws.ec2 import volume as aws_vol
from heat.engine.resources import scheduler_hints as sh
from heat.engine import scheduler
from heat.engine import support
from heat.engine import volume_tasks as vol_task

LOG = logging.getLogger(__name__)


class CinderVolume(aws_vol.Volume, sh.SchedulerHintsMixin):

    PROPERTIES = (
        AVAILABILITY_ZONE, SIZE, SNAPSHOT_ID, BACKUP_ID, NAME,
        DESCRIPTION, VOLUME_TYPE, METADATA, IMAGE_REF, IMAGE,
        SOURCE_VOLID, CINDER_SCHEDULER_HINTS,
    ) = (
        'availability_zone', 'size', 'snapshot_id', 'backup_id', 'name',
        'description', 'volume_type', 'metadata', 'imageRef', 'image',
        'source_volid', 'scheduler_hints',
    )

    ATTRIBUTES = (
        AVAILABILITY_ZONE_ATTR, SIZE_ATTR, SNAPSHOT_ID_ATTR, DISPLAY_NAME_ATTR,
        DISPLAY_DESCRIPTION_ATTR, VOLUME_TYPE_ATTR, METADATA_ATTR,
        SOURCE_VOLID_ATTR, STATUS, CREATED_AT, BOOTABLE, METADATA_VALUES_ATTR,
        ENCRYPTED_ATTR, ATTACHMENTS,
    ) = (
        'availability_zone', 'size', 'snapshot_id', 'display_name',
        'display_description', 'volume_type', 'metadata',
        'source_volid', 'status', 'created_at', 'bootable', 'metadata_values',
        'encrypted', 'attachments',
    )

    properties_schema = {
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('The availability zone in which the volume will be created.')
        ),
        SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('The size of the volume in GB. '
              'On update only increase in size is supported.'),
            update_allowed=True,
            constraints=[
                constraints.Range(min=1),
            ]
        ),
        SNAPSHOT_ID: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the snapshot to create the volume from.'),
            constraints=[
                constraints.CustomConstraint('cinder.snapshot')
            ]
        ),
        BACKUP_ID: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the backup to create the volume from.')
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('A name used to distinguish the volume.'),
            update_allowed=True,
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('A description of the volume.'),
            update_allowed=True,
        ),
        VOLUME_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the type of volume to use, mapping to a '
              'specific backend.'),
            constraints=[
                constraints.CustomConstraint('cinder.vtype')
            ],
            update_allowed=True
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Key/value pairs to associate with the volume.'),
            update_allowed=True,
        ),
        IMAGE_REF: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the image to create the volume from.'),
            support_status=support.SupportStatus(
                support.DEPRECATED,
                _('Use property %s.') % IMAGE)
        ),
        IMAGE: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the name or ID of the image to create the '
              'volume from.'),
            constraints=[
                constraints.CustomConstraint('glance.image')
            ]
        ),
        SOURCE_VOLID: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the volume to use as source.'),
            constraints=[
                constraints.CustomConstraint('cinder.volume')
            ]
        ),
        CINDER_SCHEDULER_HINTS: properties.Schema(
            properties.Schema.MAP,
            _('Arbitrary key-value pairs specified by the client to help '
              'the Cinder scheduler creating a volume.'),
            support_status=support.SupportStatus(version='2015.1')
        ),
    }

    attributes_schema = {
        AVAILABILITY_ZONE_ATTR: attributes.Schema(
            _('The availability zone in which the volume is located.')
        ),
        SIZE_ATTR: attributes.Schema(
            _('The size of the volume in GB.')
        ),
        SNAPSHOT_ID_ATTR: attributes.Schema(
            _('The snapshot the volume was created from, if any.')
        ),
        DISPLAY_NAME_ATTR: attributes.Schema(
            _('Name of the volume.')
        ),
        DISPLAY_DESCRIPTION_ATTR: attributes.Schema(
            _('Description of the volume.')
        ),
        VOLUME_TYPE_ATTR: attributes.Schema(
            _('The type of the volume mapping to a backend, if any.')
        ),
        METADATA_ATTR: attributes.Schema(
            _('Key/value pairs associated with the volume.')
        ),
        SOURCE_VOLID_ATTR: attributes.Schema(
            _('The volume used as source, if any.')
        ),
        STATUS: attributes.Schema(
            _('The current status of the volume.')
        ),
        CREATED_AT: attributes.Schema(
            _('The timestamp indicating volume creation.')
        ),
        BOOTABLE: attributes.Schema(
            _('Boolean indicating if the volume can be booted or not.')
        ),
        METADATA_VALUES_ATTR: attributes.Schema(
            _('Key/value pairs associated with the volume in raw dict form.')
        ),
        ENCRYPTED_ATTR: attributes.Schema(
            _('Boolean indicating if the volume is encrypted or not.')
        ),
        ATTACHMENTS: attributes.Schema(
            _('The list of attachments of the volume.')
        ),
    }

    _volume_creating_status = ['creating', 'restoring-backup', 'downloading']

    default_client_name = 'cinder'

    def _name(self):
        name = self.properties[self.NAME]
        if name:
            return name
        return super(CinderVolume, self)._name()

    def _description(self):
        return self.properties[self.DESCRIPTION]

    def _create_arguments(self):
        arguments = {
            'size': self.properties[self.SIZE],
            'availability_zone': self.properties[self.AVAILABILITY_ZONE],
        }

        scheduler_hints = self._scheduler_hints(
            self.properties.get(self.CINDER_SCHEDULER_HINTS))
        if scheduler_hints:
            arguments[self.CINDER_SCHEDULER_HINTS] = scheduler_hints

        if self.properties.get(self.IMAGE):
            arguments['imageRef'] = self.client_plugin('glance').get_image_id(
                self.properties[self.IMAGE])
        elif self.properties.get(self.IMAGE_REF):
            arguments['imageRef'] = self.properties[self.IMAGE_REF]

        optionals = (self.SNAPSHOT_ID, self.VOLUME_TYPE, self.SOURCE_VOLID,
                     self.METADATA)
        arguments.update((prop, self.properties[prop]) for prop in optionals
                         if self.properties[prop])

        return arguments

    def _resolve_attribute(self, name):
        cinder = self.client()
        vol = cinder.volumes.get(self.resource_id)
        if name == self.METADATA_ATTR:
            return six.text_type(jsonutils.dumps(vol.metadata))
        elif name == self.METADATA_VALUES_ATTR:
            return vol.metadata
        if cinder.volume_api_version >= 2:
            if name == self.DISPLAY_NAME_ATTR:
                return vol.name
            elif name == self.DISPLAY_DESCRIPTION_ATTR:
                return vol.description
        return six.text_type(getattr(vol, name))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        vol = None
        checkers = []
        cinder = self.client()
        # update the name and description for cinder volume
        if self.NAME in prop_diff or self.DESCRIPTION in prop_diff:
            vol = cinder.volumes.get(self.resource_id)
            update_name = (prop_diff.get(self.NAME) or
                           self.properties.get(self.NAME))
            update_description = (prop_diff.get(self.DESCRIPTION) or
                                  self.properties.get(self.DESCRIPTION))
            kwargs = self._fetch_name_and_description(
                cinder.volume_api_version, update_name, update_description)
            cinder.volumes.update(vol, **kwargs)
        # update the metadata for cinder volume
        if self.METADATA in prop_diff:
            if not vol:
                vol = cinder.volumes.get(self.resource_id)
            metadata = prop_diff.get(self.METADATA)
            cinder.volumes.update_all_metadata(vol, metadata)
        # retype
        if self.VOLUME_TYPE in prop_diff:
            if cinder.volume_api_version == 1:
                LOG.info(_LI('Volume type update not supported '
                             'by Cinder API V1.'))
                raise exception.NotSupported(
                    feature=_('Using Cinder API V1, volume_type update'))
            else:
                if not vol:
                    vol = cinder.volumes.get(self.resource_id)
                new_vol_type = prop_diff.get(self.VOLUME_TYPE)
                cinder.volumes.retype(vol, new_vol_type, 'never')
        # extend volume size
        if self.SIZE in prop_diff:
            if not vol:
                vol = cinder.volumes.get(self.resource_id)

            new_size = prop_diff[self.SIZE]
            if new_size < vol.size:
                raise exception.NotSupported(feature=_("Shrinking volume"))

            elif new_size > vol.size:
                if vol.attachments:
                    # NOTE(pshchelo):
                    # this relies on current behavior of cinder attachments,
                    # i.e. volume attachments is a list with len<=1,
                    # so the volume can be attached only to single instance,
                    # and id of attachment is the same as id of the volume
                    # it describes, so detach/attach the same volume
                    # will not change volume attachment id.
                    server_id = vol.attachments[0]['server_id']
                    device = vol.attachments[0]['device']
                    attachment_id = vol.attachments[0]['id']
                    detach_task = vol_task.VolumeDetachTask(
                        self.stack, server_id, attachment_id)
                    checkers.append(scheduler.TaskRunner(detach_task))
                    extend_task = vol_task.VolumeExtendTask(
                        self.stack, vol.id, new_size)
                    checkers.append(scheduler.TaskRunner(extend_task))
                    attach_task = vol_task.VolumeAttachTask(
                        self.stack, server_id, vol.id, device)
                    checkers.append(scheduler.TaskRunner(attach_task))

                else:
                    extend_task = vol_task.VolumeExtendTask(
                        self.stack, vol.id, new_size)
                    checkers.append(scheduler.TaskRunner(extend_task))

        if checkers:
            checkers[0].start()
        return checkers

    def check_update_complete(self, checkers):
        for checker in checkers:
            if not checker.started():
                checker.start()
            if not checker.step():
                return False
        return True

    def handle_snapshot(self):
        backup = self.client().backups.create(self.resource_id)
        return backup.id

    def check_snapshot_complete(self, backup_id):
        backup = self.client().backups.get(backup_id)
        if backup.status == 'creating':
            return False
        if backup.status == 'available':
            self.data_set('backup_id', backup_id)
            return True
        raise exception.Error(backup.status)

    def handle_delete_snapshot(self, snapshot):
        backup_id = snapshot['resource_data']['backup_id']

        def delete():
            cinder = self.client()
            try:
                cinder.backups.delete(backup_id)
                while True:
                    yield
                    cinder.backups.get(backup_id)
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)

        delete_task = scheduler.TaskRunner(delete)
        delete_task.start()
        return delete_task

    def check_delete_snapshot_complete(self, delete_task):
        return delete_task.step()

    def validate(self):
        """Validate provided params."""
        res = super(CinderVolume, self).validate()
        if res is not None:
            return res

        # Scheduler hints are only supported from Cinder API v2
        if (self.properties.get(self.CINDER_SCHEDULER_HINTS)
                and self.client().volume_api_version == 1):
            raise exception.StackValidationFailed(
                message=_('Scheduler hints are not supported by the current '
                          'volume API.'))

    def handle_restore(self, defn, restore_data):
        backup_id = restore_data['resource_data']['backup_id']
        ignore_props = (
            self.IMAGE_REF, self.IMAGE, self.SOURCE_VOLID, self.SIZE)
        props = dict(
            (key, value) for (key, value) in
            six.iteritems(defn.properties(self.properties_schema))
            if key not in ignore_props and value is not None)
        props[self.BACKUP_ID] = backup_id
        return defn.freeze(properties=props)


class CinderVolumeAttachment(aws_vol.VolumeAttachment):

    PROPERTIES = (
        INSTANCE_ID, VOLUME_ID, DEVICE,
    ) = (
        'instance_uuid', 'volume_id', 'mountpoint',
    )

    properties_schema = {
        INSTANCE_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the server to which the volume attaches.'),
            required=True,
            update_allowed=True
        ),
        VOLUME_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the volume to be attached.'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('cinder.volume')
            ]
        ),
        DEVICE: properties.Schema(
            properties.Schema.STRING,
            _('The location where the volume is exposed on the instance. This '
              'assignment may not be honored and it is advised that the path '
              '/dev/disk/by-id/virtio-<VolumeId> be used instead.'),
            update_allowed=True
        ),
    }

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        checkers = []
        if prop_diff:
            # Even though some combinations of changed properties
            # could be updated in UpdateReplace manner,
            # we still first detach the old resource so that
            # self.resource_id is not replaced prematurely
            volume_id = self.properties.get(self.VOLUME_ID)
            if self.VOLUME_ID in prop_diff:
                volume_id = prop_diff.get(self.VOLUME_ID)

            device = self.properties.get(self.DEVICE)
            if self.DEVICE in prop_diff:
                device = prop_diff.get(self.DEVICE)

            server_id = self._stored_properties_data.get(self.INSTANCE_ID)
            detach_task = vol_task.VolumeDetachTask(
                self.stack, server_id, self.resource_id)
            checkers.append(scheduler.TaskRunner(detach_task))

            if self.INSTANCE_ID in prop_diff:
                server_id = prop_diff.get(self.INSTANCE_ID)
            attach_task = vol_task.VolumeAttachTask(
                self.stack, server_id, volume_id, device)

            checkers.append(scheduler.TaskRunner(attach_task))

        if checkers:
            checkers[0].start()
        return checkers

    def check_update_complete(self, checkers):
        for checker in checkers:
            if not checker.started():
                checker.start()
            if not checker.step():
                return False
        self.resource_id_set(checkers[-1]._task.attachment_id)
        return True


def resource_mapping():
    return {
        'OS::Cinder::Volume': CinderVolume,
        'OS::Cinder::VolumeAttachment': CinderVolumeAttachment,
    }
