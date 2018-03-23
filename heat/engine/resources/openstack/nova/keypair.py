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
from heat.engine import translation


NOVA_MICROVERSIONS = (MICROVERSION_KEY_TYPE,
                      MICROVERSION_USER) = ('2.2', '2.10')


class KeyPair(resource.Resource):
    """A resource for creating Nova key pairs.

    A keypair is a ssh key that can be injected into a server on launch.

    **Note** that if a new key is generated setting `save_private_key` to
    `True` results in the system saving the private key which can then be
    retrieved via the `private_key` attribute of this resource.

    Setting the `public_key` property means that the `private_key` attribute
    of this resource will always return an empty string regardless of the
    `save_private_key` setting since there will be no private key data to
    save.
    """

    support_status = support.SupportStatus(version='2014.1')

    required_service_extension = 'os-keypairs'

    PROPERTIES = (
        NAME, SAVE_PRIVATE_KEY, PUBLIC_KEY, KEY_TYPE, USER,
    ) = (
        'name', 'save_private_key', 'public_key', 'type', 'user',
    )

    ATTRIBUTES = (
        PUBLIC_KEY_ATTR, PRIVATE_KEY_ATTR,
    ) = (
        'public_key', 'private_key',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of the key pair.'),
            required=True,
            constraints=[
                constraints.Length(min=1, max=255)
            ]
        ),
        SAVE_PRIVATE_KEY: properties.Schema(
            properties.Schema.BOOLEAN,
            _('True if the system should remember a generated private key; '
              'False otherwise.'),
            default=False
        ),
        PUBLIC_KEY: properties.Schema(
            properties.Schema.STRING,
            _('The optional public key. This allows users to supply the '
              'public key from a pre-existing key pair. If not supplied, a '
              'new key pair will be generated.')
        ),
        KEY_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Keypair type. Supported since Nova api version 2.2.'),
            constraints=[
                constraints.AllowedValues(['ssh', 'x509'])],
            support_status=support.SupportStatus(version='8.0.0')
        ),
        USER: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of user to whom to add key-pair. The usage of this '
              'property is limited to being used by administrators only. '
              'Supported since Nova api version 2.10.'),
            constraints=[constraints.CustomConstraint('keystone.user')],
            support_status=support.SupportStatus(version='9.0.0')
        ),
    }

    attributes_schema = {
        PUBLIC_KEY_ATTR: attributes.Schema(
            _('The public key.'),
            type=attributes.Schema.STRING
        ),
        PRIVATE_KEY_ATTR: attributes.Schema(
            _('The private key if it has been saved.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'nova'

    entity = 'keypairs'

    def __init__(self, name, json_snippet, stack):
        super(KeyPair, self).__init__(name, json_snippet, stack)
        self._public_key = None

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.USER],
                client_plugin=self.client_plugin('keystone'),
                finder='get_user_id'
            )
        ]

    @property
    def private_key(self):
        """Return the private SSH key for the resource."""
        if self.properties[self.SAVE_PRIVATE_KEY]:
            return self.data().get('private_key', '')
        else:
            return ''

    @property
    def public_key(self):
        """Return the public SSH key for the resource."""
        if not self._public_key:
            if self.properties[self.PUBLIC_KEY]:
                self._public_key = self.properties[self.PUBLIC_KEY]
            elif self.resource_id:
                nova_key = self.client_plugin().get_keypair(self.resource_id)
                self._public_key = nova_key.public_key
        return self._public_key

    def validate(self):
        super(KeyPair, self).validate()

        # Check if key_type is allowed to use
        key_type = self.properties[self.KEY_TYPE]
        user = self.properties[self.USER]

        validate_props = []
        c_plugin = self.client_plugin()
        if key_type and not c_plugin.is_version_supported(
                MICROVERSION_KEY_TYPE):
            validate_props.append(self.KEY_TYPE)
        if user and not c_plugin.is_version_supported(MICROVERSION_USER):
            validate_props.append(self.USER)
        if validate_props:
            msg = (_('Cannot use "%s" properties - nova does not '
                     'support required api microversion.') % validate_props)
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        pub_key = self.properties[self.PUBLIC_KEY] or None
        user_id = self.properties[self.USER]
        key_type = self.properties[self.KEY_TYPE]

        create_kwargs = {
            'name': self.properties[self.NAME],
            'public_key': pub_key
        }

        if key_type:
            create_kwargs[self.KEY_TYPE] = key_type
        if user_id:
            create_kwargs['user_id'] = user_id

        new_keypair = self.client().keypairs.create(**create_kwargs)

        if (self.properties[self.SAVE_PRIVATE_KEY] and
                hasattr(new_keypair, 'private_key')):
            self.data_set('private_key',
                          new_keypair.private_key,
                          True)
        self.resource_id_set(new_keypair.id)

    def handle_check(self):
        self.client().keypairs.get(self.resource_id)

    def _resolve_attribute(self, key):
        attr_fn = {self.PRIVATE_KEY_ATTR: self.private_key,
                   self.PUBLIC_KEY_ATTR: self.public_key}
        return six.text_type(attr_fn[key])

    def get_reference_id(self):
        return self.resource_id

    def prepare_for_replace(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            self.client().keypairs.delete(self.resource_id)


def resource_mapping():
    return {'OS::Nova::KeyPair': KeyPair}
