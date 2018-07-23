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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class NovaQuota(resource.Resource):
    """A resource for creating nova quotas.

    Nova Quota is used to manage operational limits for projects. Currently,
    this resource can manage Nova's quotas for:

        - cores
        - fixed_ips
        - floating_ips
        - instances
        - injected_files
        - injected_file_content_bytes
        - injected_file_path_bytes
        - key_pairs
        - metadata_items
        - ram
        - security_groups
        - security_group_rules
        - server_groups
        - server_group_members

    Note that default nova security policy usage of this resource
    is limited to being used by administrators only. Administrators should be
    careful to create only one Nova Quota resource per project, otherwise
    it will be hard for them to manage the quota properly.
    """

    support_status = support.SupportStatus(version='8.0.0')

    default_client_name = 'nova'

    entity = 'quotas'

    required_service_extension = 'os-quota-sets'

    PROPERTIES = (
        PROJECT, CORES, FIXED_IPS, FLOATING_IPS, INSTANCES,
        INJECTED_FILES, INJECTED_FILE_CONTENT_BYTES, INJECTED_FILE_PATH_BYTES,
        KEYPAIRS, METADATA_ITEMS, RAM, SECURITY_GROUPS, SECURITY_GROUP_RULES,
        SERVER_GROUPS, SERVER_GROUP_MEMBERS
    ) = (
        'project', 'cores', 'fixed_ips', 'floating_ips', 'instances',
        'injected_files', 'injected_file_content_bytes',
        'injected_file_path_bytes', 'key_pairs', 'metadata_items', 'ram',
        'security_groups', 'security_group_rules', 'server_groups',
        'server_group_members'
    )

    properties_schema = {
        PROJECT: properties.Schema(
            properties.Schema.STRING,
            _('Name or id of the project to set the quota for.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('keystone.project')
            ]
        ),
        CORES: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of cores. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        FIXED_IPS: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of fixed IPs. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        FLOATING_IPS: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of floating IPs. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        INSTANCES: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of instances. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        INJECTED_FILES: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of injected files. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        INJECTED_FILE_CONTENT_BYTES: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of injected file content bytes. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        INJECTED_FILE_PATH_BYTES: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of injected file path bytes. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        KEYPAIRS: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of key pairs. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        METADATA_ITEMS: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of metadata items. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        RAM: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the amount of ram (in megabytes). '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of security groups. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        SECURITY_GROUP_RULES: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of security group rules. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        SERVER_GROUPS: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of server groups. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        SERVER_GROUP_MEMBERS: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of server group members. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.PROJECT],
                client_plugin=self.client_plugin('keystone'),
                finder='get_project_id')
        ]

    def handle_create(self):
        self._set_quota()
        self.resource_id_set(self.physical_resource_name())

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self._set_quota(json_snippet.properties(self.properties_schema,
                                                self.context))

    def _set_quota(self, props=None):
        if props is None:
            props = self.properties

        kwargs = dict((k, v) for k, v in props.items()
                      if k != self.PROJECT and v is not None)
        self.client().quotas.update(props.get(self.PROJECT), **kwargs)

    def handle_delete(self):
        self.client().quotas.delete(self.properties[self.PROJECT])

    def validate(self):
        super(NovaQuota, self).validate()
        if sum(1 for p in self.properties.values() if p is not None) <= 1:
            raise exception.PropertyUnspecifiedError(
                *sorted(set(self.PROPERTIES) - {self.PROJECT}))


def resource_mapping():
    return {
        'OS::Nova::Quota': NovaQuota
    }
