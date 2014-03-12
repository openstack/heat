
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

from heat.engine import clients
from heat.tests.common import HeatTestCase
from heatclient import client as heatclient


class ClientsTest(HeatTestCase):

    def test_clients_chosen_at_module_initilization(self):
        self.assertFalse(hasattr(clients.Clients, 'nova'))
        self.assertTrue(hasattr(clients.Clients('fakecontext'), 'nova'))

    def test_clients_get_heat_url(self):
        con = mock.Mock()
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        obj = clients.Clients(con)
        obj._get_client_option = mock.Mock()
        obj._get_client_option.return_value = None
        self.assertIsNone(obj._get_heat_url())
        heat_url = "http://0.0.0.0:8004/v1/%(tenant_id)s"
        obj._get_client_option.return_value = heat_url
        tenant_id = "b363706f891f48019483f8bd6503c54b"
        result = heat_url % {"tenant_id": tenant_id}
        self.assertEqual(result, obj._get_heat_url())
        obj._get_client_option.return_value = result
        self.assertEqual(result, obj._get_heat_url())

    @mock.patch.object(heatclient, 'Client')
    def test_clients_heat(self, mock_call):
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        con.auth_token = "3bcc3d3a03f44e3d8377f9247b0ad155"
        obj = clients.Clients(con)
        obj._get_heat_url = mock.Mock(name="_get_heat_url")
        obj._get_heat_url.return_value = None
        obj.url_for = mock.Mock(name="url_for")
        obj.url_for.return_value = "url_from_keystone"
        obj.heat()
        self.assertEqual('url_from_keystone', mock_call.call_args[0][1])
        obj._get_heat_url.return_value = "url_from_config"
        obj._heat = None
        obj.heat()
        self.assertEqual('url_from_config', mock_call.call_args[0][1])
