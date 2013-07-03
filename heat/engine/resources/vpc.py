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
from heat.engine import clients
from heat.openstack.common import log as logging
from heat.engine import resource
from heat.engine.resources.quantum import quantum

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
        # The VPC's net and router are associated by having identical names.
        net_props = {'name': self.physical_resource_name()}
        router_props = {'name': self.physical_resource_name()}

        net = client.create_network({'network': net_props})['network']
        client.create_router({'router': router_props})['router']

        self.resource_id_set(net['id'])

    @staticmethod
    def network_for_vpc(client, network_id):
        return client.show_network(network_id)['network']

    @staticmethod
    def router_for_vpc(client, network_id):
        # first get the quantum net
        net = VPC.network_for_vpc(client, network_id)
        # then find a router with the same name
        routers = client.list_routers(name=net['name'])['routers']
        if len(routers) == 0:
            # There may be no router if the net was created manually
            # instead of in another stack.
            return None
        if len(routers) > 1:
            raise exception.Error(
                _('Multiple routers found with name %s') % net['name'])
        return routers[0]

    def check_create_complete(self, *args):
        net = self.network_for_vpc(self.quantum(), self.resource_id)
        if not quantum.QuantumResource.is_built(net):
            return False
        router = self.router_for_vpc(self.quantum(), self.resource_id)
        return quantum.QuantumResource.is_built(router)

    def handle_delete(self):
        from quantumclient.common.exceptions import QuantumClientException
        client = self.quantum()
        router = self.router_for_vpc(client, self.resource_id)
        try:
            client.delete_router(router['id'])
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

        try:
            client.delete_network(self.resource_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'AWS::EC2::VPC': VPC,
    }
