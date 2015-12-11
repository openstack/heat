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
from oslo_utils import uuidutils

from heat.common import exception
from heat.engine.clients import client_plugin
from heat.engine.clients import os as os_client


class NeutronClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [NETWORK] = ['network']

    def _create(self):

        con = self.context

        endpoint_type = self._get_client_option('neutron', 'endpoint_type')
        endpoint = self.url_for(service_type=self.NETWORK,
                                endpoint_type=endpoint_type)

        args = {
            'auth_url': con.auth_url,
            'service_type': self.NETWORK,
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
        bad_conflicts = (exceptions.OverQuotaClient,)
        return (isinstance(ex, exceptions.Conflict) and
                not isinstance(ex, bad_conflicts))

    def is_over_limit(self, ex):
        if not isinstance(ex, exceptions.NeutronClientException):
            return False
        return ex.status_code == 413

    def is_no_unique(self, ex):
        return isinstance(ex, exceptions.NeutronClientNoUniqueMatch)

    def find_neutron_resource(self, props, key, key_type):
        return self.find_resourceid_by_name_or_id(
            key_type, props.get(key))

    def find_resourceid_by_name_or_id(self, resource, name_or_id,
                                      cmd_resource=None):
        return neutronV20.find_resourceid_by_name_or_id(
            self.client(), resource, name_or_id, cmd_resource=cmd_resource)

    @os_client.MEMOIZE
    def _list_extensions(self):
        extensions = self.client().list_extensions().get('extensions')
        return set(extension.get('alias') for extension in extensions)

    def has_extension(self, alias):
        """Check if specific extension is present."""
        return alias in self._list_extensions()

    def _resolve(self, props, key, id_key, key_type):
        if props.get(key):
            props[id_key] = self.find_neutron_resource(
                props, key, key_type)
            props.pop(key)
        return props[id_key]

    def resolve_network(self, props, net_key, net_id_key):
        return self._resolve(props, net_key, net_id_key, 'network')

    def resolve_subnet(self, props, subnet_key, subnet_id_key):
        return self._resolve(props, subnet_key, subnet_id_key, 'subnet')

    def resolve_router(self, props, router_key, router_id_key):
        return self._resolve(props, router_key, router_id_key, 'router')

    def resolve_port(self, props, port_key, port_id_key):
        return self._resolve(props, port_key, port_id_key, 'port')

    def network_id_from_subnet_id(self, subnet_id):
        subnet_info = self.client().show_subnet(subnet_id)
        return subnet_info['subnet']['network_id']

    def get_qos_policy_id(self, policy):
        """Returns the id of QoS policy.

        Args:
        policy: ID or name of the policy.
        """
        return self.find_resourceid_by_name_or_id(
            'policy', policy, cmd_resource='qos_policy')

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
                    raise exception.EntityNotFound(entity='Resource', name=sg)
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
