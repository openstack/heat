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

from ceilometerclient import exc as ceil_exc
from ceilometerclient.openstack.common.apiclient import exceptions as c_a_exc
from cinderclient import exceptions as cinder_exc
from glanceclient import exc as glance_exc
from heatclient import exc as heat_exc
from keystoneclient import exceptions as keystone_exc
from neutronclient.common import exceptions as neutron_exc
from swiftclient import exceptions as swift_exc
from troveclient.client import exceptions as trove_exc

from heatclient import client as heatclient
import mock
from oslo.config import cfg
from testtools.testcase import skip

from heat.engine import clients
from heat.engine.clients import client_plugin
from heat.tests.common import HeatTestCase
from heat.tests.v1_1 import fakes


class ClientsTest(HeatTestCase):

    def test_clients_get_heat_url(self):
        con = mock.Mock()
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        c = clients.Clients(con)
        con.clients = c

        obj = c.client_plugin('heat')
        obj._get_client_option = mock.Mock()
        obj._get_client_option.return_value = None
        obj.url_for = mock.Mock(name="url_for")
        obj.url_for.return_value = "url_from_keystone"
        self.assertEqual("url_from_keystone", obj.get_heat_url())
        heat_url = "http://0.0.0.0:8004/v1/%(tenant_id)s"
        obj._get_client_option.return_value = heat_url
        tenant_id = "b363706f891f48019483f8bd6503c54b"
        result = heat_url % {"tenant_id": tenant_id}
        self.assertEqual(result, obj.get_heat_url())
        obj._get_client_option.return_value = result
        self.assertEqual(result, obj.get_heat_url())

    @mock.patch.object(heatclient, 'Client')
    def test_clients_heat(self, mock_call):
        self.stub_keystoneclient()
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        con.auth_token = "3bcc3d3a03f44e3d8377f9247b0ad155"
        c = clients.Clients(con)
        con.clients = c

        obj = c.client_plugin('heat')
        obj.url_for = mock.Mock(name="url_for")
        obj.url_for.return_value = "url_from_keystone"
        obj.client()
        self.assertEqual('url_from_keystone', obj.get_heat_url())

    @mock.patch.object(heatclient, 'Client')
    def test_clients_heat_no_auth_token(self, mock_call):
        self.stub_keystoneclient(auth_token='anewtoken')
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        con.auth_token = None
        c = clients.Clients(con)
        con.clients = c

        obj = c.client_plugin('heat')
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
        con.clients = c

        obj = c.client_plugin('heat')
        obj.get_heat_url = mock.Mock(name="get_heat_url")
        obj.get_heat_url.return_value = None
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
        con.clients = obj

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
        con.clients = c

        plugin = FooClientsPlugin(con)

        cfg.CONF.set_override('ca_file', '/tmp/bar',
                              group='clients_heat')
        cfg.CONF.set_override('ca_file', '/tmp/foo',
                              group='clients')
        cfg.CONF.set_override('endpoint_type', 'internalURL',
                              group='clients')

        # check heat group
        self.assertEqual('/tmp/bar',
                         plugin._get_client_option('heat', 'ca_file'))

        # check fallback clients group for known client
        self.assertEqual('internalURL',
                         plugin._get_client_option('glance', 'endpoint_type'))

        # check fallback clients group for unknown client foo
        self.assertEqual('/tmp/foo',
                         plugin._get_client_option('foo', 'ca_file'))

    def test_auth_token(self):
        con = mock.Mock()
        con.auth_token = "1234"

        c = clients.Clients(con)
        con.clients = c

        c.client = mock.Mock(name="client")
        mock_keystone = mock.Mock()
        c.client.return_value = mock_keystone
        mock_keystone.auth_token = '5678'
        plugin = FooClientsPlugin(con)

        # assert token is from keystone rather than context
        # even though both are set
        self.assertEqual('5678', plugin.auth_token)
        c.client.assert_called_with('keystone')

    def test_url_for(self):
        con = mock.Mock()
        con.auth_token = "1234"

        c = clients.Clients(con)
        con.clients = c

        c.client = mock.Mock(name="client")
        mock_keystone = mock.Mock()
        c.client.return_value = mock_keystone
        mock_keystone.url_for.return_value = 'http://192.0.2.1/foo'
        plugin = FooClientsPlugin(con)

        self.assertEqual('http://192.0.2.1/foo',
                         plugin.url_for(service_type='foo'))
        c.client.assert_called_with('keystone')

    def test_abstract_create(self):
        con = mock.Mock()
        c = clients.Clients(con)
        con.clients = c

        self.assertRaises(TypeError, client_plugin.ClientPlugin, c)


class TestClientPluginsInitialise(HeatTestCase):

    @skip('skipped until keystone can read context auth_ref')
    def test_create_all_clients(self):
        con = mock.Mock()
        con.auth_url = "http://auth.example.com:5000/v2.0"
        con.tenant_id = "b363706f891f48019483f8bd6503c54b"
        con.auth_token = "3bcc3d3a03f44e3d8377f9247b0ad155"
        c = clients.Clients(con)
        con.clients = c

        for plugin_name in clients._mgr.names():
            self.assertTrue(clients.has_client(plugin_name))
            c.client(plugin_name)

    def test_create_all_client_plugins(self):
        plugin_types = clients._mgr.names()
        self.assertIsNotNone(plugin_types)

        con = mock.Mock()
        c = clients.Clients(con)
        con.clients = c

        for plugin_name in plugin_types:
            plugin = c.client_plugin(plugin_name)
            self.assertIsNotNone(plugin)
            self.assertEqual(c, plugin.clients)
            self.assertEqual(con, plugin.context)
            self.assertIsNone(plugin._client)
            self.assertTrue(clients.has_client(plugin_name))


class TestIsNotFound(HeatTestCase):

    scenarios = [
        ('ceilometer_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='ceilometer',
            exception=lambda: ceil_exc.HTTPNotFound(details='gone'),
        )),
        ('ceilometer_not_found_apiclient', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='ceilometer',
            exception=lambda: c_a_exc.NotFound(details='gone'),
        )),
        ('ceilometer_exception', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=False,
            plugin='ceilometer',
            exception=lambda: Exception()
        )),
        ('ceilometer_overlimit', dict(
            is_not_found=False,
            is_over_limit=True,
            is_client_exception=True,
            plugin='ceilometer',
            exception=lambda: ceil_exc.HTTPOverLimit(details='over'),
        )),
        ('cinder_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='cinder',
            exception=lambda: cinder_exc.NotFound(code=404),
        )),
        ('cinder_exception', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=False,
            plugin='cinder',
            exception=lambda: Exception()
        )),
        ('cinder_overlimit', dict(
            is_not_found=False,
            is_over_limit=True,
            is_client_exception=True,
            plugin='cinder',
            exception=lambda: cinder_exc.OverLimit(code=413),
        )),
        ('glance_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='glance',
            exception=lambda: glance_exc.HTTPNotFound(details='gone'),
        )),
        ('glance_exception', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=False,
            plugin='glance',
            exception=lambda: Exception()
        )),
        ('glance_overlimit', dict(
            is_not_found=False,
            is_over_limit=True,
            is_client_exception=True,
            plugin='glance',
            exception=lambda: glance_exc.HTTPOverLimit(details='over'),
        )),
        ('heat_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='heat',
            exception=lambda: heat_exc.HTTPNotFound(message='gone'),
        )),
        ('heat_exception', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=False,
            plugin='heat',
            exception=lambda: Exception()
        )),
        ('heat_overlimit', dict(
            is_not_found=False,
            is_over_limit=True,
            is_client_exception=True,
            plugin='heat',
            exception=lambda: heat_exc.HTTPOverLimit(message='over'),
        )),
        ('keystone_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='keystone',
            exception=lambda: keystone_exc.NotFound(details='gone'),
        )),
        ('keystone_exception', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=False,
            plugin='keystone',
            exception=lambda: Exception()
        )),
        ('keystone_overlimit', dict(
            is_not_found=False,
            is_over_limit=True,
            is_client_exception=True,
            plugin='keystone',
            exception=lambda: keystone_exc.RequestEntityTooLarge(
                details='over'),
        )),
        ('neutron_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='neutron',
            exception=lambda: neutron_exc.NotFound,
        )),
        ('neutron_network_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='neutron',
            exception=lambda: neutron_exc.NetworkNotFoundClient(),
        )),
        ('neutron_port_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='neutron',
            exception=lambda: neutron_exc.PortNotFoundClient(),
        )),
        ('neutron_status_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='neutron',
            exception=lambda: neutron_exc.NeutronClientException(
                status_code=404),
        )),
        ('neutron_exception', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=False,
            plugin='neutron',
            exception=lambda: Exception()
        )),
        ('neutron_overlimit', dict(
            is_not_found=False,
            is_over_limit=True,
            is_client_exception=True,
            plugin='neutron',
            exception=lambda: neutron_exc.NeutronClientException(
                status_code=413),
        )),
        ('nova_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            is_unprocessable_entity=False,
            plugin='nova',
            exception=lambda: fakes.fake_exception(),
        )),
        ('nova_exception', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=False,
            is_unprocessable_entity=False,
            plugin='nova',
            exception=lambda: Exception()
        )),
        ('nova_overlimit', dict(
            is_not_found=False,
            is_over_limit=True,
            is_client_exception=True,
            is_unprocessable_entity=False,
            plugin='nova',
            exception=lambda: fakes.fake_exception(413),
        )),
        ('nova_unprocessable_entity', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=True,
            is_unprocessable_entity=True,
            plugin='nova',
            exception=lambda: fakes.fake_exception(422),
        )),
        ('swift_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='swift',
            exception=lambda: swift_exc.ClientException(
                msg='gone', http_status=404),
        )),
        ('swift_exception', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=False,
            plugin='swift',
            exception=lambda: Exception()
        )),
        ('swift_overlimit', dict(
            is_not_found=False,
            is_over_limit=True,
            is_client_exception=True,
            plugin='swift',
            exception=lambda: swift_exc.ClientException(
                msg='ouch', http_status=413),
        )),
        ('trove_not_found', dict(
            is_not_found=True,
            is_over_limit=False,
            is_client_exception=True,
            plugin='trove',
            exception=lambda: trove_exc.NotFound(message='gone'),
        )),
        ('trove_exception', dict(
            is_not_found=False,
            is_over_limit=False,
            is_client_exception=False,
            plugin='trove',
            exception=lambda: Exception()
        )),
        ('trove_overlimit', dict(
            is_not_found=False,
            is_over_limit=True,
            is_client_exception=True,
            plugin='trove',
            exception=lambda: trove_exc.RequestEntityTooLarge(
                message='over'),
        )),
    ]

    def test_is_not_found(self):
        con = mock.Mock()
        c = clients.Clients(con)
        client_plugin = c.client_plugin(self.plugin)
        try:
            raise self.exception()
        except Exception as e:
            if self.is_not_found != client_plugin.is_not_found(e):
                raise

    def test_ignore_not_found(self):
        con = mock.Mock()
        c = clients.Clients(con)
        client_plugin = c.client_plugin(self.plugin)
        try:
            exp = self.exception()
            exp_class = exp.__class__
            raise exp
        except Exception as e:
            if self.is_not_found:
                client_plugin.ignore_not_found(e)
            else:
                self.assertRaises(exp_class,
                                  client_plugin.ignore_not_found,
                                  e)

    def test_is_over_limit(self):
        con = mock.Mock()
        c = clients.Clients(con)
        client_plugin = c.client_plugin(self.plugin)
        try:
            raise self.exception()
        except Exception as e:
            if self.is_over_limit != client_plugin.is_over_limit(e):
                raise

    def test_is_client_exception(self):
        con = mock.Mock()
        c = clients.Clients(con)
        client_plugin = c.client_plugin(self.plugin)
        try:
            raise self.exception()
        except Exception as e:
            ice = self.is_client_exception
            actual = client_plugin.is_client_exception(e)
            if ice != actual:
                raise

    def test_is_unprocessable_entity(self):
        con = mock.Mock()
        c = clients.Clients(con)
        # only 'nova' client plugin need to check this exception
        if self.plugin == 'nova':
            client_plugin = c.client_plugin(self.plugin)
            try:
                raise self.exception()
            except Exception as e:
                iue = self.is_unprocessable_entity
                if iue != client_plugin.is_unprocessable_entity(e):
                    raise
