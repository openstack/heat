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

from heatclient import client as heatclient
import mock
from oslo.config import cfg
from testtools.testcase import skip

from heat.engine import clients
from heat.engine.clients import client_plugin
from heat.tests.common import HeatTestCase


class ClientsTest(HeatTestCase):

    def test_clients_get_heat_url(self):
        con = mock.Mock()
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        c = clients.Clients(con)
        obj = c.client_plugin('heat')
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
        self.stub_keystoneclient()
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        con.auth_token = "3bcc3d3a03f44e3d8377f9247b0ad155"
        c = clients.Clients(con)
        obj = c.client_plugin('heat')
        obj._get_heat_url = mock.Mock(name="_get_heat_url")
        obj._get_heat_url.return_value = None
        obj.url_for = mock.Mock(name="url_for")
        obj.url_for.return_value = "url_from_keystone"
        obj.client()
        self.assertEqual('url_from_keystone', mock_call.call_args[0][1])
        obj._get_heat_url.return_value = "url_from_config"
        obj._client = None
        obj.client()
        self.assertEqual('url_from_config', mock_call.call_args[0][1])

    @mock.patch.object(heatclient, 'Client')
    def test_clients_heat_no_auth_token(self, mock_call):
        self.stub_keystoneclient(auth_token='anewtoken')
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        con.auth_token = None
        c = clients.Clients(con)
        obj = c.client_plugin('heat')
        obj._get_heat_url = mock.Mock(name="_get_heat_url")
        obj._get_heat_url.return_value = None
        obj.url_for = mock.Mock(name="url_for")
        obj.url_for.return_value = "url_from_keystone"
        self.assertEqual('anewtoken', c.client('keystone').auth_token)

    @mock.patch.object(heatclient, 'Client')
    def test_clients_heat_cached(self, mock_call):
        self.stub_keystoneclient()
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        con.auth_token = "3bcc3d3a03f44e3d8377f9247b0ad155"
        c = clients.Clients(con)
        obj = c.client_plugin('heat')
        obj._get_heat_url = mock.Mock(name="_get_heat_url")
        obj._get_heat_url.return_value = None
        obj.url_for = mock.Mock(name="url_for")
        obj.url_for.return_value = "url_from_keystone"
        obj._client = None
        heat = obj.client()
        heat_cached = obj.client()
        self.assertEqual(heat, heat_cached)

    def test_clients_auth_token_update(self):
        fkc = self.stub_keystoneclient(auth_token='token1')
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.trust_id = "b363706f891f48019483f8bd6503c54b"
        con.username = 'heat'
        con.password = 'verysecret'
        con.auth_token = None
        obj = clients.Clients(con)
        self.assertIsNotNone(obj.client('heat'))
        self.assertEqual('token1', obj.auth_token)
        fkc.auth_token = 'token2'
        self.assertEqual('token2', obj.auth_token)


class FooClientsPlugin(client_plugin.ClientPlugin):

    def _create(self):
        pass


class ClientPluginTest(HeatTestCase):

    def test_get_client_option(self):
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        con.auth_token = "3bcc3d3a03f44e3d8377f9247b0ad155"
        c = clients.Clients(con)
        plugin = FooClientsPlugin(c)

        cfg.CONF.set_override('ca_file', '/tmp/bar',
                              group='clients_heat')
        cfg.CONF.set_override('ca_file', '/tmp/foo',
                              group='clients')

        # check heat group
        self.assertEqual('/tmp/bar',
                         plugin._get_client_option('heat', 'ca_file'))

        # check fallback clients group for unknown client foo
        self.assertEqual('/tmp/foo',
                         plugin._get_client_option('foo', 'ca_file'))

    def test_auth_token(self):
        con = mock.Mock()
        con.auth_token = "1234"

        c = clients.Clients(con)
        c.client = mock.Mock(name="client")
        mock_keystone = mock.Mock()
        c.client.return_value = mock_keystone
        mock_keystone.auth_token = '5678'
        plugin = FooClientsPlugin(c)

        # assert token is from keystone rather than context
        # even though both are set
        self.assertEqual('5678', plugin.auth_token)
        c.client.assert_called_with('keystone')

    def test_url_for(self):
        con = mock.Mock()
        con.auth_token = "1234"

        c = clients.Clients(con)
        c.client = mock.Mock(name="client")
        mock_keystone = mock.Mock()
        c.client.return_value = mock_keystone
        mock_keystone.url_for.return_value = 'http://192.0.2.1/foo'
        plugin = FooClientsPlugin(c)

        self.assertEqual('http://192.0.2.1/foo',
                         plugin.url_for(service_type='foo'))
        c.client.assert_called_with('keystone')

    def test_abstract_create(self):
        con = mock.Mock()
        c = clients.Clients(con)
        self.assertRaises(TypeError, client_plugin.ClientPlugin, c)


class TestClientPluginsInitialise(HeatTestCase):

    @skip('skipped until keystone can read context auth_ref')
    def test_create_all_clients(self):
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        con.auth_token = "3bcc3d3a03f44e3d8377f9247b0ad155"
        c = clients.Clients(con)

        for plugin_name in clients._mgr.names():
            self.assertTrue(clients.has_client(plugin_name))
            c.client(plugin_name)

    def test_create_all_client_plugins(self):
        plugin_types = clients._mgr.names()
        self.assertIsNotNone(plugin_types)

        con = mock.Mock()
        c = clients.Clients(con)

        for plugin_name in plugin_types:
            plugin = c.client_plugin(plugin_name)
            self.assertIsNotNone(plugin)
            self.assertEqual(c, plugin.clients)
            self.assertEqual(con, plugin.context)
            self.assertIsNone(plugin._client)
