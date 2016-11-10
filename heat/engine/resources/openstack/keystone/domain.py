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


class KeystoneDomain(resource.Resource):
    """Heat Template Resource for Keystone Domain.

    This plug-in helps to create, update and delete a keystone domain. Also
    it can be used for enable or disable a given keystone domain.
    """

    support_status = support.SupportStatus(
        version='8.0.0',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    entity = 'domains'

    PROPERTIES = (
        NAME, DESCRIPTION, ENABLED
    ) = (
        'name', 'description', 'enabled'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of the domain.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of keystone domain.'),
            update_allowed=True
        ),
        ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('This domain is enabled or disabled.'),
            default=True,
            update_allowed=True
        )
    }

    def client(self):
        return super(KeystoneDomain, self).client().client

    def handle_create(self):
        name = (self.properties[self.NAME] or
                self.physical_resource_name())
        description = self.properties[self.DESCRIPTION]
        enabled = self.properties[self.ENABLED]

        domain = self.client().domains.create(
            name=name,
            description=description,
            enabled=enabled)

        self.resource_id_set(domain.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            description = prop_diff.get(self.DESCRIPTION)
            enabled = prop_diff.get(self.ENABLED)
            name = None
            # Don't update the name if no change
            if self.NAME in prop_diff:
                name = prop_diff[self.NAME] or self.physical_resource_name()

            self.client().domains.update(
                domain=self.resource_id,
                name=name,
                description=description,
                enabled=enabled
            )

    def parse_live_resource_data(self, resource_properties, resource_data):
        return {self.NAME: resource_data.get(self.NAME),
                self.DESCRIPTION: resource_data.get(self.DESCRIPTION),
                self.ENABLED: resource_data.get(self.ENABLED)}


def resource_mapping():
    return {
        'OS::Keystone::Domain': KeystoneDomain
    }
