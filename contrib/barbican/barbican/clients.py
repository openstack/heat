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

from heat.engine import clients as heat_clients


try:
    from barbicanclient import client as barbican_client
    from barbicanclient.common import auth
except ImportError:
    barbican_client = None
    auth = None


class Clients(heat_clients.OpenStackClients):

    def _barbican(self):
        keystone_client = self.client('keystone').client
        auth_plugin = auth.KeystoneAuthV2(keystone=keystone_client)
        return barbican_client.Client(auth_plugin=auth_plugin)
