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

from heat.openstack.common import log as logging
from heat.engine import resource

logger = logging.getLogger(__name__)


class VPC(resource.Resource):
    properties_schema = {'CidrBlock': {'Type': 'String'},
                         'InstanceTenancy': {'Type': 'String',
                            'AllowedValues': ['default', 'dedicated'],
                            'Default': 'default',
                            'Implemented': False}
    }

    def __init__(self, name, json_snippet, stack):
        super(VPC, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        client = self.quantum()
        props = {'name': self.name}
        # Creates a network with an implicit router
        net = client.create_network({'network': props})['network']
        router = client.create_router({'router': props})['router']
        id = '%s:%s' % (net['id'], router['id'])
        self.resource_id_set(id)

    def handle_delete(self):
        client = self.quantum()
        (network_id, router_id) = self.resource_id.split(':')
        client.delete_router(router_id)
        client.delete_network(network_id)

    def handle_update(self):
        return self.UPDATE_REPLACE


def resource_mapping():
    return {
        'AWS::EC2::VPC': VPC,
    }
