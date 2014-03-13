
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
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources import route_table
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class InternetGateway(resource.Resource):

    PROPERTIES = (
        TAGS,
    ) = (
        'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        TAGS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    TAG_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    TAG_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
                implemented=False,
            )
        ),
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
                _('Expected 1 external network, found %d') % len(ext_nets))
        external_network_id = ext_nets[0]['id']
        return external_network_id


class VPCGatewayAttachment(resource.Resource):

    PROPERTIES = (
        VPC_ID, INTERNET_GATEWAY_ID, VPN_GATEWAY_ID,
    ) = (
        'VpcId', 'InternetGatewayId', 'VpnGatewayId',
    )

    properties_schema = {
        VPC_ID: properties.Schema(
            properties.Schema.STRING,
            _('VPC ID for this gateway association.'),
            required=True
        ),
        INTERNET_GATEWAY_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the InternetGateway.')
        ),
        VPN_GATEWAY_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the VPNGateway to attach to the VPC.'),
            implemented=False
        ),
    }

    def _vpc_route_tables(self):
        for resource in self.stack.itervalues():
            if (resource.has_interface('AWS::EC2::RouteTable') and
                resource.properties.get(route_table.RouteTable.VPC_ID) ==
                    self.properties.get(self.VPC_ID)):
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
