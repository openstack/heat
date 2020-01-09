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


class FlavorProfile(resource.Resource):
    """A resource for creating octavia Flavor Profiles.

    This resource creates and manages octavia Flavor Profiles,
    which allows to tune Load Balancers' capabilities.
    """

    default_client_name = 'octavia'

    support_status = support.SupportStatus(version='14.0.0')

    PROPERTIES = (
        NAME, FLAVOR_DATA, PROVIDER_NAME
    ) = (
        'name', 'flavor_data', 'provider_name'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of this Flavor Profile.'),
            update_allowed=True
        ),
        FLAVOR_DATA: properties.Schema(
            properties.Schema.STRING,
            _('JSON string containing the flavor metadata.'),
            update_allowed=True,
            required=True
        ),
        PROVIDER_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Provider name of this Flavor Profile.'),
            update_allowed=True,
        ),
    }

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items()
                     if v is not None)
        if self.NAME not in props:
            props[self.NAME] = self.physical_resource_name()
        return props

    def handle_create(self):
        props = self._prepare_args(self.properties)

        flavorprofile = self.client().flavorprofile_create(
            json={'flavorprofile': props})['flavorprofile']
        self.resource_id_set(flavorprofile['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            if self.NAME in prop_diff and prop_diff[self.NAME] is None:
                prop_diff[self.NAME] = self.physical_resource_name()
            self.client().flavorprofile_set(
                self.resource_id,
                json={'flavorprofile': prop_diff})

    def handle_delete(self):
        with self.client_plugin().ignore_not_found:
            self.client().flavorprofile_delete(self.resource_id)
            return True

    def _show_resource(self):
        return self.client().flavorprofile_show(self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::FlavorProfile': FlavorProfile
    }
