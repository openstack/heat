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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class GenericContainer(resource.Resource):
    """A resource for creating Barbican generic container.

    A generic container is used for any type of secret that a user
    may wish to aggregate. There are no restrictions on the amount
    of secrets that can be held within this container.
    """

    support_status = support.SupportStatus(version='6.0.0')

    default_client_name = 'barbican'

    entity = 'containers'

    PROPERTIES = (
        NAME, SECRETS,
    ) = (
        'name', 'secrets',
    )

    ATTRIBUTES = (
        STATUS, CONTAINER_REF, SECRET_REFS, CONSUMERS,
    ) = (
        'status', 'container_ref', 'secret_refs', 'consumers',
    )

    _SECRETS_PROPERTIES = (
        NAME, REF,
    ) = (
        'name', 'ref'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Human-readable name for the container.'),
        ),
        SECRETS: properties.Schema(
            properties.Schema.LIST,
            _('References to secrets that will be stored in container.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('Name of the secret.'),
                        required=True
                    ),
                    REF: properties.Schema(
                        properties.Schema.STRING,
                        _('Reference to the secret.'),
                        required=True,
                        constraints=[constraints.CustomConstraint(
                            'barbican.secret')],
                    ),
                }
            ),
        ),
    }

    attributes_schema = {
        STATUS: attributes.Schema(
            _('The status of the container.'),
            type=attributes.Schema.STRING
        ),
        CONTAINER_REF: attributes.Schema(
            _('The URI to the container.'),
            type=attributes.Schema.STRING
        ),
        SECRET_REFS: attributes.Schema(
            _('The URIs to secrets stored in container.'),
            type=attributes.Schema.MAP
        ),
        CONSUMERS: attributes.Schema(
            _('The URIs to container consumers.'),
            type=attributes.Schema.LIST
        ),
    }

    def get_refs(self):
        secrets = self.properties.get(self.SECRETS) or []
        return [secret['ref'] for secret in secrets]

    def validate(self):
        super(GenericContainer, self).validate()
        refs = self.get_refs()
        if len(refs) != len(set(refs)):
            msg = _("Duplicate refs are not allowed.")
            raise exception.StackValidationFailed(message=msg)

    def create_container(self):
        if self.properties[self.SECRETS]:
            secrets = dict((secret['name'], secret['ref'])
                           for secret in self.properties[self.SECRETS])
        else:
            secrets = {}
        info = {'secret_refs': secrets}
        if self.properties[self.NAME] is not None:
            info.update({'name': self.properties[self.NAME]})
        return self.client_plugin().create_generic_container(**info)

    def handle_create(self):
        container_ref = self.create_container().store()
        self.resource_id_set(container_ref)
        return container_ref

    def check_create_complete(self, container_href):
        container = self.client().containers.get(container_href)

        if container.status == 'ERROR':
            reason = container.error_reason
            code = container.error_status_code
            msg = (_("Container '%(name)s' creation failed: "
                     "%(code)s - %(reason)s")
                   % {'name': self.name, 'code': code, 'reason': reason})
            raise exception.ResourceInError(
                status_reason=msg, resource_status=container.status)

        return container.status == 'ACTIVE'

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        container = self.client().containers.get(self.resource_id)
        return getattr(container, name, None)


class CertificateContainer(GenericContainer):
    """A resource for creating barbican certificate container.

    A certificate container is used for storing the secrets that
    are relevant to certificates.
    """

    PROPERTIES = (
        NAME, CERTIFICATE_REF, PRIVATE_KEY_REF,
        PRIVATE_KEY_PASSPHRASE_REF, INTERMEDIATES_REF,
    ) = (
        'name', 'certificate_ref', 'private_key_ref',
        'private_key_passphrase_ref', 'intermediates_ref',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Human-readable name for the container.'),
        ),
        CERTIFICATE_REF: properties.Schema(
            properties.Schema.STRING,
            _('Reference to certificate.'),
            constraints=[constraints.CustomConstraint('barbican.secret')],
        ),
        PRIVATE_KEY_REF: properties.Schema(
            properties.Schema.STRING,
            _('Reference to private key.'),
            constraints=[constraints.CustomConstraint('barbican.secret')],
        ),
        PRIVATE_KEY_PASSPHRASE_REF: properties.Schema(
            properties.Schema.STRING,
            _('Reference to private key passphrase.'),
            constraints=[constraints.CustomConstraint('barbican.secret')],
        ),
        INTERMEDIATES_REF: properties.Schema(
            properties.Schema.STRING,
            _('Reference to intermediates.'),
            constraints=[constraints.CustomConstraint('barbican.secret')],
        ),
    }

    def create_container(self):
        info = dict((k, v) for k, v in six.iteritems(self.properties)
                    if v is not None)
        return self.client_plugin().create_certificate(**info)

    def get_refs(self):
        return [v for k, v in six.iteritems(self.properties)
                if (k != self.NAME and v is not None)]


class RSAContainer(GenericContainer):
    """A resource for creating barbican RSA container.

    An RSA container is used for storing RSA public keys, private keys,
    and private key pass phrases.
    """

    PROPERTIES = (
        NAME, PRIVATE_KEY_REF, PRIVATE_KEY_PASSPHRASE_REF,
        PUBLIC_KEY_REF,
    ) = (
        'name', 'private_key_ref', 'private_key_passphrase_ref',
        'public_key_ref',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Human-readable name for the container.'),
        ),
        PRIVATE_KEY_REF: properties.Schema(
            properties.Schema.STRING,
            _('Reference to private key.'),
            constraints=[constraints.CustomConstraint('barbican.secret')],
        ),
        PRIVATE_KEY_PASSPHRASE_REF: properties.Schema(
            properties.Schema.STRING,
            _('Reference to private key passphrase.'),
            constraints=[constraints.CustomConstraint('barbican.secret')],
        ),
        PUBLIC_KEY_REF: properties.Schema(
            properties.Schema.STRING,
            _('Reference to public key.'),
            constraints=[constraints.CustomConstraint('barbican.secret')],
        ),
    }

    def create_container(self):
        info = dict((k, v) for k, v in six.iteritems(self.properties)
                    if v is not None)
        return self.client_plugin().create_rsa(**info)

    def get_refs(self):
        return [v for k, v in six.iteritems(self.properties)
                if (k != self.NAME and v is not None)]


def resource_mapping():
    return {
        'OS::Barbican::GenericContainer': GenericContainer,
        'OS::Barbican::CertificateContainer': CertificateContainer,
        'OS::Barbican::RSAContainer': RSAContainer
    }
