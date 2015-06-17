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

from designateclient import client
from designateclient import exceptions

from heat.engine.clients import client_plugin


class DesignateClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = [exceptions]

    def _create(self):
        args = self._get_client_args(service_name='designate',
                                     service_type='dns')

        return client.client('1', **args)

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)
