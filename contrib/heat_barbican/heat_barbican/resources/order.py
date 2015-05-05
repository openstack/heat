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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import clients
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class Order(resource.Resource):

    PROPERTIES = (
        NAME, PAYLOAD_CONTENT_TYPE, MODE, EXPIRATION,
        ALGORITHM, BIT_LENGTH, TYPE, REQUEST_TYPE, SUBJECT_DN,
        SOURCE_CONTAINER_REF, CA_ID, PROFILE, REQUEST_DATA,
        PASS_PHRASE
    ) = (
        'name', 'payload_content_type', 'mode', 'expiration',
        'algorithm', 'bit_length', 'type', 'request_type', 'subject_dn',
        'source_container_ref', 'ca_id', 'profile', 'request_data',
        'pass_phrase'
    )

    ATTRIBUTES = (
        STATUS, ORDER_REF, SECRET_REF, PUBLIC_KEY, PRIVATE_KEY,
        CERTIFICATE, INTERMEDIATES, CONTAINER_REF
    ) = (
        'status', 'order_ref', 'secret_ref', 'public_key', 'private_key',
        'certificate', 'intermediates', 'container_ref'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Human readable name for the secret.'),
        ),
        PAYLOAD_CONTENT_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The type/format the secret data is provided in.'),
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
        ),
        MODE: properties.Schema(
            properties.Schema.STRING,
            _('The type/mode of the algorithm associated with the secret '
              'information.'),
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The type of the order.'),
            constraints=[
                constraints.AllowedValues([
                    'key', 'asymmetric', 'certificate'
                ]),
            ],
            support_status=support.SupportStatus(version='2015.2'),
        ),
        REQUEST_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The type of the certificate request.'),
            support_status=support.SupportStatus(version='2015.2'),
        ),
        SUBJECT_DN: properties.Schema(
            properties.Schema.STRING,
            _('The subject of the certificate request.'),
            support_status=support.SupportStatus(version='2015.2'),
        ),
        SOURCE_CONTAINER_REF: properties.Schema(
            properties.Schema.STRING,
            _('The source of certificate request.'),
            support_status=support.SupportStatus(version='2015.2'),
        ),
        CA_ID: properties.Schema(
            properties.Schema.STRING,
            _('The identifier of the CA to use.'),
            support_status=support.SupportStatus(version='2015.2'),
        ),
        PROFILE: properties.Schema(
            properties.Schema.STRING,
            _('The profile of certificate to use.'),
            support_status=support.SupportStatus(version='2015.2'),
        ),
        REQUEST_DATA: properties.Schema(
            properties.Schema.STRING,
            _('The content of the CSR.'),
            support_status=support.SupportStatus(version='2015.2'),
        ),
        PASS_PHRASE: properties.Schema(
            properties.Schema.STRING,
            _('The passphrase the created key.'),
            support_status=support.SupportStatus(version='2015.2'),
        ),
    }

    attributes_schema = {
        STATUS: attributes.Schema(_('The status of the order.')),
        ORDER_REF: attributes.Schema(_('The URI to the order.')),
        SECRET_REF: attributes.Schema(_('The URI to the created secret.')),
        CONTAINER_REF: attributes.Schema(
            _('The URI to the created container.'),
            support_status=support.SupportStatus(version='2015.2')),
        PUBLIC_KEY: attributes.Schema(
            _('The payload of the created public key, if available.'),
            support_status=support.SupportStatus(version='2015.2')),
        PRIVATE_KEY: attributes.Schema(
            _('The payload of the created private key, if available.'),
            support_status=support.SupportStatus(version='2015.2')),
        CERTIFICATE: attributes.Schema(
            _('The payload of the created certificate, if available.'),
            support_status=support.SupportStatus(version='2015.2')),
        INTERMEDIATES: attributes.Schema(
            _('The payload of the created intermediates, if available.'),
            support_status=support.SupportStatus(version='2015.2')),
    }

    def barbican(self):
        return self.client('barbican')

    def handle_create(self):
        info = dict((k, v) for k, v in self.properties.items()
                    if v is not None)
        order = self.barbican().orders.create(**info)
        order_ref = order.submit()
        self.resource_id_set(order_ref)
        return order_ref

    def check_create_complete(self, order_href):
        order = self.barbican().orders.get(order_href)

        if order.status == 'ERROR':
            reason = order.error_reason
            code = order.error_status_code
            msg = (_("Order '%(name)s' failed: %(code)s - %(reason)s")
                   % {'name': self.name, 'code': code, 'reason': reason})
            raise exception.Error(msg)

        return order.status == 'ACTIVE'

    def handle_delete(self):
        if not self.resource_id:
            return

        client = self.barbican()
        try:
            client.orders.delete(self.resource_id)
        except Exception as exc:
            # This is the only exception the client raises
            # Inspecting the message to see if it's a 'Not Found'
            if 'Not Found' not in six.text_type(exc):
                raise

    def _resolve_attribute(self, name):
        client = self.barbican()
        order = client.orders.get(self.resource_id)
        if name in (
                self.PUBLIC_KEY, self.PRIVATE_KEY, self.CERTIFICATE,
                self.INTERMEDIATES):
            container = client.containers.get(order.container_ref)
            secret = getattr(container, name)
            return secret.payload

        return getattr(order, name)


def resource_mapping():
    return {
        'OS::Barbican::Order': Order,
    }


def available_resource_mapping():
    if not clients.has_client('barbican'):
        return {}

    return resource_mapping()
