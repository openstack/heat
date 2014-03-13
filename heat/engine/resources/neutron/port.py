
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
from heat.engine import properties
from heat.engine.resources.neutron import neutron
from heat.engine.resources.neutron import subnet
from heat.openstack.common import log as logging

if clients.neutronclient is not None:
    import neutronclient.common.exceptions as neutron_exp

logger = logging.getLogger(__name__)


class Port(neutron.NeutronResource):

    PROPERTIES = (
        NETWORK_ID, NAME, VALUE_SPECS, ADMIN_STATE_UP, FIXED_IPS,
        MAC_ADDRESS, DEVICE_ID, SECURITY_GROUPS, ALLOWED_ADDRESS_PAIRS,
        DEVICE_OWNER,
    ) = (
        'network_id', 'name', 'value_specs', 'admin_state_up', 'fixed_ips',
        'mac_address', 'device_id', 'security_groups', 'allowed_address_pairs',
        'device_owner',
    )

    _FIXED_IP_KEYS = (
        FIXED_IP_SUBNET_ID, FIXED_IP_IP_ADDRESS,
    ) = (
        'subnet_id', 'ip_address',
    )

    _ALLOWED_ADDRESS_PAIR_KEYS = (
        ALLOWED_ADDRESS_PAIR_MAC_ADDRESS, ALLOWED_ADDRESS_PAIR_IP_ADDRESS,
    ) = (
        'mac_address', 'ip_address',
    )

    properties_schema = {
        NETWORK_ID: properties.Schema(
            properties.Schema.STRING,
            _('Network ID this port belongs to.'),
            required=True
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
    }

    attributes_schema = {
        "admin_state_up": _("The administrative state of this port."),
        "device_id": _("Unique identifier for the device."),
        "device_owner": _("Name of the network owning the port."),
        "fixed_ips": _("Fixed IP addresses."),
        "mac_address": _("MAC address of the port."),
        "name": _("Friendly name of the port."),
        "network_id": _("Unique identifier for the network owning the port."),
        "security_groups": _("A list of security groups for the port."),
        "status": _("The status of the port."),
        "tenant_id": _("Tenant owning the port."),
        "allowed_address_pairs": _("Additional MAC/IP address pairs allowed "
                                   "to pass through a port."),
        "show": _("All attributes."),
    }

    update_allowed_keys = ('Properties',)

    def add_dependencies(self, deps):
        super(Port, self).add_dependencies(deps)
        # Depend on any Subnet in this template with the same
        # network_id as this network_id.
        # It is not known which subnet a port might be assigned
        # to so all subnets in a network should be created before
        # the ports in that network.
        for resource in self.stack.itervalues():
            if (resource.has_interface('OS::Neutron::Subnet') and
                resource.properties.get(subnet.Subnet.NETWORK_ID) ==
                    self.properties.get(self.NETWORK_ID)):
                        deps += (self, resource)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        self._prepare_list_properties(props)

        if not props['fixed_ips']:
            del(props['fixed_ips'])

        port = self.neutron().create_port({'port': props})['port']
        self.resource_id_set(port['id'])

    def _prepare_list_properties(self, props):
        for fixed_ip in props.get(self.FIXED_IPS, []):
            for key, value in fixed_ip.items():
                if value is None:
                    fixed_ip.pop(key)

        # delete empty MAC addresses so that Neutron validation code
        # wouldn't fail as it not accepts Nones
        for pair in props.get(self.ALLOWED_ADDRESS_PAIRS, []):
            if (self.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS in pair and
                    pair[self.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS] is None):
                del pair[self.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS]

        if props.get(self.SECURITY_GROUPS):
            props[self.SECURITY_GROUPS] = self.get_secgroup_uuids(
                props.get(self.SECURITY_GROUPS), self.neutron())
        else:
            props.pop(self.SECURITY_GROUPS, None)

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
        except neutron_exp.NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return self._delete_task()

    def _handle_not_found_exception(self, ex):
        # raise any exception which is not for a not found port
        if not (ex.status_code == 404 or
                isinstance(ex, neutron_exp.PortNotFoundClient)):
            raise ex

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)

        self._prepare_list_properties(props)

        logger.debug(_('updating port with %s') % props)
        self.neutron().update_port(self.resource_id, {'port': props})

    def check_update_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::Port': Port,
    }
