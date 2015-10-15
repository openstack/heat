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


class KeystoneProject(resource.Resource):
    """Heat Template Resource for Keystone Project."""

    support_status = support.SupportStatus(
        version='2015.1',
        message=_('Supported versions: keystone v3'))

    default_client_name = 'keystone'

    entity = 'projects'

    PROPERTIES = (
        NAME, DOMAIN, DESCRIPTION, ENABLED, PARENT,
    ) = (
        'name', 'domain', 'description', 'enabled', 'parent',
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
    }

    def client(self):
        return super(KeystoneProject, self).client().client

    def handle_create(self):
        project_name = (self.properties[self.NAME] or
                        self.physical_resource_name())
        description = self.properties[self.DESCRIPTION]
        domain = self.client_plugin().get_domain_id(
            self.properties[self.DOMAIN])
        enabled = self.properties[self.ENABLED]
        pp = self.properties[self.PARENT]
        parent = self.client_plugin().get_project_id(pp)

        project = self.client().projects.create(
            name=project_name,
            domain=domain,
            description=description,
            enabled=enabled,
            parent=parent)

        self.resource_id_set(project.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            name = prop_diff.get(self.NAME) or self.physical_resource_name()
            description = prop_diff.get(self.DESCRIPTION)
            enabled = prop_diff.get(self.ENABLED)
            domain = (prop_diff.get(self.DOMAIN) or
                      self._stored_properties_data.get(self.DOMAIN))
            domain_id = self.client_plugin().get_domain_id(domain)

            self.client().projects.update(
                project=self.resource_id,
                name=name,
                description=description,
                enabled=enabled,
                domain=domain_id
            )


def resource_mapping():
    return {
        'OS::Keystone::Project': KeystoneProject
    }
