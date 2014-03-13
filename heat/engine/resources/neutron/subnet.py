
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


class Subnet(neutron.NeutronResource):

    PROPERTIES = (
        NETWORK_ID, CIDR, VALUE_SPECS, NAME, IP_VERSION,
        DNS_NAMESERVERS, GATEWAY_IP, ENABLE_DHCP, ALLOCATION_POOLS,
        TENANT_ID, HOST_ROUTES,
    ) = (
        'network_id', 'cidr', 'value_specs', 'name', 'ip_version',
        'dns_nameservers', 'gateway_ip', 'enable_dhcp', 'allocation_pools',
        'tenant_id', 'host_routes',
    )

    _ALLOCATION_POOL_KEYS = (
        ALLOCATION_POOL_START, ALLOCATION_POOL_END,
    ) = (
        'start', 'end',
    )

    _HOST_ROUTES_KEYS = (
        ROUTE_DESTINATION, ROUTE_NEXTHOP,
    ) = (
        'destination', 'nexthop',
    )

    properties_schema = {
        NETWORK_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the attached network.'),
            required=True
        ),
        CIDR: properties.Schema(
            properties.Schema.STRING,
            _('The CIDR.'),
            required=True
        ),
        VALUE_SPECS: properties.Schema(
            properties.Schema.MAP,
            _('Extra parameters to include in the creation request.'),
            default={},
            update_allowed=True
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of the subnet.'),
            update_allowed=True
        ),
        IP_VERSION: properties.Schema(
            properties.Schema.INTEGER,
            _('The IP version, which is 4 or 6.'),
            default=4,
            constraints=[
                constraints.AllowedValues([4, 6]),
            ]
        ),
        DNS_NAMESERVERS: properties.Schema(
            properties.Schema.LIST,
            _('A specified set of DNS name servers to be used.'),
            default=[],
            update_allowed=True
        ),
        GATEWAY_IP: properties.Schema(
            properties.Schema.STRING,
            _('The gateway IP address.'),
            update_allowed=True
        ),
        ENABLE_DHCP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Set to true if DHCP is enabled and false if DHCP is disabled.'),
            default=True,
            update_allowed=True
        ),
        ALLOCATION_POOLS: properties.Schema(
            properties.Schema.LIST,
            _('The start and end addresses for the allocation pools.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    ALLOCATION_POOL_START: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    ALLOCATION_POOL_END: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
            )
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the tenant who owns the network. Only administrative'
              ' users can specify a tenant ID other than their own.')
        ),
        HOST_ROUTES: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    ROUTE_DESTINATION: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    ROUTE_NEXTHOP: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
            )
        ),
    }

    attributes_schema = {
        "name": _("Friendly name of the subnet."),
        "network_id": _("Parent network of the subnet."),
        "tenant_id": _("Tenant owning the subnet."),
        "allocation_pools": _("Ip allocation pools and their ranges."),
        "gateway_ip": _("Ip of the subnet's gateway."),
        "host_routes": _("Additional routes for this subnet."),
        "ip_version": _("Ip version for the subnet."),
        "cidr": _("CIDR block notation for this subnet."),
        "dns_nameservers": _("List of dns nameservers."),
        "enable_dhcp": _("'true' if DHCP is enabled for this subnet; 'false' "
                         "otherwise."),
        "show": _("All attributes."),
    }

    update_allowed_keys = ('Properties',)

    @classmethod
    def _null_gateway_ip(cls, props):
        if cls.GATEWAY_IP not in props:
            return
        # Specifying null in the gateway_ip will result in
        # a property containing an empty string.
        # A null gateway_ip has special meaning in the API
        # so this needs to be set back to None.
        # See bug https://bugs.launchpad.net/heat/+bug/1226666
        if props.get(cls.GATEWAY_IP) == '':
            props[cls.GATEWAY_IP] = None

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        self._null_gateway_ip(props)

        subnet = self.neutron().create_subnet({'subnet': props})['subnet']
        self.resource_id_set(subnet['id'])

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_subnet(self.resource_id)
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return self._delete_task()

    def _show_resource(self):
        return self.neutron().show_subnet(self.resource_id)['subnet']

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)
        self.neutron().update_subnet(
            self.resource_id, {'subnet': props})


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::Subnet': Subnet,
    }
