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


class Subnet(quantum.QuantumResource):

    allocation_schema = {'start': {'Type': 'String',
                                   'Required': True},
                         'end': {'Type': 'String',
                                 'Required': True}}

    properties_schema = {'network_id': {'Type': 'String',
                                        'Required': True},
                         'cidr': {'Type': 'String',
                                  'Required': True},
                         'value_specs': {'Type': 'Map',
                                         'Default': {}},
                         'name': {'Type': 'String'},
                         'ip_version': {'Type': 'Integer',
                                        'AllowedValues': [4, 6],
                                        'Default': 4},
                         'dns_nameservers': {'Type': 'List'},
                         'gateway_ip': {'Type': 'String'},
                         'allocation_pools': {'Type': 'List',
                                              'Schema': {
                                              'Type': 'Map',
                                              'Schema': allocation_schema
                                              }}}

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        subnet = self.quantum().create_subnet({'subnet': props})['subnet']
        self.resource_id_set(subnet['id'])

    def handle_delete(self):
        client = self.quantum()
        try:
            client.delete_subnet(self.resource_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

    def FnGetAtt(self, key):
        try:
            attributes = self.quantum().show_subnet(
                self.resource_id)['subnet']
        except QuantumClientException as ex:
            logger.warn("failed to fetch resource attributes: %s" % str(ex))
            return None
        return self.handle_get_attributes(self.name, key, attributes)


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'OS::Quantum::Subnet': Subnet,
    }
