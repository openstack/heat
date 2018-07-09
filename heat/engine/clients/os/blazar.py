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

from blazarclient import client as blazar_client
from blazarclient import exception as client_exception

from heat.engine.clients import client_plugin

CLIENT_NAME = 'blazar'


class BlazarClientPlugin(client_plugin.ClientPlugin):

    service_types = [RESERVATION] = ['reservation']

    def _create(self, version=None):
        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        args = {
            'session': self.context.keystone_session,
            'service_type': self.RESERVATION,
            'interface': interface,
            'region_name': self._get_region_name(),
        }

        client = blazar_client.Client(**args)
        return client

    def is_not_found(self, exc):
        # TODO(asmita): Implement exception NotFound in blazarclient
        if isinstance(exc, client_exception.BlazarClientException) \
                and exc.kwargs['code'] == 404:
            return True
        return False

    def has_host(self):
        return True if self.client().host.list() else False

    def create_lease(self, **args):
        return self.client().lease.create(**args)

    def get_lease(self, id):
        return self.client().lease.get(id)

    def create_host(self, **args):
        return self.client().host.create(**args)

    def get_host(self, id):
        return self.client().host.get(id)
