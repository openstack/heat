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

from heat.engine.clients import client_plugin
from heat.engine import constraints

from senlinclient import client
from senlinclient.common import exc

CLIENT_NAME = 'senlin'


class SenlinClientPlugin(client_plugin.ClientPlugin):

    service_types = [CLUSTERING] = ['clustering']
    VERSION = '1'

    def _create(self):
        con = self.context
        args = {
            'auth_url': con.auth_url,
            'project_id': con.tenant_id,
            'token': self.auth_token,
        }
        return client.Client(self.VERSION, **args)

    def is_not_found(self, ex):
        return isinstance(ex, exc.HTTPNotFound)


class ProfileConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exc.HTTPNotFound,)

    def validate_with_client(self, client, profile):
        client.client(CLIENT_NAME).get_profile(profile)
