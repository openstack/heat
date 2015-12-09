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
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class Firewall(neutron.NeutronResource):
    """A resource for the Firewall resource in Neutron FWaaS.

    Resource for using the Neutron firewall implementation. Firewall is a
    network security system that monitors and controls the incoming and
    outgoing network traffic based on predetermined security rules.
    """

    required_service_extension = 'fwaas'

    entity = 'firewall'

    PROPERTIES = (
        NAME, DESCRIPTION, ADMIN_STATE_UP, FIREWALL_POLICY_ID,
        VALUE_SPECS, SHARED,
    ) = (
        'name', 'description', 'admin_state_up', 'firewall_policy_id',
        'value_specs', 'shared',
    )

    ATTRIBUTES = (
        NAME_ATTR, DESCRIPTION_ATTR, ADMIN_STATE_UP_ATTR,
        FIREWALL_POLICY_ID_ATTR, SHARED_ATTR, STATUS, TENANT_ID,
    ) = (
        'name', 'description', 'admin_state_up',
        'firewall_policy_id', 'shared', 'status', 'tenant_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the firewall.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the firewall.'),
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Administrative state of the firewall. If false (down), '
              'firewall does not forward packets and will drop all '
              'traffic to/from VMs behind the firewall.'),
            default=True,
            update_allowed=True
        ),
        FIREWALL_POLICY_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the firewall policy that this firewall is '
              'associated with.'),
            required=True,
            update_allowed=True
        ),
        VALUE_SPECS: properties.Schema(
            properties.Schema.MAP,
            _('Extra parameters to include in the request. Parameters '
              'are often specific to installed hardware or extensions.'),
            support_status=support.SupportStatus(version='5.0.0'),
            default={},
            update_allowed=True
        ),
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this firewall should be shared across all tenants. '
              'NOTE: The default policy setting in Neutron restricts usage '
              'of this property to administrative users only.'),
            update_allowed=True,
            support_status=support.SupportStatus(
                status=support.UNSUPPORTED,
                message=_('There is no such option during 5.0.0, so need to '
                          'make this property unsupported while it not used.'),
                version='6.0.0',
                previous_status=support.SupportStatus(version='2015.1')
            )
        ),
    }

    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _('Name for the firewall.'),
            type=attributes.Schema.STRING
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('Description of the firewall.'),
            type=attributes.Schema.STRING
        ),
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _('The administrative state of the firewall.'),
            type=attributes.Schema.STRING
        ),
        FIREWALL_POLICY_ID_ATTR: attributes.Schema(
            _('Unique identifier of the firewall policy used to create '
              'the firewall.'),
            type=attributes.Schema.STRING
        ),
        SHARED_ATTR: attributes.Schema(
            _('Shared status of this firewall.'),
            support_status=support.SupportStatus(
                status=support.UNSUPPORTED,
                message=_('There is no such option during 5.0.0, so need to '
                          'make this attribute unsupported, otherwise error '
                          'will raised.'),
                version='6.0.0'
            ),
            type=attributes.Schema.STRING
        ),
        STATUS: attributes.Schema(
            _('The status of the firewall.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('Id of the tenant owning the firewall.'),
            type=attributes.Schema.STRING
        ),
    }

    def check_create_complete(self, data):
        attributes = self._show_resource()
        status = attributes['status']
        if status == 'PENDING_CREATE':
            return False
        elif status == 'ACTIVE':
            return True
        elif status == 'ERROR':
            raise exception.ResourceInError(
                resource_status=status,
                status_reason=_('Error in Firewall'))
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=status,
                result=_('Firewall creation failed'))

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        firewall = self.client().create_firewall({'firewall': props})[
            'firewall']
        self.resource_id_set(firewall['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client().update_firewall(
                self.resource_id, {'firewall': prop_diff})

    def handle_delete(self):
        try:
            self.client().delete_firewall(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True

    def _resolve_attribute(self, name):
        if name == self.SHARED_ATTR:
            return ('This attribute is currently unsupported in neutron '
                    'firewall resource.')
        return super(Firewall, self)._resolve_attribute(name)

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(Firewall, self).parse_live_resource_data(
            resource_properties, resource_data)
        if self.SHARED in result:
            result.pop(self.SHARED)
        return result


class FirewallPolicy(neutron.NeutronResource):
    """A resource for the FirewallPolicy resource in Neutron FWaaS.

    FirewallPolicy resource is an ordered collection of firewall rules. A
    firewall policy can be shared across tenants.
    """

    required_service_extension = 'fwaas'

    entity = 'firewall_policy'

    PROPERTIES = (
        NAME, DESCRIPTION, SHARED, AUDITED, FIREWALL_RULES,
    ) = (
        'name', 'description', 'shared', 'audited', 'firewall_rules',
    )

    ATTRIBUTES = (
        NAME_ATTR, DESCRIPTION_ATTR, FIREWALL_RULES_ATTR, SHARED_ATTR,
        AUDITED_ATTR, TENANT_ID,
    ) = (
        'name', 'description', 'firewall_rules', 'shared',
        'audited', 'tenant_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the firewall policy.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the firewall policy.'),
            update_allowed=True
        ),
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this policy should be shared across all tenants.'),
            default=False,
            update_allowed=True
        ),
        AUDITED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this policy should be audited. When set to True, '
              'each time the firewall policy or the associated firewall '
              'rules are changed, this attribute will be set to False and '
              'will have to be explicitly set to True through an update '
              'operation.'),
            default=False,
            update_allowed=True
        ),
        FIREWALL_RULES: properties.Schema(
            properties.Schema.LIST,
            _('An ordered list of firewall rules to apply to the firewall.'),
            required=True,
            update_allowed=True
        ),
    }

    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _('Name for the firewall policy.'),
            type=attributes.Schema.STRING
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('Description of the firewall policy.'),
            type=attributes.Schema.STRING
        ),
        FIREWALL_RULES_ATTR: attributes.Schema(
            _('List of firewall rules in this firewall policy.'),
            type=attributes.Schema.LIST
        ),
        SHARED_ATTR: attributes.Schema(
            _('Shared status of this firewall policy.'),
            type=attributes.Schema.STRING
        ),
        AUDITED_ATTR: attributes.Schema(
            _('Audit status of this firewall policy.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('Id of the tenant owning the firewall policy.'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        firewall_policy = self.client().create_firewall_policy(
            {'firewall_policy': props})['firewall_policy']
        self.resource_id_set(firewall_policy['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_firewall_policy(
                self.resource_id, {'firewall_policy': prop_diff})

    def handle_delete(self):
        try:
            self.client().delete_firewall_policy(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


class FirewallRule(neutron.NeutronResource):
    """A resource for the FirewallRule resource in Neutron FWaaS.

    FirewallRule represents a collection of attributes like ports,
    ip addresses etc. which define match criteria and action (allow, or deny)
    that needs to be taken on the matched data traffic.
    """

    required_service_extension = 'fwaas'

    entity = 'firewall_rule'

    PROPERTIES = (
        NAME, DESCRIPTION, SHARED, PROTOCOL, IP_VERSION,
        SOURCE_IP_ADDRESS, DESTINATION_IP_ADDRESS, SOURCE_PORT,
        DESTINATION_PORT, ACTION, ENABLED,
    ) = (
        'name', 'description', 'shared', 'protocol', 'ip_version',
        'source_ip_address', 'destination_ip_address', 'source_port',
        'destination_port', 'action', 'enabled',
    )

    ATTRIBUTES = (
        NAME_ATTR, DESCRIPTION_ATTR, FIREWALL_POLICY_ID, SHARED_ATTR,
        PROTOCOL_ATTR, IP_VERSION_ATTR, SOURCE_IP_ADDRESS_ATTR,
        DESTINATION_IP_ADDRESS_ATTR, SOURCE_PORT_ATTR, DESTINATION_PORT_ATTR,
        ACTION_ATTR, ENABLED_ATTR, POSITION, TENANT_ID,
    ) = (
        'name', 'description', 'firewall_policy_id', 'shared',
        'protocol', 'ip_version', 'source_ip_address',
        'destination_ip_address', 'source_port', 'destination_port',
        'action', 'enabled', 'position', 'tenant_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the firewall rule.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the firewall rule.'),
            update_allowed=True
        ),
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this rule should be shared across all tenants.'),
            default=False,
            update_allowed=True
        ),
        PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _('Protocol for the firewall rule.'),
            constraints=[
                constraints.AllowedValues(['tcp', 'udp', 'icmp', 'any']),
            ],
            default='any',
            update_allowed=True,
        ),
        IP_VERSION: properties.Schema(
            properties.Schema.STRING,
            _('Internet protocol version.'),
            default='4',
            constraints=[
                constraints.AllowedValues(['4', '6']),
            ],
            update_allowed=True
        ),
        SOURCE_IP_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('Source IP address or CIDR.'),
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('net_cidr')
            ]
        ),
        DESTINATION_IP_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('Destination IP address or CIDR.'),
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('net_cidr')
            ]
        ),
        SOURCE_PORT: properties.Schema(
            properties.Schema.STRING,
            _('Source port number or a range.'),
            update_allowed=True
        ),
        DESTINATION_PORT: properties.Schema(
            properties.Schema.STRING,
            _('Destination port number or a range.'),
            update_allowed=True
        ),
        ACTION: properties.Schema(
            properties.Schema.STRING,
            _('Action to be performed on the traffic matching the rule.'),
            default='deny',
            constraints=[
                constraints.AllowedValues(['allow', 'deny']),
            ],
            update_allowed=True
        ),
        ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this rule should be enabled.'),
            default=True,
            update_allowed=True
        ),
    }

    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _('Name for the firewall rule.'),
            type=attributes.Schema.STRING
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('Description of the firewall rule.'),
            type=attributes.Schema.STRING
        ),
        FIREWALL_POLICY_ID: attributes.Schema(
            _('Unique identifier of the firewall policy to which this '
              'firewall rule belongs.'),
            type=attributes.Schema.STRING
        ),
        SHARED_ATTR: attributes.Schema(
            _('Shared status of this firewall rule.'),
            type=attributes.Schema.STRING
        ),
        PROTOCOL_ATTR: attributes.Schema(
            _('Protocol value for this firewall rule.'),
            type=attributes.Schema.STRING
        ),
        IP_VERSION_ATTR: attributes.Schema(
            _('Ip_version for this firewall rule.'),
            type=attributes.Schema.STRING
        ),
        SOURCE_IP_ADDRESS_ATTR: attributes.Schema(
            _('Source ip_address for this firewall rule.'),
            type=attributes.Schema.STRING
        ),
        DESTINATION_IP_ADDRESS_ATTR: attributes.Schema(
            _('Destination ip_address for this firewall rule.'),
            type=attributes.Schema.STRING
        ),
        SOURCE_PORT_ATTR: attributes.Schema(
            _('Source port range for this firewall rule.'),
            type=attributes.Schema.STRING
        ),
        DESTINATION_PORT_ATTR: attributes.Schema(
            _('Destination port range for this firewall rule.'),
            type=attributes.Schema.STRING
        ),
        ACTION_ATTR: attributes.Schema(
            _('Allow or deny action for this firewall rule.'),
            type=attributes.Schema.STRING
        ),
        ENABLED_ATTR: attributes.Schema(
            _('Indicates whether this firewall rule is enabled or not.'),
            type=attributes.Schema.STRING
        ),
        POSITION: attributes.Schema(
            _('Position of the rule within the firewall policy.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('Id of the tenant owning the firewall.'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        if props.get(self.PROTOCOL) == 'any':
            props[self.PROTOCOL] = None
        firewall_rule = self.client().create_firewall_rule(
            {'firewall_rule': props})['firewall_rule']
        self.resource_id_set(firewall_rule['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            if prop_diff.get(self.PROTOCOL) == 'any':
                prop_diff[self.PROTOCOL] = None
            self.client().update_firewall_rule(
                self.resource_id, {'firewall_rule': prop_diff})

    def handle_delete(self):
        try:
            self.client().delete_firewall_rule(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


def resource_mapping():
    return {
        'OS::Neutron::Firewall': Firewall,
        'OS::Neutron::FirewallPolicy': FirewallPolicy,
        'OS::Neutron::FirewallRule': FirewallRule,
    }
