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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource


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

    ATTRIBUTES = (
        PRIVATE_IP_ADDRESS_ATTR,
    ) = (
        'PrivateIpAddress',
    )

    properties_schema = {
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for this interface.')
        ),
        GROUP_SET: properties.Schema(
            properties.Schema.LIST,
            _('List of security group IDs associated with this interface.'),
            update_allowed=True
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
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ]
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

    attributes_schema = {
        PRIVATE_IP_ADDRESS: attributes.Schema(
            _('Private IP address of the network interface.'),
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'neutron'

    @staticmethod
    def network_id_from_subnet_id(neutronclient, subnet_id):
        subnet_info = neutronclient.show_subnet(subnet_id)
        return subnet_info['subnet']['network_id']

    def __init__(self, name, json_snippet, stack):
        super(NetworkInterface, self).__init__(name, json_snippet, stack)
        self.fixed_ip_address = None

    def handle_create(self):
        subnet_id = self.properties[self.SUBNET_ID]
        network_id = self.client_plugin().network_id_from_subnet_id(
            subnet_id)

        fixed_ip = {'subnet_id': subnet_id}
        if self.properties[self.PRIVATE_IP_ADDRESS]:
            fixed_ip['ip_address'] = self.properties[self.PRIVATE_IP_ADDRESS]

        props = {
            'name': self.physical_resource_name(),
            'admin_state_up': True,
            'network_id': network_id,
            'fixed_ips': [fixed_ip]
        }
        # if without group_set, don't set the 'security_groups' property,
        # neutron will create the port with the 'default' securityGroup,
        # if has the group_set and the value is [], which means to create the
        # port without securityGroup(same as the behavior of neutron)
        if self.properties[self.GROUP_SET] is not None:
            sgs = self.client_plugin().get_secgroup_uuids(
                self.properties.get(self.GROUP_SET))
            props['security_groups'] = sgs
        port = self.client().create_port({'port': props})['port']
        self.resource_id_set(port['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            self.client().delete_port(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            update_props = {}
            if self.GROUP_SET in prop_diff:
                group_set = prop_diff.get(self.GROUP_SET)
                # update should keep the same behavior as creation,
                # if without the GroupSet in update template, we should
                # update the security_groups property to referent
                # the 'default' security group
                if group_set is not None:
                    sgs = self.client_plugin().get_secgroup_uuids(group_set)
                else:
                    sgs = self.client_plugin().get_secgroup_uuids(['default'])

                update_props['security_groups'] = sgs

                self.client().update_port(self.resource_id,
                                          {'port': update_props})

    def _get_fixed_ip_address(self):
        if self.fixed_ip_address is None:
            port = self.client().show_port(self.resource_id)['port']
            if port['fixed_ips'] and len(port['fixed_ips']) > 0:
                self.fixed_ip_address = port['fixed_ips'][0]['ip_address']

        return self.fixed_ip_address

    def _resolve_attribute(self, name):
        if name == self.PRIVATE_IP_ADDRESS:
            return self._get_fixed_ip_address()


def resource_mapping():
    return {
        'AWS::EC2::NetworkInterface': NetworkInterface,
    }
