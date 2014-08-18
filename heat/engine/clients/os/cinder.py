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

from cinderclient import client as cc
from cinderclient import exceptions

from heat.engine.clients import client_plugin


class CinderClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option('cinder', 'endpoint_type')
        args = {
            'service_type': 'volume',
            'auth_url': con.auth_url,
            'project_id': con.tenant,
            'username': None,
            'api_key': None,
            'endpoint_type': endpoint_type,
            'http_log_debug': self._get_client_option('cinder',
                                                      'http_log_debug'),
            'cacert': self._get_client_option('cinder', 'ca_file'),
            'insecure': self._get_client_option('cinder', 'insecure')
        }

        client = cc.Client('1', **args)
        management_url = self.url_for(service_type='volume',
                                      endpoint_type=endpoint_type)
        client.client.auth_token = self.auth_token
        client.client.management_url = management_url

        return client

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.OverLimit)
