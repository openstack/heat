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

from aodhclient import client as ac
from aodhclient import exceptions

from heat.engine.clients import client_plugin

CLIENT_NAME = 'aodh'


class AodhClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [ALARMING] = ['alarming']

    supported_versions = [V2] = ['2']

    default_version = V2

    def _create(self, version=None):
        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')

        return ac.Client(
            version,
            session=self.context.keystone_session,
            interface=interface,
            service_type=self.ALARMING,
            region_name=self._get_region_name())

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.OverLimit)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)
