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
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class KeystoneRole(resource.Resource):
    """Heat Template Resource for Keystone Role."""

    support_status = support.SupportStatus(
        version='2015.1',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    entity = 'roles'

    PROPERTIES = (
        NAME
    ) = (
        'name'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of keystone role.'),
            update_allowed=True
        )
    }

    def client(self):
        return super(KeystoneRole, self).client().client

    def handle_create(self):
        role_name = (self.properties[self.NAME] or
                     self.physical_resource_name())

        role = self.client().roles.create(name=role_name)

        self.resource_id_set(role.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            name = prop_diff.get(self.NAME) or self.physical_resource_name()
            self.client().roles.update(role=self.resource_id, name=name)


def resource_mapping():
    return {
        'OS::Keystone::Role': KeystoneRole
    }
