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
from heat.engine import attributes
from heat.engine.clients import progress
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources import scheduler_hints as sh
from heat.engine.resources import volume_base as vb
from heat.engine import support
from heat.engine import translation

LOG = logging.getLogger(__name__)


class CinderVolume(vb.BaseVolume, sh.SchedulerHintsMixin):
    """A resource that implements Cinder volumes.

    Cinder volume is a storage in the form of block devices. It can be used,
    for example, for providing storage to instance. Volume supports creation
    from snapshot, backup or image. Also volume can be created only by size.
    """

    PROPERTIES = (
        AVAILABILITY_ZONE, SIZE, SNAPSHOT_ID, BACKUP_ID, NAME,
        DESCRIPTION, VOLUME_TYPE, METADATA, IMAGE_REF, IMAGE,
        SOURCE_VOLID, CINDER_SCHEDULER_HINTS, READ_ONLY, MULTI_ATTACH,
    ) = (
        'availability_zone', 'size', 'snapshot_id', 'backup_id', 'name',
        'description', 'volume_type', 'metadata', 'imageRef', 'image',
        'source_volid', 'scheduler_hints', 'read_only', 'multiattach',
    )

    ATTRIBUTES = (
        AVAILABILITY_ZONE_ATTR, SIZE_ATTR, SNAPSHOT_ID_ATTR, DISPLAY_NAME_ATTR,
        DISPLAY_DESCRIPTION_ATTR, VOLUME_TYPE_ATTR, METADATA_ATTR,
        SOURCE_VOLID_ATTR, STATUS, CREATED_AT, BOOTABLE, METADATA_VALUES_ATTR,
        ENCRYPTED_ATTR, ATTACHMENTS, ATTACHMENTS_LIST, MULTI_ATTACH_ATTR,
    ) = (
        'availability_zone', 'size', 'snapshot_id', 'display_name',
        'display_description', 'volume_type', 'metadata',
        'source_volid', 'status', 'created_at', 'bootable', 'metadata_values',
        'encrypted', 'attachments', 'attachments_list', 'multiattach',
    )

    properties_schema = {
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('The availability zone in which the volume will be created.')
        ),
        SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('The size of the volume in GB. '
              'On update only increase in size is supported. This property '
              'is required unless property %(backup)s or %(vol)s or '
              '%(snapshot)s is specified.')
            % dict(backup=BACKUP_ID,
                   vol=SOURCE_VOLID,
                   snapshot=SNAPSHOT_ID),
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
            _('If specified, the backup to create the volume from.'),
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('cinder.backup')
            ]
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
            default={}
        ),
        IMAGE_REF: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the image to create the volume from.'),
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                message=_('Use property %s.') % IMAGE,
                version='5.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='2014.1'
                )
            )
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
        READ_ONLY: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Enables or disables read-only access mode of volume.'),
            support_status=support.SupportStatus(version='5.0.0'),
            update_allowed=True,
        ),
        MULTI_ATTACH: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether allow the volume to be attached more than once.'),
            support_status=support.SupportStatus(version='6.0.0'),
            default=False
        ),
    }

    attributes_schema = {
        AVAILABILITY_ZONE_ATTR: attributes.Schema(
            _('The availability zone in which the volume is located.'),
            type=attributes.Schema.STRING
        ),
        SIZE_ATTR: attributes.Schema(
            _('The size of the volume in GB.'),
            type=attributes.Schema.STRING
        ),
        SNAPSHOT_ID_ATTR: attributes.Schema(
            _('The snapshot the volume was created from, if any.'),
            type=attributes.Schema.STRING
        ),
        DISPLAY_NAME_ATTR: attributes.Schema(
            _('Name of the volume.'),
            type=attributes.Schema.STRING
        ),
        DISPLAY_DESCRIPTION_ATTR: attributes.Schema(
            _('Description of the volume.'),
            type=attributes.Schema.STRING
        ),
        VOLUME_TYPE_ATTR: attributes.Schema(
            _('The type of the volume mapping to a backend, if any.'),
            type=attributes.Schema.STRING
        ),
        METADATA_ATTR: attributes.Schema(
            _('Key/value pairs associated with the volume.'),
            type=attributes.Schema.STRING
        ),
        SOURCE_VOLID_ATTR: attributes.Schema(
            _('The volume used as source, if any.'),
            type=attributes.Schema.STRING
        ),
        STATUS: attributes.Schema(
            _('The current status of the volume.'),
            type=attributes.Schema.STRING
        ),
        CREATED_AT: attributes.Schema(
            _('The timestamp indicating volume creation.'),
            type=attributes.Schema.STRING
        ),
        BOOTABLE: attributes.Schema(
            _('Boolean indicating if the volume can be booted or not.'),
            type=attributes.Schema.STRING
        ),
        METADATA_VALUES_ATTR: attributes.Schema(
            _('Key/value pairs associated with the volume in raw dict form.'),
            type=attributes.Schema.MAP
        ),
        ENCRYPTED_ATTR: attributes.Schema(
            _('Boolean indicating if the volume is encrypted or not.'),
            type=attributes.Schema.STRING
        ),
        ATTACHMENTS: attributes.Schema(
            _('A string representation of the list of attachments of the '
              'volume.'),
            type=attributes.Schema.STRING,
            cache_mode=attributes.Schema.CACHE_NONE,
            support_status=support.SupportStatus(
                status=support.DEPRECATED,
                message=_('Use property %s.') % ATTACHMENTS_LIST,
                version='9.0.0',
                previous_status=support.SupportStatus(
                    status=support.SUPPORTED,
                    version='2015.1'
                )
            )
        ),
        ATTACHMENTS_LIST: attributes.Schema(
            _('The list of attachments of the volume.'),
            type=attributes.Schema.LIST,
            cache_mode=attributes.Schema.CACHE_NONE,
            support_status=support.SupportStatus(version='9.0.0'),
        ),
        MULTI_ATTACH_ATTR: attributes.Schema(
            _('Boolean indicating whether allow the volume to be attached '
              'more than once.'),
            type=attributes.Schema.BOOLEAN,
            support_status=support.SupportStatus(version='6.0.0'),
        ),
    }

    _volume_creating_status = ['creating', 'restoring-backup', 'downloading']

    entity = 'volumes'

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.IMAGE],
                value_path=[self.IMAGE_REF]
            )
        ]

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
            self.properties[self.CINDER_SCHEDULER_HINTS])
        if scheduler_hints:
            arguments[self.CINDER_SCHEDULER_HINTS] = scheduler_hints

        if self.properties[self.IMAGE]:
            arguments['imageRef'] = self.client_plugin(
                'glance').find_image_by_name_or_id(
                self.properties[self.IMAGE])
        elif self.properties[self.IMAGE_REF]:
            arguments['imageRef'] = self.properties[self.IMAGE_REF]

        optionals = (self.SNAPSHOT_ID, self.VOLUME_TYPE, self.SOURCE_VOLID,
                     self.METADATA, self.MULTI_ATTACH)

        arguments.update((prop, self.properties[prop]) for prop in optionals
                         if self.properties[prop] is not None)

        return arguments

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        cinder = self.client()
        vol = cinder.volumes.get(self.resource_id)
        if name == self.METADATA_ATTR:
            return six.text_type(jsonutils.dumps(vol.metadata))
        elif name == self.METADATA_VALUES_ATTR:
            return vol.metadata
        if name == self.DISPLAY_NAME_ATTR:
            return vol.name
        elif name == self.DISPLAY_DESCRIPTION_ATTR:
            return vol.description
        elif name == self.ATTACHMENTS_LIST:
            return vol.attachments
        return six.text_type(getattr(vol, name))

    def check_create_complete(self, vol_id):
        complete = super(CinderVolume, self).check_create_complete(vol_id)
        # Cinder just supports update read only for volume in available,
        # if we update in handle_create(), maybe the volume still in
        # creating, then cinder will raise an exception
        if complete:
            self._store_config_default_properties()
            self._update_read_only(self.properties[self.READ_ONLY])

        return complete

    def _store_config_default_properties(self, attributes=None):
        """Method for storing default values of properties in resource data.

        Some properties have default values, specified in project configuration
        file, so cannot be hardcoded into properties_schema, but should be
        stored for further using. So need to get created resource and take
        required property's value.
        """
        if attributes is None:
            attributes = self._show_resource()

        if attributes.get('volume_type') is not None:
            self.data_set(self.VOLUME_TYPE, attributes['volume_type'])
        else:
            self.data_delete(self.VOLUME_TYPE)

    def _extend_volume(self, new_size):
        try:
            self.client().volumes.extend(self.resource_id, new_size)
        except Exception as ex:
            if self.client_plugin().is_client_exception(ex):
                raise exception.Error(_(
                    "Failed to extend volume %(vol)s - %(err)s") % {
                        'vol': self.resource_id, 'err': six.text_type(ex)})
            else:
                raise
        return True

    def _update_read_only(self, read_only_flag):
        if read_only_flag is not None:
            self.client().volumes.update_readonly_flag(self.resource_id,
                                                       read_only_flag)

        return True

    def _check_extend_volume_complete(self):
        vol = self.client().volumes.get(self.resource_id)
        if vol.status == 'extending':
            LOG.debug("Volume %s is being extended", vol.id)
            return False

        if vol.status != 'available':
            LOG.info("Resize failed: Volume %(vol)s "
                     "is in %(status)s state.",
                     {'vol': vol.id, 'status': vol.status})
            raise exception.ResourceUnknownStatus(
                resource_status=vol.status,
                result=_('Volume resize failed'))

        LOG.info('Volume %(id)s resize complete', {'id': vol.id})
        return True

    def _backup_restore(self, vol_id, backup_id):
        try:
            self.client().restores.restore(backup_id, vol_id)
        except Exception as ex:
            if self.client_plugin().is_client_exception(ex):
                raise exception.Error(_(
                    "Failed to restore volume %(vol)s from backup %(backup)s "
                    "- %(err)s") % {'vol': vol_id,
                                    'backup': backup_id,
                                    'err': ex})
            else:
                raise
        return True

    def _check_backup_restore_complete(self):
        vol = self.client().volumes.get(self.resource_id)
        if vol.status == 'restoring-backup':
            LOG.debug("Volume %s is being restoring from backup", vol.id)
            return False

        if vol.status != 'available':
            LOG.info("Restore failed: Volume %(vol)s is in %(status)s "
                     "state.", {'vol': vol.id, 'status': vol.status})
            raise exception.ResourceUnknownStatus(
                resource_status=vol.status,
                result=_('Volume backup restore failed'))

        LOG.info('Volume %s backup restore complete', vol.id)
        return True

    def needs_replace_failed(self):
        if not self.resource_id:
            return True

        with self.client_plugin().ignore_not_found:
            vol = self.client().volumes.get(self.resource_id)
            return vol.status in ('error', 'deleting')

        return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        vol = None
        cinder = self.client()
        prg_resize = None
        prg_attach = None
        prg_detach = None
        prg_restore = None
        prg_access = None

        # update the name and description for cinder volume
        if self.NAME in prop_diff or self.DESCRIPTION in prop_diff:
            vol = cinder.volumes.get(self.resource_id)
            update_name = (prop_diff.get(self.NAME) or
                           self.properties[self.NAME])
            update_description = (prop_diff.get(self.DESCRIPTION) or
                                  self.properties[self.DESCRIPTION])
            kwargs = self._fetch_name_and_description(update_name,
                                                      update_description)
            cinder.volumes.update(vol, **kwargs)
        # update the metadata for cinder volume
        if self.METADATA in prop_diff:
            if not vol:
                vol = cinder.volumes.get(self.resource_id)
            metadata = prop_diff.get(self.METADATA)
            cinder.volumes.update_all_metadata(vol, metadata)
        # retype
        if self.VOLUME_TYPE in prop_diff:
            if not vol:
                vol = cinder.volumes.get(self.resource_id)
            new_vol_type = prop_diff.get(self.VOLUME_TYPE)
            cinder.volumes.retype(vol, new_vol_type, 'never')
        # update read_only access mode
        if self.READ_ONLY in prop_diff:
            if not vol:
                vol = cinder.volumes.get(self.resource_id)
            flag = prop_diff.get(self.READ_ONLY)
            prg_access = progress.VolumeUpdateAccessModeProgress(
                read_only=flag)
            prg_detach, prg_attach = self._detach_attach_progress(vol)
        # restore the volume from backup
        if self.BACKUP_ID in prop_diff:
            if not vol:
                vol = cinder.volumes.get(self.resource_id)
            prg_restore = progress.VolumeBackupRestoreProgress(
                vol_id=self.resource_id,
                backup_id=prop_diff.get(self.BACKUP_ID))
            prg_detach, prg_attach = self._detach_attach_progress(vol)
        # extend volume size
        if self.SIZE in prop_diff:
            if not vol:
                vol = cinder.volumes.get(self.resource_id)

            new_size = prop_diff[self.SIZE]
            if new_size < vol.size:
                raise exception.NotSupported(feature=_("Shrinking volume"))

            elif new_size > vol.size:
                prg_resize = progress.VolumeResizeProgress(size=new_size)
                prg_detach, prg_attach = self._detach_attach_progress(vol)

        return prg_restore, prg_detach, prg_resize, prg_access, prg_attach

    def _detach_attach_progress(self, vol):
        prg_attach = None
        prg_detach = None
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
            prg_detach = progress.VolumeDetachProgress(
                server_id, vol.id, attachment_id)
            prg_attach = progress.VolumeAttachProgress(
                server_id, vol.id, device)

        return prg_detach, prg_attach

    def _detach_volume_to_complete(self, prg_detach):
        if not prg_detach.called:
            self.client_plugin('nova').detach_volume(prg_detach.srv_id,
                                                     prg_detach.attach_id)
            prg_detach.called = True
            return False
        if not prg_detach.cinder_complete:
            prg_detach.cinder_complete = self.client_plugin(
            ).check_detach_volume_complete(prg_detach.vol_id,
                                           prg_detach.srv_id)
            return False
        if not prg_detach.nova_complete:
            prg_detach.nova_complete = self.client_plugin(
                'nova').check_detach_volume_complete(prg_detach.srv_id,
                                                     prg_detach.attach_id)
            return False

    def _attach_volume_to_complete(self, prg_attach):
        if not prg_attach.called:
            prg_attach.called = self.client_plugin('nova').attach_volume(
                prg_attach.srv_id, prg_attach.vol_id, prg_attach.device)
            return False
        if not prg_attach.complete:
            prg_attach.complete = self.client_plugin(
            ).check_attach_volume_complete(prg_attach.vol_id)
            return prg_attach.complete

    def check_update_complete(self, checkers):
        prg_restore, prg_detach, prg_resize, prg_access, prg_attach = checkers
        # detach volume
        if prg_detach:
            if not prg_detach.nova_complete:
                self._detach_volume_to_complete(prg_detach)
                return False
        if prg_restore:
            if not prg_restore.called:
                prg_restore.called = self._backup_restore(
                    prg_restore.vol_id,
                    prg_restore.backup_id)
                return False
            if not prg_restore.complete:
                prg_restore.complete = self._check_backup_restore_complete()
                return prg_restore.complete and not prg_resize
        # resize volume
        if prg_resize:
            if not prg_resize.called:
                prg_resize.called = self._extend_volume(prg_resize.size)
                return False
            if not prg_resize.complete:
                prg_resize.complete = self._check_extend_volume_complete()
                return prg_resize.complete and not prg_attach
        # update read_only access mode
        if prg_access:
            if not prg_access.called:
                prg_access.called = self._update_read_only(
                    prg_access.read_only)
                return False
        # reattach volume back
        if prg_attach:
            return self._attach_volume_to_complete(prg_attach)
        return True

    def handle_snapshot(self):
        backup = self.client().backups.create(self.resource_id, force=True)
        self.data_set('backup_id', backup.id)
        return backup.id

    def check_snapshot_complete(self, backup_id):
        backup = self.client().backups.get(backup_id)
        if backup.status == 'creating':
            return False
        if backup.status == 'available':
            return True
        raise exception.Error(backup.fail_reason)

    def handle_delete_snapshot(self, snapshot):
        backup_id = snapshot['resource_data'].get('backup_id')
        if not backup_id:
            return
        try:
            self.client().backups.delete(backup_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return
        else:
            return backup_id

    def check_delete_snapshot_complete(self, backup_id):
        if not backup_id:
            return True
        try:
            self.client().backups.get(backup_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return True
        else:
            return False

    def _build_exclusive_options(self):
        exclusive_options = []
        allow_no_size_options = []
        if self.properties.get(self.SNAPSHOT_ID):
            exclusive_options.append(self.SNAPSHOT_ID)
            allow_no_size_options.append(self.SNAPSHOT_ID)
        if self.properties.get(self.SOURCE_VOLID):
            exclusive_options.append(self.SOURCE_VOLID)
            allow_no_size_options.append(self.SOURCE_VOLID)
        if self.properties.get(self.IMAGE):
            exclusive_options.append(self.IMAGE)
        if self.properties.get(self.IMAGE_REF):
            exclusive_options.append(self.IMAGE_REF)
        return exclusive_options, allow_no_size_options

    def _validate_create_sources(self):
        exclusive_options, allow_no_size_ops = self._build_exclusive_options()
        size = self.properties.get(self.SIZE)
        if (size is None and
                (len(allow_no_size_ops) != 1 or len(exclusive_options) != 1)):
            msg = (_('If neither "%(backup_id)s" nor "%(size)s" is '
                     'provided, one and only one of "%(source_vol)s", '
                     '"%(snapshot_id)s" must be specified, but currently '
                     'specified options: %(exclusive_options)s.')
                   % {'backup_id': self.BACKUP_ID,
                      'size': self.SIZE,
                      'source_vol': self.SOURCE_VOLID,
                      'snapshot_id': self.SNAPSHOT_ID,
                      'exclusive_options': exclusive_options})
            raise exception.StackValidationFailed(message=msg)
        elif size and len(exclusive_options) > 1:
            msg = (_('If "%(size)s" is provided, only one of '
                     '"%(image)s", "%(image_ref)s", "%(source_vol)s", '
                     '"%(snapshot_id)s" can be specified, but currently '
                     'specified options: %(exclusive_options)s.')
                   % {'size': self.SIZE,
                      'image': self.IMAGE,
                      'image_ref': self.IMAGE_REF,
                      'source_vol': self.SOURCE_VOLID,
                      'snapshot_id': self.SNAPSHOT_ID,
                      'exclusive_options': exclusive_options})
            raise exception.StackValidationFailed(message=msg)

    def validate(self):
        """Validate provided params."""
        res = super(CinderVolume, self).validate()
        if res is not None:
            return res

        # can not specify both image and imageRef
        image = self.properties.get(self.IMAGE)
        imageRef = self.properties.get(self.IMAGE_REF)
        if image and imageRef:
            raise exception.ResourcePropertyConflict(self.IMAGE,
                                                     self.IMAGE_REF)
        # if not create from backup, need to check other create sources
        if not self.properties.get(self.BACKUP_ID):
            self._validate_create_sources()

    def handle_restore(self, defn, restore_data):
        backup_id = restore_data['resource_data']['backup_id']
        # we can't ignore 'size' property: if user update the size
        # of volume after snapshot, we need to change to old size
        # when restore the volume.
        ignore_props = (
            self.IMAGE_REF, self.IMAGE, self.SOURCE_VOLID)
        props = dict(
            (key, value) for (key, value) in
            self.properties.data.items()
            if key not in ignore_props and value is not None)
        props[self.BACKUP_ID] = backup_id
        return defn.freeze(properties=props)

    def parse_live_resource_data(self, resource_properties, resource_data):
        volume_reality = {}

        if (resource_data.get(self.METADATA) and
                resource_data.get(self.METADATA).get(
                    'readonly') is not None):
            read_only = resource_data.get(self.METADATA).pop('readonly')
            volume_reality.update({self.READ_ONLY: read_only})

        old_vt = self.data().get(self.VOLUME_TYPE)
        new_vt = resource_data.get(self.VOLUME_TYPE)
        if old_vt != new_vt:
            volume_reality.update({self.VOLUME_TYPE: new_vt})
            self._store_config_default_properties(dict(volume_type=new_vt))

        props_keys = [self.SIZE, self.NAME, self.DESCRIPTION,
                      self.METADATA, self.BACKUP_ID]
        for key in props_keys:
            volume_reality.update({key: resource_data.get(key)})

        return volume_reality


class CinderVolumeAttachment(vb.BaseVolumeAttachment):
    """Resource for associating volume to instance.

    Resource for associating existing volume to instance. Also, the location
    where the volume is exposed on the instance can be specified.
    """

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
        prg_attach = None
        prg_detach = None
        if prop_diff:
            # Even though some combinations of changed properties
            # could be updated in UpdateReplace manner,
            # we still first detach the old resource so that
            # self.resource_id is not replaced prematurely
            volume_id = self.properties[self.VOLUME_ID]
            server_id = self.properties[self.INSTANCE_ID]
            self.client_plugin('nova').detach_volume(server_id,
                                                     self.resource_id)
            prg_detach = progress.VolumeDetachProgress(
                server_id, volume_id, self.resource_id)
            prg_detach.called = True

            if self.VOLUME_ID in prop_diff:
                volume_id = prop_diff.get(self.VOLUME_ID)

            device = (self.properties[self.DEVICE]
                      if self.properties[self.DEVICE] else None)
            if self.DEVICE in prop_diff:
                device = (prop_diff[self.DEVICE]
                          if prop_diff[self.DEVICE] else None)

            if self.INSTANCE_ID in prop_diff:
                server_id = prop_diff.get(self.INSTANCE_ID)
            prg_attach = progress.VolumeAttachProgress(
                server_id, volume_id, device)

        return prg_detach, prg_attach

    def check_update_complete(self, checkers):
        prg_detach, prg_attach = checkers
        if not (prg_detach and prg_attach):
            return True
        if not prg_detach.cinder_complete:
            prg_detach.cinder_complete = self.client_plugin(
            ).check_detach_volume_complete(prg_detach.vol_id,
                                           prg_detach.srv_id)
            return False
        if not prg_detach.nova_complete:
            prg_detach.nova_complete = self.client_plugin(
                'nova').check_detach_volume_complete(prg_detach.srv_id,
                                                     self.resource_id)
            return False
        if not prg_attach.called:
            prg_attach.called = self.client_plugin('nova').attach_volume(
                prg_attach.srv_id, prg_attach.vol_id, prg_attach.device)
            return False
        if not prg_attach.complete:
            prg_attach.complete = self.client_plugin(
            ).check_attach_volume_complete(prg_attach.vol_id)
            if prg_attach.complete:
                self.resource_id_set(prg_attach.called)
            return prg_attach.complete
        return True


def resource_mapping():
    return {
        'OS::Cinder::Volume': CinderVolume,
        'OS::Cinder::VolumeAttachment': CinderVolumeAttachment,
    }
