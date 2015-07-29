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

from magnumclient.openstack.common.apiclient import exceptions
from magnumclient.v1 import client as magnum_client

from heat.engine.clients import client_plugin


class MagnumClientPlugin(client_plugin.ClientPlugin):

    service_types = [CONTAINER] = ['container']

    def _create(self):
        endpoint_type = self._get_client_option('magnum', 'endpoint_type')
        endpoint = self.url_for(service_type=self.CONTAINER,
                                endpoint_type=endpoint_type)

        args = {
            'magnum_url': endpoint,
            'input_auth_token': self.auth_token
        }
        client = magnum_client.Client(**args)
        return client

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)
