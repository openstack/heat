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


class AvailabilityZone(resource.Resource):
    """A resource for creating octavia Availability Zones.

    This resource creates and manages octavia Availability Zones,
    which allows to tune Load Balancers' capabilities.
    """

    default_client_name = 'octavia'

    support_status = support.SupportStatus(version='24.0.0')

    PROPERTIES = (
        DESCRIPTION, ENABLED, NAME, AVAILABILITY_ZONE_PROFILE
    ) = (
        'description', 'enabled', 'name', 'availability_zone_profile'
    )

    ATTRIBUTES = (
        AVAILABILITY_ZONE_PROFILE_ID_ATTR,
    ) = (
        'availability_zone_profile_id',
    )

    properties_schema = {
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of this Availability Zone.'),
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
            _('Name of this Availability Zone.'),
            update_allowed=True
        ),
        AVAILABILITY_ZONE_PROFILE: properties.Schema(
            properties.Schema.STRING,
            _('The ID or the name of the Availability Zone Profile.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('octavia.availabilityzoneprofile')
            ]
        ),
    }

    attributes_schema = {
        AVAILABILITY_ZONE_PROFILE_ID_ATTR: attributes.Schema(
            _('The ID of the availability zone profile.'),
            type=attributes.Schema.STRING,
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.AVAILABILITY_ZONE_PROFILE],
                client_plugin=self.client_plugin(),
                finder='get_availabilityzoneprofile'
            )
        ]

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items()
                     if v is not None)
        if self.NAME not in props:
            props[self.NAME] = self.physical_resource_name()
        props['availability_zone_profile_id'] = props.pop(
            self.AVAILABILITY_ZONE_PROFILE
        )
        return props

    def handle_create(self):
        props = self._prepare_args(self.properties)

        availability_zone = self.client().availabilityzone_create(
            json={'availability_zone': props})['availability_zone']
        self.resource_id_set(availability_zone.get('name'))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            if self.NAME in prop_diff and prop_diff[self.NAME] is None:
                prop_diff[self.NAME] = self.physical_resource_name()
            self.client().availabilityzone_set(
                self.resource_id,
                json={'availability_zone': prop_diff})

    def handle_delete(self):
        with self.client_plugin().ignore_not_found:
            self.client().availabilityzone_delete(self.resource_id)
            return True

    def _show_resource(self):
        return self.client().availabilityzone_show(self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::AvailabilityZone': AvailabilityZone
    }
