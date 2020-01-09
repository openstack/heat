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
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class Flavor(resource.Resource):
    """A resource for creating octavia Flavors.

    This resource creates and manages octavia Flavors,
    which allows to tune Load Balancers' capabilities.
    """

    default_client_name = 'octavia'

    support_status = support.SupportStatus(version='14.0.0')

    PROPERTIES = (
        DESCRIPTION, ENABLED, FLAVOR_PROFILE, NAME
    ) = (
        'description', 'enabled', 'flavor_profile', 'name'
    )

    ATTRIBUTES = (
        FLAVOR_PROFILE_ID_ATTR,
    ) = (
        'flavor_profile_id',
    )

    properties_schema = {
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of this Flavor.'),
            update_allowed=True,
            default=''
        ),
        ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('If the resource if available for use.'),
            update_allowed=True,
            default=True,
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of this Flavor.'),
            update_allowed=True
        ),
        FLAVOR_PROFILE: properties.Schema(
            properties.Schema.STRING,
            _('The ID or the name of the Flavor Profile.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('octavia.flavorprofile')
            ]
        ),
    }

    attributes_schema = {
        FLAVOR_PROFILE_ID_ATTR: attributes.Schema(
            _('The ID of the flavor profile.'),
            type=attributes.Schema.STRING,
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.FLAVOR_PROFILE],
                client_plugin=self.client_plugin(),
                finder='get_flavorprofile'
            )
        ]

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items()
                     if v is not None)
        if self.NAME not in props:
            props[self.NAME] = self.physical_resource_name()
        props['flavor_profile_id'] = props.pop(self.FLAVOR_PROFILE)
        return props

    def handle_create(self):
        props = self._prepare_args(self.properties)

        flavor = self.client().flavor_create(
            json={'flavor': props})['flavor']
        self.resource_id_set(flavor['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            if self.NAME in prop_diff and prop_diff[self.NAME] is None:
                prop_diff[self.NAME] = self.physical_resource_name()
            self.client().flavor_set(self.resource_id,
                                     json={'flavor': prop_diff})

    def handle_delete(self):
        with self.client_plugin().ignore_not_found:
            self.client().flavor_delete(self.resource_id)
            return True

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return None
        resource = self._show_resource()
        return resource[name]

    def _show_resource(self):
        return self.client().flavor_show(self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::Flavor': Flavor
    }
