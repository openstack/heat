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


class KeystoneEndpoint(resource.Resource):
    """Heat Template Resource for Keystone Service Endpoint."""

    support_status = support.SupportStatus(
        version='2015.2',
        message=_('Supported versions: keystone v3'))

    PROPERTIES = (
        NAME, REGION, SERVICE, INTERFACE, SERVICE_URL
    ) = (
        'name', 'region', 'service', 'interface', 'url'
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
            update_allowed=True
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
        )
    }

    def _create_endpoint(self,
                         service,
                         interface,
                         url,
                         region=None,
                         name=None):
        return self.keystone().client.endpoints.create(
            region=region,
            service=service,
            interface=interface,
            url=url,
            name=name)

    def _delete_endpoint(self, endpoint_id):
        return self.keystone().client.endpoints.delete(endpoint_id)

    def _update_endpoint(self,
                         endpoint_id,
                         new_region=None,
                         new_service=None,
                         new_interface=None,
                         new_url=None,
                         new_name=None):
        return self.keystone().client.endpoints.update(
            endpoint=endpoint_id,
            region=new_region,
            service=new_service,
            interface=new_interface,
            url=new_url,
            name=new_name)

    def handle_create(self):
        region = self.properties.get(self.REGION)
        service = self.properties.get(self.SERVICE)
        interface = self.properties.get(self.INTERFACE)
        url = self.properties.get(self.SERVICE_URL)
        name = (self.properties.get(self.NAME) or
                self.physical_resource_name())

        endpoint = self._create_endpoint(
            region=region,
            service=service,
            interface=interface,
            url=url,
            name=name
        )

        self.resource_id_set(endpoint.id)

    def handle_update(self,
                      json_snippet=None,
                      tmpl_diff=None,
                      prop_diff=None):
        region = prop_diff.get(self.REGION)
        service = prop_diff.get(self.SERVICE)
        interface = prop_diff.get(self.INTERFACE)
        url = prop_diff.get(self.SERVICE_URL)
        name = None
        if self.NAME in prop_diff:
            name = (prop_diff.get(self.NAME) or
                    self.physical_resource_name())

        self._update_endpoint(
            endpoint_id=self.resource_id,
            new_region=region,
            new_interface=interface,
            new_service=service,
            new_url=url,
            new_name=name
        )

    def handle_delete(self):
        if self.resource_id is not None:
            try:
                self._delete_endpoint(endpoint_id=self.resource_id)
            except Exception as ex:
                self.client_plugin('keystone').ignore_not_found(ex)


def resource_mapping():
    return {
        'OS::Keystone::Endpoint': KeystoneEndpoint
    }
