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

import mock

from heat.tests.common import HeatTestCase
from heat.tests import utils

from .. import clients  # noqa


class TestClient(HeatTestCase):

    def setUp(self):
        super(TestClient, self).setUp()
        self.ctx = utils.dummy_context()
        self.clients = clients.Clients(self.ctx)

    @mock.patch.object(clients.heat_clients, 'Clients')
    @mock.patch.object(clients, 'barbican_client')
    @mock.patch.object(clients, 'auth')
    def test_barbican_passes_in_heat_keystone_client(self, mock_auth,
                                                     mock_barbican_client,
                                                     mock_heat_clients):
        mock_ks = mock.Mock()
        self.clients._keystone = mock.Mock()
        self.clients._keystone.return_value.client = mock_ks
        mock_plugin = mock.Mock()
        mock_auth.KeystoneAuthV2.return_value = mock_plugin

        self.clients.client('barbican')
        mock_auth.KeystoneAuthV2.assert_called_once_with(keystone=mock_ks)
        mock_barbican_client.Client.assert_called_once_with(auth_plugin=
                                                            mock_plugin)
