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
    """Heat Template Resource for Keystone Service."""

    support_status = support.SupportStatus(
        version='5.0.0',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    PROPERTIES = (
        NAME, DESCRIPTION, TYPE
    ) = (
        'name', 'description', 'type'
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
        )
    }

    def _create_service(self,
                        name,
                        type,
                        description=None):
        return self.client().client.services.create(
            name=name,
            description=description,
            type=type)

    def _delete_service(self, service_id):
        return self.client().client.services.delete(service_id)

    def _update_service(self,
                        service_id,
                        new_name=None,
                        new_description=None,
                        new_type=None):
        return self.client().client.services.update(
            service=service_id,
            name=new_name,
            description=new_description,
            type=new_type)

    def handle_create(self):
        name = (self.properties.get(self.NAME) or
                self.physical_resource_name())
        description = self.properties.get(self.DESCRIPTION)
        type = self.properties.get(self.TYPE)

        service = self._create_service(
            name=name,
            description=description,
            type=type
        )

        self.resource_id_set(service.id)

    def handle_update(self,
                      json_snippet=None,
                      tmpl_diff=None,
                      prop_diff=None):
        name = None
        if self.NAME in prop_diff:
            name = (prop_diff.get(self.NAME) or
                    self.physical_resource_name())
        description = prop_diff.get(self.DESCRIPTION)
        type = prop_diff.get(self.TYPE)

        self._update_service(
            service_id=self.resource_id,
            new_name=name,
            new_description=description,
            new_type=type
        )

    def handle_delete(self):
        if self.resource_id is not None:
            try:
                self._delete_service(service_id=self.resource_id)
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)


def resource_mapping():
    return {
        'OS::Keystone::Service': KeystoneService
    }
