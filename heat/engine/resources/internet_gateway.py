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
        self.resource_id_set(self.physical_resource_name())

    def handle_delete(self):
        pass

    @staticmethod
    def get_external_network_id(client):
        ext_filter = {'router:external': True}
        ext_nets = client.list_networks(**ext_filter)['networks']
        if len(ext_nets) != 1:
            # TODO(sbaker) if there is more than one external network
            # add a heat configuration variable to set the ID of
            # the default one
            raise exception.Error(
                'Expected 1 external network, found %d' % len(ext_nets))
        external_network_id = ext_nets[0]['id']
        return external_network_id


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

    def _vpc_route_tables(self):
        for resource in self.stack.resources.itervalues():
            if (resource.has_interface('AWS::EC2::RouteTable') and
                resource.properties.get('VpcId') ==
                    self.properties.get('VpcId')):
                        yield resource

    def add_dependencies(self, deps):
        super(VPCGatewayAttachment, self).add_dependencies(deps)
        # Depend on any route table in this template with the same
        # VpcId as this VpcId.
        # All route tables must exist before gateway attachment
        # as attachment happens to routers (not VPCs)
        for route_table in self._vpc_route_tables():
            deps += (self, route_table)

    def handle_create(self):
        client = self.neutron()
        external_network_id = InternetGateway.get_external_network_id(client)
        for router in self._vpc_route_tables():
            client.add_gateway_router(router.resource_id, {
                'network_id': external_network_id})

    def handle_delete(self):
        from neutronclient.common.exceptions import NeutronClientException

        client = self.neutron()
        for router in self._vpc_route_tables():
            try:
                client.remove_gateway_router(router.resource_id)
            except NeutronClientException as ex:
                if ex.status_code != 404:
                    raise ex


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'AWS::EC2::InternetGateway': InternetGateway,
        'AWS::EC2::VPCGatewayAttachment': VPCGatewayAttachment,
    }
