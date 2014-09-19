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
from heat.engine import resource


class GlanceImage(resource.Resource):
    '''
    A resource managing for image in Glance.
    '''

    PROPERTIES = (
        NAME, IMAGE_ID, IS_PUBLIC, MIN_DISK, MIN_RAM, PROTECTED,
        DISK_FORMAT, CONTAINER_FORMAT, LOCATION
    ) = (
        'name', 'id', 'is_public', 'min_disk', 'min_ram', 'protected',
        'disk_format', 'container_format', 'location'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the image. The name of an image is not '
              'unique to a Image Service node.')
        ),
        IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _('The image ID. Glance will generate a UUID if not specified.')
        ),
        IS_PUBLIC: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Scope of image accessibility. Public or private. '
              'Default value is False means private.'),
            default=False,
        ),
        MIN_DISK: properties.Schema(
            properties.Schema.INTEGER,
            _('Amount of disk space (in GB) required to boot image. '
              'Default value is 0 if not specified '
              'and means no limit on the disk size.'),
            constraints=[
                constraints.Range(min=0),
            ]
        ),
        MIN_RAM: properties.Schema(
            properties.Schema.INTEGER,
            _('Amount of ram (in MB) required to boot image. Default value '
              'is 0 if not specified and means no limit on the ram size.'),
            constraints=[
                constraints.Range(min=0),
            ]
        ),
        PROTECTED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether the image can be deleted. If the value is True, '
              'the image is protected and cannot be deleted.')
        ),
        DISK_FORMAT: properties.Schema(
            properties.Schema.STRING,
            _('Disk format of image.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['ami', 'ari', 'aki',
                                           'vhd', 'vmdk', 'raw',
                                           'qcow2', 'vdi', 'iso'])
            ]
        ),
        CONTAINER_FORMAT: properties.Schema(
            properties.Schema.STRING,
            _('Container format of image.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['ami', 'ari', 'aki',
                                           'bare', 'ova', 'ovf'])
            ]
        ),
        LOCATION: properties.Schema(
            properties.Schema.STRING,
            _('URL where the data for this image already resides. For '
              'example, if the image data is stored in swift, you could '
              'specify "swift://example.com/container/obj".'),
            required=True,
        ),
    }

    default_client_name = 'glance'

    def handle_create(self):
        args = dict((k, v) for k, v in self.properties.items()
                    if v is not None)
        image_id = self.glance().images.create(**args).id
        self.resource_id_set(image_id)
        return image_id

    def check_create_complete(self, image_id):
        image = self.glance().images.get(image_id)
        return image.status == 'active'

    def handle_delete(self):
        if self.resource_id is None:
            return

        try:
            self.glance().images.delete(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)


def resource_mapping():
    return {
        'OS::Glance::Image': GlanceImage
    }
