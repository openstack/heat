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

from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.neutron import neutron
from heat.engine.resources.neutron import subnet
from heat.engine import support
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class Port(neutron.NeutronResource):

    PROPERTIES = (
        NETWORK_ID, NETWORK, NAME, VALUE_SPECS,
        ADMIN_STATE_UP, FIXED_IPS, MAC_ADDRESS,
        DEVICE_ID, SECURITY_GROUPS, ALLOWED_ADDRESS_PAIRS,
        DEVICE_OWNER, REPLACEMENT_POLICY,
    ) = (
        'network_id', 'network', 'name', 'value_specs',
        'admin_state_up', 'fixed_ips', 'mac_address',
        'device_id', 'security_groups', 'allowed_address_pairs',
        'device_owner', 'replacement_policy',
    )

    _FIXED_IP_KEYS = (
        FIXED_IP_SUBNET_ID, FIXED_IP_SUBNET, FIXED_IP_IP_ADDRESS,
    ) = (
        'subnet_id', 'subnet', 'ip_address',
    )

    _ALLOWED_ADDRESS_PAIR_KEYS = (
        ALLOWED_ADDRESS_PAIR_MAC_ADDRESS, ALLOWED_ADDRESS_PAIR_IP_ADDRESS,
    ) = (
        'mac_address', 'ip_address',
    )

    ATTRIBUTES = (
        ADMIN_STATE_UP_ATTR, DEVICE_ID_ATTR, DEVICE_OWNER_ATTR, FIXED_IPS_ATTR,
        MAC_ADDRESS_ATTR, NAME_ATTR, NETWORK_ID_ATTR, SECURITY_GROUPS_ATTR,
        STATUS, TENANT_ID, ALLOWED_ADDRESS_PAIRS_ATTR, SHOW, SUBNETS_ATTR,
    ) = (
        'admin_state_up', 'device_id', 'device_owner', 'fixed_ips',
        'mac_address', 'name', 'network_id', 'security_groups',
        'status', 'tenant_id', 'allowed_address_pairs', 'show', 'subnets',
    )

    properties_schema = {
        NETWORK_ID: properties.Schema(
            properties.Schema.STRING,
            support_status=support.SupportStatus(
                support.DEPRECATED,
                _('Use property %s.') % NETWORK)
        ),

        NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('Network this port belongs to.')
        ),

        NAME: properties.Schema(
            properties.Schema.STRING,
            _('A symbolic name for this port.'),
            update_allowed=True
        ),
        VALUE_SPECS: properties.Schema(
            properties.Schema.MAP,
            _('Extra parameters to include in the "port" object in the '
              'creation request.'),
            default={}
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of this port.'),
            default=True,
            update_allowed=True
        ),
        FIXED_IPS: properties.Schema(
            properties.Schema.LIST,
            _('Desired IPs for this port.'),
            default=[],
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    FIXED_IP_SUBNET_ID: properties.Schema(
                        properties.Schema.STRING,
                        support_status=support.SupportStatus(
                            support.DEPRECATED,
                            _('Use property %s.') % FIXED_IP_SUBNET)
                    ),
                    FIXED_IP_SUBNET: properties.Schema(
                        properties.Schema.STRING,
                        _('Subnet in which to allocate the IP address for '
                          'this port.')
                    ),
                    FIXED_IP_IP_ADDRESS: properties.Schema(
                        properties.Schema.STRING,
                        _('IP address desired in the subnet for this port.')
                    ),
                },
            ),
            update_allowed=True
        ),
        MAC_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('MAC address to give to this port.')
        ),
        DEVICE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Device ID of this port.'),
            update_allowed=True
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('Security group IDs to associate with this port.'),
            default=[],
            update_allowed=True
        ),
        ALLOWED_ADDRESS_PAIRS: properties.Schema(
            properties.Schema.LIST,
            _('Additional MAC/IP address pairs allowed to pass through the '
              'port.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    ALLOWED_ADDRESS_PAIR_MAC_ADDRESS: properties.Schema(
                        properties.Schema.STRING,
                        _('MAC address to allow through this port.')
                    ),
                    ALLOWED_ADDRESS_PAIR_IP_ADDRESS: properties.Schema(
                        properties.Schema.STRING,
                        _('IP address to allow through this port.'),
                        required=True
                    ),
                },
            )
        ),
        DEVICE_OWNER: properties.Schema(
            properties.Schema.STRING,
            _('Name of the network owning the port. '
              'The value is typically network:floatingip '
              'or network:router_interface or network:dhcp'),
            update_allowed=True
        ),
        REPLACEMENT_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('Policy on how to respond to a stack-update for this resource. '
              'REPLACE_ALWAYS will replace the port regardless of any '
              'property changes. AUTO will update the existing port for any '
              'changed update-allowed property.'),
            default='REPLACE_ALWAYS',
            constraints=[
                constraints.AllowedValues(['REPLACE_ALWAYS', 'AUTO']),
            ],
            update_allowed=True
        ),
    }

    attributes_schema = {
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _("The administrative state of this port.")
        ),
        DEVICE_ID_ATTR: attributes.Schema(
            _("Unique identifier for the device.")
        ),
        DEVICE_OWNER: attributes.Schema(
            _("Name of the network owning the port.")
        ),
        FIXED_IPS_ATTR: attributes.Schema(
            _("Fixed IP addresses.")
        ),
        MAC_ADDRESS_ATTR: attributes.Schema(
            _("MAC address of the port.")
        ),
        NAME_ATTR: attributes.Schema(
            _("Friendly name of the port.")
        ),
        NETWORK_ID_ATTR: attributes.Schema(
            _("Unique identifier for the network owning the port.")
        ),
        SECURITY_GROUPS_ATTR: attributes.Schema(
            _("A list of security groups for the port.")
        ),
        STATUS: attributes.Schema(
            _("The status of the port.")
        ),
        TENANT_ID: attributes.Schema(
            _("Tenant owning the port.")
        ),
        ALLOWED_ADDRESS_PAIRS_ATTR: attributes.Schema(
            _("Additional MAC/IP address pairs allowed to pass through "
              "a port.")
        ),
        SHOW: attributes.Schema(
            _("All attributes.")
        ),
        SUBNETS_ATTR: attributes.Schema(
            _("A list of all subnet attributes for the port.")
        ),
    }

    def validate(self):
        super(Port, self).validate()
        self._validate_depr_property_required(self.properties,
                                              self.NETWORK, self.NETWORK_ID)

    def add_dependencies(self, deps):
        super(Port, self).add_dependencies(deps)
        # Depend on any Subnet in this template with the same
        # network_id as this network_id.
        # It is not known which subnet a port might be assigned
        # to so all subnets in a network should be created before
        # the ports in that network.
        for res in self.stack.itervalues():
            if res.has_interface('OS::Neutron::Subnet'):
                dep_network = res.properties.get(
                    subnet.Subnet.NETWORK) or res.properties.get(
                        subnet.Subnet.NETWORK_ID)
                network = self.properties.get(
                    self.NETWORK) or self.properties.get(self.NETWORK_ID)
                if dep_network == network:
                    deps += (self, res)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        self.client_plugin().resolve_network(props, self.NETWORK, 'network_id')
        self._prepare_port_properties(props)

        port = self.neutron().create_port({'port': props})['port']
        self.resource_id_set(port['id'])

    def _prepare_port_properties(self, props):
        for fixed_ip in props.get(self.FIXED_IPS, []):
            for key, value in fixed_ip.items():
                if value is None:
                    fixed_ip.pop(key)
            if fixed_ip.get(self.FIXED_IP_SUBNET):
                self.client_plugin().resolve_subnet(
                    fixed_ip, self.FIXED_IP_SUBNET, 'subnet_id')
        # delete empty MAC addresses so that Neutron validation code
        # wouldn't fail as it not accepts Nones
        for pair in props.get(self.ALLOWED_ADDRESS_PAIRS, []):
            if (self.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS in pair and
                    pair[self.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS] is None):
                del pair[self.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS]

        if props.get(self.SECURITY_GROUPS):
            props[self.SECURITY_GROUPS] = self.client_plugin().\
                get_secgroup_uuids(props.get(self.SECURITY_GROUPS))
        else:
            props.pop(self.SECURITY_GROUPS, None)

        if not props[self.FIXED_IPS]:
            del(props[self.FIXED_IPS])

        del(props[self.REPLACEMENT_POLICY])

    def _show_resource(self):
        return self.neutron().show_port(
            self.resource_id)['port']

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_port(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return self._delete_task()

    def _resolve_attribute(self, name):
        if name == self.SUBNETS_ATTR:
            subnets = []
            try:
                fixed_ips = self._show_resource().get('fixed_ips', [])
                for fixed_ip in fixed_ips:
                    subnet_id = fixed_ip.get('subnet_id')
                    if subnet_id:
                        subnets.append(self.neutron().show_subnet(
                            subnet_id)['subnet'])
            except Exception as ex:
                LOG.warn(_("Failed to fetch resource attributes: %s") % ex)
                return
            return subnets
        return super(Port, self)._resolve_attribute(name)

    def _needs_update(self, after, before, after_props, before_props,
                      prev_resource):

        if after_props.get(self.REPLACEMENT_POLICY) == 'REPLACE_ALWAYS':
            raise resource.UpdateReplace(self.name)

        return super(Port, self)._needs_update(
            after, before, after_props, before_props, prev_resource)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)

        self._prepare_port_properties(props)
        LOG.debug('updating port with %s' % props)
        self.neutron().update_port(self.resource_id, {'port': props})

    def check_update_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)


def resource_mapping():
    return {
        'OS::Neutron::Port': Port,
    }
