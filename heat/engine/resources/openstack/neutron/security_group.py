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


class SecurityGroup(neutron.NeutronResource):
    """A resource for managing Neutron security groups.

    Security groups are sets of IP filter rules that are applied to an
    instance's networking. They are project specific, and project members can
    edit the default rules for their group and add new rules sets. All projects
    have a "default" security group, which is applied to instances that have no
    other security group defined.
    """

    required_service_extension = 'security-group'

    entity = 'security_group'

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        NAME, DESCRIPTION, RULES,
    ) = (
        'name', 'description', 'rules',
    )

    _RULE_KEYS = (
        RULE_DIRECTION, RULE_ETHERTYPE, RULE_PORT_RANGE_MIN,
        RULE_PORT_RANGE_MAX, RULE_PROTOCOL, RULE_REMOTE_MODE,
        RULE_REMOTE_GROUP_ID, RULE_REMOTE_IP_PREFIX, RULE_DESCRIPTION,
    ) = (
        'direction', 'ethertype', 'port_range_min',
        'port_range_max', 'protocol', 'remote_mode',
        'remote_group_id', 'remote_ip_prefix', 'description',
    )

    _rule_schema = {
        RULE_DIRECTION: properties.Schema(
            properties.Schema.STRING,
            _('The direction in which the security group rule is applied. '
              'For a compute instance, an ingress security group rule '
              'matches traffic that is incoming (ingress) for that '
              'instance. An egress rule is applied to traffic leaving '
              'the instance.'),
            default='ingress',
            constraints=[
                constraints.AllowedValues(['ingress', 'egress']),
            ]
        ),
        RULE_ETHERTYPE: properties.Schema(
            properties.Schema.STRING,
            _('Ethertype of the traffic.'),
            default='IPv4',
            constraints=[
                constraints.AllowedValues(['IPv4', 'IPv6']),
            ]
        ),
        RULE_PORT_RANGE_MIN: properties.Schema(
            properties.Schema.INTEGER,
            _('The minimum port number in the range that is matched by the '
              'security group rule. If the protocol is TCP or UDP, this '
              'value must be less than or equal to the value of the '
              'port_range_max attribute. If the protocol is ICMP, this '
              'value must be an ICMP type.'),
            constraints=[
                constraints.Range(0, 65535)
            ]
        ),
        RULE_PORT_RANGE_MAX: properties.Schema(
            properties.Schema.INTEGER,
            _('The maximum port number in the range that is matched by the '
              'security group rule. The port_range_min attribute constrains '
              'the port_range_max attribute. If the protocol is ICMP, this '
              'value must be an ICMP type.'),
            constraints=[
                constraints.Range(0, 65535)
            ]
        ),
        RULE_PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _(neutron.SECURITY_GROUP_PROTOCOL_DESCRIPTION +
              ' If not specified, all protocols will be matched.'),
            constraints=[
                constraints.AllowedValues(
                    neutron.ALLOWED_SECURITY_GROUP_PROTOCOLS)
            ]
        ),
        RULE_REMOTE_MODE: properties.Schema(
            properties.Schema.STRING,
            _('Whether to specify a remote group or a remote IP prefix.'),
            default='remote_ip_prefix',
            constraints=[
                constraints.AllowedValues(['remote_ip_prefix',
                                           'remote_group_id']),
            ]
        ),
        RULE_REMOTE_GROUP_ID: properties.Schema(
            properties.Schema.STRING,
            _('The remote group ID to be associated with this security group '
              'rule. If no value is specified then this rule will use this '
              'security group for the remote_group_id. The remote mode '
              'parameter must be set to "remote_group_id".'),
            constraints=[
                constraints.CustomConstraint('neutron.security_group')
            ]
        ),
        RULE_REMOTE_IP_PREFIX: properties.Schema(
            properties.Schema.STRING,
            _('The remote IP prefix (CIDR) to be associated with this '
              'security group rule.'),
            constraints=[
                constraints.CustomConstraint('net_cidr')
            ]
        ),
        RULE_DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the security group rule.'),
            support_status=support.SupportStatus(version='27.0.0')
        ),
    }

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('A string specifying a symbolic name for the security group, '
              'which is not required to be unique.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the security group.'),
            update_allowed=True
        ),
        RULES: properties.Schema(
            properties.Schema.LIST,
            _('List of security group rules.'),
            default=[],
            schema=properties.Schema(
                properties.Schema.MAP,
                schema=_rule_schema
            ),
            update_allowed=True
        ),
    }

    default_egress_rules = [
        {"direction": "egress", "ethertype": "IPv4"},
        {"direction": "egress", "ethertype": "IPv6"}
    ]

    _COMPARABLE_RULE_KEYS = (
        'direction', 'ethertype', 'protocol',
        'port_range_min', 'port_range_max',
        'remote_group_id', 'remote_ip_prefix',
        'security_group_id',
    )

    @staticmethod
    def _rule_key(rule):
        return tuple(
            str(rule.get(k)) if rule.get(k) is not None else None
            for k in SecurityGroup._COMPARABLE_RULE_KEYS
        )

    def validate(self):
        super(SecurityGroup, self).validate()
        if self.properties[self.NAME] == 'default':
            msg = _('Security groups cannot be assigned the name "default".')
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        rules = props.pop(self.RULES, [])

        sec = self.client().create_security_group(
            {'security_group': props})['security_group']

        self.resource_id_set(sec['id'])
        self._create_rules(rules)

    def _format_rule(self, r):
        rule = dict(r)
        rule['security_group_id'] = self.resource_id

        if 'remote_mode' in rule:
            remote_mode = rule.get(self.RULE_REMOTE_MODE)
            del rule[self.RULE_REMOTE_MODE]

            if remote_mode == self.RULE_REMOTE_GROUP_ID:
                rule[self.RULE_REMOTE_IP_PREFIX] = None
                if not rule.get(self.RULE_REMOTE_GROUP_ID):
                    # if remote group is not specified then make this
                    # a self-referencing rule
                    rule[self.RULE_REMOTE_GROUP_ID] = self.resource_id
            else:
                rule[self.RULE_REMOTE_GROUP_ID] = None

        for key in (self.RULE_PORT_RANGE_MIN, self.RULE_PORT_RANGE_MAX):
            if rule.get(key) is not None:
                rule[key] = str(rule[key])

        # Remove description if None - Neutron API doesn't accept None
        if rule.get(self.RULE_DESCRIPTION) is None:
            rule.pop(self.RULE_DESCRIPTION, None)

        return rule

    def _create_rules(self, rules):
        if not rules:
            return

        if any(r[self.RULE_DIRECTION] == 'egress' for r in rules):
            self._delete_rules(
                lambda rule: rule[self.RULE_DIRECTION] == 'egress')

        formatted_rules = [self._format_rule(r) for r in rules]

        self.client().create_security_group_rule(
            {'security_group_rules': formatted_rules})

    def _delete_rules(self, to_delete=None):
        try:
            sec = self.client().show_security_group(
                self.resource_id)['security_group']
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            for rule in sec['security_group_rules']:
                if to_delete is None or to_delete(rule):
                    with self.client_plugin().ignore_not_found:
                        self.client().delete_security_group_rule(rule['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return

        self._delete_rules()
        with self.client_plugin().ignore_not_found:
            self.client().delete_security_group(self.resource_id)

    def _update_rules(self, rules):
        desired_rules = list(rules) if rules else []
        if not any(r[self.RULE_DIRECTION] == 'egress'
                   for r in desired_rules):
            desired_rules.extend(self.default_egress_rules)

        desired = [(self._rule_key(r), r)
                   for r in (self._format_rule(r) for r in desired_rules)]
        desired_keys = set(k for k, r in desired)

        sec = self.client().show_security_group(
            self.resource_id)['security_group']

        current = [(self._rule_key(r), r)
                   for r in sec['security_group_rules']]
        current_keys = set(k for k, r in current)

        stale = current_keys - desired_keys
        missing = desired_keys - current_keys

        for key, rule in current:
            if key in stale:
                with self.client_plugin().ignore_not_found:
                    self.client().delete_security_group_rule(rule['id'])

        if missing:
            new_rules = [rule for key, rule in desired if key in missing]
            self.client().create_security_group_rule(
                {'security_group_rules': new_rules})

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        rules = prop_diff.pop(self.RULES, None)

        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client().update_security_group(
                self.resource_id, {'security_group': prop_diff})

        if rules is not None:
            self._update_rules(rules)


def resource_mapping():
    return {
        'OS::Neutron::SecurityGroup': SecurityGroup,
    }
