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

logger = logging.getLogger('heat.engine.quantum')


class Net(quantum.QuantumResource):
    properties_schema = {'name': {'Type': 'String'},
                        'value_specs': {'Type': 'Map',
                                       'Default': {}},
                        'admin_state_up': {'Default': True,
                                          'Type': 'Boolean'},
    }

    def __init__(self, name, json_snippet, stack):
        super(Net, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        props = self.prepare_properties(self.properties, self.name)
        net = self.quantum().create_network({'network': props})['network']
        self.resource_id_set(net['id'])

    def handle_delete(self):
        client = self.quantum()
        try:
            client.delete_network(self.resource_id)
        except:
            pass

    def FnGetAtt(self, key):
        attributes = self.quantum().show_network(
            self.resource_id)['network']
        return self.handle_get_attributes(self.name, key, attributes)


def resource_mapping():
    return {
        'OS::Quantum::Net': Net,
    }
