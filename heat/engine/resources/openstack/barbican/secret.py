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

import six

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class Secret(resource.Resource):

    support_status = support.SupportStatus(version='2014.2')

    PROPERTIES = (
        NAME, PAYLOAD, PAYLOAD_CONTENT_TYPE, PAYLOAD_CONTENT_ENCODING,
        MODE, EXPIRATION, ALGORITHM, BIT_LENGTH,
    ) = (
        'name', 'payload', 'payload_content_type', 'payload_content_encoding',
        'mode', 'expiration', 'algorithm', 'bit_length',
    )

    ATTRIBUTES = (
        STATUS, DECRYPTED_PAYLOAD,
    ) = (
        'status', 'decrypted_payload',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Human readable name for the secret.'),
        ),
        PAYLOAD: properties.Schema(
            properties.Schema.STRING,
            _('The unencrypted plain text of the secret.'),
        ),
        PAYLOAD_CONTENT_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The type/format the secret data is provided in.'),
            constraints=[
                constraints.AllowedValues([
                    'text/plain',
                    'application/octet-stream',
                ]),
            ],
        ),
        PAYLOAD_CONTENT_ENCODING: properties.Schema(
            properties.Schema.STRING,
            _('The encoding format used to provide the payload data.'),
            constraints=[
                constraints.AllowedValues([
                    'base64',
                ]),
            ],
        ),
        EXPIRATION: properties.Schema(
            properties.Schema.STRING,
            _('The expiration date for the secret in ISO-8601 format.'),
            constraints=[
                constraints.CustomConstraint('iso_8601'),
            ],
        ),
        ALGORITHM: properties.Schema(
            properties.Schema.STRING,
            _('The algorithm type used to generate the secret.'),
        ),
        BIT_LENGTH: properties.Schema(
            properties.Schema.INTEGER,
            _('The bit-length of the secret.'),
            constraints=[
                constraints.Range(
                    min=0,
                ),
            ],
        ),
        MODE: properties.Schema(
            properties.Schema.STRING,
            _('The type/mode of the algorithm associated with the secret '
              'information.'),
        ),
    }

    attributes_schema = {
        STATUS: attributes.Schema(
            _('The status of the secret.')
        ),
        DECRYPTED_PAYLOAD: attributes.Schema(
            _('The decrypted secret payload.')
        ),
    }

    def barbican(self):
        return self.client('barbican')

    def handle_create(self):
        info = dict(self.properties)
        secret = self.barbican().secrets.create(**info)
        secret_ref = secret.store()
        self.resource_id_set(secret_ref)
        return secret_ref

    def handle_delete(self):
        if not self.resource_id:
            return

        client = self.barbican()
        try:
            client.secrets.delete(self.resource_id)
        except Exception as exc:
            # This is the only exception the client raises
            # Inspecting the message to see if it's a 'Not Found'
            if 'Not Found' not in six.text_type(exc):
                raise

    def _resolve_attribute(self, name):
        secret = self.barbican().secrets.get(self.resource_id)

        if name == self.DECRYPTED_PAYLOAD:
            return secret.payload

        if name == self.STATUS:
            return secret.status


def resource_mapping():
    return {
        'OS::Barbican::Secret': Secret,
    }
