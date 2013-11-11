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
from heat.openstack.common import log as logging
from heat.engine import resource
from heat.engine.resources.neutron import neutron

logger = logging.getLogger(__name__)


class NetworkInterface(resource.Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

    properties_schema = {
        'Description': {
            'Type': 'String',
            'Description': _('Description for this interface.')},
        'GroupSet': {
            'Type': 'List',
            'Description': _('List of security group IDs associated '
                             'with this interface.')},
        'PrivateIpAddress': {'Type': 'String'},
        'SourceDestCheck': {
            'Type': 'Boolean',
            'Implemented': False,
            'Description': _('Flag indicating if traffic to or from '
                             'instance is validated.')},
        'SubnetId': {
            'Type': 'String',
            'Required': True,
            'Description': _('Subnet ID to associate with this interface.')},
        'Tags': {'Type': 'List', 'Schema': {
            'Type': 'Map',
            'Implemented': False,
            'Schema': tags_schema,
            'Description': _('List of tags associated with this interface.')}}
    }

    @staticmethod
    def network_id_from_subnet_id(neutronclient, subnet_id):
        subnet_info = neutronclient.show_subnet(subnet_id)
        return subnet_info['subnet']['network_id']

    def handle_create(self):
        client = self.neutron()

        subnet_id = self.properties['SubnetId']
        network_id = self.network_id_from_subnet_id(client, subnet_id)

        fixed_ip = {'subnet_id': subnet_id}
        if self.properties['PrivateIpAddress']:
            fixed_ip['ip_address'] = self.properties['PrivateIpAddress']

        props = {
            'name': self.physical_resource_name(),
            'admin_state_up': True,
            'network_id': network_id,
            'fixed_ips': [fixed_ip]
        }

        if self.properties['GroupSet']:
            sgs = neutron.NeutronResource.get_secgroup_uuids(
                self.properties.get('GroupSet', []), self.neutron())
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


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'AWS::EC2::NetworkInterface': NetworkInterface,
    }
