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


class Net(quantum.QuantumResource):
    properties_schema = {'name': {'Type': 'String'},
                         'value_specs': {'Type': 'Map',
                                         'Default': {}},
                         'admin_state_up': {'Default': True,
                                            'Type': 'Boolean'}}
    attributes_schema = {
        "id": "the unique identifier for this network",
        "status": "the status of the network",
        "name": "the name of the network",
        "subnets": "subnets of this network",
        "admin_state_up": "the administrative status of the network",
        "tenant_id": "the tenant owning this network"
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        net = self.quantum().create_network({'network': props})['network']
        self.resource_id_set(net['id'])

    def _show_resource(self):
        return self.quantum().show_network(
            self.resource_id)['network']

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        client = self.quantum()
        try:
            client.delete_network(self.resource_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'OS::Quantum::Net': Net,
    }
