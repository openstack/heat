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


class AvailabilityZoneProfile(resource.Resource):
    """A resource for creating octavia Availability Zone Profiles.

    This resource creates and manages octavia Availability Zone Profiles,
    which allows to tune Load Balancers' capabilities.
    """

    default_client_name = 'octavia'

    support_status = support.SupportStatus(version='24.0.0')

    PROPERTIES = (
        NAME, AVAILABILITY_ZONE_DATA, PROVIDER_NAME
    ) = (
        'name', 'availability_zone_data', 'provider_name'
    )

    ATTRIBUTES = (
        AVAILABILITY_ZONE_PROFILE_ID_ATTR,
    ) = (
        'availability_zone_profile_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of this Availability Zone Profile.'),
            update_allowed=True
        ),
        AVAILABILITY_ZONE_DATA: properties.Schema(
            properties.Schema.STRING,
            _('JSON string containing the availability zone metadata.'),
            update_allowed=True,
            required=True,
            constraints=[constraints.CustomConstraint('json_string')]
        ),
        PROVIDER_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Provider name of this Availability Zone.'),
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

        availabilityzoneprofile = self.client().availabilityzoneprofile_create(
            json={'availability_zone_profile': props}
        )['availability_zone_profile']
        self.resource_id_set(availabilityzoneprofile['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            if self.NAME in prop_diff and prop_diff[self.NAME] is None:
                prop_diff[self.NAME] = self.physical_resource_name()
            self.client().availabilityzoneprofile_set(
                self.resource_id,
                json={'availability_zone_profile': prop_diff})

    def handle_delete(self):
        with self.client_plugin().ignore_not_found:
            self.client().availabilityzoneprofile_delete(self.resource_id)
            return True

    def _show_resource(self):
        return self.client().availabilityzoneprofile_show(self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::AvailabilityZoneProfile': AvailabilityZoneProfile
    }
