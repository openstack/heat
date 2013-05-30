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
from heat.common import exception
from heat.openstack.common import log as logging
from heat.engine import resource

logger = logging.getLogger(__name__)


class InternetGateway(resource.Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

    properties_schema = {
        'Tags': {'Type': 'List', 'Schema': {
            'Type': 'Map',
            'Implemented': False,
            'Schema': tags_schema}}
    }

    def handle_create(self):
        client = self.quantum()

        ext_filter = {'router:external': True}
        ext_nets = client.list_networks(**ext_filter)['networks']
        if len(ext_nets) != 1:
            # TODO(sbaker) if there is more than one external network
            # add a heat configuration variable to set the ID of
            # the default one
            raise exception.Error(
                'Expected 1 external network, found %d' % len(ext_nets))

        external_network_id = ext_nets[0]['id']
        md = {
            'external_network_id': external_network_id
        }
        self.metadata = md

    def handle_delete(self):
        pass


class VPCGatewayAttachment(resource.Resource):

    properties_schema = {
        'VpcId': {
            'Type': 'String',
            'Required': True},
        'InternetGatewayId': {'Type': 'String'},
        'VpnGatewayId': {
            'Type': 'String',
            'Implemented': False}
    }

    def handle_create(self):
        client = self.quantum()
        gateway = self.stack[self.properties.get('InternetGatewayId')]
        vpc = self.stack.resource_by_refid(self.properties.get('VpcId'))
        external_network_id = gateway.metadata['external_network_id']

        for router_id in vpc.metadata['all_router_ids']:
            client.add_gateway_router(router_id, {
                'network_id': external_network_id})

    def handle_delete(self):
        from quantumclient.common.exceptions import QuantumClientException

        client = self.quantum()
        vpc = self.stack.resource_by_refid(self.properties.get('VpcId'))
        for router_id in vpc.metadata['all_router_ids']:
            try:
                client.remove_gateway_router(router_id)
            except QuantumClientException as ex:
                if ex.status_code != 404:
                    raise ex


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'AWS::EC2::InternetGateway': InternetGateway,
        'AWS::EC2::VPCGatewayAttachment': VPCGatewayAttachment,
    }
