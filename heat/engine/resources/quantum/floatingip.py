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


class FloatingIP(quantum.QuantumResource):
    properties_schema = {'floating_network_id': {'Type': 'String',
                                                 'Required': True},
                         'value_specs': {'Type': 'Map',
                                         'Default': {}},
                         'port_id': {'Type': 'String'},
                         'fixed_ip_address': {'Type': 'String'}}

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        fip = self.quantum().create_floatingip({
            'floatingip': props})['floatingip']
        self.resource_id_set(fip['id'])

    def handle_delete(self):
        client = self.quantum()
        try:
            client.delete_floatingip(self.resource_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

    def FnGetAtt(self, key):
        try:
            attributes = self.quantum().show_floatingip(
                self.resource_id)['floatingip']
        except QuantumClientException as ex:
            logger.warn("failed to fetch resource attributes: %s" % str(ex))
            return None
        return self.handle_get_attributes(self.name, key, attributes)


class FloatingIPAssociation(quantum.QuantumResource):
    properties_schema = {'floatingip_id': {'Type': 'String',
                                           'Required': True},
                         'port_id': {'Type': 'String',
                                     'Required': True},
                         'fixed_ip_address': {'Type': 'String'}}

    def handle_create(self):
        props = self.prepare_properties(self.properties, self.name)

        floatingip_id = props.pop('floatingip_id')

        self.quantum().update_floatingip(floatingip_id, {
            'floatingip': props})['floatingip']
        self.resource_id_set('%s:%s' % (floatingip_id, props['port_id']))

    def handle_delete(self):
        client = self.quantum()
        (floatingip_id, port_id) = self.resource_id.split(':')
        try:
            client.update_floatingip(
                floatingip_id,
                {'floatingip': {'port_id': None}})
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'OS::Quantum::FloatingIP': FloatingIP,
        'OS::Quantum::FloatingIPAssociation': FloatingIPAssociation,
    }
