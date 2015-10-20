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
from heat.engine import attributes
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.aws.ec2 import vpc


class Subnet(resource.Resource):

    PROPERTIES = (
        AVAILABILITY_ZONE, CIDR_BLOCK, VPC_ID, TAGS,
    ) = (
        'AvailabilityZone', 'CidrBlock', 'VpcId', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    ATTRIBUTES = (
        AVAILABILITY_ZONE,
    )

    properties_schema = {
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('Availability zone in which you want the subnet.')
        ),
        CIDR_BLOCK: properties.Schema(
            properties.Schema.STRING,
            _('CIDR block to apply to subnet.'),
            required=True
        ),
        VPC_ID: properties.Schema(
            properties.Schema.STRING,
            _('Ref structure that contains the ID of the VPC on which you '
              'want to create the subnet.'),
            required=True
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of tags to attach to this resource.'),
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

    attributes_schema = {
        AVAILABILITY_ZONE: attributes.Schema(
            _('Availability Zone of the subnet.'),
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'neutron'

    def handle_create(self):
        # TODO(sbaker) Verify that this CidrBlock is within the vpc CidrBlock
        network_id = self.properties.get(self.VPC_ID)

        props = {
            'network_id': network_id,
            'cidr': self.properties.get(self.CIDR_BLOCK),
            'name': self.physical_resource_name(),
            'ip_version': 4
        }
        subnet = self.client().create_subnet({'subnet': props})['subnet']
        self.resource_id_set(subnet['id'])

        router = vpc.VPC.router_for_vpc(self.client(), network_id)
        if router:
            self.client().add_interface_router(
                router['id'],
                {'subnet_id': subnet['id']})

    def handle_delete(self):
        if self.resource_id is None:
            return

        network_id = self.properties.get(self.VPC_ID)
        subnet_id = self.resource_id

        with self.client_plugin().ignore_not_found:
            router = vpc.VPC.router_for_vpc(self.client(), network_id)
            if router:
                self.client().remove_interface_router(
                    router['id'],
                    {'subnet_id': subnet_id})

        with self.client_plugin().ignore_not_found:
            self.client().delete_subnet(subnet_id)

    def _resolve_attribute(self, name):
        if name == self.AVAILABILITY_ZONE:
            return self.properties.get(self.AVAILABILITY_ZONE)


def resource_mapping():
    return {
        'AWS::EC2::Subnet': Subnet,
    }
