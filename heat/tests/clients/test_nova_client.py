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
"""Tests for :module:'heat.engine.clients.os.nova'."""

import collections
import uuid

import mock
from novaclient import client as nc
from novaclient import exceptions as nova_exceptions
from oslo_config import cfg
from oslo_serialization import jsonutils as json
import requests
import six

from heat.common import exception
from heat.engine.clients.os import nova
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


class NovaClientPluginTestCase(common.HeatTestCase):
    def setUp(self):
        super(NovaClientPluginTestCase, self).setUp()
        self.nova_client = mock.MagicMock()
        con = utils.dummy_context()
        c = con.clients
        self.nova_plugin = c.client_plugin('nova')
        self.nova_plugin.client = lambda: self.nova_client


class NovaClientPluginTest(NovaClientPluginTestCase):
    """Basic tests for :module:'heat.engine.clients.os.nova'."""

    def test_create(self):
        context = utils.dummy_context()
        ext_mock = self.patchobject(nc, 'discover_extensions')
        plugin = context.clients.client_plugin('nova')
        plugin.max_microversion = '2.53'
        client = plugin.client()
        ext_mock.assert_called_once_with('2.53')
        self.assertIsNotNone(client.servers)

    def test_v2_26_create(self):
        ctxt = utils.dummy_context()
        ext_mock = self.patchobject(nc, 'discover_extensions')
        self.patchobject(nc, 'Client', return_value=mock.Mock())

        plugin = ctxt.clients.client_plugin('nova')
        plugin.max_microversion = '2.53'
        plugin.client(version='2.26')

        ext_mock.assert_called_once_with('2.26')

    def test_v2_26_create_failed(self):
        ctxt = utils.dummy_context()
        self.patchobject(nc, 'discover_extensions')
        plugin = ctxt.clients.client_plugin('nova')
        plugin.max_microversion = '2.23'
        client_stub = mock.Mock()
        self.patchobject(nc, 'Client', return_value=client_stub)

        self.assertRaises(exception.InvalidServiceVersion,
                          plugin.client, '2.26')

    def test_get_ip(self):
        my_image = mock.MagicMock()
        my_image.addresses = {
            'public': [{'version': 4,
                        'addr': '4.5.6.7'},
                       {'version': 6,
                        'addr': '2401:1801:7800:0101:c058:dd33:ff18:04e6'}],
            'private': [{'version': 4,
                         'addr': '10.13.12.13'}]}

        expected = '4.5.6.7'
        observed = self.nova_plugin.get_ip(my_image, 'public', 4)
        self.assertEqual(expected, observed)

        expected = '10.13.12.13'
        observed = self.nova_plugin.get_ip(my_image, 'private', 4)
        self.assertEqual(expected, observed)

        expected = '2401:1801:7800:0101:c058:dd33:ff18:04e6'
        observed = self.nova_plugin.get_ip(my_image, 'public', 6)
        self.assertEqual(expected, observed)

    def test_find_flavor_by_name_or_id(self):
        """Tests the find_flavor_by_name_or_id function."""
        flav_id = str(uuid.uuid4())
        flav_name = 'X-Large'
        my_flavor = mock.MagicMock()
        my_flavor.name = flav_name
        my_flavor.id = flav_id

        self.nova_client.flavors.get.side_effect = [
            my_flavor,
            nova_exceptions.NotFound(''),
            nova_exceptions.NotFound(''),
        ]
        self.nova_client.flavors.find.side_effect = [
            my_flavor,
            nova_exceptions.NotFound(''),
        ]
        self.assertEqual(flav_id,
                         self.nova_plugin.find_flavor_by_name_or_id(flav_id))
        self.assertEqual(flav_id,
                         self.nova_plugin.find_flavor_by_name_or_id(flav_name))
        self.assertRaises(nova_exceptions.ClientException,
                          self.nova_plugin.find_flavor_by_name_or_id,
                          'noflavor')
        self.assertEqual(3, self.nova_client.flavors.get.call_count)
        self.assertEqual(2, self.nova_client.flavors.find.call_count)

    def test_get_host(self):
        """Tests the get_host function."""
        my_host_name = 'myhost'
        my_host = mock.MagicMock()
        my_host.host_name = my_host_name
        my_host.service = 'compute'

        wrong_host = mock.MagicMock()
        wrong_host.host_name = 'wrong_host'
        wrong_host.service = 'compute'
        self.nova_client.hosts.list.side_effect = [
            [my_host],
            [wrong_host],
            exception.EntityNotFound(entity='Host', name='nohost')
        ]
        self.assertEqual(my_host, self.nova_plugin.get_host(my_host_name))
        self.assertRaises(exception.EntityNotFound,
                          self.nova_plugin.get_host, my_host_name)
        self.assertRaises(exception.EntityNotFound,
                          self.nova_plugin.get_host, 'nohost')
        self.assertEqual(3, self.nova_client.hosts.list.call_count)
        calls = [mock.call(), mock.call(), mock.call()]
        self.assertEqual(calls,
                         self.nova_client.hosts.list.call_args_list)

    def test_get_keypair(self):
        """Tests the get_keypair function."""
        my_pub_key = 'a cool public key string'
        my_key_name = 'mykey'
        my_key = mock.MagicMock()
        my_key.public_key = my_pub_key
        my_key.name = my_key_name
        self.nova_client.keypairs.get.side_effect = [
            my_key, nova_exceptions.NotFound(404)]
        self.assertEqual(my_key, self.nova_plugin.get_keypair(my_key_name))
        self.assertRaises(exception.EntityNotFound,
                          self.nova_plugin.get_keypair, 'notakey')
        calls = [mock.call(my_key_name),
                 mock.call('notakey')]
        self.nova_client.keypairs.get.assert_has_calls(calls)

    def test_get_server(self):
        """Tests the get_server function."""
        my_server = mock.MagicMock()
        self.nova_client.servers.get.side_effect = [
            my_server, nova_exceptions.NotFound(404)]
        self.assertEqual(my_server, self.nova_plugin.get_server('my_server'))
        self.assertRaises(exception.EntityNotFound,
                          self.nova_plugin.get_server, 'idontexist')
        calls = [mock.call('my_server'),
                 mock.call('idontexist')]
        self.nova_client.servers.get.assert_has_calls(calls)

    def test_get_status(self):
        server = mock.Mock()
        server.status = 'ACTIVE'

        observed = self.nova_plugin.get_status(server)
        self.assertEqual('ACTIVE', observed)

        server.status = 'ACTIVE(STATUS)'
        observed = self.nova_plugin.get_status(server)
        self.assertEqual('ACTIVE', observed)

    def _absolute_limits(self):
        max_personality = mock.Mock()
        max_personality.name = 'maxPersonality'
        max_personality.value = 5
        max_personality_size = mock.Mock()
        max_personality_size.name = 'maxPersonalitySize'
        max_personality_size.value = 10240
        max_server_meta = mock.Mock()
        max_server_meta.name = 'maxServerMeta'
        max_server_meta.value = 3
        yield max_personality
        yield max_personality_size
        yield max_server_meta

    def test_absolute_limits_success(self):
        limits = mock.Mock()
        limits.absolute = self._absolute_limits()
        self.nova_client.limits.get.return_value = limits
        self.nova_plugin.absolute_limits()

    def test_absolute_limits_retry(self):
        limits = mock.Mock()
        limits.absolute = self._absolute_limits()
        self.nova_client.limits.get.side_effect = [
            requests.ConnectionError, requests.ConnectionError,
            limits]
        self.nova_plugin.absolute_limits()
        self.assertEqual(3, self.nova_client.limits.get.call_count)

    def test_absolute_limits_failure(self):
        limits = mock.Mock()
        limits.absolute = self._absolute_limits()
        self.nova_client.limits.get.side_effect = [
            requests.ConnectionError, requests.ConnectionError,
            requests.ConnectionError]
        self.assertRaises(requests.ConnectionError,
                          self.nova_plugin.absolute_limits)


class NovaClientPluginRefreshServerTest(NovaClientPluginTestCase):
    msg = ("ClientException: The server has either erred or is "
           "incapable of performing the requested operation.")

    scenarios = [
        ('successful_refresh', dict(
            value=None,
            e_raise=False)),
        ('overlimit_error', dict(
            value=nova_exceptions.OverLimit(413, "limit reached"),
            e_raise=False)),
        ('500_error', dict(
            value=nova_exceptions.ClientException(500, msg),
            e_raise=False)),
        ('503_error', dict(
            value=nova_exceptions.ClientException(503, msg),
            e_raise=False)),
        ('unhandled_exception', dict(
            value=nova_exceptions.ClientException(501, msg),
            e_raise=True)),
    ]

    def test_refresh(self):
        server = mock.MagicMock()
        server.get.side_effect = [self.value]
        if self.e_raise:
            self.assertRaises(nova_exceptions.ClientException,
                              self.nova_plugin.refresh_server, server)
        else:
            self.assertIsNone(self.nova_plugin.refresh_server(server))
        server.get.assert_called_once_with()


class NovaClientPluginFetchServerTest(NovaClientPluginTestCase):

    server = mock.Mock()
    # set explicitly as id and name has internal meaning in mock.Mock
    server.id = '1234'
    server.name = 'test_fetch_server'
    msg = ("ClientException: The server has either erred or is "
           "incapable of performing the requested operation.")
    scenarios = [
        ('successful_refresh', dict(
            value=server,
            e_raise=False)),
        ('overlimit_error', dict(
            value=nova_exceptions.OverLimit(413, "limit reached"),
            e_raise=False)),
        ('500_error', dict(
            value=nova_exceptions.ClientException(500, msg),
            e_raise=False)),
        ('503_error', dict(
            value=nova_exceptions.ClientException(503, msg),
            e_raise=False)),
        ('unhandled_exception', dict(
            value=nova_exceptions.ClientException(501, msg),
            e_raise=True)),
    ]

    def test_fetch_server(self):
        self.nova_client.servers.get.side_effect = [self.value]
        if self.e_raise:
            self.assertRaises(nova_exceptions.ClientException,
                              self.nova_plugin.fetch_server, self.server.id)
        elif isinstance(self.value, mock.Mock):
            self.assertEqual(self.value,
                             self.nova_plugin.fetch_server(self.server.id))
        else:
            self.assertIsNone(self.nova_plugin.fetch_server(self.server.id))

        self.nova_client.servers.get.assert_called_once_with(self.server.id)


class NovaClientPluginCheckActiveTest(NovaClientPluginTestCase):

    scenarios = [
        ('active', dict(
            status='ACTIVE',
            e_raise=False)),
        ('deferred', dict(
            status='BUILD',
            e_raise=False)),
        ('error', dict(
            status='ERROR',
            e_raise=exception.ResourceInError)),
        ('unknown', dict(
            status='VIKINGS!',
            e_raise=exception.ResourceUnknownStatus))
    ]

    def setUp(self):
        super(NovaClientPluginCheckActiveTest, self).setUp()
        self.server = mock.Mock()
        self.server.id = '1234'
        self.server.status = self.status
        self.r_mock = self.patchobject(self.nova_plugin, 'refresh_server',
                                       return_value=None)
        self.f_mock = self.patchobject(self.nova_plugin, 'fetch_server',
                                       return_value=self.server)

    def test_check_active_with_object(self):
        if self.e_raise:
            self.assertRaises(self.e_raise,
                              self.nova_plugin._check_active, self.server)
            self.r_mock.assert_called_once_with(self.server)
        elif self.status in self.nova_plugin.deferred_server_statuses:
            self.assertFalse(self.nova_plugin._check_active(self.server))
            self.r_mock.assert_called_once_with(self.server)
        else:
            self.assertTrue(self.nova_plugin._check_active(self.server))
            self.assertEqual(0, self.r_mock.call_count)
        self.assertEqual(0, self.f_mock.call_count)

    def test_check_active_with_string(self):
        if self.e_raise:
            self.assertRaises(self.e_raise,
                              self.nova_plugin._check_active, self.server.id)
        elif self.status in self.nova_plugin.deferred_server_statuses:
            self.assertFalse(self.nova_plugin._check_active(self.server.id))
        else:
            self.assertTrue(self.nova_plugin._check_active(self.server.id))

        self.f_mock.assert_called_once_with(self.server.id)
        self.assertEqual(0, self.r_mock.call_count)

    def test_check_active_with_string_unavailable(self):
        self.f_mock.return_value = None
        self.assertFalse(self.nova_plugin._check_active(self.server.id))
        self.f_mock.assert_called_once_with(self.server.id)
        self.assertEqual(0, self.r_mock.call_count)


class NovaClientPluginUserdataTest(NovaClientPluginTestCase):

    def test_build_userdata(self):
        """Tests the build_userdata function."""
        cfg.CONF.set_override('heat_metadata_server_url',
                              'http://server.test:123')
        cfg.CONF.set_override('instance_connection_is_secure', False)
        cfg.CONF.set_override(
            'instance_connection_https_validate_certificates', False)
        data = self.nova_plugin.build_userdata({})
        self.assertIn("Content-Type: text/cloud-config;", data)
        self.assertIn("Content-Type: text/cloud-boothook;", data)
        self.assertIn("Content-Type: text/part-handler;", data)
        self.assertIn("Content-Type: text/x-cfninitdata;", data)
        self.assertIn("Content-Type: text/x-shellscript;", data)
        self.assertIn("http://server.test:123", data)
        self.assertIn("[Boto]", data)

    def test_build_userdata_without_instance_user(self):
        """Don't add a custom instance user when not requested."""
        cfg.CONF.set_override('heat_metadata_server_url',
                              'http://server.test:123')
        data = self.nova_plugin.build_userdata({}, instance_user=None)
        self.assertNotIn('user: ', data)
        self.assertNotIn('useradd', data)
        self.assertNotIn('ec2-user', data)

    def test_build_userdata_with_instance_user(self):
        """Add a custom instance user."""
        cfg.CONF.set_override('heat_metadata_server_url',
                              'http://server.test:123')
        data = self.nova_plugin.build_userdata({}, instance_user='ec2-user')
        self.assertIn('user: ', data)
        self.assertIn('useradd', data)
        self.assertIn('ec2-user', data)


class NovaClientPluginMetadataTest(NovaClientPluginTestCase):

    def test_serialize_string(self):
        original = {'test_key': 'simple string value'}
        self.assertEqual(original, self.nova_plugin.meta_serialize(original))

    def test_serialize_int(self):
        original = {'test_key': 123}
        expected = {'test_key': '123'}
        self.assertEqual(expected, self.nova_plugin.meta_serialize(original))

    def test_serialize_list(self):
        original = {'test_key': [1, 2, 3]}
        expected = {'test_key': '[1, 2, 3]'}
        self.assertEqual(expected, self.nova_plugin.meta_serialize(original))

    def test_serialize_dict(self):
        original = collections.OrderedDict([
            ('test_key', collections.OrderedDict([
                ('a', 'b'),
                ('c', 'd'),
            ]))
        ])
        expected = {'test_key': '{"a": "b", "c": "d"}'}
        actual = self.nova_plugin.meta_serialize(original)
        self.assertEqual(json.loads(expected['test_key']),
                         json.loads(actual['test_key']))

    def test_serialize_none(self):
        original = {'test_key': None}
        expected = {'test_key': 'null'}
        self.assertEqual(expected, self.nova_plugin.meta_serialize(original))

    def test_serialize_no_value(self):
        """Prove that the user can only pass in a dict to nova metadata."""
        excp = self.assertRaises(exception.StackValidationFailed,
                                 self.nova_plugin.meta_serialize, "foo")
        self.assertIn('metadata needs to be a Map', six.text_type(excp))

    def test_serialize_combined(self):
        original = {
            'test_key_1': 123,
            'test_key_2': 'a string',
            'test_key_3': {'a': 'b'},
            'test_key_4': None,
        }
        expected = {
            'test_key_1': '123',
            'test_key_2': 'a string',
            'test_key_3': '{"a": "b"}',
            'test_key_4': 'null',
        }

        self.assertEqual(expected, self.nova_plugin.meta_serialize(original))


class ServerConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(ServerConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_server = mock.Mock()
        self.ctx.clients.client_plugin(
            'nova').get_server = self.mock_get_server
        self.constraint = nova.ServerConstraint()

    def test_validation(self):
        self.mock_get_server.return_value = mock.MagicMock()
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        self.mock_get_server.side_effect = exception.EntityNotFound(
            entity='Server', name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))


class FlavorConstraintTest(common.HeatTestCase):

    def test_validate(self):
        client = fakes_nova.FakeClient()
        self.stub_keystoneclient()
        self.patchobject(nova.NovaClientPlugin, 'get_max_microversion',
                         return_value='2.27')
        self.patchobject(nova.NovaClientPlugin, '_create', return_value=client)
        client.flavors = mock.MagicMock()

        flavor = collections.namedtuple("Flavor", ["id", "name"])
        flavor.id = "1234"
        flavor.name = "foo"

        client.flavors.get.side_effect = [flavor,
                                          nova_exceptions.NotFound(''),
                                          nova_exceptions.NotFound('')]
        client.flavors.find.side_effect = [flavor,
                                           nova_exceptions.NotFound('')]
        constraint = nova.FlavorConstraint()
        ctx = utils.dummy_context()
        self.assertTrue(constraint.validate("1234", ctx))
        self.assertTrue(constraint.validate("foo", ctx))
        self.assertFalse(constraint.validate("bar", ctx))
        self.assertEqual(1, nova.NovaClientPlugin._create.call_count)
        self.assertEqual(3, client.flavors.get.call_count)
        self.assertEqual(2, client.flavors.find.call_count)


class HostConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(HostConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_host = mock.Mock()
        self.ctx.clients.client_plugin(
            'nova').get_host = self.mock_get_host
        self.constraint = nova.HostConstraint()

    def test_validation(self):
        self.mock_get_host.return_value = mock.MagicMock()
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        self.mock_get_host.side_effect = exception.EntityNotFound(
            entity='Host', name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))


class KeypairConstraintTest(common.HeatTestCase):

    def test_validation(self):
        client = fakes_nova.FakeClient()
        self.patchobject(nova.NovaClientPlugin, 'get_max_microversion',
                         return_value='2.27')
        self.patchobject(nova.NovaClientPlugin, '_create', return_value=client)
        client.keypairs = mock.MagicMock()

        key = collections.namedtuple("Key", ["name"])
        key.name = "foo"
        client.keypairs.get.side_effect = [
            fakes_nova.fake_exception(), key]

        constraint = nova.KeypairConstraint()
        ctx = utils.dummy_context()
        self.assertFalse(constraint.validate("bar", ctx))
        self.assertTrue(constraint.validate("foo", ctx))
        self.assertTrue(constraint.validate("", ctx))
        nova.NovaClientPlugin._create.assert_called_once_with(version='2.27')
        calls = [mock.call('bar'),
                 mock.call(key.name)]
        client.keypairs.get.assert_has_calls(calls)


class ConsoleUrlsTest(common.HeatTestCase):

    scenarios = [
        ('novnc', dict(console_type='novnc', res_obj=True)),
        ('xvpvnc', dict(console_type='xvpvnc', res_obj=True)),
        ('spice', dict(console_type='spice-html5', res_obj=True)),
        ('rdp', dict(console_type='rdp-html5', res_obj=True)),
        ('serial', dict(console_type='serial', res_obj=True)),
        ('mks', dict(console_type='webmks', res_obj=False)),
    ]

    def setUp(self):
        super(ConsoleUrlsTest, self).setUp()
        self.nova_client = mock.Mock()
        con = utils.dummy_context()
        c = con.clients
        self.nova_plugin = c.client_plugin('nova')
        self.patchobject(self.nova_plugin, 'client',
                         return_value=self.nova_client)
        self.server = mock.Mock()
        if self.res_obj:
            self.console_method = getattr(self.server, 'get_console_url')
        else:
            self.console_method = getattr(self.nova_client.servers,
                                          'get_console_url')

    def test_get_console_url(self):
        console = {
            'console': {
                'type': self.console_type,
                'url': '%s_console_url' % self.console_type
            }
        }
        self.console_method.return_value = console

        console_url = self.nova_plugin.get_console_urls(self.server)[
            self.console_type]

        self.assertEqual(console['console']['url'], console_url)
        self._assert_console_method_called()

    def _assert_console_method_called(self):
        if self.console_type == 'webmks':
            self.console_method.assert_called_once_with(self.server,
                                                        self.console_type)
        else:
            self.console_method.assert_called_once_with(self.console_type)

    def _test_get_console_url_tolerate_exception(self, msg):
        console_url = self.nova_plugin.get_console_urls(self.server)[
            self.console_type]

        self._assert_console_method_called()
        self.assertIn(msg, console_url)

    def test_get_console_url_tolerate_unavailable(self):
        msg = 'Unavailable console type %s.' % self.console_type
        self.console_method.side_effect = nova_exceptions.BadRequest(
            400, message=msg)

        self._test_get_console_url_tolerate_exception(msg)

    def test_get_console_url_tolerate_unsupport(self):
        msg = 'Unsupported console_type "%s"' % self.console_type
        self.console_method.side_effect = (
            nova_exceptions.UnsupportedConsoleType(
                console_type=self.console_type))

        self._test_get_console_url_tolerate_exception(msg)

    def test_get_console_urls_tolerate_other_400(self):
        exc = nova_exceptions.BadRequest
        self.console_method.side_effect = exc(400, message="spam")

        self._test_get_console_url_tolerate_exception('spam')

    def test_get_console_urls_reraises_other(self):
        exc = Exception
        self.console_method.side_effect = exc("spam")

        self._test_get_console_url_tolerate_exception('spam')


class NovaClientPluginExtensionsTest(NovaClientPluginTestCase):
    """Tests for extensions in novaclient."""

    def test_has_no_extensions(self):
        self.nova_client.list_extensions.show_all.return_value = []
        self.assertFalse(self.nova_plugin.has_extension(
            "os-virtual-interfaces"))

    def test_has_no_interface_extensions(self):
        mock_extension = mock.Mock()
        p = mock.PropertyMock(return_value='os-xxxx')
        type(mock_extension).alias = p
        self.nova_client.list_extensions.show_all.return_value = [
            mock_extension]
        self.assertFalse(self.nova_plugin.has_extension(
            "os-virtual-interfaces"))

    def test_has_os_interface_extension(self):
        mock_extension = mock.Mock()
        p = mock.PropertyMock(return_value='os-virtual-interfaces')
        type(mock_extension).alias = p
        self.nova_client.list_extensions.show_all.return_value = [
            mock_extension]
        self.assertTrue(self.nova_plugin.has_extension(
            "os-virtual-interfaces"))
