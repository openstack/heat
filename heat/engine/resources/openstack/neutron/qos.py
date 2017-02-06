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
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class QoSPolicy(neutron.NeutronResource):
    """A resource for Neutron QoS Policy.

    This QoS policy can be associated with neutron resources,
    such as port and network, to provide QoS capabilities.

    The default policy usage of this resource is limited to
    administrators only.
    """

    required_service_extension = 'qos'

    entity = 'qos_policy'

    res_info_key = 'policy'

    support_status = support.SupportStatus(version='6.0.0')

    PROPERTIES = (
        NAME, DESCRIPTION, SHARED, TENANT_ID,
    ) = (
        'name', 'description', 'shared', 'tenant_id',
    )

    ATTRIBUTES = (
        RULES_ATTR,
    ) = (
        'rules',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name for the QoS policy.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('The description for the QoS policy.'),
            update_allowed=True
        ),
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this QoS policy should be shared to other tenants.'),
            default=False,
            update_allowed=True
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The owner tenant ID of this QoS policy.')
        ),
    }

    attributes_schema = {
        RULES_ATTR: attributes.Schema(
            _("A list of all rules for the QoS policy."),
            type=attributes.Schema.LIST
        )
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        policy = self.client().create_qos_policy({'policy': props})['policy']
        self.resource_id_set(policy['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            self.client().delete_qos_policy(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client().update_qos_policy(
                self.resource_id,
                {'policy': prop_diff})


class QoSRule(neutron.NeutronResource):
    """A resource for Neutron QoS base rule."""

    required_service_extension = 'qos'

    support_status = support.SupportStatus(version='6.0.0')

    PROPERTIES = (
        POLICY,  TENANT_ID,
    ) = (
        'policy', 'tenant_id',
    )

    properties_schema = {
        POLICY: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the QoS policy.'),
            required=True,
            constraints=[constraints.CustomConstraint('neutron.qos_policy')]
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The owner tenant ID of this rule.')
        ),
    }

    def __init__(self, name, json_snippet, stack):
        super(QoSRule, self).__init__(name, json_snippet, stack)
        self._policy_id = None

    @property
    def policy_id(self):
        if not self._policy_id:
            self._policy_id = self.client_plugin().get_qos_policy_id(
                self.properties[self.POLICY])

        return self._policy_id


class QoSBandwidthLimitRule(QoSRule):
    """A resource for Neutron QoS bandwidth limit rule.

    This rule can be associated with QoS policy, and then the policy
    can be used by neutron port and network, to provide bandwidth limit
    QoS capabilities.

    The default policy usage of this resource is limited to
    administrators only.
    """

    entity = 'bandwidth_limit_rule'

    PROPERTIES = (
        MAX_BANDWIDTH, MAX_BURST_BANDWIDTH,
    ) = (
        'max_kbps', 'max_burst_kbps',
    )

    properties_schema = {
        MAX_BANDWIDTH: properties.Schema(
            properties.Schema.INTEGER,
            _('Max bandwidth in kbps.'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.Range(min=0)
            ]
        ),
        MAX_BURST_BANDWIDTH: properties.Schema(
            properties.Schema.INTEGER,
            _('Max burst bandwidth in kbps.'),
            update_allowed=True,
            constraints=[
                constraints.Range(min=0)
            ],
            default=0
        )
    }

    properties_schema.update(QoSRule.properties_schema)

    def handle_create(self):
        props = self.prepare_properties(self.properties,
                                        self.physical_resource_name())
        props.pop(self.POLICY)

        rule = self.client().create_bandwidth_limit_rule(
            self.policy_id,
            {'bandwidth_limit_rule': props})['bandwidth_limit_rule']

        self.resource_id_set(rule['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            self.client().delete_bandwidth_limit_rule(
                self.resource_id, self.policy_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_bandwidth_limit_rule(
                self.resource_id,
                self.policy_id,
                {'bandwidth_limit_rule': prop_diff})

    def _res_get_args(self):
        return [self.resource_id, self.policy_id]


class QoSDscpMarkingRule(QoSRule):
    """A resource for Neutron QoS DSCP marking rule.

    This rule can be associated with QoS policy, and then the policy
    can be used by neutron port and network, to provide DSCP marking
    QoS capabilities.

    The default policy usage of this resource is limited to
    administrators only.
    """

    support_status = support.SupportStatus(version='7.0.0')

    entity = 'dscp_marking_rule'

    PROPERTIES = (
        DSCP_MARK,
    ) = (
        'dscp_mark',
    )

    properties_schema = {
        DSCP_MARK: properties.Schema(
            properties.Schema.INTEGER,
            _('DSCP mark between 0 and 56, except 2-6, 42, 44, and 50-54.'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.AllowedValues([
                    0, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34,
                    36, 38, 40, 46, 48, 56]
                )
            ]
        )
    }

    properties_schema.update(QoSRule.properties_schema)

    def handle_create(self):
        props = self.prepare_properties(self.properties,
                                        self.physical_resource_name())
        props.pop(self.POLICY)

        rule = self.client().create_dscp_marking_rule(
            self.policy_id,
            {'dscp_marking_rule': props})['dscp_marking_rule']

        self.resource_id_set(rule['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            self.client().delete_dscp_marking_rule(
                self.resource_id, self.policy_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_dscp_marking_rule(
                self.resource_id,
                self.policy_id,
                {'dscp_marking_rule': prop_diff})

    def _res_get_args(self):
        return [self.resource_id, self.policy_id]


def resource_mapping():
    return {
        'OS::Neutron::QoSPolicy': QoSPolicy,
        'OS::Neutron::QoSBandwidthLimitRule': QoSBandwidthLimitRule,
        'OS::Neutron::QoSDscpMarkingRule': QoSDscpMarkingRule
    }
