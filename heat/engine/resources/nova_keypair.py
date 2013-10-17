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
from heat.db.sqlalchemy import api as db_api
from heat.engine import resource
from heat.engine.resources import nova_utils
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

from novaclient import exceptions as nova_exceptions

logger = logging.getLogger(__name__)


class KeyPair(resource.Resource):
    """
    A resource for creating Nova key pairs.

    **Note** that if a new key is generated setting `save_private_key` to
    `True` results in the system saving the private key which can then be
    retrieved via the `private_key` attribute of this resource.

    Setting the `public_key` property means that the `private_key` attribute
    of this resource will always return an empty string regardless of the
    `save_private_key` setting since there will be no private key data to
    save.
    """

    properties_schema = {
        'name': {
            'Type': 'String',
            'Description': _("The name of the key pair."),
            'Required': True
        },
        'save_private_key': {
            'Type': 'Boolean',
            'Description': _("True if the system should remember a generated "
                             "private key; False otherwise."),
            'Default': False
        },
        'public_key': {
            'Type': 'String',
            'Description': _("The optional public key. This allows users to "
                             "supply the public key from a pre-existing key "
                             "pair. If not supplied, a new key pair will be "
                             "generated.")
        }

    }

    attributes_schema = {
        'public_key': _('The public key.'),
        'private_key': _('The private key if it has been saved.')
    }

    def __init__(self, name, json_snippet, stack):
        super(KeyPair, self).__init__(name, json_snippet, stack)
        self._private_key = None
        self._public_key = None

    @property
    def private_key(self):
        """Return the private SSH key for the resource."""
        if (self._private_key is None and self.id and
                self.properties['save_private_key']):
                try:
                    self._private_key = db_api.resource_data_get(self,
                                                                 'private_key')
                except exception.NotFound:
                    pass
        return self._private_key or ""

    @property
    def public_key(self):
        """Return the public SSH key for the resource."""
        if not self._public_key:
            if self.properties['public_key']:
                self._public_key = self.properties['public_key']
            elif self.resource_id:
                nova_key = nova_utils.get_keypair(self.nova(),
                                                  self.resource_id)
                self._public_key = nova_key.public_key
        return self._public_key

    def handle_create(self):
        pub_key = self.properties['public_key'] or None
        new_keypair = self.nova().keypairs.create(self.properties['name'],
                                                  public_key=pub_key)
        if (self.properties['save_private_key'] and
                hasattr(new_keypair, 'private_key')):
            db_api.resource_data_set(self, 'private_key',
                                     new_keypair.private_key,
                                     True)
        self.resource_id_set(new_keypair.id)

    def handle_delete(self):
        if self.resource_id:
            try:
                self.nova().keypairs.delete(self.resource_id)
            except nova_exceptions.NotFound:
                pass

    def _resolve_attribute(self, key):
        attr_fn = {'private_key': self.private_key,
                   'public_key': self.public_key}
        return unicode(attr_fn[key])


def resource_mapping():
    return {'OS::Nova::KeyPair': KeyPair}
