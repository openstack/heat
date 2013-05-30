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

if clients.quantumclient is not None:
    from quantumclient.common.exceptions import QuantumClientException

logger = logging.getLogger(__name__)


class RouteTable(resource.Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

    properties_schema = {
        'VpcId': {
            'Type': 'String',
            'Required': True},
        'Tags': {'Type': 'List', 'Schema': {
            'Type': 'Map',
            'Implemented': False,
            'Schema': tags_schema}}
    }

    def handle_create(self):
        client = self.quantum()
        props = {'name': self.physical_resource_name()}
        router = client.create_router({'router': props})['router']

        # add this router to the list of all routers in the VPC
        vpc = self.stack.resource_by_refid(self.properties.get('VpcId'))
        vpc_md = vpc.metadata
        vpc_md['all_router_ids'].append(router['id'])
        vpc.metadata = vpc_md

        # TODO(sbaker) all_router_ids has changed, any VPCGatewayAttachment
        # for this vpc needs to be notified
        self.resource_id_set(router['id'])

    def handle_delete(self):
        client = self.quantum()

        router_id = self.resource_id
        try:
            client.delete_router(router_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

        # remove this router from the list of all routers in the VPC
        vpc = self.stack.resource_by_refid(self.properties.get('VpcId'))
        vpc_md = vpc.metadata
        vpc_md['all_router_ids'].remove(router_id)
        vpc.metadata = vpc_md
        # TODO(sbaker) all_router_ids has changed, any VPCGatewayAttachment
        # for this vpc needs to be notified


class SubnetRouteTableAssocation(resource.Resource):

    properties_schema = {
        'RouteTableId': {
            'Type': 'String',
            'Required': True},
        'SubnetId': {
            'Type': 'String',
            'Required': True}
    }

    def handle_create(self):
        client = self.quantum()
        subnet = self.stack.resource_by_refid(self.properties.get('SubnetId'))
        subnet_id = self.properties.get('SubnetId')
        previous_router_id = subnet.metadata['router_id']

        router_id = self.properties.get('RouteTableId')

        #remove the default router association for this subnet.
        try:
            client.remove_interface_router(
                previous_router_id,
                {'subnet_id': subnet_id})
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

        client.add_interface_router(
            router_id, {'subnet_id': subnet_id})

    def handle_delete(self):
        client = self.quantum()
        subnet = self.stack.resource_by_refid(self.properties.get('SubnetId'))
        subnet_id = self.properties.get('SubnetId')
        default_router_id = subnet.metadata['default_router_id']

        router_id = self.properties.get('RouteTableId')

        try:
            client.remove_interface_router(router_id, {
                'subnet_id': subnet_id})
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

        # add back the default router
        client.add_interface_router(
            default_router_id, {'subnet_id': subnet_id})


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'AWS::EC2::RouteTable': RouteTable,
        'AWS::EC2::SubnetRouteTableAssocation': SubnetRouteTableAssocation,
    }
