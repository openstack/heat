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

    @classmethod
    def _validate_quota(cls, quota_property, quota_size, total_size):
        err_message = _("Invalid quota %(property)s value(s): %(value)s. "
                        "Can not be less than the current usage value(s): "
                        "%(total)s.")
        if quota_size < total_size:
            message_format = {'property': quota_property, 'value':
                              quota_size, 'total': total_size}
            raise ValueError(err_message % message_format)

    def validate_quotas(self, project, **kwargs):
        search_opts = {'all_tenants': True, 'project_id': project}
        volume_list = None
        snapshot_list = None
        for key, value in kwargs.copy().items():
            if value == -1:
                del kwargs[key]

        if self.GIGABYTES in kwargs:
            quota_size = kwargs[self.GIGABYTES]
            volume_list = self.client().volumes.list(search_opts=search_opts)
            snapshot_list = self.client().volume_snapshots.list(
                search_opts=search_opts)
            total_size = sum(item.size for item in (
                volume_list + snapshot_list))
            self._validate_quota(self.GIGABYTES, quota_size, total_size)

        if self.VOLUMES in kwargs:
            quota_size = kwargs[self.VOLUMES]
            if volume_list is None:
                volume_list = self.client().volumes.list(
                    search_opts=search_opts)
            total_size = len(volume_list)
            self._validate_quota(self.VOLUMES, quota_size, total_size)

        if self.SNAPSHOTS in kwargs:
            quota_size = kwargs[self.SNAPSHOTS]
            if snapshot_list is None:
                snapshot_list = self.client().volume_snapshots.list(
                    search_opts=search_opts)
            total_size = len(snapshot_list)
            self._validate_quota(self.SNAPSHOTS, quota_size, total_size)

    def _set_quota(self, props=None):
        if props is None:
            props = self.properties

        kwargs = dict((k, v) for k, v in props.items()
                      if k != self.PROJECT and v is not None)
        # TODO(ricolin): Move this to stack validate stage. In some cases
        # we still can't get project or other properties form other resources
        # at validate stage.
        self.validate_quotas(props[self.PROJECT], **kwargs)
        self.client().quotas.update(props[self.PROJECT], **kwargs)

    def handle_delete(self):
        self.client().quotas.delete(self.properties[self.PROJECT])

    def validate(self):
        super(CinderQuota, self).validate()
        if sum(1 for p in self.properties.values() if p is not None) <= 1:
            raise exception.PropertyUnspecifiedError(self.GIGABYTES,
                                                     self.SNAPSHOTS,
                                                     self.VOLUMES)


def resource_mapping():
    return {
        'OS::Cinder::Quota': CinderQuota
    }
