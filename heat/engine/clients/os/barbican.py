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
import six

from heat.engine.clients import client_plugin


from barbicanclient import client as barbican_client

CLIENT_NAME = 'barbican'


class BarbicanClientPlugin(client_plugin.ClientPlugin):

    service_types = [KEY_MANAGER] = ['key-manager']

    def _create(self):
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        endpoint = self.url_for(service_type=self.KEY_MANAGER,
                                endpoint_type=endpoint_type)
        self._keystone_session.auth = self.context.auth_plugin
        client = barbican_client.Client(
            session=self._keystone_session, endpoint=endpoint)

        return client

    def is_not_found(self, ex):
        # This is the only exception the client raises
        # Inspecting the message to see if it's a 'Not Found'
        return 'Not Found' in six.text_type(ex)
