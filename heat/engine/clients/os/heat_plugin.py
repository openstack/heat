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

from heat.engine.clients import client_plugin


class HeatClientPlugin(client_plugin.ClientPlugin):

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option('heat', 'endpoint_type')
        args = {
            'auth_url': con.auth_url,
            'token': self.auth_token,
            'username': None,
            'password': None,
            'ca_file': self._get_client_option('heat', 'ca_file'),
            'cert_file': self._get_client_option('heat', 'cert_file'),
            'key_file': self._get_client_option('heat', 'key_file'),
            'insecure': self._get_client_option('heat', 'insecure')
        }

        endpoint = self._get_heat_url()
        if not endpoint:
            endpoint = self.url_for(service_type='orchestration',
                                    endpoint_type=endpoint_type)
        return hc.Client('1', endpoint, **args)

    def _get_heat_url(self):
        heat_url = self._get_client_option('heat', 'url')
        if heat_url:
            tenant_id = self.context.tenant_id
            heat_url = heat_url % {'tenant_id': tenant_id}
        return heat_url
