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
from heat.engine.resources.vpc import VPC

logger = logging.getLogger(__name__)


class Subnet(resource.Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

    properties_schema = {
        'AvailabilityZone': {'Type': 'String'},
        'CidrBlock': {
            'Type': 'String',
            'Required': True},
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
        # TODO(sbaker) Verify that this CidrBlock is within the vpc CidrBlock
        network_id = self.properties.get('VpcId')

        props = {
            'network_id': network_id,
            'cidr': self.properties.get('CidrBlock'),
            'name': self.physical_resource_name(),
            'ip_version': 4
        }
        subnet = client.create_subnet({'subnet': props})['subnet']

        router = VPC.router_for_vpc(self.quantum(), network_id)
        if router:
            client.add_interface_router(
                router['id'],
                {'subnet_id': subnet['id']})
        self.resource_id_set(subnet['id'])

    def handle_delete(self):
        from quantumclient.common.exceptions import QuantumClientException

        client = self.quantum()
        network_id = self.properties.get('VpcId')
        subnet_id = self.resource_id

        try:
            router = VPC.router_for_vpc(self.quantum(), network_id)
            if router:
                client.remove_interface_router(
                    router['id'],
                    {'subnet_id': subnet_id})
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

        try:
            client.delete_subnet(subnet_id)
        except QuantumClientException as ex:
            if ex.status_code != 404:
                raise ex

    def FnGetAtt(self, key):
        if key == 'AvailabilityZone':
            return self.properties.get(key, '')
        raise exception.InvalidTemplateAttribute(resource=self.name, key=key)


def resource_mapping():
    if clients.quantumclient is None:
        return {}

    return {
        'AWS::EC2::Subnet': Subnet,
    }
