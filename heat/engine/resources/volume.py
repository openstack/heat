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
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LI
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import support
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


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
        cinder = self.cinder()
        if backup_id is not None:
            vol_id = cinder.restores.restore(backup_id).volume_id

            vol = cinder.volumes.get(vol_id)
            kwargs = self._fetch_name_and_description(
                cinder.volume_api_version)
            vol.update(**kwargs)
        else:
            kwargs = self._create_arguments()
            kwargs.update(self._fetch_name_and_description(
                cinder.volume_api_version))
            vol = cinder.volumes.create(**kwargs)
        self.resource_id_set(vol.id)

        return vol

    def check_create_complete(self, vol):
        vol.get()

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
        vol = self.cinder().volumes.get(self.resource_id)
        statuses = ['available', 'in-use']
        checks = [
            {'attr': 'status', 'expected': statuses, 'current': vol.status},
        ]
        self._verify_check_conditions(checks)

    def _backup(self):
        backup = self.cinder().backups.create(self.resource_id)
        while backup.status == 'creating':
            yield
            backup.get()
        if backup.status != 'available':
            raise resource.ResourceUnknownStatus(
                resource_status=backup.status,
                result=_('Volume backup failed'))

    @scheduler.wrappertask
    def _delete(self, backup=False):
        if self.resource_id is not None:
            try:
                vol = self.cinder().volumes.get(self.resource_id)

                if backup:
                    yield self._backup()
                    vol.get()

                if vol.status == 'in-use':
                    raise exception.Error(_('Volume in use'))
                # if the volume is already in deleting status,
                # just wait for the deletion to complete
                if vol.status != 'deleting':
                    vol.delete()
                while True:
                    yield
                    vol.get()
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


class VolumeExtendTask(object):
    """A task to resize volume using Cinder API."""

    def __init__(self, stack, volume_id, size):
        self.clients = stack.clients
        self.volume_id = volume_id
        self.size = size

    def __str__(self):
        return _("Resizing volume %(vol)s to size %(size)i") % {
            'vol': self.volume_id, 'size': self.size}

    def __repr__(self):
        return "%s(%s +-> %i)" % (type(self).__name__, self.volume_id,
                                  self.size)

    def __call__(self):
        LOG.debug(str(self))

        cinder = self.clients.client('cinder').volumes
        vol = cinder.get(self.volume_id)

        try:
            cinder.extend(self.volume_id, self.size)
        except Exception as ex:
            if self.clients.client_plugin('cinder').is_client_exception(ex):
                raise exception.Error(_(
                    "Failed to extend volume %(vol)s - %(err)s") % {
                        'vol': vol.id, 'err': str(ex)})
            else:
                raise

        yield

        vol.get()
        while vol.status == 'extending':
            LOG.debug("Volume %s is being extended" % self.volume_id)
            yield
            vol.get()

        if vol.status != 'available':
            LOG.info(_LI("Resize failed: Volume %(vol)s is in %(status)s "
                         "state."), {'vol': vol.id, 'status': vol.status})
            raise resource.ResourceUnknownStatus(
                resource_status=vol.status,
                result=_('Volume resize failed'))

        LOG.info(_LI('%s - complete'), str(self))


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
        LOG.debug(str(self))

        va = self.clients.client('nova').volumes.create_server_volume(
            server_id=self.server_id,
            volume_id=self.volume_id,
            device=self.device)
        self.attachment_id = va.id
        yield

        vol = self.clients.client('cinder').volumes.get(self.volume_id)
        while vol.status == 'available' or vol.status == 'attaching':
            LOG.debug('%(name)s - volume status: %(status)s'
                      % {'name': str(self), 'status': vol.status})
            yield
            vol.get()

        if vol.status != 'in-use':
            LOG.info(_LI("Attachment failed - volume %(vol)s "
                         "is in %(status)s status"),
                     {"vol": vol.id,
                      "status": vol.status})
            raise resource.ResourceUnknownStatus(
                resource_status=vol.status,
                result=_('Volume attachment failed'))

        LOG.info(_LI('%s - complete'), str(self))


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
        LOG.debug(str(self))

        nova_plugin = self.clients.client_plugin('nova')
        cinder_plugin = self.clients.client_plugin('cinder')
        server_api = self.clients.client('nova').volumes
        # get reference to the volume while it is attached
        try:
            nova_vol = server_api.get_server_volume(self.server_id,
                                                    self.attachment_id)
            vol = self.clients.client('cinder').volumes.get(nova_vol.id)
        except Exception as ex:
            if (cinder_plugin.is_not_found(ex) or
                    nova_plugin.is_not_found(ex) or
                    nova_plugin.is_bad_request(ex)):
                return
            else:
                raise

        # detach the volume using volume_attachment
        try:
            server_api.delete_server_volume(self.server_id, self.attachment_id)
        except Exception as ex:
            if nova_plugin.is_not_found(ex) or nova_plugin.is_bad_request(ex):
                pass
            else:
                raise

        yield

        try:
            while vol.status in ('in-use', 'detaching'):
                LOG.debug('%s - volume still in use' % str(self))
                yield
                vol.get()

            LOG.info(_LI('%(name)s - status: %(status)s'),
                     {'name': str(self), 'status': vol.status})
            if vol.status != 'available':
                LOG.info(_LI("Detachment failed - volume %(vol)s "
                             "is in %(status)s status"),
                         {"vol": vol.id,
                          "status": vol.status})
                raise resource.ResourceUnknownStatus(
                    resource_status=vol.status,
                    result=_('Volume detachment failed'))

        except Exception as ex:
            cinder_plugin.ignore_not_found(ex)

        # The next check is needed for immediate reattachment when updating:
        # there might be some time between cinder marking volume as 'available'
        # and nova removing attachment from its own objects, so we
        # check that nova already knows that the volume is detached
        def server_has_attachment(server_id, attachment_id):
            try:
                server_api.get_server_volume(server_id, attachment_id)
            except Exception as ex:
                nova_plugin.ignore_not_found(ex)
                return False
            return True

        while server_has_attachment(self.server_id, self.attachment_id):
            LOG.info(_LI("Server %(srv)s still has attachment %(att)s."),
                     {'att': self.attachment_id, 'srv': self.server_id})
            yield

        LOG.info(_LI("Volume %(vol)s is detached from server %(srv)s"),
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
        detach_runner = scheduler.TaskRunner(detach_task)
        detach_runner.start()
        return detach_runner

    def check_delete_complete(self, detach_runner):
        return detach_runner.step()


class CinderVolume(Volume):

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
            'availability_zone': self.properties[self.AVAILABILITY_ZONE]
        }
        if self.properties.get(self.IMAGE):
            arguments['imageRef'] = self.client_plugin('glance').get_image_id(
                self.properties[self.IMAGE])
        elif self.properties.get(self.IMAGE_REF):
            arguments['imageRef'] = self.properties[self.IMAGE_REF]

        optionals = (self.SNAPSHOT_ID, self.VOLUME_TYPE, self.SOURCE_VOLID,
                     self.METADATA, self.CINDER_SCHEDULER_HINTS)
        arguments.update((prop, self.properties[prop]) for prop in optionals
                         if self.properties[prop])

        return arguments

    def _resolve_attribute(self, name):
        vol = self.cinder().volumes.get(self.resource_id)
        if name == self.METADATA_ATTR:
            return six.text_type(json.dumps(vol.metadata))
        elif name == self.METADATA_VALUES_ATTR:
            return vol.metadata
        if self.cinder().volume_api_version >= 2:
            if name == self.DISPLAY_NAME_ATTR:
                return vol.name
            elif name == self.DISPLAY_DESCRIPTION_ATTR:
                return vol.description
        return six.text_type(getattr(vol, name))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        vol = None
        checkers = []
        cinder = self.cinder()
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
            if self.cinder().volume_api_version == 1:
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
                    detach_task = VolumeDetachTask(self.stack, server_id,
                                                   attachment_id)
                    checkers.append(scheduler.TaskRunner(detach_task))
                    extend_task = VolumeExtendTask(self.stack, vol.id,
                                                   new_size)
                    checkers.append(scheduler.TaskRunner(extend_task))
                    attach_task = VolumeAttachTask(self.stack, server_id,
                                                   vol.id, device)
                    checkers.append(scheduler.TaskRunner(attach_task))

                else:
                    extend_task = VolumeExtendTask(self.stack, vol.id,
                                                   new_size)
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
        return self.cinder().backups.create(self.resource_id)

    def check_snapshot_complete(self, backup):
        if backup.status == 'creating':
            backup.get()
            return False
        if backup.status == 'available':
            self.data_set('backup_id', backup.id)
            return True
        raise exception.Error(backup.status)

    def handle_delete_snapshot(self, snapshot):
        backup_id = snapshot['resource_data']['backup_id']

        def delete():
            client = self.cinder()
            try:
                backup = client.backups.get(backup_id)
                backup.delete()
                while True:
                    yield
                    backup.get()
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
        if self.properties.get(self.CINDER_SCHEDULER_HINTS) \
                and self.cinder().volume_api_version == 1:
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


def resource_mapping():
    return {
        'AWS::EC2::Volume': Volume,
        'AWS::EC2::VolumeAttachment': VolumeAttachment,
        'OS::Cinder::Volume': CinderVolume,
        'OS::Cinder::VolumeAttachment': CinderVolumeAttachment,
    }
