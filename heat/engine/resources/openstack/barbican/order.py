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
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class Order(resource.Resource):
    """A resource allowing for the generation secret material by Barbican.

    The resource allows to generate some secret material. It can be, for
    example, some key or certificate. The order encapsulates the workflow
    and history for the creation of a secret. The time to generate a secret can
    vary depending on the type of secret.
    """

    support_status = support.SupportStatus(version='2014.2')

    default_client_name = 'barbican'

    entity = 'orders'

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
            required=True,
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        REQUEST_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The type of the certificate request.'),
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        SUBJECT_DN: properties.Schema(
            properties.Schema.STRING,
            _('The subject of the certificate request.'),
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        SOURCE_CONTAINER_REF: properties.Schema(
            properties.Schema.STRING,
            _('The source of certificate request.'),
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        CA_ID: properties.Schema(
            properties.Schema.STRING,
            _('The identifier of the CA to use.'),
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        PROFILE: properties.Schema(
            properties.Schema.STRING,
            _('The profile of certificate to use.'),
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        REQUEST_DATA: properties.Schema(
            properties.Schema.STRING,
            _('The content of the CSR.'),
            support_status=support.SupportStatus(version='5.0.0'),
        ),
        PASS_PHRASE: properties.Schema(
            properties.Schema.STRING,
            _('The passphrase the created key.'),
            support_status=support.SupportStatus(version='5.0.0'),
        ),
    }

    attributes_schema = {
        STATUS: attributes.Schema(
            _('The status of the order.'),
            type=attributes.Schema.STRING
        ),
        ORDER_REF: attributes.Schema(
            _('The URI to the order.'),
            type=attributes.Schema.STRING
        ),
        SECRET_REF: attributes.Schema(
            _('The URI to the created secret.'),
            type=attributes.Schema.STRING
        ),
        CONTAINER_REF: attributes.Schema(
            _('The URI to the created container.'),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.STRING
        ),
        PUBLIC_KEY: attributes.Schema(
            _('The payload of the created public key, if available.'),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.STRING
        ),
        PRIVATE_KEY: attributes.Schema(
            _('The payload of the created private key, if available.'),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.STRING
        ),
        CERTIFICATE: attributes.Schema(
            _('The payload of the created certificate, if available.'),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.STRING
        ),
        INTERMEDIATES: attributes.Schema(
            _('The payload of the created intermediates, if available.'),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        info = dict((k, v) for k, v in self.properties.items()
                    if v is not None)
        order = self.client().orders.create(**info)
        order_ref = order.submit()
        self.resource_id_set(order_ref)
        # NOTE(pshchelo): order_ref is HATEOAS reference, i.e a string
        # need not to be fixed re LP bug #1393268
        return order_ref

    def check_create_complete(self, order_href):
        order = self.client().orders.get(order_href)

        if order.status == 'ERROR':
            reason = order.error_reason
            code = order.error_status_code
            msg = (_("Order '%(name)s' failed: %(code)s - %(reason)s")
                   % {'name': self.name, 'code': code, 'reason': reason})
            raise exception.Error(msg)

        return order.status == 'ACTIVE'

    def _resolve_attribute(self, name):
        client = self.client()
        order = client.orders.get(self.resource_id)
        if name in (
                self.PUBLIC_KEY, self.PRIVATE_KEY, self.CERTIFICATE,
                self.INTERMEDIATES):
            container = client.containers.get(order.container_ref)
            secret = getattr(container, name)
            return secret.payload

        return getattr(order, name)

    # TODO(ochuprykov): remove this method when bug #1485619 will be fixed
    def _show_resource(self):
        order = self.client().orders.get(self.resource_id)
        info = order._get_formatted_entity()
        return dict(zip(info[0], info[1]))


def resource_mapping():
    return {
        'OS::Barbican::Order': Order,
    }
