
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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.neutron import neutron
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class VPC(resource.Resource):

    PROPERTIES = (
        CIDR_BLOCK, INSTANCE_TENANCY, TAGS,
    ) = (
        'CidrBlock', 'InstanceTenancy', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        CIDR_BLOCK: properties.Schema(
            properties.Schema.STRING,
            _('CIDR block to apply to the VPC.')
        ),
        INSTANCE_TENANCY: properties.Schema(
            properties.Schema.STRING,
            _('Allowed tenancy of instances launched in the VPC. default - '
              'any tenancy; dedicated - instance will be dedicated, '
              'regardless of the tenancy option specified at instance '
              'launch.'),
            default='default',
            constraints=[
                constraints.AllowedValues(['default', 'dedicated']),
            ],
            implemented=False
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of tags to attach to the instance.'),
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
        # first get the neutron net
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
        net = self.network_for_vpc(self.neutron(), self.resource_id)
        if not neutron.NeutronResource.is_built(net):
            return False
        router = self.router_for_vpc(self.neutron(), self.resource_id)
        return neutron.NeutronResource.is_built(router)

    def handle_delete(self):
        from neutronclient.common.exceptions import NeutronClientException
        client = self.neutron()
        router = self.router_for_vpc(client, self.resource_id)
        try:
            client.delete_router(router['id'])
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex

        try:
            client.delete_network(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'AWS::EC2::VPC': VPC,
    }
