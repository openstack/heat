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

from heat.engine import clients
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.neutron import neutron
from heat.openstack.common import log as logging

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException

logger = logging.getLogger(__name__)


class Firewall(neutron.NeutronResource):
    """
    A resource for the Firewall resource in Neutron FWaaS.
    """

    PROPERTIES = (
        NAME, DESCRIPTION, ADMIN_STATE_UP, FIREWALL_POLICY_ID,
    ) = (
        'name', 'description', 'admin_state_up', 'firewall_policy_id',
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
    }

    attributes_schema = {
        'name': _('Name for the firewall.'),
        'description': _('Description of the firewall.'),
        'admin_state_up': _('The administrative state of the firewall.'),
        'firewall_policy_id': _('Unique identifier of the firewall policy '
                                'used to create the firewall.'),
        'status': _('The status of the firewall.'),
        'tenant_id': _('Id of the tenant owning the firewall.'),
        'show': _('All attributes.'),
    }

    update_allowed_keys = ('Properties',)

    def _show_resource(self):
        return self.neutron().show_firewall(self.resource_id)['firewall']

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        firewall = self.neutron().create_firewall({'firewall': props})[
            'firewall']
        self.resource_id_set(firewall['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_firewall(
                self.resource_id, {'firewall': prop_diff})

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_firewall(self.resource_id)
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return self._delete_task()


class FirewallPolicy(neutron.NeutronResource):
    """
    A resource for the FirewallPolicy resource in Neutron FWaaS.
    """

    PROPERTIES = (
        NAME, DESCRIPTION, SHARED, AUDITED, FIREWALL_RULES,
    ) = (
        'name', 'description', 'shared', 'audited', 'firewall_rules',
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
        'name': _('Name for the firewall policy.'),
        'description': _('Description of the firewall policy.'),
        'firewall_rules': _('List of firewall rules in this firewall policy.'),
        'shared': _('Shared status of this firewall policy.'),
        'audited': _('Audit status of this firewall policy.'),
        'tenant_id': _('Id of the tenant owning the firewall policy.')
    }

    update_allowed_keys = ('Properties',)

    def _show_resource(self):
        return self.neutron().show_firewall_policy(self.resource_id)[
            'firewall_policy']

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        firewall_policy = self.neutron().create_firewall_policy(
            {'firewall_policy': props})['firewall_policy']
        self.resource_id_set(firewall_policy['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_firewall_policy(
                self.resource_id, {'firewall_policy': prop_diff})

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_firewall_policy(self.resource_id)
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return self._delete_task()


class FirewallRule(neutron.NeutronResource):
    """
    A resource for the FirewallRule resource in Neutron FWaaS.
    """

    PROPERTIES = (
        NAME, DESCRIPTION, SHARED, PROTOCOL, IP_VERSION,
        SOURCE_IP_ADDRESS, DESTINATION_IP_ADDRESS, SOURCE_PORT,
        DESTINATION_PORT, ACTION, ENABLED,
    ) = (
        'name', 'description', 'shared', 'protocol', 'ip_version',
        'source_ip_address', 'destination_ip_address', 'source_port',
        'destination_port', 'action', 'enabled',
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
                constraints.AllowedValues(['tcp', 'udp', 'icmp', None]),
            ],
            update_allowed=True
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
            update_allowed=True
        ),
        DESTINATION_IP_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('Destination IP address or CIDR.'),
            update_allowed=True
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
        'name': _('Name for the firewall rule.'),
        'description': _('Description of the firewall rule.'),
        'firewall_policy_id': _('Unique identifier of the firewall policy to '
                                'which this firewall rule belongs.'),
        'shared': _('Shared status of this firewall rule.'),
        'protocol': _('Protocol value for this firewall rule.'),
        'ip_version': _('Ip_version for this firewall rule.'),
        'source_ip_address': _('Source ip_address for this firewall rule.'),
        'destination_ip_address': _('Destination ip_address for this '
                                    'firewall rule.'),
        'source_port': _('Source port range for this firewall rule.'),
        'destination_port': _('Destination port range for this firewall '
                              'rule.'),
        'action': _('Allow or deny action for this firewall rule.'),
        'enabled': _('Indicates whether this firewall rule is enabled or '
                     'not.'),
        'position': _('Position of the rule within the firewall policy.'),
        'tenant_id': _('Id of the tenant owning the firewall.')
    }

    update_allowed_keys = ('Properties',)

    def _show_resource(self):
        return self.neutron().show_firewall_rule(
            self.resource_id)['firewall_rule']

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        firewall_rule = self.neutron().create_firewall_rule(
            {'firewall_rule': props})['firewall_rule']
        self.resource_id_set(firewall_rule['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_firewall_rule(
                self.resource_id, {'firewall_rule': prop_diff})

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_firewall_rule(self.resource_id)
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return self._delete_task()


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::Firewall': Firewall,
        'OS::Neutron::FirewallPolicy': FirewallPolicy,
        'OS::Neutron::FirewallRule': FirewallRule,
    }
