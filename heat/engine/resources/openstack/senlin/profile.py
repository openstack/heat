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
#
#    Copyright 2015 IBM Corp.

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.senlin import res_base


class Profile(res_base.BaseSenlinResource):
    """A resource that creates a Senlin Profile.

    Profile resource in senlin is a template describing how to create nodes in
    cluster.
    """

    entity = 'profile'

    PROPERTIES = (
        NAME, TYPE, METADATA, PROFILE_PROPERTIES,
    ) = (
        'name', 'type', 'metadata', 'properties',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the senlin profile. By default, physical resource name '
              'is used.'),
            update_allowed=True,
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The type of profile.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('senlin.profile_type')
            ]
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Metadata key-values defined for profile.'),
            update_allowed=True,
        ),
        PROFILE_PROPERTIES: properties.Schema(
            properties.Schema.MAP,
            _('Properties for profile.'),
        )
    }

    def handle_create(self):
        params = {
            'name': (self.properties[self.NAME] or
                     self.physical_resource_name()),
            'spec': self.client_plugin().generate_spec(
                spec_type=self.properties[self.TYPE],
                spec_props=self.properties[self.PROFILE_PROPERTIES]),
            'metadata': self.properties[self.METADATA],
        }

        profile = self.client().create_profile(**params)
        self.resource_id_set(profile.id)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().delete_profile(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            profile_obj = self.client().get_profile(self.resource_id)
            self.client().update_profile(profile_obj, **prop_diff)


def resource_mapping():
    return {
        'OS::Senlin::Profile': Profile
    }
