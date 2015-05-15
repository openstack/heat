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

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources import volume_base as vb


class Volume(vb.BaseVolume):

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
            immutable=True,
            constraints=[
                constraints.CustomConstraint('cinder.backup')
            ]
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


class VolumeAttachment(vb.BaseVolumeAttachment):
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


def resource_mapping():
    return {
        'AWS::EC2::Volume': Volume,
        'AWS::EC2::VolumeAttachment': VolumeAttachment,
    }
