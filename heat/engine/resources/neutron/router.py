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
from heat.engine import attributes
from heat.engine import properties
from heat.engine.resources.neutron import neutron
from heat.engine.resources.neutron import subnet
from heat.engine import support


class Router(neutron.NeutronResource):

    PROPERTIES = (
        NAME, EXTERNAL_GATEWAY, VALUE_SPECS, ADMIN_STATE_UP,
        L3_AGENT_ID,
    ) = (
        'name', 'external_gateway_info', 'value_specs', 'admin_state_up',
        'l3_agent_id',
    )

    _EXTERNAL_GATEWAY_KEYS = (
        EXTERNAL_GATEWAY_NETWORK, EXTERNAL_GATEWAY_ENABLE_SNAT,
    ) = (
        'network', 'enable_snat',
    )

    ATTRIBUTES = (
        STATUS, EXTERNAL_GATEWAY_INFO_ATTR, NAME_ATTR, ADMIN_STATE_UP_ATTR,
        TENANT_ID, SHOW,
    ) = (
        'status', 'external_gateway_info', 'name', 'admin_state_up',
        'tenant_id', 'show',
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
            update_allowed=True
        ),
    }

    attributes_schema = {
        STATUS: attributes.Schema(
            _("The status of the router.")
        ),
        EXTERNAL_GATEWAY_INFO_ATTR: attributes.Schema(
            _("Gateway network for the router.")
        ),
        NAME_ATTR: attributes.Schema(
            _("Friendly name of the router.")
        ),
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _("Administrative state of the router.")
        ),
        TENANT_ID: attributes.Schema(
            _("Tenant owning the router.")
        ),
        SHOW: attributes.Schema(
            _("All attributes.")
        ),
    }

    def add_dependencies(self, deps):
        super(Router, self).add_dependencies(deps)
        external_gw = self.properties.get(self.EXTERNAL_GATEWAY)
        if external_gw:
            external_gw_net = external_gw.get(self.EXTERNAL_GATEWAY_NETWORK)
            for res in self.stack.itervalues():
                if res.has_interface('OS::Neutron::Subnet'):
                    subnet_net = res.properties.get(
                        subnet.Subnet.NETWORK) or res.properties.get(
                            subnet.Subnet.NETWORK_ID)
                    if subnet_net == external_gw_net:
                        deps += (self, res)

    def prepare_properties(self, properties, name):
        props = super(Router, self).prepare_properties(properties, name)
        gateway = props.get(self.EXTERNAL_GATEWAY)
        if gateway:
            self.client_plugin().resolve_network(
                gateway, self.EXTERNAL_GATEWAY_NETWORK, 'network_id')
            if gateway[self.EXTERNAL_GATEWAY_ENABLE_SNAT] is None:
                del gateway[self.EXTERNAL_GATEWAY_ENABLE_SNAT]
        return props

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        l3_agent_id = props.pop(self.L3_AGENT_ID, None)

        router = self.neutron().create_router({'router': props})['router']
        self.resource_id_set(router['id'])

        if l3_agent_id:
            self._replace_agent(l3_agent_id)

    def _show_resource(self):
        return self.neutron().show_router(
            self.resource_id)['router']

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_router(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return self._delete_task()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)

        l3_agent_id = props.pop(self.L3_AGENT_ID, None)

        if self.L3_AGENT_ID in prop_diff:
            self._replace_agent(l3_agent_id)
            del prop_diff[self.L3_AGENT_ID]

        if len(prop_diff) > 0:
            self.neutron().update_router(
                self.resource_id, {'router': props})

    def _replace_agent(self, l3_agent_id=None):
        ret = self.neutron().list_l3_agent_hosting_routers(
            self.resource_id)
        for agent in ret['agents']:
            self.neutron().remove_router_from_l3_agent(
                agent['id'], self.resource_id)
        if l3_agent_id:
            self.neutron().add_router_to_l3_agent(
                l3_agent_id, {'router_id': self.resource_id})


class RouterInterface(neutron.NeutronResource):
    PROPERTIES = (
        ROUTER_ID, SUBNET_ID, SUBNET, PORT_ID,
    ) = (
        'router_id', 'subnet_id', 'subnet', 'port_id',
    )

    properties_schema = {
        ROUTER_ID: properties.Schema(
            properties.Schema.STRING,
            _('The router id.'),
            required=True
        ),
        SUBNET_ID: properties.Schema(
            properties.Schema.STRING,
            support_status=support.SupportStatus(
                support.DEPRECATED,
                _('Use property %s.') % SUBNET)
        ),
        SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('The subnet, either subnet or port_id should be '
              'specified.')
        ),
        PORT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The port id, either subnet or port_id should be specified.')
        ),
    }

    @staticmethod
    def _validate_depr_subnet_keys(properties, subnet_key, depr_subnet_key):
        subnet_value = properties.get(subnet_key)
        subnet_id_value = properties.get(depr_subnet_key)
        if subnet_value and subnet_id_value:
            raise exception.ResourcePropertyConflict(subnet_key,
                                                     subnet_key)
        if not subnet_value and not subnet_id_value:
            return False
        return True

    def validate(self):
        '''
        Validate any of the provided params
        '''
        super(RouterInterface, self).validate()

        prop_subnet_exists = self._validate_depr_subnet_keys(
            self.properties, self.SUBNET, self.SUBNET_ID)

        port_id = self.properties.get(self.PORT_ID)
        if prop_subnet_exists and port_id:
            raise exception.ResourcePropertyConflict(self.SUBNET,
                                                     self.PORT_ID)
        if not prop_subnet_exists and not port_id:
            msg = 'Either subnet or port_id must be specified.'
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        router_id = self.properties.get(self.ROUTER_ID)
        key = 'subnet_id'
        value = self.client_plugin().resolve_subnet(
            dict(self.properties), self.SUBNET, key)
        if not value:
            key = self.PORT_ID
            value = self.properties.get(key)
        self.neutron().add_interface_router(
            router_id,
            {key: value})
        self.resource_id_set('%s:%s=%s' % (router_id, key, value))

    def handle_delete(self):
        if not self.resource_id:
            return
        client = self.neutron()
        tokens = self.resource_id.replace('=', ':').split(':')
        if len(tokens) == 2:    # compatible with old data
            tokens.insert(1, 'subnet_id')
        (router_id, key, value) = tokens
        try:
            client.remove_interface_router(
                router_id,
                {key: value})
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)


class RouterGateway(neutron.NeutronResource):

    support_status = support.SupportStatus(
        support.DEPRECATED,
        _('RouterGateway resource is deprecated and should not be used. '
          'Instead use the `external_gateway_info` property in the router '
          'resource to set up the gateway.')
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
            required=True
        ),
        NETWORK_ID: properties.Schema(
            properties.Schema.STRING,
            support_status=support.SupportStatus(
                support.DEPRECATED,
                _('Use property %s.') % NETWORK),
            required=False
        ),
        NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('external network for the gateway.'),
            required=False
        ),

    }

    def validate(self):
        super(RouterGateway, self).validate()
        self._validate_depr_property_required(
            self.properties, self.NETWORK, self.NETWORK_ID)

    def add_dependencies(self, deps):
        super(RouterGateway, self).add_dependencies(deps)
        for resource in self.stack.itervalues():
            # depend on any RouterInterface in this template with the same
            # router_id as this router_id
            if resource.has_interface('OS::Neutron::RouterInterface'):
                dep_router_id = resource.properties.get(
                    RouterInterface.ROUTER_ID)
                router_id = self.properties.get(self.ROUTER_ID)
                if dep_router_id == router_id:
                    deps += (self, resource)
            # depend on any subnet in this template with the same network_id
            # as this network_id, as the gateway implicitly creates a port
            # on that subnet
            if resource.has_interface('OS::Neutron::Subnet'):
                dep_network = resource.properties.get(
                    subnet.Subnet.NETWORK) or resource.properties.get(
                        subnet.Subnet.NETWORK_ID)
                network = self.properties.get(
                    self.NETWORK) or self.properties.get(self.NETWORK_ID)
                if dep_network == network:
                    deps += (self, resource)

    def handle_create(self):
        router_id = self.properties.get(self.ROUTER_ID)
        network_id = self.client_plugin().resolve_network(
            dict(self.properties), self.NETWORK, 'network_id')
        self.neutron().add_gateway_router(
            router_id,
            {'network_id': network_id})
        self.resource_id_set('%s:%s' % (router_id, network_id))

    def handle_delete(self):
        if not self.resource_id:
            return
        client = self.neutron()
        (router_id, network_id) = self.resource_id.split(':')
        try:
            client.remove_gateway_router(router_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)


def resource_mapping():
    return {
        'OS::Neutron::Router': Router,
        'OS::Neutron::RouterInterface': RouterInterface,
        'OS::Neutron::RouterGateway': RouterGateway,
    }
