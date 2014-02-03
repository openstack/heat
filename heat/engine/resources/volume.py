
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

from heat.common import exception
from heat.engine import clients
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources import nova_utils
from heat.engine import scheduler
from heat.engine import support
from heat.openstack.common.importutils import try_import
from heat.openstack.common import log as logging

volume_backups = try_import('cinderclient.v1.volume_backups')

logger = logging.getLogger(__name__)


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
            required=True
        ),
        SIZE: properties.Schema(
            properties.Schema.NUMBER,
            _('The size of the volume in GB.')
        ),
        BACKUP_ID: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the backup used as the source to create the '
              'volume.')
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('The list of tags to associate with the volume.'),
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

    def _display_name(self):
        return self.physical_resource_name()

    def _display_description(self):
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

    def handle_create(self):
        backup_id = self.properties.get(self.BACKUP_ID)
        cinder = self.cinder()
        if backup_id is not None:
            if volume_backups is None:
                raise exception.Error(_('Backups not supported.'))
            vol_id = cinder.restores.restore(backup_id).volume_id

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
        elif vol.status in self._volume_creating_status:
            return False
        else:
            raise exception.Error(vol.status)

    def _backup(self):
        backup = self.cinder().backups.create(self.resource_id)
        while backup.status == 'creating':
            yield
            backup.get()
        if backup.status != 'available':
            raise exception.Error(backup.status)

    @scheduler.wrappertask
    def _delete(self, backup=False):
        if self.resource_id is not None:
            try:
                vol = self.cinder().volumes.get(self.resource_id)

                if backup:
                    yield self._backup()
                    vol.get()

                if vol.status == 'in-use':
                    logger.warn(_('can not delete volume when in-use'))
                    raise exception.Error(_('Volume in use'))

                vol.delete()
                while True:
                    yield
                    vol.get()
            except clients.cinderclient.exceptions.NotFound:
                self.resource_id_set(None)

    if volume_backups is not None:
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


class VolumeAttachTask(object):
    """A task for attaching a volume to a Nova server."""

    def __init__(self, stack, server_id, volume_id, device):
        """
        Initialise with the stack (for obtaining the clients), ID of the
        server and volume, and the device name on the server.
        """
        self.clients = stack.clients
        self.server_id = server_id
        self.volume_id = volume_id
        self.device = device
        self.attachment_id = None

    def __str__(self):
        """Return a human-readable string description of the task."""
        return 'Attaching Volume %s to Instance %s as %s' % (self.volume_id,
                                                             self.server_id,
                                                             self.device)

    def __repr__(self):
        """Return a brief string description of the task."""
        return '%s(%s -> %s [%s])' % (type(self).__name__,
                                      self.volume_id,
                                      self.server_id,
                                      self.device)

    def __call__(self):
        """Return a co-routine which runs the task."""
        logger.debug(str(self))

        va = self.clients.nova().volumes.create_server_volume(
            server_id=self.server_id,
            volume_id=self.volume_id,
            device=self.device)
        self.attachment_id = va.id
        yield

        vol = self.clients.cinder().volumes.get(self.volume_id)
        while vol.status == 'available' or vol.status == 'attaching':
            logger.debug(_('%(name)s - volume status: %(status)s') % {
                         'name': str(self), 'status': vol.status})
            yield
            vol.get()

        if vol.status != 'in-use':
            raise exception.Error(vol.status)

        logger.info(_('%s - complete') % str(self))


class VolumeDetachTask(object):
    """A task for detaching a volume from a Nova server."""

    def __init__(self, stack, server_id, attachment_id):
        """
        Initialise with the stack (for obtaining the clients), and the IDs of
        the server and volume.
        """
        self.clients = stack.clients
        self.server_id = server_id
        self.attachment_id = attachment_id

    def __str__(self):
        """Return a human-readable string description of the task."""
        return _('Removing attachment %(att)s from Instance %(srv)s') % {
            'att': self.attachment_id, 'srv': self.server_id}

    def __repr__(self):
        """Return a brief string description of the task."""
        return '%s(%s -/> %s)' % (type(self).__name__,
                                  self.attachment_id,
                                  self.server_id)

    def __call__(self):
        """Return a co-routine which runs the task."""
        logger.debug(str(self))

        server_api = self.clients.nova().volumes

        # get reference to the volume while it is attached
        try:
            nova_vol = server_api.get_server_volume(self.server_id,
                                                    self.attachment_id)
            vol = self.clients.cinder().volumes.get(nova_vol.id)
        except (clients.cinderclient.exceptions.NotFound,
                clients.novaclient.exceptions.BadRequest,
                clients.novaclient.exceptions.NotFound):
            logger.warning(_('%s - volume not found') % str(self))
            return

        # detach the volume using volume_attachment
        try:
            server_api.delete_server_volume(self.server_id, self.attachment_id)
        except (clients.novaclient.exceptions.BadRequest,
                clients.novaclient.exceptions.NotFound) as e:
            logger.warning('%(res)s - %(err)s' % {'res': str(self),
                                                  'err': str(e)})

        yield

        try:
            vol.get()
            while vol.status in ('in-use', 'detaching'):
                logger.debug(_('%s - volume still in use') % str(self))
                yield

                try:
                    server_api.delete_server_volume(self.server_id,
                                                    self.attachment_id)
                except (clients.novaclient.exceptions.BadRequest,
                        clients.novaclient.exceptions.NotFound):
                    pass
                vol.get()

            logger.info(_('%(name)s - status: %(status)s') % {
                        'name': str(self), 'status': vol.status})
            if vol.status != 'available':
                raise exception.Error(vol.status)

        except clients.cinderclient.exceptions.NotFound:
            logger.warning(_('%s - volume not found') % str(self))

        # The next check is needed for immediate reattachment when updating:
        # as the volume info is taken from cinder, but the detach
        # request is sent to nova, there might be some time
        # between cinder marking volume as 'available' and
        # nova removing attachment from it's own objects, so we
        # check that nova already knows that the volume is detached
        def server_has_attachment(server_id, attachment_id):
            try:
                server_api.get_server_volume(server_id, attachment_id)
            except clients.novaclient.exceptions.NotFound:
                return False
            return True

        while server_has_attachment(self.server_id, self.attachment_id):
            logger.info(_("Server %(srv)s still has attachment %(att)s.") %
                        {'att': self.attachment_id, 'srv': self.server_id})
            yield

        logger.info(_("Volume %(vol)s is detached from server %(srv)s") %
                    {'vol': vol.id, 'srv': self.server_id})


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
            required=True,
            update_allowed=True
        ),
        VOLUME_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the volume to be attached.'),
            required=True,
            update_allowed=True
        ),
        DEVICE: properties.Schema(
            properties.Schema.STRING,
            _('The device where the volume is exposed on the instance. This '
              'assignment may not be honored and it is advised that the path '
              '/dev/disk/by-id/virtio-<VolumeId> be used instead.'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.AllowedPattern('/dev/vd[b-z]'),
            ]
        ),
    }

    update_allowed_keys = ('Properties',)

    def handle_create(self):
        server_id = self.properties[self.INSTANCE_ID]
        volume_id = self.properties[self.VOLUME_ID]
        dev = self.properties[self.DEVICE]

        attach_task = VolumeAttachTask(self.stack, server_id, volume_id, dev)
        attach_runner = scheduler.TaskRunner(attach_task)

        attach_runner.start()

        self.resource_id_set(attach_task.attachment_id)

        return attach_runner

    def check_create_complete(self, attach_runner):
        return attach_runner.step()

    def handle_delete(self):
        server_id = self.properties[self.INSTANCE_ID]
        detach_task = VolumeDetachTask(self.stack, server_id, self.resource_id)
        scheduler.TaskRunner(detach_task)()

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

            server_id = self.properties.get(self.INSTANCE_ID)
            detach_task = VolumeDetachTask(self.stack, server_id,
                                           self.resource_id)
            checkers.append(scheduler.TaskRunner(detach_task))

            if self.INSTANCE_ID in prop_diff:
                server_id = prop_diff.get(self.INSTANCE_ID)
            attach_task = VolumeAttachTask(self.stack, server_id,
                                           volume_id, device)

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


class CinderVolume(Volume):

    PROPERTIES = (
        AVAILABILITY_ZONE, SIZE, SNAPSHOT_ID, BACKUP_ID, NAME,
        DESCRIPTION, VOLUME_TYPE, METADATA, IMAGE_REF, IMAGE,
        SOURCE_VOLID,
    ) = (
        'availability_zone', 'size', 'snapshot_id', 'backup_id', 'name',
        'description', 'volume_type', 'metadata', 'imageRef', 'image',
        'source_volid',
    )

    properties_schema = {
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('The availability zone in which the volume will be created.')
        ),
        SIZE: properties.Schema(
            properties.Schema.NUMBER,
            _('The size of the volume in GB.'),
            constraints=[
                constraints.Range(min=1),
            ]
        ),
        SNAPSHOT_ID: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the snapshot to create the volume from.')
        ),
        BACKUP_ID: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the backup to create the volume from.')
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('A name used to distinguish the volume.')
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('A description of the volume.')
        ),
        VOLUME_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('If specified, the type of volume to use, mapping to a '
              'specific backend.')
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Key/value pairs to associate with the volume.')
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
            _('If specified, the volume to use as source.')
        ),
    }

    attributes_schema = {
        'availability_zone': _('The availability zone in which the volume is '
                               ' located.'),
        'size': _('The size of the volume in GB.'),
        'snapshot_id': _('The snapshot the volume was created from, if any.'),
        'display_name': _('Name of the volume.'),
        'display_description': _('Description of the volume.'),
        'volume_type': _('The type of the volume mapping to a backend, if '
                         'any.'),
        'metadata': _('Key/value pairs associated with the volume.'),
        'source_volid': _('The volume used as source, if any.'),
        'status': _('The current status of the volume.'),
        'created_at': _('The timestamp indicating volume creation.'),
        'bootable': _('Boolean indicating if the volume can be booted or '
                      'not.'),
    }

    _volume_creating_status = ['creating', 'restoring-backup', 'downloading']

    def _display_name(self):
        name = self.properties[self.NAME]
        if name:
            return name
        return super(CinderVolume, self)._display_name()

    def _display_description(self):
        return self.properties[self.DESCRIPTION]

    def _create_arguments(self):
        arguments = {
            'size': self.properties[self.SIZE],
            'availability_zone': self.properties[self.AVAILABILITY_ZONE]
        }
        if self.properties.get(self.IMAGE):
            arguments['imageRef'] = nova_utils.get_image_id(
                self.nova(), self.properties[self.IMAGE])
        elif self.properties.get(self.IMAGE_REF):
            arguments['imageRef'] = self.properties[self.IMAGE_REF]

        optionals = (self.SNAPSHOT_ID, self.VOLUME_TYPE, self.SOURCE_VOLID,
                     self.METADATA)
        arguments.update((prop, self.properties[prop]) for prop in optionals
                         if self.properties[prop])
        return arguments

    def _resolve_attribute(self, name):
        vol = self.cinder().volumes.get(self.resource_id)
        if name == 'metadata':
            return unicode(json.dumps(vol.metadata))
        return unicode(getattr(vol, name))


class CinderVolumeAttachment(VolumeAttachment):

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
            update_allowed=True
        ),
        DEVICE: properties.Schema(
            properties.Schema.STRING,
            _('The location where the volume is exposed on the instance. This '
              'assignment may not be honored and it is advised that the path '
              '/dev/disk/by-id/virtio-<VolumeId> be used instead.'),
            update_allowed=True
        ),
    }


def resource_mapping():
    return {
        'AWS::EC2::Volume': Volume,
        'AWS::EC2::VolumeAttachment': VolumeAttachment,
        'OS::Cinder::Volume': CinderVolume,
        'OS::Cinder::VolumeAttachment': CinderVolumeAttachment,
    }
