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


class KeystoneService(resource.Resource):
    """Heat Template Resource for Keystone Service.

    A resource that allows to create new service and manage it by Keystone.
    """

    support_status = support.SupportStatus(
        version='5.0.0',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    entity = 'services'

    PROPERTIES = (
        NAME, DESCRIPTION, TYPE, ENABLED,
    ) = (
        'name', 'description', 'type', 'enabled',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of keystone service.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of keystone service.'),
            update_allowed=True
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of keystone Service.'),
            update_allowed=True,
            required=True
        ),
        ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('This service is enabled or disabled.'),
            default=True,
            update_allowed=True,
            support_status=support.SupportStatus(version='6.0.0')
        )
    }

    def client(self):
        return super(KeystoneService, self).client().client

    def handle_create(self):
        name = (self.properties[self.NAME] or
                self.physical_resource_name())
        description = self.properties[self.DESCRIPTION]
        type = self.properties[self.TYPE]
        enabled = self.properties[self.ENABLED]

        service = self.client().services.create(
            name=name,
            description=description,
            type=type,
            enabled=enabled)

        self.resource_id_set(service.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            name = None
            # Don't update the name if no change
            if self.NAME in prop_diff:
                name = prop_diff[self.NAME] or self.physical_resource_name()
            description = prop_diff.get(self.DESCRIPTION)
            type = prop_diff.get(self.TYPE)
            enabled = prop_diff.get(self.ENABLED)

            self.client().services.update(
                service=self.resource_id,
                name=name,
                description=description,
                type=type,
                enabled=enabled)


def resource_mapping():
    return {
        'OS::Keystone::Service': KeystoneService
    }
