# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from heat.openstack.common import log as logging
from heat.engine.resources.neutron import neutron

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException

logger = logging.getLogger(__name__)


class FloatingIP(neutron.NeutronResource):
    properties_schema = {
        'floating_network_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('ID of network to allocate floating IP from.')
        },
        'value_specs': {
            'Type': 'Map',
            'Default': {},
            'Description': _('Extra parameters to include in the '
                             '"floatingip" object in the creation request. '
                             'Parameters are often specific to installed '
                             'hardware or extensions.')
        },
        'port_id': {
            'Type': 'String',
            'Description': _('ID of an existing port with at least one IP '
                             'address to associate with this floating IP.')
        },
        'fixed_ip_address': {
            'Type': 'String',
            'Description': _('IP address to use if the port has '
                             'multiple addresses.')
        }}

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
                resource.properties.get('network_id') ==
                    self.properties.get('floating_network_id')):
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
            if ex.status_code != 404:
                raise ex


class FloatingIPAssociation(neutron.NeutronResource):
    properties_schema = {
        'floatingip_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('ID of the floating IP to associate.')
        },
        'port_id': {
            'Type': 'String',
            'Description': _('ID of an existing port with at least one IP '
                             'address to associate with this floating IP.')
        },
        'fixed_ip_address': {
            'Type': 'String',
            'Description': _('IP address to use if the port has '
                             'multiple addresses.')
        }}

    def handle_create(self):
        props = self.prepare_properties(self.properties, self.name)

        floatingip_id = props.pop('floatingip_id')

        self.neutron().update_floatingip(floatingip_id, {
            'floatingip': props})['floatingip']
        self.resource_id_set('%s:%s' % (floatingip_id, props['port_id']))

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
            if ex.status_code != 404:
                raise ex


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::FloatingIP': FloatingIP,
        'OS::Neutron::FloatingIPAssociation': FloatingIPAssociation,
    }
