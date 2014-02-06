
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
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.neutron import neutron
from heat.engine.resources.vpc import VPC
from heat.openstack.common import log as logging

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException

logger = logging.getLogger(__name__)


class RouteTable(resource.Resource):

    PROPERTIES = (
        VPC_ID, TAGS,
    ) = (
        'VpcId', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        VPC_ID: properties.Schema(
            properties.Schema.STRING,
            _('VPC ID for where the route table is created.'),
            required=True
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of tags to be attached to this resource.'),
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
        client = self.neutron()
        props = {'name': self.physical_resource_name()}
        router = client.create_router({'router': props})['router']
        self.resource_id_set(router['id'])

    def check_create_complete(self, *args):
        client = self.neutron()
        attributes = client.show_router(
            self.resource_id)['router']
        if not neutron.NeutronResource.is_built(attributes):
            return False

        network_id = self.properties.get(self.VPC_ID)
        default_router = VPC.router_for_vpc(client, network_id)
        if default_router and default_router.get('external_gateway_info'):
            # the default router for the VPC is connected
            # to the external router, so do it for this too.
            external_network_id = default_router[
                'external_gateway_info']['network_id']
            client.add_gateway_router(self.resource_id, {
                'network_id': external_network_id})
        return True

    def handle_delete(self):
        client = self.neutron()

        router_id = self.resource_id
        try:
            client.delete_router(router_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex

        # just in case this router has been added to a gateway, remove it
        try:
            client.remove_gateway_router(router_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex


class SubnetRouteTableAssociation(resource.Resource):

    PROPERTIES = (
        ROUTE_TABLE_ID, SUBNET_ID,
    ) = (
        'RouteTableId', 'SubnetId',
    )

    properties_schema = {
        ROUTE_TABLE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Route table ID.'),
            required=True
        ),
        SUBNET_ID: properties.Schema(
            properties.Schema.STRING,
            _('Subnet ID.'),
            required=True
        ),
    }

    def handle_create(self):
        client = self.neutron()
        subnet_id = self.properties.get(self.SUBNET_ID)

        router_id = self.properties.get(self.ROUTE_TABLE_ID)

        #remove the default router association for this subnet.
        try:
            previous_router = self._router_for_subnet(subnet_id)
            if previous_router:
                client.remove_interface_router(
                    previous_router['id'],
                    {'subnet_id': subnet_id})
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex

        client.add_interface_router(
            router_id, {'subnet_id': subnet_id})

    def _router_for_subnet(self, subnet_id):
        client = self.neutron()
        subnet = client.show_subnet(
            subnet_id)['subnet']
        network_id = subnet['network_id']
        return VPC.router_for_vpc(client, network_id)

    def handle_delete(self):
        client = self.neutron()
        subnet_id = self.properties.get(self.SUBNET_ID)

        router_id = self.properties.get(self.ROUTE_TABLE_ID)

        try:
            client.remove_interface_router(router_id, {
                'subnet_id': subnet_id})
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex

        # add back the default router
        try:
            default_router = self._router_for_subnet(subnet_id)
            if default_router:
                client.add_interface_router(
                    default_router['id'], {'subnet_id': subnet_id})
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'AWS::EC2::RouteTable': RouteTable,
        'AWS::EC2::SubnetRouteTableAssociation': SubnetRouteTableAssociation,
    }
