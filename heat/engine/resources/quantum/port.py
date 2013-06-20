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
from heat.engine.resources.quantum import quantum

if clients.quantumclient is not None:
    from quantumclient.common.exceptions import QuantumClientException

logger = logging.getLogger(__name__)


class Port(quantum.QuantumResource):

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

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        port = self.quantum().create_port({'port': props})['port']
        self.resource_id_set(port['id'])

    def _show_resource(self):
        return self.quantum().show_port(
            self.resource_id)['port']

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        client = self.quantum()
        try:
            client.delete_port(self.resource_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'OS::Quantum::Port': Port,
    }
