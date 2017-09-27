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


class KeystoneProject(resource.Resource):
    """Heat Template Resource for Keystone Project.

    Projects represent the base unit of ownership in OpenStack, in that all
    resources in OpenStack should be owned by a specific project. A project
    itself must be owned by a specific domain, and hence all project names are
    not globally unique, but unique to their domain. If the domain for a
    project is not specified, then it is added to the default domain.
    """

    support_status = support.SupportStatus(
        version='2015.1',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    entity = 'projects'

    PROPERTIES = (
        NAME, DOMAIN, DESCRIPTION, ENABLED, PARENT, TAGS,
    ) = (
        'name', 'domain', 'description', 'enabled', 'parent', 'tags',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of keystone project.'),
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
            _('Description of keystone project.'),
            default='',
            update_allowed=True
        ),
        ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('This project is enabled or disabled.'),
            default=True,
            update_allowed=True
        ),
        PARENT: properties.Schema(
            properties.Schema.STRING,
            _('The name or ID of parent of this keystone project '
              'in hierarchy.'),
            support_status=support.SupportStatus(version='6.0.0'),
            constraints=[constraints.CustomConstraint('keystone.project')]
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('A list of tags for labeling and sorting projects.'),
            support_status=support.SupportStatus(version='10.0.0'),
            default=[],
            update_allowed=True
        ),
    }

    ATTRIBUTES = (
        NAME_ATTR, PARENT_ATTR, DOMAIN_ATTR, ENABLED_ATTR, IS_DOMAIN_ATTR
    ) = (
        'name', 'parent_id', 'domain_id', 'enabled', 'is_domain'
    )
    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _('Project name.'),
            support_status=support.SupportStatus(version='10.0.0'),
            type=attributes.Schema.STRING
        ),
        PARENT_ATTR: attributes.Schema(
            _('Parent project id.'),
            support_status=support.SupportStatus(version='10.0.0'),
            type=attributes.Schema.STRING
        ),
        DOMAIN_ATTR: attributes.Schema(
            _('Domain id for project.'),
            support_status=support.SupportStatus(version='10.0.0'),
            type=attributes.Schema.STRING
        ),
        ENABLED_ATTR: attributes.Schema(
            _('Flag of enable project.'),
            support_status=support.SupportStatus(version='10.0.0'),
            type=attributes.Schema.BOOLEAN
        ),
        IS_DOMAIN_ATTR: attributes.Schema(
            _('Indicates whether the project also acts as a domain.'),
            support_status=support.SupportStatus(version='10.0.0'),
            type=attributes.Schema.BOOLEAN
        ),
    }

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        project = self.client().projects.get(self.resource_id)
        return getattr(project, name, None)

    def translation_rules(self, properties):
        return [
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.DOMAIN],
                client_plugin=self.client_plugin(),
                finder='get_domain_id'
            ),
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.PARENT],
                client_plugin=self.client_plugin(),
                finder='get_project_id'
            ),
        ]

    def client(self):
        return super(KeystoneProject, self).client().client

    def handle_create(self):
        project_name = (self.properties[self.NAME] or
                        self.physical_resource_name())
        description = self.properties[self.DESCRIPTION]
        domain = self.properties[self.DOMAIN]
        enabled = self.properties[self.ENABLED]
        parent = self.properties[self.PARENT]
        tags = self.properties[self.TAGS]

        project = self.client().projects.create(
            name=project_name,
            domain=domain,
            description=description,
            enabled=enabled,
            parent=parent,
            tags=tags)

        self.resource_id_set(project.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            name = None
            # Don't update the name if no change
            if self.NAME in prop_diff:
                name = prop_diff[self.NAME] or self.physical_resource_name()

            description = prop_diff.get(self.DESCRIPTION)
            enabled = prop_diff.get(self.ENABLED)
            domain = prop_diff.get(self.DOMAIN, self.properties[self.DOMAIN])
            tags = (prop_diff.get(self.TAGS) or
                    self.properties[self.TAGS])

            self.client().projects.update(
                project=self.resource_id,
                name=name,
                description=description,
                enabled=enabled,
                domain=domain,
                tags=tags
            )

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(KeystoneProject, self).parse_live_resource_data(
            resource_properties, resource_data)
        result[self.DOMAIN] = resource_data.get('domain_id')
        return result


def resource_mapping():
    return {
        'OS::Keystone::Project': KeystoneProject
    }
