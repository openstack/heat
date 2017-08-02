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

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.aws.ec2 import route_table


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

    default_client_name = 'neutron'

    def _vpc_route_tables(self, ignore_errors=False):
        for res in six.itervalues(self.stack):
            if res.has_interface('AWS::EC2::RouteTable'):
                try:
                    vpc_id = self.properties[self.VPC_ID]
                    rt_vpc_id = res.properties.get(
                        route_table.RouteTable.VPC_ID)
                except (ValueError, TypeError):
                    if ignore_errors:
                        continue
                    else:
                        raise
                if rt_vpc_id == vpc_id:
                    yield res

    def add_dependencies(self, deps):
        super(VPCGatewayAttachment, self).add_dependencies(deps)
        # Depend on any route table in this template with the same
        # VpcId as this VpcId.
        # All route tables must exist before gateway attachment
        # as attachment happens to routers (not VPCs)
        # Properties errors will be caught later in validation,
        # where we can report them in their proper context.
        for route_tbl in self._vpc_route_tables(ignore_errors=True):
            deps += (self, route_tbl)

    def handle_create(self):
        client = self.client()
        external_network_id = InternetGateway.get_external_network_id(client)
        for router in self._vpc_route_tables():
            client.add_gateway_router(router.resource_id, {
                'network_id': external_network_id})

    def handle_delete(self):
        for router in self._vpc_route_tables():
            with self.client_plugin().ignore_not_found:
                self.client().remove_gateway_router(router.resource_id)


def resource_mapping():
    return {
        'AWS::EC2::InternetGateway': InternetGateway,
        'AWS::EC2::VPCGatewayAttachment': VPCGatewayAttachment,
    }
