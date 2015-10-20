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

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.aws.ec2 import vpc
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class RouteTable(resource.Resource):

    support_status = support.SupportStatus(version='2014.1')

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

    default_client_name = 'neutron'

    def handle_create(self):
        client = self.client()
        props = {'name': self.physical_resource_name()}
        router = client.create_router({'router': props})['router']
        self.resource_id_set(router['id'])

    def check_create_complete(self, *args):
        client = self.client()
        attributes = client.show_router(
            self.resource_id)['router']
        if not neutron.NeutronResource.is_built(attributes):
            return False

        network_id = self.properties.get(self.VPC_ID)
        default_router = vpc.VPC.router_for_vpc(client, network_id)
        if default_router and default_router.get('external_gateway_info'):
            # the default router for the VPC is connected
            # to the external router, so do it for this too.
            external_network_id = default_router[
                'external_gateway_info']['network_id']
            client.add_gateway_router(self.resource_id, {
                'network_id': external_network_id})
        return True

    def handle_delete(self):
        client = self.client()

        router_id = self.resource_id
        with self.client_plugin().ignore_not_found:
            client.delete_router(router_id)

        # just in case this router has been added to a gateway, remove it
        with self.client_plugin().ignore_not_found:
            client.remove_gateway_router(router_id)


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
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ]
        ),
    }

    default_client_name = 'neutron'

    def handle_create(self):
        client = self.client()
        subnet_id = self.properties.get(self.SUBNET_ID)

        router_id = self.properties.get(self.ROUTE_TABLE_ID)

        # remove the default router association for this subnet.
        with self.client_plugin().ignore_not_found:
            previous_router = self._router_for_subnet(subnet_id)
            if previous_router:
                client.remove_interface_router(
                    previous_router['id'],
                    {'subnet_id': subnet_id})

        client.add_interface_router(
            router_id, {'subnet_id': subnet_id})

    def _router_for_subnet(self, subnet_id):
        client = self.client()
        subnet = client.show_subnet(
            subnet_id)['subnet']
        network_id = subnet['network_id']
        return vpc.VPC.router_for_vpc(client, network_id)

    def handle_delete(self):
        client = self.client()
        subnet_id = self.properties.get(self.SUBNET_ID)

        router_id = self.properties.get(self.ROUTE_TABLE_ID)

        with self.client_plugin().ignore_not_found:
            client.remove_interface_router(router_id, {
                'subnet_id': subnet_id})

        # add back the default router
        with self.client_plugin().ignore_not_found:
            default_router = self._router_for_subnet(subnet_id)
            if default_router:
                client.add_interface_router(
                    default_router['id'], {'subnet_id': subnet_id})


def resource_mapping():
    return {
        'AWS::EC2::RouteTable': RouteTable,
        'AWS::EC2::SubnetRouteTableAssociation': SubnetRouteTableAssociation,
    }
