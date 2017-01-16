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
from heat.engine.resources.openstack.keystone import role_assignments
from heat.engine import support
from heat.engine import translation


class KeystoneGroup(resource.Resource,
                    role_assignments.KeystoneRoleAssignmentMixin):
    """Heat Template Resource for Keystone Group.

    Groups are a container representing a collection of users. A group itself
    must be owned by a specific domain, and hence all group names are not
    globally unique, but only unique to their domain.
    """

    support_status = support.SupportStatus(
        version='2015.1',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    entity = 'groups'

    PROPERTIES = (
        NAME, DOMAIN, DESCRIPTION
    ) = (
        'name', 'domain', 'description'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of keystone group.'),
            update_allowed=True
        ),
        DOMAIN: properties.Schema(
            properties.Schema.STRING,
            _('Name or id of keystone domain.'),
            default='default',
            update_allowed=True,
            constraints=[constraints.CustomConstraint('keystone.domain')]
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of keystone group.'),
            default='',
            update_allowed=True
        )
    }

    def translation_rules(self, properties):
        return [
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.DOMAIN],
                client_plugin=self.client_plugin(),
                finder='get_domain_id'
            )
        ]

    properties_schema.update(
        role_assignments.KeystoneRoleAssignmentMixin.mixin_properties_schema)

    def validate(self):
        super(KeystoneGroup, self).validate()
        self.validate_assignment_properties()

    def client(self):
        return super(KeystoneGroup, self).client().client

    def handle_create(self):
        group_name = (self.properties[self.NAME] or
                      self.physical_resource_name())
        description = self.properties[self.DESCRIPTION]
        domain = self.properties[self.DOMAIN]

        group = self.client().groups.create(
            name=group_name,
            domain=domain,
            description=description)

        self.resource_id_set(group.id)

        self.create_assignment(group_id=group.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            name = None
            # Don't update the name if no change
            if self.NAME in prop_diff:
                name = prop_diff[self.NAME] or self.physical_resource_name()

            description = prop_diff.get(self.DESCRIPTION)
            domain = (prop_diff.get(self.DOMAIN) or
                      self.properties[self.DOMAIN])

            self.client().groups.update(
                group=self.resource_id,
                name=name,
                description=description,
                domain_id=domain)

            self.update_assignment(prop_diff=prop_diff,
                                   group_id=self.resource_id)

    def parse_live_resource_data(self, resource_properties, resource_data):
        return {
            self.NAME: resource_data.get(self.NAME),
            self.DESCRIPTION: resource_data.get(self.DESCRIPTION),
            self.DOMAIN: resource_data.get('domain_id'),
            self.ROLES: self.parse_list_assignments(group_id=self.resource_id)
        }


def resource_mapping():
    return {
        'OS::Keystone::Group': KeystoneGroup
    }
