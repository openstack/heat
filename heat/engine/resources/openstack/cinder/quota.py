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

import copy

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class CinderQuota(resource.Resource):
    """A resource for creating cinder quotas.

    Cinder Quota is used to manage operational limits for projects. Currently,
    this resource can manage Cinder's gigabytes, snapshots, and volumes
    quotas.

    Note that default cinder security policy usage of this resource
    is limited to being used by administrators only. Administrators should be
    careful to create only one Cinder Quota resource per project, otherwise
    it will be hard for them to manage the quota properly.
    """

    support_status = support.SupportStatus(version='7.0.0')

    default_client_name = 'cinder'

    entity = 'quotas'

    required_service_extension = 'os-quota-sets'

    PROPERTIES = (PROJECT, GIGABYTES, VOLUMES, SNAPSHOTS) = (
        'project', 'gigabytes', 'volumes', 'snapshots'
    )

    properties_schema = {
        PROJECT: properties.Schema(
            properties.Schema.STRING,
            _('OpenStack Keystone Project.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('keystone.project')
            ]
        ),
        GIGABYTES: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the amount of disk space (in Gigabytes). '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        VOLUMES: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of volumes. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        SNAPSHOTS: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of snapshots. '
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

        args = copy.copy(props.data)
        project = args.pop(self.PROJECT)
        self.client().quotas.update(project, **args)

    def handle_delete(self):
        self.client().quotas.delete(self.properties[self.PROJECT])

    def validate(self):
        super(CinderQuota, self).validate()
        if len(self.properties.data) == 1:
            raise exception.PropertyUnspecifiedError(self.GIGABYTES,
                                                     self.SNAPSHOTS,
                                                     self.VOLUMES)


def resource_mapping():
    return {
        'OS::Cinder::Quota': CinderQuota
    }
