# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from heat.engine import clients
from heat.engine import properties
from heat.engine.resources.neutron import neutron
from heat.openstack.common import log as logging

if clients.neutronclient is not None:
    import neutronclient.common.exceptions as neutron_exp

logger = logging.getLogger(__name__)


class SecurityGroup(neutron.NeutronResource):

    rule_schema = {
        'direction': properties.Schema(
            properties.STRING,
            _('The direction in which the security group rule is applied. '
              'For a compute instance, an ingress security group rule '
              'matches traffic that is incoming (ingress) for that '
              'instance. An egress rule is applied to traffic leaving '
              'the instance.'),
            default='ingress',
            constraints=[properties.AllowedValues(('ingress', 'egress'))]
        ),
        'ethertype': properties.Schema(
            properties.STRING,
            _('Ethertype of the traffic.'),
            default='IPv4',
            constraints=[properties.AllowedValues(('IPv4', 'IPv6'))]
        ),
        'port_range_min': properties.Schema(
            properties.INTEGER,
            _('The minimum port number in the range that is matched by the '
              'security group rule. If the protocol is TCP or UDP, this '
              'value must be less than or equal to the value of the '
              'port_range_max attribute. If the protocol is ICMP, this '
              'value must be an ICMP type.')
        ),
        'port_range_max': properties.Schema(
            properties.INTEGER,
            _('The maximum port number in the range that is matched by the '
              'security group rule. The port_range_min attribute constrains '
              'the port_range_max attribute. If the protocol is ICMP, this '
              'value must be an ICMP type.')
        ),
        'protocol': properties.Schema(
            properties.STRING,
            _('The protocol that is matched by the security group rule. '
              'Valid values include tcp, udp, and icmp.')
        ),
        'remote_mode': properties.Schema(
            properties.STRING,
            _('Whether to specify a remote group or a remote IP prefix.'),
            default='remote_ip_prefix',
            constraints=[properties.AllowedValues((
                'remote_ip_prefix', 'remote_group_id'))]
        ),
        'remote_group_id': properties.Schema(
            properties.STRING,
            _('The remote group ID to be associated with this security group '
              'rule. If no value is specified then this rule will use this '
              'security group for the remote_group_id.')
        ),
        'remote_ip_prefix': properties.Schema(
            properties.STRING,
            _('The remote IP prefix (CIDR) to be associated with this '
              'security group rule.')
        ),
    }

    properties_schema = {
        'name': properties.Schema(
            properties.STRING,
            _('A string specifying a symbolic name for '
              'the security group, which is not required to be '
              'unique.'),
            update_allowed=True
        ),
        'description': properties.Schema(
            properties.STRING,
            _('Description of the security group.'),
            update_allowed=True
        ),
        'rules': properties.Schema(
            properties.LIST,
            _('List of security group rules.'),
            default=[],
            schema=properties.Schema(
                properties.MAP,
                schema=rule_schema
            ),
            update_allowed=True
        )
    }

    default_egress_rules = [
        {"direction": "egress", "ethertype": "IPv4"},
        {"direction": "egress", "ethertype": "IPv6"}
    ]

    update_allowed_keys = ('Properties',)

    def validate(self):
        super(SecurityGroup, self).validate()
        if self.properties.get('name') == 'default':
            msg = _('Security groups cannot be assigned the name "default".')
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        rules = props.pop('rules', [])

        sec = self.neutron().create_security_group(
            {'security_group': props})['security_group']

        self.resource_id_set(sec['id'])
        self._create_rules(rules)

    def _format_rule(self, r):
        rule = dict(r)
        rule['security_group_id'] = self.resource_id

        if 'remote_mode' in rule:
            remote_mode = rule.get('remote_mode')
            del(rule['remote_mode'])

            if remote_mode == 'remote_group_id':
                rule['remote_ip_prefix'] = None
                if not rule.get('remote_group_id'):
                    # if remote group is not specified then make this
                    # a self-referencing rule
                    rule['remote_group_id'] = self.resource_id
            else:
                rule['remote_group_id'] = None

        if rule.get('port_range_min', None) is not None:
            rule['port_range_min'] = str(rule['port_range_min'])
        if rule.get('port_range_max', None) is not None:
            rule['port_range_max'] = str(rule['port_range_max'])
        return rule

    def _create_rules(self, rules):
        egress_deleted = False

        for i in rules:
            if i['direction'] == 'egress' and not egress_deleted:
                # There is at least one egress rule, so delete the default
                # rules which allow all egress traffic
                egress_deleted = True

                def is_egress(rule):
                    return rule['direction'] == 'egress'

                self._delete_rules(is_egress)

            rule = self._format_rule(i)

            try:
                self.neutron().create_security_group_rule(
                    {'security_group_rule': rule})
            except neutron_exp.NeutronClientException as ex:
                # ignore error if rule already exists
                if ex.status_code != 409:
                    raise

    def _delete_rules(self, to_delete=None):
        try:
            sec = self.neutron().show_security_group(
                self.resource_id)['security_group']
        except neutron_exp.NeutronClientException as ex:
            if ex.status_code != 404:
                raise
        else:
            for rule in sec['security_group_rules']:
                if to_delete is None or to_delete(rule):
                    try:
                        self.neutron().delete_security_group_rule(rule['id'])
                    except neutron_exp.NeutronClientException as ex:
                        if ex.status_code != 404:
                            raise

    def handle_delete(self):

        if self.resource_id is None:
            return

        self._delete_rules()
        try:
            self.neutron().delete_security_group(self.resource_id)
        except neutron_exp.NeutronClientException as ex:
            if ex.status_code != 404:
                raise
        self.resource_id_set(None)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)
        rules = props.pop('rules', [])

        self.neutron().update_security_group(
            self.resource_id, {'security_group': props})

        # handle rules changes by:
        # * deleting all rules
        # * restoring the default egress rules
        # * creating new rules
        self._delete_rules()
        self._create_rules(self.default_egress_rules)
        if rules:
            self._create_rules(rules)


def resource_mapping():
    return {
        'OS::Neutron::SecurityGroup': SecurityGroup,
    }
