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

from troveclient import client as tc
from troveclient.openstack.common.apiclient import exceptions

from heat.common import exception
from heat.engine.clients import client_plugin


class TroveClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option('trove', 'endpoint_type')
        args = {
            'service_type': 'database',
            'auth_url': con.auth_url or '',
            'proxy_token': con.auth_token,
            'username': None,
            'password': None,
            'cacert': self._get_client_option('trove', 'ca_file'),
            'insecure': self._get_client_option('trove', 'insecure'),
            'endpoint_type': endpoint_type
        }

        client = tc.Client('1.0', **args)
        management_url = self.url_for(service_type='database',
                                      endpoint_type=endpoint_type)
        client.client.auth_token = con.auth_token
        client.client.management_url = management_url

        return client

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)

    def get_flavor_id(self, flavor):
        '''
        Get the id for the specified flavor name.
        If the specified value is flavor id, just return it.

        :param flavor: the name of the flavor to find
        :returns: the id of :flavor:
        :raises: exception.FlavorMissing
        '''
        flavor_id = None
        flavor_list = self.client().flavors.list()
        for o in flavor_list:
            if o.name == flavor:
                flavor_id = o.id
                break
            if o.id == flavor:
                flavor_id = o.id
                break
        if flavor_id is None:
            raise exception.FlavorMissing(flavor_id=flavor)
        return flavor_id
