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
from heat.engine import scheduler

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException

logger = logging.getLogger(__name__)


class Port(neutron.NeutronResource):

    fixed_ip_schema = {'subnet_id': {'Type': 'String',
                                     'Required': True},
                       'ip_address': {'Type': 'String'}}

    properties_schema = {'network_id': {'Type': 'String',
                                        'Required': True},
                         'name': {'Type': 'String'},
                         'value_specs': {'Type': 'Map',
                                         'Default': {}},
                         'admin_state_up': {'Default': True,
                                            'Type': 'Boolean'},
                         'fixed_ips': {'Type': 'List',
                                       'Schema': {'Type': 'Map',
                                                  'Schema': fixed_ip_schema}},
                         'mac_address': {'Type': 'String'},
                         'device_id': {'Type': 'String'},
                         'security_groups': {'Type': 'List'}}
    attributes_schema = {
        "admin_state_up": "the administrative state of this port",
        "device_id": "unique identifier for the device",
        "device_owner": "name of the network owning the port",
        "fixed_ips": "fixed ip addresses",
        "id": "the unique identifier for the port",
        "mac_address": "mac address of the port",
        "name": "friendly name of the port",
        "network_id": "unique identifier for the network owning the port",
        "security_groups": "a list of security groups for the port",
        "status": "the status of the port",
        "tenant_id": "tenant owning the port"
    }

    def add_dependencies(self, deps):
        super(Port, self).add_dependencies(deps)
        # Depend on any Subnet in this template with the same
        # network_id as this network_id.
        # It is not known which subnet a port might be assigned
        # to so all subnets in a network should be created before
        # the ports in that network.
        for resource in self.stack.resources.itervalues():
            if (resource.has_interface('OS::Neutron::Subnet') and
                resource.properties.get('network_id') ==
                    self.properties.get('network_id')):
                        deps += (self, resource)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        port = self.neutron().create_port({'port': props})['port']
        self.resource_id_set(port['id'])

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
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::Port': Port,
    }
