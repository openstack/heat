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


class OctaviaQuota(resource.Resource):
    """A resource for creating Octavia quotas.

    Ocatavia Quota is used to manage operational limits for Octavia. Currently,
    this resource can manage Octavia's quotas for:

        - healthmonitor
        - listener
        - loadbalancer
        - pool
        - member

    Note that default octavia security policy usage of this resource
    is limited to being used by administrators only. Administrators should be
    careful to create only one Octavia Quota resource per project, otherwise
    it will be hard for them to manage the quota properly.
    """

    support_status = support.SupportStatus(version='14.0.0')

    default_client_name = 'octavia'

    entity = 'quotas'

    PROPERTIES = (
        PROJECT, HEALTHMONITOR, LISTENER, LOADBALANCER,
        POOL, MEMBER
    ) = (
        'project', 'healthmonitor', 'listener', 'loadbalancer',
        'pool', 'member'
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
        HEALTHMONITOR: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of healthmonitors. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        LISTENER: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of listeners. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        LOADBALANCER: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of load balancers. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        POOL: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of pools. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
        MEMBER: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of m. '
              'Setting the value to -1 removes the limit.'),
            constraints=[
                constraints.Range(min=-1),
            ],
            update_allowed=True
        ),
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
        super(OctaviaQuota, self).validate()
        if sum(1 for p in self.properties.values() if p is not None) <= 1:
            raise exception.PropertyUnspecifiedError(
                *sorted(set(self.PROPERTIES) - {self.PROJECT}))


def resource_mapping():
    return {
        'OS::Octavia::Quota': OctaviaQuota
    }
