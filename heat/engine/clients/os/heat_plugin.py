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

from heatclient import client as hc
from heatclient import exc

from heat.engine.clients import client_plugin


class HeatClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exc

    def _create(self):
        args = {
            'auth_url': self.context.auth_url,
            'token': self.auth_token,
            'username': None,
            'password': None,
            'ca_file': self._get_client_option('heat', 'ca_file'),
            'cert_file': self._get_client_option('heat', 'cert_file'),
            'key_file': self._get_client_option('heat', 'key_file'),
            'insecure': self._get_client_option('heat', 'insecure')
        }

        endpoint = self.get_heat_url()
        if self._get_client_option('heat', 'url'):
            # assume that the heat API URL is manually configured because
            # it is not in the keystone catalog, so include the credentials
            # for the standalone auth_password middleware
            args['username'] = self.context.username
            args['password'] = self.context.password
            del(args['token'])

        return hc.Client('1', endpoint, **args)

    def is_not_found(self, ex):
        return isinstance(ex, exc.HTTPNotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exc.HTTPOverLimit)

    def is_conflict(self, ex):
        return isinstance(ex, exc.HTTPConflict)

    def get_heat_url(self):
        heat_url = self._get_client_option('heat', 'url')
        if heat_url:
            tenant_id = self.context.tenant_id
            heat_url = heat_url % {'tenant_id': tenant_id}
        else:
            endpoint_type = self._get_client_option('heat', 'endpoint_type')
            heat_url = self.url_for(service_type='orchestration',
                                    endpoint_type=endpoint_type)
        return heat_url
