
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
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class NetworkInterface(resource.Resource):

    PROPERTIES = (
        DESCRIPTION, GROUP_SET, PRIVATE_IP_ADDRESS, SOURCE_DEST_CHECK,
        SUBNET_ID, TAGS,
    ) = (
        'Description', 'GroupSet', 'PrivateIpAddress', 'SourceDestCheck',
        'SubnetId', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for this interface.')
        ),
        GROUP_SET: properties.Schema(
            properties.Schema.LIST,
            _('List of security group IDs associated with this interface.'),
            default=[]
        ),
        PRIVATE_IP_ADDRESS: properties.Schema(
            properties.Schema.STRING
        ),
        SOURCE_DEST_CHECK: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Flag indicating if traffic to or from instance is validated.'),
            implemented=False
        ),
        SUBNET_ID: properties.Schema(
            properties.Schema.STRING,
            _('Subnet ID to associate with this interface.'),
            required=True
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of tags associated with this interface.'),
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

    attributes_schema = {'PrivateIpAddress': _('Private IP address of the '
                                               'network interface.')}

    @staticmethod
    def network_id_from_subnet_id(neutronclient, subnet_id):
        subnet_info = neutronclient.show_subnet(subnet_id)
        return subnet_info['subnet']['network_id']

    def __init__(self, name, json_snippet, stack):
        super(NetworkInterface, self).__init__(name, json_snippet, stack)
        self.fixed_ip_address = None

    def handle_create(self):
        client = self.neutron()

        subnet_id = self.properties[self.SUBNET_ID]
        network_id = self.network_id_from_subnet_id(client, subnet_id)

        fixed_ip = {'subnet_id': subnet_id}
        if self.properties[self.PRIVATE_IP_ADDRESS]:
            fixed_ip['ip_address'] = self.properties[self.PRIVATE_IP_ADDRESS]

        props = {
            'name': self.physical_resource_name(),
            'admin_state_up': True,
            'network_id': network_id,
            'fixed_ips': [fixed_ip]
        }

        if self.properties[self.GROUP_SET]:
            sgs = neutron.NeutronResource.get_secgroup_uuids(
                self.properties.get(self.GROUP_SET), self.neutron())
            props['security_groups'] = sgs
        port = client.create_port({'port': props})['port']
        self.resource_id_set(port['id'])

    def handle_delete(self):
        from neutronclient.common.exceptions import NeutronClientException

        client = self.neutron()
        try:
            client.delete_port(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex

    def _get_fixed_ip_address(self, ):
        if self.fixed_ip_address is None:
            from neutronclient.common.exceptions import NeutronClientException

            client = self.neutron()
            try:
                port = client.show_port(self.resource_id)['port']
                if port['fixed_ips'] and len(port['fixed_ips']) > 0:
                    self.fixed_ip_address = port['fixed_ips'][0]['ip_address']
            except NeutronClientException as ex:
                if ex.status_code != 404:
                    raise ex

        return self.fixed_ip_address

    def _resolve_attribute(self, name):
        if name == 'PrivateIpAddress':
            return self._get_fixed_ip_address()


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'AWS::EC2::NetworkInterface': NetworkInterface,
    }
