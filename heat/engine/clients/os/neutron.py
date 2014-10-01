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

from neutronclient.common import exceptions
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as nc

from heat.common import exception
from heat.engine.clients import client_plugin
from heat.engine import constraints
from heat.openstack.common import uuidutils


class NeutronClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    def _create(self):

        con = self.context

        endpoint_type = self._get_client_option('neutron', 'endpoint_type')
        endpoint = self.url_for(service_type='network',
                                endpoint_type=endpoint_type)

        args = {
            'auth_url': con.auth_url,
            'service_type': 'network',
            'token': self.auth_token,
            'endpoint_url': endpoint,
            'endpoint_type': endpoint_type,
            'ca_cert': self._get_client_option('neutron', 'ca_file'),
            'insecure': self._get_client_option('neutron', 'insecure')
        }

        return nc.Client(**args)

    def is_not_found(self, ex):
        if isinstance(ex, (exceptions.NotFound,
                           exceptions.NetworkNotFoundClient,
                           exceptions.PortNotFoundClient)):
            return True
        return (isinstance(ex, exceptions.NeutronClientException) and
                ex.status_code == 404)

    def is_conflict(self, ex):
        if not isinstance(ex, exceptions.NeutronClientException):
            return False
        return ex.status_code == 409

    def is_over_limit(self, ex):
        if not isinstance(ex, exceptions.NeutronClientException):
            return False
        return ex.status_code == 413

    def find_neutron_resource(self, props, key, key_type):
        return neutronV20.find_resourceid_by_name_or_id(
            self.client(), key_type, props.get(key))

    def resolve_network(self, props, net_key, net_id_key):
        if props.get(net_key):
            props[net_id_key] = self.find_neutron_resource(
                props, net_key, 'network')
            props.pop(net_key)
        return props[net_id_key]

    def resolve_subnet(self, props, subnet_key, subnet_id_key):
        if props.get(subnet_key):
            props[subnet_id_key] = self.find_neutron_resource(
                props, subnet_key, 'subnet')
            props.pop(subnet_key)
        return props[subnet_id_key]

    def network_id_from_subnet_id(self, subnet_id):
        subnet_info = self.client().show_subnet(subnet_id)
        return subnet_info['subnet']['network_id']

    def get_secgroup_uuids(self, security_groups):
        '''Returns a list of security group UUIDs.

        Args:
        security_groups: List of security group names or UUIDs
        '''
        seclist = []
        all_groups = None
        for sg in security_groups:
            if uuidutils.is_uuid_like(sg):
                seclist.append(sg)
            else:
                if not all_groups:
                    response = self.client().list_security_groups()
                    all_groups = response['security_groups']
                same_name_groups = [g for g in all_groups if g['name'] == sg]
                groups = [g['id'] for g in same_name_groups]
                if len(groups) == 0:
                    raise exception.PhysicalResourceNotFound(resource_id=sg)
                elif len(groups) == 1:
                    seclist.append(groups[0])
                else:
                    # for admin roles, can get the other users'
                    # securityGroups, so we should match the tenant_id with
                    # the groups, and return the own one
                    own_groups = [g['id'] for g in same_name_groups
                                  if g['tenant_id'] == self.context.tenant_id]
                    if len(own_groups) == 1:
                        seclist.append(own_groups[0])
                    else:
                        raise exception.PhysicalResourceNameAmbiguity(name=sg)
        return seclist


class NetworkConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.NeutronClientException,)

    def validate_with_client(self, client, value):
        neutron_client = client.client('neutron')
        neutronV20.find_resourceid_by_name_or_id(
            neutron_client, 'network', value)


class PortConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.NeutronClientException,)

    def validate_with_client(self, client, value):
        neutron_client = client.client('neutron')
        neutronV20.find_resourceid_by_name_or_id(
            neutron_client, 'port', value)


class RouterConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.NeutronClientException,)

    def validate_with_client(self, client, value):
        neutron_client = client.client('neutron')
        neutronV20.find_resourceid_by_name_or_id(
            neutron_client, 'router', value)


class SubnetConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.NeutronClientException,)

    def validate_with_client(self, client, value):
        neutron_client = client.client('neutron')
        neutronV20.find_resourceid_by_name_or_id(
            neutron_client, 'subnet', value)
