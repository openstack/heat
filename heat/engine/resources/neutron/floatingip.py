
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
from heat.engine.resources.neutron import router
from heat.openstack.common import log as logging

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException

logger = logging.getLogger(__name__)


class FloatingIP(neutron.NeutronResource):
    PROPERTIES = (
        FLOATING_NETWORK_ID, VALUE_SPECS, PORT_ID, FIXED_IP_ADDRESS,
    ) = (
        'floating_network_id', 'value_specs', 'port_id', 'fixed_ip_address',
    )

    properties_schema = {
        FLOATING_NETWORK_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of network to allocate floating IP from.'),
            required=True
        ),
        VALUE_SPECS: properties.Schema(
            properties.Schema.MAP,
            _('Extra parameters to include in the "floatingip" object in the '
              'creation request. Parameters are often specific to installed '
              'hardware or extensions.'),
            default={}
        ),
        PORT_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of an existing port with at least one IP address to '
              'associate with this floating IP.')
        ),
        FIXED_IP_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('IP address to use if the port has multiple addresses.')
        ),
    }

    attributes_schema = {
        'router_id': _('ID of the router used as gateway, set when associated '
                       'with a port.'),
        'tenant_id': _('The tenant owning this floating IP.'),
        'floating_network_id': _('ID of the network in which this IP is '
                                 'allocated.'),
        'fixed_ip_address': _('IP address of the associated port, if '
                              'specified.'),
        'floating_ip_address': _('The allocated address of this IP.'),
        'port_id': _('ID of the port associated with this IP.'),
        'show': _('All attributes.')
    }

    def add_dependencies(self, deps):
        super(FloatingIP, self).add_dependencies(deps)
        # depend on any RouterGateway in this template with the same
        # network_id as this floating_network_id
        for resource in self.stack.itervalues():
            if (resource.has_interface('OS::Neutron::RouterGateway') and
                resource.properties.get(router.RouterGateway.NETWORK_ID) ==
                    self.properties.get(self.FLOATING_NETWORK_ID)):
                        deps += (self, resource)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        fip = self.neutron().create_floatingip({
            'floatingip': props})['floatingip']
        self.resource_id_set(fip['id'])

    def _show_resource(self):
        return self.neutron().show_floatingip(self.resource_id)['floatingip']

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_floatingip(self.resource_id)
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)


class FloatingIPAssociation(neutron.NeutronResource):
    PROPERTIES = (
        FLOATINGIP_ID, PORT_ID, FIXED_IP_ADDRESS,
    ) = (
        'floatingip_id', 'port_id', 'fixed_ip_address',
    )

    properties_schema = {
        FLOATINGIP_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the floating IP to associate.'),
            required=True
        ),
        PORT_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of an existing port with at least one IP address to '
              'associate with this floating IP.')
        ),
        FIXED_IP_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('IP address to use if the port has multiple addresses.')
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(self.properties, self.name)

        floatingip_id = props.pop(self.FLOATINGIP_ID)

        self.neutron().update_floatingip(floatingip_id, {
            'floatingip': props})['floatingip']
        self.resource_id_set('%s:%s' % (floatingip_id, props[self.PORT_ID]))

    def handle_delete(self):
        if not self.resource_id:
            return
        client = self.neutron()
        (floatingip_id, port_id) = self.resource_id.split(':')
        try:
            client.update_floatingip(
                floatingip_id,
                {'floatingip': {'port_id': None}})
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::FloatingIP': FloatingIP,
        'OS::Neutron::FloatingIPAssociation': FloatingIPAssociation,
    }
