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
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class NeutronQuota(neutron.NeutronResource):
    """A resource for managing neutron quotas.

    Neutron Quota is used to manage operational limits for projects. Currently,
    this resource can manage Neutron's quotas for:

        - subnet
        - network
        - floatingip
        - security_group_rule
        - security_group
        - router
        - port
        - subnetpool
        - rbac_policy

    Note that default neutron security policy usage of this resource
    is limited to being used by administrators only. Administrators should be
    careful to create only one Neutron Quota resource per project, otherwise
    it will be hard for them to manage the quota properly.
    """

    support_status = support.SupportStatus(version='8.0.0')

    required_service_extension = 'quotas'

    PROPERTIES = (
        PROJECT, SUBNET, NETWORK, FLOATINGIP, SECURITY_GROUP_RULE,
        SECURITY_GROUP, ROUTER, PORT, SUBNETPOOL, RBAC_POLICY
    ) = (
        'project', 'subnet', 'network', 'floatingip', 'security_group_rule',
        'security_group', 'router', 'port', 'subnetpool', 'rbac_policy'
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
        SUBNET: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of subnets. '
              'Setting -1 means unlimited.'),
            constraints=[constraints.Range(min=-1)],
            update_allowed=True
        ),
        NETWORK: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of networks. '
              'Setting -1 means unlimited.'),
            constraints=[constraints.Range(min=-1)],
            update_allowed=True
        ),
        FLOATINGIP: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of floating IPs. '
              'Setting -1 means unlimited.'),
            constraints=[constraints.Range(min=-1)],
            update_allowed=True
        ),
        SECURITY_GROUP_RULE: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of security group rules. '
              'Setting -1 means unlimited.'),
            constraints=[constraints.Range(min=-1)],
            update_allowed=True
        ),
        SECURITY_GROUP: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of security groups. '
              'Setting -1 means unlimited.'),
            constraints=[constraints.Range(min=-1)],
            update_allowed=True
        ),
        ROUTER: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of routers. '
              'Setting -1 means unlimited.'),
            constraints=[constraints.Range(min=-1)],
            update_allowed=True
        ),
        PORT: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of ports. '
              'Setting -1 means unlimited.'),
            constraints=[constraints.Range(min=-1)],
            update_allowed=True
        ),
        SUBNETPOOL: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of subnet pools. '
              'Setting -1 means unlimited.'),
            constraints=[constraints.Range(min=-1)],
            update_allowed=True,
            support_status=support.SupportStatus(version='12.0.0')
        ),
        RBAC_POLICY: properties.Schema(
            properties.Schema.INTEGER,
            _('Quota for the number of rbac policies. '
              'Setting -1 means unlimited.'),
            constraints=[constraints.Range(min=-1)],
            update_allowed=True,
            support_status=support.SupportStatus(version='12.0.0')
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
        body = {"quota": kwargs}
        self.client().update_quota(props[self.PROJECT], body)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().delete_quota(self.resource_id)

    def validate(self):
        super(NeutronQuota, self).validate()
        if sum(1 for p in self.properties.values() if p is not None) <= 1:
            raise exception.PropertyUnspecifiedError(
                *sorted(set(self.PROPERTIES) - {self.PROJECT}))


def resource_mapping():
    return {
        'OS::Neutron::Quota': NeutronQuota
    }
