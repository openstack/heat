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

from heat.openstack.common import log as logging
from heat.engine.resources.quantum import quantum

logger = logging.getLogger(__name__)


class Port(quantum.QuantumResource):

    fixed_ip_schema = {'subnet_id': {'Type': 'String',
                                  'Required': True},
                        'ip_address': {'Type': 'String',
                               'Required': True}}

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
    }

    def __init__(self, name, json_snippet, stack):
        super(Port, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        props = self.prepare_properties(self.properties, self.name)
        port = self.quantum().create_port({'port': props})['port']
        self.resource_id_set(port['id'])

    def handle_delete(self):
        client = self.quantum()
        client.delete_port(self.resource_id)

    def FnGetAtt(self, key):
        attributes = self.quantum().show_port(
            self.resource_id)['port']
        return self.handle_get_attributes(self.name, key, attributes)


def resource_mapping():
    return {
        'OS::Quantum::Port': Port,
    }
