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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class KeystoneEndpoint(resource.Resource):
    """Heat Template Resource for Keystone Service Endpoint.

    Keystone endpoint is just the URL that can be used for accessing a service
    within OpenStack. Endpoint can be accessed by admin, by services or public,
    i.e. everyone can use this endpoint.
    """

    support_status = support.SupportStatus(
        version='5.0.0',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    entity = 'endpoints'

    PROPERTIES = (
        NAME, REGION, SERVICE, INTERFACE, SERVICE_URL, ENABLED,
    ) = (
        'name', 'region', 'service', 'interface', 'url', 'enabled',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of keystone endpoint.'),
            update_allowed=True
        ),
        REGION: properties.Schema(
            properties.Schema.STRING,
            _('Name or Id of keystone region.'),
            update_allowed=True,
            constraints=[constraints.CustomConstraint('keystone.region')]
        ),
        SERVICE: properties.Schema(
            properties.Schema.STRING,
            _('Name or Id of keystone service.'),
            update_allowed=True,
            required=True,
            constraints=[constraints.CustomConstraint('keystone.service')]
        ),
        INTERFACE: properties.Schema(
            properties.Schema.STRING,
            _('Interface type of keystone service endpoint.'),
            update_allowed=True,
            required=True,
            constraints=[constraints.AllowedValues(
                ['public', 'internal', 'admin']
            )]
        ),
        SERVICE_URL: properties.Schema(
            properties.Schema.STRING,
            _('URL of keystone service endpoint.'),
            update_allowed=True,
            required=True
        ),
        ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('This endpoint is enabled or disabled.'),
            default=True,
            update_allowed=True,
            support_status=support.SupportStatus(version='6.0.0')
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.SERVICE],
                client_plugin=self.client_plugin(),
                finder='get_service_id'
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.REGION],
                client_plugin=self.client_plugin(),
                finder='get_region_id'
            ),
        ]

    def client(self):
        return super(KeystoneEndpoint, self).client().client

    def handle_create(self):
        region = self.properties[self.REGION]
        service = self.properties[self.SERVICE]
        interface = self.properties[self.INTERFACE]
        url = self.properties[self.SERVICE_URL]
        name = (self.properties[self.NAME] or
                self.physical_resource_name())
        enabled = self.properties[self.ENABLED]

        endpoint = self.client().endpoints.create(
            region=region,
            service=service,
            interface=interface,
            url=url,
            name=name,
            enabled=enabled)

        self.resource_id_set(endpoint.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            region = prop_diff.get(self.REGION)
            service = prop_diff.get(self.SERVICE)
            interface = prop_diff.get(self.INTERFACE)
            url = prop_diff.get(self.SERVICE_URL)
            name = None
            # Don't update the name if no change
            if self.NAME in prop_diff:
                name = prop_diff[self.NAME] or self.physical_resource_name()
            enabled = prop_diff.get(self.ENABLED)

            self.client().endpoints.update(
                endpoint=self.resource_id,
                region=region,
                service=service,
                interface=interface,
                url=url,
                name=name,
                enabled=enabled)

    def parse_live_resource_data(self, resource_properties, resource_data):
        endpoint_reality = {}

        endpoint_reality.update(
            {self.SERVICE: resource_data.get('service_id'),
             self.REGION: resource_data.get('region_id')})
        for key in (set(self.PROPERTIES) - {self.SERVICE, self.REGION}):
            endpoint_reality.update({key: resource_data.get(key)})
        return endpoint_reality


def resource_mapping():
    return {
        'OS::Keystone::Endpoint': KeystoneEndpoint
    }
