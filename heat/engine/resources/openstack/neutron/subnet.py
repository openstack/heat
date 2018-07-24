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

from oslo_utils import netutils

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class Subnet(neutron.NeutronResource):
    """A resource for managing Neutron subnets.

    A subnet represents an IP address block that can be used for assigning IP
    addresses to virtual instances. Each subnet must have a CIDR and must be
    associated with a network. IPs can be either selected from the whole subnet
    CIDR, or from "allocation pools" that can be specified by the user.
    """

    entity = 'subnet'

    PROPERTIES = (
        NETWORK_ID, NETWORK, SUBNETPOOL, PREFIXLEN, CIDR,
        VALUE_SPECS, NAME, IP_VERSION, DNS_NAMESERVERS, GATEWAY_IP,
        ENABLE_DHCP, ALLOCATION_POOLS, TENANT_ID, HOST_ROUTES,
        IPV6_RA_MODE, IPV6_ADDRESS_MODE, SEGMENT, TAGS,
    ) = (
        'network_id', 'network', 'subnetpool', 'prefixlen', 'cidr',
        'value_specs', 'name', 'ip_version', 'dns_nameservers', 'gateway_ip',
        'enable_dhcp', 'allocation_pools', 'tenant_id', 'host_routes',
        'ipv6_ra_mode', 'ipv6_address_mode', 'segment', 'tags',
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

    _IPV6_DHCP_MODES = (
        DHCPV6_STATEFUL, DHCPV6_STATELESS, SLAAC,
    ) = (
        'dhcpv6-stateful', 'dhcpv6-stateless', 'slaac',
    )

    ATTRIBUTES = (
        NAME_ATTR, NETWORK_ID_ATTR, TENANT_ID_ATTR, ALLOCATION_POOLS_ATTR,
        GATEWAY_IP_ATTR, HOST_ROUTES_ATTR, IP_VERSION_ATTR, CIDR_ATTR,
        DNS_NAMESERVERS_ATTR, ENABLE_DHCP_ATTR,
    ) = (
        'name', 'network_id', 'tenant_id', 'allocation_pools',
        'gateway_ip', 'host_routes', 'ip_version', 'cidr',
        'dns_nameservers', 'enable_dhcp',
    )

    properties_schema = {
        NETWORK_ID: properties.Schema(
            properties.Schema.STRING,
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='5.0.0',
                message=_('Use property %s.') % NETWORK,
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='2014.2'
                )
            ),
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
        ),
        NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the attached network.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
            support_status=support.SupportStatus(version='2014.2')
        ),
        SUBNETPOOL: properties.Schema(
            properties.Schema.STRING,
            _('The name or ID of the subnet pool.'),
            constraints=[
                constraints.CustomConstraint('neutron.subnetpool')
            ],
            support_status=support.SupportStatus(version='6.0.0'),
        ),
        PREFIXLEN: properties.Schema(
            properties.Schema.INTEGER,
            _('Prefix length for subnet allocation from subnet pool.'),
            constraints=[constraints.Range(min=0)],
            support_status=support.SupportStatus(version='6.0.0'),
        ),
        CIDR: properties.Schema(
            properties.Schema.STRING,
            _('The CIDR.'),
            constraints=[
                constraints.CustomConstraint('net_cidr')
            ]
        ),
        VALUE_SPECS: properties.Schema(
            properties.Schema.MAP,
            _('Extra parameters to include in the request.'),
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
            _('The gateway IP address. Set to any of [ null | ~ | "" ] '
              'to create/update a subnet without a gateway. '
              'If omitted when creation, neutron will assign the first '
              'free IP address within the subnet to the gateway '
              'automatically. If remove this from template when update, '
              'the old gateway IP address will be detached.'),
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
                        _('Start address for the allocation pool.'),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('ip_addr')
                        ]
                    ),
                    ALLOCATION_POOL_END: properties.Schema(
                        properties.Schema.STRING,
                        _('End address for the allocation pool.'),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('ip_addr')
                        ]
                    ),
                },
            ),
            update_allowed=True
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the tenant who owns the network. Only administrative '
              'users can specify a tenant ID other than their own.')
        ),
        HOST_ROUTES: properties.Schema(
            properties.Schema.LIST,
            _('A list of host route dictionaries for the subnet.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    ROUTE_DESTINATION: properties.Schema(
                        properties.Schema.STRING,
                        _('The destination for static route.'),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('net_cidr')
                        ]
                    ),
                    ROUTE_NEXTHOP: properties.Schema(
                        properties.Schema.STRING,
                        _('The next hop for the destination.'),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('ip_addr')
                        ]
                    ),
                },
            ),
            update_allowed=True
        ),
        IPV6_RA_MODE: properties.Schema(
            properties.Schema.STRING,
            _('IPv6 RA (Router Advertisement) mode.'),
            constraints=[
                constraints.AllowedValues([DHCPV6_STATEFUL, DHCPV6_STATELESS,
                                           SLAAC]),
            ],
            support_status=support.SupportStatus(version='2015.1')
        ),
        IPV6_ADDRESS_MODE: properties.Schema(
            properties.Schema.STRING,
            _('IPv6 address mode.'),
            constraints=[
                constraints.AllowedValues([DHCPV6_STATEFUL, DHCPV6_STATELESS,
                                           SLAAC]),
            ],
            support_status=support.SupportStatus(version='2015.1')
        ),
        SEGMENT: properties.Schema(
            properties.Schema.STRING,
            _('The name/ID of the segment to associate.'),
            constraints=[
                constraints.CustomConstraint('neutron.segment')
            ],
            update_allowed=True,
            support_status=support.SupportStatus(
                version='11.0.0',
                status=support.SUPPORTED,
                message=_('Update allowed since version 11.0.0.'),
                previous_status=support.SupportStatus(
                    version='9.0.0',
                    status=support.SUPPORTED
                )
            )
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('The tags to be added to the subnet.'),
            schema=properties.Schema(properties.Schema.STRING),
            update_allowed=True,
            support_status=support.SupportStatus(version='9.0.0')
        ),
    }

    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _("Friendly name of the subnet."),
            type=attributes.Schema.STRING
        ),
        NETWORK_ID_ATTR: attributes.Schema(
            _("Parent network of the subnet."),
            type=attributes.Schema.STRING
        ),
        TENANT_ID_ATTR: attributes.Schema(
            _("Tenant owning the subnet."),
            type=attributes.Schema.STRING
        ),
        ALLOCATION_POOLS_ATTR: attributes.Schema(
            _("Ip allocation pools and their ranges."),
            type=attributes.Schema.LIST
        ),
        GATEWAY_IP_ATTR: attributes.Schema(
            _("Ip of the subnet's gateway."),
            type=attributes.Schema.STRING
        ),
        HOST_ROUTES_ATTR: attributes.Schema(
            _("Additional routes for this subnet."),
            type=attributes.Schema.LIST
        ),
        IP_VERSION_ATTR: attributes.Schema(
            _("Ip version for the subnet."),
            type=attributes.Schema.STRING
        ),
        CIDR_ATTR: attributes.Schema(
            _("CIDR block notation for this subnet."),
            type=attributes.Schema.STRING
        ),
        DNS_NAMESERVERS_ATTR: attributes.Schema(
            _("List of dns nameservers."),
            type=attributes.Schema.LIST
        ),
        ENABLE_DHCP_ATTR: attributes.Schema(
            _("'true' if DHCP is enabled for this subnet; 'false' otherwise."),
            type=attributes.Schema.STRING
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.NETWORK],
                value_path=[self.NETWORK_ID]),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.NETWORK],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_NETWORK
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.SUBNETPOOL],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SUBNET_POOL
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.SEGMENT],
                client_plugin=self.client_plugin('openstack'),
                finder='find_network_segment'
            )
        ]

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

    def validate(self):
        super(Subnet, self).validate()
        subnetpool = self.properties[self.SUBNETPOOL]
        prefixlen = self.properties[self.PREFIXLEN]
        cidr = self.properties[self.CIDR]
        if subnetpool is not None and cidr:
            raise exception.ResourcePropertyConflict(self.SUBNETPOOL,
                                                     self.CIDR)
        if subnetpool is None and not cidr:
            raise exception.PropertyUnspecifiedError(self.SUBNETPOOL,
                                                     self.CIDR)
        if prefixlen and cidr:
            raise exception.ResourcePropertyConflict(self.PREFIXLEN,
                                                     self.CIDR)
        ra_mode = self.properties[self.IPV6_RA_MODE]
        address_mode = self.properties[self.IPV6_ADDRESS_MODE]

        if (self.properties[self.IP_VERSION] == 4) and (
                ra_mode or address_mode):
            msg = _('ipv6_ra_mode and ipv6_address_mode are not supported '
                    'for ipv4.')
            raise exception.StackValidationFailed(message=msg)
        if ra_mode and address_mode and (ra_mode != address_mode):
            msg = _('When both ipv6_ra_mode and ipv6_address_mode are set, '
                    'they must be equal.')
            raise exception.StackValidationFailed(message=msg)

        gateway_ip = self.properties.get(self.GATEWAY_IP)
        if (gateway_ip and gateway_ip not in ['~', ''] and
                not netutils.is_valid_ip(gateway_ip)):
            msg = (_('Gateway IP address "%(gateway)s" is in '
                     'invalid format.'), gateway_ip)
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        props['network_id'] = props.pop(self.NETWORK)
        if self.SEGMENT in props and props[self.SEGMENT]:
            props['segment_id'] = props.pop(self.SEGMENT)

        tags = props.pop(self.TAGS, [])

        if self.SUBNETPOOL in props and props[self.SUBNETPOOL]:
            props['subnetpool_id'] = props.pop('subnetpool')
        self._null_gateway_ip(props)

        subnet = self.client().create_subnet({'subnet': props})['subnet']
        self.resource_id_set(subnet['id'])

        if tags:
            self.set_tags(tags)

    def handle_delete(self):
        try:
            self.client().delete_subnet(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True

    def _validate_segment_update_supported(self):
        # TODO(hjensas): Validation to ensure the subnet-segmentid-writable
        # extension is available.
        # https://storyboard.openstack.org/#!/story/2002189
        # Current segment id must be None
        if self.properties[self.SEGMENT] is not None:
            msg = _('Updating the subnet segment assciation only allowed '
                    'when the current segment_id is None. The subnet is '
                    'currently associated with segment. In this state update')
            raise exception.ResourceActionNotSupported(action=msg)
        else:
            return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            if (self.ALLOCATION_POOLS in prop_diff and
                    prop_diff[self.ALLOCATION_POOLS] is None):
                prop_diff[self.ALLOCATION_POOLS] = []
            if (self.SEGMENT in prop_diff and prop_diff[self.SEGMENT] and
                    self._validate_segment_update_supported()):
                prop_diff['segment_id'] = prop_diff.pop(self.SEGMENT)

            # If the new value is '', set to None
            self._null_gateway_ip(prop_diff)
            if self.TAGS in prop_diff:
                tags = prop_diff.pop(self.TAGS)
                self.set_tags(tags)
            self.client().update_subnet(
                self.resource_id, {'subnet': prop_diff})


def resource_mapping():
    return {
        'OS::Neutron::Subnet': Subnet,
    }
