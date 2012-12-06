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

from heat.common import exception

from heat.openstack.common import log as logging
from heat.engine.resources.quantum import quantum

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
                        'admin_state_up': {'Default': True,
                                          'Type': 'Boolean'},
                        'ip_version': {'Type': 'Integer',
                                      'AllowedValues': [4, 6],
                                      'Default': 4},
                        'gateway_ip': {'Type': 'String'},
                        'allocation_pools': {'Type': 'List',
                                             'Schema': {
                                                 'Type': 'Map',
                                                 'Schema': allocation_schema
                                             }}
    }

    def __init__(self, name, json_snippet, stack):
        super(Subnet, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        props = self.prepare_properties(self.properties, self.name)
        subnet = self.quantum().create_subnet({'subnet': props})['subnet']
        self.resource_id_set(subnet['id'])

    def handle_delete(self):
        client = self.quantum()
        client.delete_subnet(self.resource_id)

    def FnGetAtt(self, key):
        attributes = self.quantum().show_subnet(
            self.resource_id)['subnet']
        return self.handle_get_attributes(self.name, key, attributes)


def resource_mapping():
    return {
        'OS::Quantum::Subnet': Subnet,
    }
