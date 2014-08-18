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
"""Tests for :module:'heat.engine.resources.nova_utls'."""

import mock
from novaclient import exceptions as nova_exceptions
from oslo.config import cfg
import uuid

from heat.common import exception
from heat.engine.clients.os import nova
from heat.tests.common import HeatTestCase
from heat.tests import utils


class NovaClientPluginTestCase(HeatTestCase):
    def setUp(self):
        super(NovaClientPluginTestCase, self).setUp()
        self.nova_client = self.m.CreateMockAnything()
        con = utils.dummy_context()
        c = con.clients
        self.nova_plugin = c.client_plugin('nova')
        self.nova_plugin._client = self.nova_client


class NovaClientPluginTests(NovaClientPluginTestCase):
    """
    Basic tests for the helper methods in
    :module:'heat.engine.resources.nova_utils'.
    """

    def test_get_ip(self):
        my_image = self.m.CreateMockAnything()
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

    def test_get_flavor_id(self):
        """Tests the get_flavor_id function."""
        flav_id = str(uuid.uuid4())
        flav_name = 'X-Large'
        my_flavor = self.m.CreateMockAnything()
        my_flavor.name = flav_name
        my_flavor.id = flav_id
        self.nova_client.flavors = self.m.CreateMockAnything()
        self.nova_client.flavors.list().MultipleTimes().AndReturn([my_flavor])
        self.m.ReplayAll()
        self.assertEqual(flav_id, self.nova_plugin.get_flavor_id(flav_name))
        self.assertEqual(flav_id, self.nova_plugin.get_flavor_id(flav_id))
        self.assertRaises(exception.FlavorMissing,
                          self.nova_plugin.get_flavor_id, 'noflavor')
        self.m.VerifyAll()

    def test_get_keypair(self):
        """Tests the get_keypair function."""
        my_pub_key = 'a cool public key string'
        my_key_name = 'mykey'
        my_key = self.m.CreateMockAnything()
        my_key.public_key = my_pub_key
        my_key.name = my_key_name
        self.nova_client.keypairs = self.m.CreateMockAnything()
        self.nova_client.keypairs.get(
            my_key_name).AndReturn(my_key)
        self.nova_client.keypairs.get(
            'notakey').AndRaise(nova_exceptions.NotFound(404))
        self.m.ReplayAll()
        self.assertEqual(my_key, self.nova_plugin.get_keypair(my_key_name))
        self.assertRaises(exception.UserKeyPairMissing,
                          self.nova_plugin.get_keypair, 'notakey')
        self.m.VerifyAll()

    def test_get_status(self):
        server = self.m.CreateMockAnything()
        server.status = 'ACTIVE'

        observed = self.nova_plugin.get_status(server)
        self.assertEqual('ACTIVE', observed)

        server.status = 'ACTIVE(STATUS)'
        observed = self.nova_plugin.get_status(server)
        self.assertEqual('ACTIVE', observed)


class NovaUtilsRefreshServerTests(NovaClientPluginTestCase):

    def test_successful_refresh(self):
        server = self.m.CreateMockAnything()
        server.get().AndReturn(None)
        self.m.ReplayAll()

        self.assertIsNone(self.nova_plugin.refresh_server(server))
        self.m.VerifyAll()

    def test_overlimit_error(self):
        server = mock.Mock()
        server.get.side_effect = nova_exceptions.OverLimit(
            413, "limit reached")
        self.assertIsNone(self.nova_plugin.refresh_server(server))

    def test_500_error(self):
        server = self.m.CreateMockAnything()
        msg = ("ClientException: The server has either erred or is "
               "incapable of performing the requested operation.")
        server.get().AndRaise(
            nova_exceptions.ClientException(500, msg))
        self.m.ReplayAll()

        self.assertIsNone(self.nova_plugin.refresh_server(server))
        self.m.VerifyAll()

    def test_503_error(self):
        server = self.m.CreateMockAnything()
        msg = ("ClientException: The server has either erred or is "
               "incapable of performing the requested operation.")
        server.get().AndRaise(
            nova_exceptions.ClientException(503, msg))
        self.m.ReplayAll()

        self.assertIsNone(self.nova_plugin.refresh_server(server))
        self.m.VerifyAll()

    def test_unhandled_exception(self):
        server = self.m.CreateMockAnything()
        msg = ("ClientException: The server has either erred or is "
               "incapable of performing the requested operation.")
        server.get().AndRaise(
            nova_exceptions.ClientException(501, msg))
        self.m.ReplayAll()

        self.assertRaises(nova_exceptions.ClientException,
                          self.nova_plugin.refresh_server, server)
        self.m.VerifyAll()


class NovaUtilsUserdataTests(NovaClientPluginTestCase):

    def test_build_userdata(self):
        """Tests the build_userdata function."""
        cfg.CONF.set_override('heat_metadata_server_url',
                              'http://server.test:123')
        cfg.CONF.set_override('heat_watch_server_url',
                              'http://server.test:345')
        cfg.CONF.set_override('instance_connection_is_secure',
                              False)
        cfg.CONF.set_override(
            'instance_connection_https_validate_certificates', False)
        data = self.nova_plugin.build_userdata({})
        self.assertIn("Content-Type: text/cloud-config;", data)
        self.assertIn("Content-Type: text/cloud-boothook;", data)
        self.assertIn("Content-Type: text/part-handler;", data)
        self.assertIn("Content-Type: text/x-cfninitdata;", data)
        self.assertIn("Content-Type: text/x-shellscript;", data)
        self.assertIn("http://server.test:345", data)
        self.assertIn("http://server.test:123", data)
        self.assertIn("[Boto]", data)

    def test_build_userdata_without_instance_user(self):
        """Don't add a custom instance user when not requested."""
        cfg.CONF.set_override('instance_user',
                              'config_instance_user')
        cfg.CONF.set_override('heat_metadata_server_url',
                              'http://server.test:123')
        cfg.CONF.set_override('heat_watch_server_url',
                              'http://server.test:345')
        data = self.nova_plugin.build_userdata({}, instance_user=None)
        self.assertNotIn('user: ', data)
        self.assertNotIn('useradd', data)
        self.assertNotIn('config_instance_user', data)

    def test_build_userdata_with_instance_user(self):
        """Add the custom instance user when requested."""
        self.m.StubOutWithMock(nova.cfg, 'CONF')
        cnf = nova.cfg.CONF
        cnf.instance_user = 'config_instance_user'
        cnf.heat_metadata_server_url = 'http://server.test:123'
        cnf.heat_watch_server_url = 'http://server.test:345'
        data = self.nova_plugin.build_userdata(
            None, instance_user="custominstanceuser")
        self.assertNotIn('config_instance_user', data)
        self.assertIn("custominstanceuser", data)


class NovaUtilsMetadataTests(NovaClientPluginTestCase):

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
        original = {'test_key': {'a': 'b', 'c': 'd'}}
        expected = {'test_key': '{"a": "b", "c": "d"}'}
        self.assertEqual(expected, self.nova_plugin.meta_serialize(original))

    def test_serialize_none(self):
        original = {'test_key': None}
        expected = {'test_key': 'null'}
        self.assertEqual(expected, self.nova_plugin.meta_serialize(original))

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
