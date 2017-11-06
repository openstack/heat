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


class SecurityGroupRule(neutron.NeutronResource):
    """A resource for managing Neutron security group rules.

    Rules to use in security group resource.
    """

    required_service_extension = 'security-group'

    entity = 'security_group_rule'

    support_status = support.SupportStatus(version='7.0.0')

    PROPERTIES = (
        SECURITY_GROUP, DESCRIPTION, DIRECTION, ETHERTYPE,
        PORT_RANGE_MIN, PORT_RANGE_MAX, PROTOCOL, REMOTE_GROUP,
        REMOTE_IP_PREFIX
    ) = (
        'security_group', 'description', 'direction', 'ethertype',
        'port_range_min', 'port_range_max', 'protocol', 'remote_group',
        'remote_ip_prefix'
    )

    _allowed_protocols = list(range(256)) + [
        'ah', 'dccp', 'egp', 'esp', 'gre', 'icmp', 'icmpv6', 'igmp',
        'ipv6-encap', 'ipv6-frag', 'ipv6-icmp', 'ipv6-nonxt', 'ipv6-opts',
        'ipv6-route', 'ospf', 'pgm', 'rsvp', 'sctp', 'tcp', 'udp', 'udplite',
        'vrrp'
    ]

    properties_schema = {
        SECURITY_GROUP: properties.Schema(
            properties.Schema.STRING,
            _('Security group name or ID to add rule.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.security_group')
            ]
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the security group rule.')
        ),
        DIRECTION: properties.Schema(
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
        ETHERTYPE: properties.Schema(
            properties.Schema.STRING,
            _('Ethertype of the traffic.'),
            default='IPv4',
            constraints=[
                constraints.AllowedValues(['IPv4', 'IPv6']),
            ]
        ),
        PORT_RANGE_MIN: properties.Schema(
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
        PORT_RANGE_MAX: properties.Schema(
            properties.Schema.INTEGER,
            _('The maximum port number in the range that is matched by the '
              'security group rule. The port_range_min attribute constrains '
              'the port_range_max attribute. If the protocol is ICMP, this '
              'value must be an ICMP code.'),
            constraints=[
                constraints.Range(0, 65535)
            ]
        ),
        PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _('The protocol that is matched by the security group rule. '
              'Allowed values are ah, dccp, egp, esp, gre, icmp, icmpv6, '
              'igmp, ipv6-encap, ipv6-frag, ipv6-icmp, ipv6-nonxt, ipv6-opts, '
              'ipv6-route, ospf, pgm, rsvp, sctp, tcp, udp, udplite, vrrp '
              'and integer representations [0-255].'),
            default='tcp',
            constraints=[constraints.AllowedValues(_allowed_protocols)]
            ),
        REMOTE_GROUP: properties.Schema(
            properties.Schema.STRING,
            _('The remote group name or ID to be associated with this '
              'security group rule.'),
            constraints=[
                constraints.CustomConstraint('neutron.security_group')
            ]
        ),
        REMOTE_IP_PREFIX: properties.Schema(
            properties.Schema.STRING,
            _('The remote IP prefix (CIDR) to be associated with this '
              'security group rule.'),
            constraints=[
                constraints.CustomConstraint('net_cidr')
            ]
        )
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.SECURITY_GROUP],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SECURITY_GROUP
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.REMOTE_GROUP],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SECURITY_GROUP
            ),
        ]

    def validate(self):
        super(SecurityGroupRule, self).validate()
        if (self.properties[self.REMOTE_GROUP] is not None and
                self.properties[self.REMOTE_IP_PREFIX] is not None):
            raise exception.ResourcePropertyConflict(
                self.REMOTE_GROUP, self.REMOTE_IP_PREFIX)
        port_max = self.properties[self.PORT_RANGE_MAX]
        port_min = self.properties[self.PORT_RANGE_MIN]
        protocol = self.properties[self.PROTOCOL]
        if (port_max is not None and port_min is not None and
                protocol not in ('icmp', 'icmpv6', 'ipv6-icmp') and
                port_max < port_min):
            msg = _('The minimum port number must be less than or equal to '
                    'the maximum port number.')
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        props['security_group_id'] = props.pop(self.SECURITY_GROUP)
        if self.REMOTE_GROUP in props:
            props['remote_group_id'] = props.pop(self.REMOTE_GROUP)

        for key in (self.PORT_RANGE_MIN, self.PORT_RANGE_MAX):
            if props.get(key) is not None:
                props[key] = str(props[key])

        rule = self.client().create_security_group_rule(
            {'security_group_rule': props})['security_group_rule']

        self.resource_id_set(rule['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            self.client().delete_security_group_rule(self.resource_id)


def resource_mapping():
    return {
        'OS::Neutron::SecurityGroupRule': SecurityGroupRule
    }
