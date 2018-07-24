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

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine.resources.openstack.neutron import subnet
from heat.engine import support
from heat.engine import translation


class Router(neutron.NeutronResource):
    """A resource that implements Neutron router.

    Router is a physical or virtual network device that passes network traffic
    between different networks.
    """

    required_service_extension = 'router'

    entity = 'router'

    PROPERTIES = (
        NAME, EXTERNAL_GATEWAY, VALUE_SPECS, ADMIN_STATE_UP,
        L3_AGENT_ID, L3_AGENT_IDS, DISTRIBUTED, HA, TAGS,
    ) = (
        'name', 'external_gateway_info', 'value_specs', 'admin_state_up',
        'l3_agent_id', 'l3_agent_ids', 'distributed', 'ha', 'tags',
    )

    _EXTERNAL_GATEWAY_KEYS = (
        EXTERNAL_GATEWAY_NETWORK, EXTERNAL_GATEWAY_ENABLE_SNAT,
        EXTERNAL_GATEWAY_FIXED_IPS,
    ) = (
        'network', 'enable_snat', 'external_fixed_ips',
    )

    _EXTERNAL_GATEWAY_FIXED_IPS_KEYS = (
        IP_ADDRESS, SUBNET
    ) = (
        'ip_address', 'subnet'
    )

    ATTRIBUTES = (
        STATUS, EXTERNAL_GATEWAY_INFO_ATTR, NAME_ATTR, ADMIN_STATE_UP_ATTR,
        TENANT_ID,
    ) = (
        'status', 'external_gateway_info', 'name', 'admin_state_up',
        'tenant_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of the router.'),
            update_allowed=True
        ),
        EXTERNAL_GATEWAY: properties.Schema(
            properties.Schema.MAP,
            _('External network gateway configuration for a router.'),
            schema={
                EXTERNAL_GATEWAY_NETWORK: properties.Schema(
                    properties.Schema.STRING,
                    _('ID or name of the external network for the gateway.'),
                    required=True,
                    update_allowed=True
                ),
                EXTERNAL_GATEWAY_ENABLE_SNAT: properties.Schema(
                    properties.Schema.BOOLEAN,
                    _('Enables Source NAT on the router gateway. NOTE: The '
                      'default policy setting in Neutron restricts usage of '
                      'this property to administrative users only.'),
                    update_allowed=True
                ),
                EXTERNAL_GATEWAY_FIXED_IPS: properties.Schema(
                    properties.Schema.LIST,
                    _('External fixed IP addresses for the gateway.'),
                    schema=properties.Schema(
                        properties.Schema.MAP,
                        schema={
                            IP_ADDRESS: properties.Schema(
                                properties.Schema.STRING,
                                _('External fixed IP address.'),
                                constraints=[
                                    constraints.CustomConstraint('ip_addr'),
                                ]
                            ),
                            SUBNET: properties.Schema(
                                properties.Schema.STRING,
                                _('Subnet of external fixed IP address.'),
                                constraints=[
                                    constraints.CustomConstraint(
                                        'neutron.subnet')
                                ]
                            ),
                        }
                    ),
                    update_allowed=True,
                    support_status=support.SupportStatus(version='6.0.0')
                ),
            },
            update_allowed=True
        ),
        VALUE_SPECS: properties.Schema(
            properties.Schema.MAP,
            _('Extra parameters to include in the creation request.'),
            default={},
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of the router.'),
            default=True,
            update_allowed=True
        ),
        L3_AGENT_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the L3 agent. NOTE: The default policy setting in '
              'Neutron restricts usage of this property to administrative '
              'users only.'),
            update_allowed=True,
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='6.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='2015.1',
                    message=_('Use property %s.') % L3_AGENT_IDS,
                    previous_status=support.SupportStatus(version='2014.1')
                )
            ),
        ),
        L3_AGENT_IDS: properties.Schema(
            properties.Schema.LIST,
            _('ID list of the L3 agent. User can specify multi-agents '
              'for highly available router. NOTE: The default policy '
              'setting in Neutron restricts usage of this property to '
              'administrative users only.'),
            schema=properties.Schema(
                properties.Schema.STRING,
            ),
            update_allowed=True,
            support_status=support.SupportStatus(version='2015.1')
        ),
        DISTRIBUTED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Indicates whether or not to create a distributed router. '
              'NOTE: The default policy setting in Neutron restricts usage '
              'of this property to administrative users only. This property '
              'can not be used in conjunction with the L3 agent ID.'),
            support_status=support.SupportStatus(version='2015.1')
        ),
        HA: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Indicates whether or not to create a highly available router. '
              'NOTE: The default policy setting in Neutron restricts usage '
              'of this property to administrative users only. And now neutron '
              'do not support distributed and ha at the same time.'),
            support_status=support.SupportStatus(version='2015.1')
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('The tags to be added to the router.'),
            schema=properties.Schema(properties.Schema.STRING),
            update_allowed=True,
            support_status=support.SupportStatus(version='9.0.0')
        ),
    }

    attributes_schema = {
        STATUS: attributes.Schema(
            _("The status of the router."),
            type=attributes.Schema.STRING
        ),
        EXTERNAL_GATEWAY_INFO_ATTR: attributes.Schema(
            _("Gateway network for the router."),
            type=attributes.Schema.MAP
        ),
        NAME_ATTR: attributes.Schema(
            _("Friendly name of the router."),
            type=attributes.Schema.STRING
        ),
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _("Administrative state of the router."),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _("Tenant owning the router."),
            type=attributes.Schema.STRING
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        rules = [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.EXTERNAL_GATEWAY, self.EXTERNAL_GATEWAY_NETWORK],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_NETWORK
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.EXTERNAL_GATEWAY, self.EXTERNAL_GATEWAY_FIXED_IPS,
                 self.SUBNET],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SUBNET
            ),
        ]
        if props.get(self.L3_AGENT_ID):
            rules.extend([
                translation.TranslationRule(
                    props,
                    translation.TranslationRule.ADD,
                    [self.L3_AGENT_IDS],
                    [props.get(self.L3_AGENT_ID)]),
                translation.TranslationRule(
                    props,
                    translation.TranslationRule.DELETE,
                    [self.L3_AGENT_ID]
                )])
        return rules

    def validate(self):
        super(Router, self).validate()
        is_distributed = self.properties[self.DISTRIBUTED]
        l3_agent_id = self.properties[self.L3_AGENT_ID]
        l3_agent_ids = self.properties[self.L3_AGENT_IDS]
        is_ha = self.properties[self.HA]
        if l3_agent_id and l3_agent_ids:
            raise exception.ResourcePropertyConflict(self.L3_AGENT_ID,
                                                     self.L3_AGENT_IDS)
        # do not specific l3 agent when creating a distributed router
        if is_distributed and (l3_agent_id or l3_agent_ids):
            raise exception.ResourcePropertyConflict(
                self.DISTRIBUTED,
                "/".join([self.L3_AGENT_ID, self.L3_AGENT_IDS]))
        if is_ha and is_distributed:
            raise exception.ResourcePropertyConflict(self.DISTRIBUTED,
                                                     self.HA)
        if not is_ha and l3_agent_ids and len(l3_agent_ids) > 1:
            msg = _('Non HA routers can only have one L3 agent.')
            raise exception.StackValidationFailed(message=msg)

    def add_dependencies(self, deps):
        super(Router, self).add_dependencies(deps)
        external_gw = self.properties[self.EXTERNAL_GATEWAY]
        if external_gw:
            external_gw_net = external_gw.get(self.EXTERNAL_GATEWAY_NETWORK)
            for res in six.itervalues(self.stack):
                if res.has_interface('OS::Neutron::Subnet'):
                    try:
                        subnet_net = res.properties.get(subnet.Subnet.NETWORK)
                    except (ValueError, TypeError):
                        # Properties errors will be caught later in validation,
                        # where we can report them in their proper context.
                        continue
                    if subnet_net == external_gw_net:
                        deps += (self, res)

    def _resolve_gateway(self, props):
        gateway = props.get(self.EXTERNAL_GATEWAY)
        if gateway:
            gateway['network_id'] = gateway.pop(self.EXTERNAL_GATEWAY_NETWORK)
            if gateway[self.EXTERNAL_GATEWAY_ENABLE_SNAT] is None:
                del gateway[self.EXTERNAL_GATEWAY_ENABLE_SNAT]
            if gateway[self.EXTERNAL_GATEWAY_FIXED_IPS] is None:
                del gateway[self.EXTERNAL_GATEWAY_FIXED_IPS]
            else:
                self._resolve_subnet(gateway)
        return props

    def _get_l3_agent_list(self, props):
        l3_agent_id = props.pop(self.L3_AGENT_ID, None)
        l3_agent_ids = props.pop(self.L3_AGENT_IDS, None)
        if not l3_agent_ids and l3_agent_id:
            l3_agent_ids = [l3_agent_id]

        return l3_agent_ids

    def _resolve_subnet(self, gateway):
        external_gw_fixed_ips = gateway[self.EXTERNAL_GATEWAY_FIXED_IPS]
        for fixed_ip in external_gw_fixed_ips:
            for key, value in fixed_ip.copy().items():
                if value is None:
                    fixed_ip.pop(key)
            if self.SUBNET in fixed_ip:
                fixed_ip['subnet_id'] = fixed_ip.pop(self.SUBNET)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        self._resolve_gateway(props)
        l3_agent_ids = self._get_l3_agent_list(props)
        tags = props.pop(self.TAGS, [])

        router = self.client().create_router({'router': props})['router']
        self.resource_id_set(router['id'])

        if l3_agent_ids:
            self._replace_agent(l3_agent_ids)
        if tags:
            self.set_tags(tags)

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        try:
            self.client().delete_router(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if self.EXTERNAL_GATEWAY in prop_diff:
            self._resolve_gateway(prop_diff)

        if self.L3_AGENT_IDS in prop_diff or self.L3_AGENT_ID in prop_diff:
            l3_agent_ids = self._get_l3_agent_list(prop_diff)
            self._replace_agent(l3_agent_ids)

        if self.TAGS in prop_diff:
            tags = prop_diff.pop(self.TAGS)
            self.set_tags(tags)

        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client().update_router(
                self.resource_id, {'router': prop_diff})

    def _replace_agent(self, l3_agent_ids=None):
        ret = self.client().list_l3_agent_hosting_routers(
            self.resource_id)
        for agent in ret['agents']:
            self.client().remove_router_from_l3_agent(
                agent['id'], self.resource_id)
        if l3_agent_ids:
            for l3_agent_id in l3_agent_ids:
                self.client().add_router_to_l3_agent(
                    l3_agent_id, {'router_id': self.resource_id})

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(Router, self).parse_live_resource_data(
            resource_properties, resource_data)

        try:
            ret = self.client().list_l3_agent_hosting_routers(self.resource_id)
            if ret:
                result[self.L3_AGENT_IDS] = list(
                    agent['id'] for agent in ret['agents'])
        except self.client_plugin().exceptions.Forbidden:
            # Just pass if forbidden
            pass

        gateway = resource_data.get(self.EXTERNAL_GATEWAY)
        if gateway is not None:
            result[self.EXTERNAL_GATEWAY] = {
                self.EXTERNAL_GATEWAY_NETWORK: gateway.get('network_id'),
                self.EXTERNAL_GATEWAY_ENABLE_SNAT: gateway.get('enable_snat')
            }
        return result


class RouterInterface(neutron.NeutronResource):
    """A resource for managing Neutron router interfaces.

    Router interfaces associate routers with existing subnets or ports.
    """

    required_service_extension = 'router'

    PROPERTIES = (
        ROUTER, ROUTER_ID, SUBNET_ID, SUBNET, PORT_ID, PORT
    ) = (
        'router', 'router_id', 'subnet_id', 'subnet', 'port_id', 'port'
    )

    properties_schema = {
        ROUTER: properties.Schema(
            properties.Schema.STRING,
            _('The router.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.router')
            ],
        ),
        ROUTER_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the router.'),
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='6.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    message=_('Use property %s.') % ROUTER,
                    version='2015.1',
                    previous_status=support.SupportStatus(version='2013.1')
                )
            ),
            constraints=[
                constraints.CustomConstraint('neutron.router')
            ],
        ),
        SUBNET_ID: properties.Schema(
            properties.Schema.STRING,
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                message=_('Use property %s.') % SUBNET,
                version='5.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='2014.2'
                )
            ),
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ]
        ),
        SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('The subnet, either subnet or port should be '
              'specified.'),
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ]
        ),
        PORT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The port id, either subnet or port_id should be specified.'),
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='6.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    message=_('Use property %s.') % PORT,
                    version='2015.1',
                    previous_status=support.SupportStatus(version='2014.1')
                )
            ),
            constraints=[
                constraints.CustomConstraint('neutron.port')
            ]
        ),
        PORT: properties.Schema(
            properties.Schema.STRING,
            _('The port, either subnet or port should be specified.'),
            support_status=support.SupportStatus(version='2015.1'),
            constraints=[
                constraints.CustomConstraint('neutron.port')
            ]
        )
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.PORT],
                value_path=[self.PORT_ID]
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.ROUTER],
                value_path=[self.ROUTER_ID]
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.SUBNET],
                value_path=[self.SUBNET_ID]
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.PORT],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_PORT
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.ROUTER],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_ROUTER
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.SUBNET],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SUBNET
            )


        ]

    def validate(self):
        """Validate any of the provided params."""
        super(RouterInterface, self).validate()

        prop_subnet_exists = self.properties.get(self.SUBNET) is not None

        prop_port_exists = self.properties.get(self.PORT) is not None

        if prop_subnet_exists and prop_port_exists:
            raise exception.ResourcePropertyConflict(self.SUBNET,
                                                     self.PORT)

        if not prop_subnet_exists and not prop_port_exists:
            raise exception.PropertyUnspecifiedError(self.SUBNET,
                                                     self.PORT)

    def handle_create(self):
        router_id = dict(self.properties).get(self.ROUTER)
        key = 'subnet_id'
        value = dict(self.properties).get(self.SUBNET)
        if not value:
            key = 'port_id'
            value = dict(self.properties).get(self.PORT)
        self.client().add_interface_router(
            router_id,
            {key: value})
        self.resource_id_set('%s:%s=%s' % (router_id, key, value))

    def handle_delete(self):
        if not self.resource_id:
            return
        tokens = self.resource_id.replace('=', ':').split(':')
        if len(tokens) == 2:    # compatible with old data
            tokens.insert(1, 'subnet_id')
        (router_id, key, value) = tokens
        with self.client_plugin().ignore_not_found:
            self.client().remove_interface_router(
                router_id,
                {key: value})


class RouterGateway(neutron.NeutronResource):

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        message=_('Use the `external_gateway_info` property in '
                  'the router resource to set up the gateway.'),
        version='5.0.0',
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            version='2014.1'
        )
    )

    PROPERTIES = (
        ROUTER_ID, NETWORK_ID, NETWORK,
    ) = (
        'router_id', 'network_id', 'network'
    )

    properties_schema = {
        ROUTER_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the router.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.router')
            ]
        ),
        NETWORK_ID: properties.Schema(
            properties.Schema.STRING,
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                message=_('Use property %s.') % NETWORK,
                version='9.0.0',
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
            _('external network for the gateway.'),
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
        ),

    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.NETWORK],
                value_path=[self.NETWORK_ID]
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.NETWORK],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_NETWORK
            )

        ]

    def add_dependencies(self, deps):
        super(RouterGateway, self).add_dependencies(deps)
        for resource in six.itervalues(self.stack):
            # depend on any RouterInterface in this template with the same
            # router_id as this router_id
            if resource.has_interface('OS::Neutron::RouterInterface'):
                try:
                    dep_router_id = resource.properties[RouterInterface.ROUTER]
                    router_id = self.properties[self.ROUTER_ID]
                except (ValueError, TypeError):
                    # Properties errors will be caught later in validation,
                    # where we can report them in their proper context.
                    continue
                if dep_router_id == router_id:
                    deps += (self, resource)
            # depend on any subnet in this template with the same network_id
            # as this network_id, as the gateway implicitly creates a port
            # on that subnet
            if resource.has_interface('OS::Neutron::Subnet'):
                try:
                    dep_network = resource.properties[subnet.Subnet.NETWORK]
                    network = self.properties[self.NETWORK]
                except (ValueError, TypeError):
                    # Properties errors will be caught later in validation,
                    # where we can report them in their proper context.
                    continue
                if dep_network == network:
                    deps += (self, resource)

    def handle_create(self):
        router_id = self.properties[self.ROUTER_ID]
        network_id = dict(self.properties).get(self.NETWORK)
        self.client().add_gateway_router(
            router_id,
            {'network_id': network_id})
        self.resource_id_set('%s:%s' % (router_id, network_id))

    def handle_delete(self):
        if not self.resource_id:
            return

        (router_id, network_id) = self.resource_id.split(':')
        with self.client_plugin().ignore_not_found:
            self.client().remove_gateway_router(router_id)


def resource_mapping():
    return {
        'OS::Neutron::Router': Router,
        'OS::Neutron::RouterInterface': RouterInterface,
        'OS::Neutron::RouterGateway': RouterGateway,
    }
