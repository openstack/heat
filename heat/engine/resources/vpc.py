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


class VPC(resource.Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

    properties_schema = {
        'CidrBlock': {'Type': 'String'},
        'InstanceTenancy': {
            'Type': 'String',
            'AllowedValues': ['default',
                              'dedicated'],
            'Default': 'default',
            'Implemented': False},
        'Tags': {'Type': 'List', 'Schema': {
            'Type': 'Map',
            'Implemented': False,
            'Schema': tags_schema}}
    }

    def handle_create(self):
        client = self.quantum()
        props = {'name': self.physical_resource_name()}
        # Creates a network with an implicit router
        net = client.create_network({'network': props})['network']
        router = client.create_router({'router': props})['router']
        md = {
            'router_id': router['id'],
            'all_router_ids': [router['id']]
        }
        self.metadata = md
        self.resource_id_set(net['id'])

    def handle_delete(self):
        from quantumclient.common.exceptions import QuantumClientException

        client = self.quantum()
        network_id = self.resource_id
        router_id = self.metadata['router_id']
        try:
            client.delete_router(router_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

        try:
            client.delete_network(network_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'AWS::EC2::VPC': VPC,
    }
