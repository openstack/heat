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

from novaclient import client as nc
from novaclient import shell as novashell

from heat.engine.clients import client_plugin


class NovaClientPlugin(client_plugin.ClientPlugin):

    def _create(self):
        computeshell = novashell.OpenStackComputeShell()
        extensions = computeshell._discover_extensions("1.1")

        endpoint_type = self._get_client_option('nova', 'endpoint_type')
        args = {
            'project_id': self.context.tenant,
            'auth_url': self.context.auth_url,
            'service_type': 'compute',
            'username': None,
            'api_key': None,
            'extensions': extensions,
            'endpoint_type': endpoint_type,
            'http_log_debug': self._get_client_option('nova',
                                                      'http_log_debug'),
            'cacert': self._get_client_option('nova', 'ca_file'),
            'insecure': self._get_client_option('nova', 'insecure')
        }

        client = nc.Client(1.1, **args)

        management_url = self.url_for(service_type='compute',
                                      endpoint_type=endpoint_type)
        client.client.auth_token = self.auth_token
        client.client.management_url = management_url

        return client
