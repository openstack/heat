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

from zunclient import client as zun_client
from zunclient import exceptions as zc_exc

from heat.engine.clients import client_plugin

CLIENT_NAME = 'zun'


class ZunClientPlugin(client_plugin.ClientPlugin):

    service_types = [CONTAINER] = ['container']

    default_version = '1.12'

    supported_versions = [
        V1_12
    ] = [
        '1.12'
    ]

    def _create(self, version=None):
        if not version:
            version = self.default_version
        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        args = {
            'interface': interface,
            'service_type': self.CONTAINER,
            'session': self.context.keystone_session,
            'region_name': self._get_region_name()
        }

        client = zun_client.Client(version, **args)
        return client

    def is_not_found(self, ex):
        return isinstance(ex, zc_exc.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, zc_exc.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, zc_exc.Conflict)
