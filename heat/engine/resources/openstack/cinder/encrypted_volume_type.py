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
from heat.engine import support


class CinderEncryptedVolumeType(resource.Resource):
    """A resource for encrypting a cinder volume type.

    A Volume Encryption Type is a collection of settings used to conduct
    encryption for a specific volume type.

    Note that default cinder security policy usage of this resource
    is limited to being used by administrators only.
    """

    support_status = support.SupportStatus(version='5.0.0')

    default_client_name = 'cinder'

    entity = 'volume_encryption_types'

    required_service_extension = 'encryption'

    PROPERTIES = (
        PROVIDER, CONTROL_LOCATION, CIPHER, KEY_SIZE, VOLUME_TYPE
    ) = (
        'provider', 'control_location', 'cipher', 'key_size', 'volume_type'
    )

    properties_schema = {
        PROVIDER: properties.Schema(
            properties.Schema.STRING,
            _('The class that provides encryption support. '
              'For example, nova.volume.encryptors.luks.LuksEncryptor.'),
            required=True,
            update_allowed=True
        ),
        CONTROL_LOCATION: properties.Schema(
            properties.Schema.STRING,
            _('Notional service where encryption is performed '
              'For example, front-end. For Nova.'),
            constraints=[
                constraints.AllowedValues(['front-end', 'back-end'])
            ],
            default='front-end',
            update_allowed=True
        ),
        CIPHER: properties.Schema(
            properties.Schema.STRING,
            _('The encryption algorithm or mode. '
              'For example, aes-xts-plain64.'),
            constraints=[
                constraints.AllowedValues(
                    ['aes-xts-plain64', 'aes-cbc-essiv']
                )
            ],
            default=None,
            update_allowed=True
        ),
        KEY_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Size of encryption key, in bits. '
              'For example, 128 or 256.'),
            default=None,
            update_allowed=True
        ),
        VOLUME_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Name or id of volume type (OS::Cinder::VolumeType).'),
            required=True,
            constraints=[constraints.CustomConstraint('cinder.vtype')]
        ),
    }

    def _get_vol_type_id(self, volume_type):
        id = self.client_plugin().get_volume_type(volume_type)
        return id

    def handle_create(self):
        body = {
            'provider': self.properties[self.PROVIDER],
            'cipher': self.properties[self.CIPHER],
            'key_size': self.properties[self.KEY_SIZE],
            'control_location': self.properties[self.CONTROL_LOCATION]
        }

        vol_type_id = self._get_vol_type_id(self.properties[self.VOLUME_TYPE])

        encrypted_vol_type = self.client().volume_encryption_types.create(
            volume_type=vol_type_id, specs=body
        )
        self.resource_id_set(encrypted_vol_type.volume_type_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().volume_encryption_types.update(
                volume_type=self.resource_id, specs=prop_diff
            )

    def get_live_resource_data(self):
        try:
            resource_data = self._show_resource()
            if not resource_data:
                # use attribute error, e.g. API call get raises AttributeError,
                # when evt is not exists or not ready (cinder bug 1562024).
                raise AttributeError()
        except Exception as ex:
            if (self.client_plugin().is_not_found(ex) or
                    isinstance(ex, AttributeError)):
                raise exception.EntityNotFound(entity='Resource',
                                               name=self.name)
            raise
        return resource_data

    def parse_live_resource_data(self, resource_properties, resource_data):
        resource_reality = {}

        for key in set(self.PROPERTIES) - {self.VOLUME_TYPE}:
            resource_reality.update({key: resource_data.get(key)})

        return resource_reality


def resource_mapping():
    return {
        'OS::Cinder::EncryptedVolumeType': CinderEncryptedVolumeType
    }
