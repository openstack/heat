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
from heat.engine import resource

logger = logging.getLogger(__name__)


class NetworkInterface(resource.Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

    properties_schema = {
        'Description': {'Type': 'String'},
        'GroupSet': {'Type': 'List'},
        'PrivateIpAddress': {'Type': 'String'},
        'SourceDestCheck': {
            'Type': 'Boolean',
            'Implemented': False},
        'SubnetId': {
            'Type': 'String',
            'Required': True},
        'Tags': {'Type': 'List', 'Schema': {
            'Type': 'Map',
            'Implemented': False,
            'Schema': tags_schema}}
    }

    def __init__(self, name, json_snippet, stack):
        super(NetworkInterface, self).__init__(name, json_snippet, stack)

    @staticmethod
    def network_id_from_subnet_id(quantumclient, subnet_id):
        subnet_info = quantumclient.show_subnet(subnet_id)
        return subnet_info['subnet']['network_id']

    def handle_create(self):
        client = self.quantum()

        subnet_id = self.properties['SubnetId']
        network_id = self.network_id_from_subnet_id(client, subnet_id)

        fixed_ip = {'subnet_id': subnet_id}
        if self.properties['PrivateIpAddress']:
            fixed_ip['ip_address'] = self.properties['PrivateIpAddress']

        props = {
            'name': self.physical_resource_name(),
            'admin_state_up': True,
            'network_id': network_id,
            'fixed_ips': [fixed_ip]
        }

        if self.properties['GroupSet']:
            props['security_groups'] = self.properties['GroupSet']
        port = client.create_port({'port': props})['port']
        self.resource_id_set(port['id'])

    def handle_delete(self):
        from quantumclient.common.exceptions import QuantumClientException

        client = self.quantum()
        try:
            client.delete_port(self.resource_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

    def handle_update(self, json_snippet):
        return self.UPDATE_REPLACE


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'AWS::EC2::NetworkInterface': NetworkInterface,
    }
