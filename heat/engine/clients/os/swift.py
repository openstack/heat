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

from swiftclient import client as sc

from heat.engine.clients import client_plugin


class SwiftClientPlugin(client_plugin.ClientPlugin):

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option('swift', 'endpoint_type')
        args = {
            'auth_version': '2.0',
            'tenant_name': con.tenant,
            'user': con.username,
            'key': None,
            'authurl': None,
            'preauthtoken': self.auth_token,
            'preauthurl': self.url_for(service_type='object-store',
                                       endpoint_type=endpoint_type),
            'os_options': {'endpoint_type': endpoint_type},
            'cacert': self._get_client_option('swift', 'ca_file'),
            'insecure': self._get_client_option('swift', 'insecure')
        }
        return sc.Connection(**args)
