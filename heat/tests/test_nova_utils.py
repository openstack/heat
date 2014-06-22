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
import six
import uuid

from novaclient import exceptions as nova_exceptions

from heat.common import exception
from heat.engine.resources import nova_utils
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests.v1_1 import fakes


class NovaUtilsTests(HeatTestCase):
    """
    Basic tests for the helper methods in
    :module:'heat.engine.resources.nova_utils'.
    """

    def setUp(self):
        super(NovaUtilsTests, self).setUp()
        self.nova_client = self.m.CreateMockAnything()
        self.mock_warnings = mock.patch(
            'heat.engine.resources.nova_utils.warnings')
        self.mock_warnings.start()
        self.addCleanup(self.mock_warnings.stop)

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
        observed = nova_utils.get_ip(my_image, 'public', 4)
        self.assertEqual(expected, observed)

        expected = '10.13.12.13'
        observed = nova_utils.get_ip(my_image, 'private', 4)
        self.assertEqual(expected, observed)

        expected = '2401:1801:7800:0101:c058:dd33:ff18:04e6'
        observed = nova_utils.get_ip(my_image, 'public', 6)
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
        self.assertEqual(flav_id, nova_utils.get_flavor_id(self.nova_client,
                                                           flav_name))
        self.assertEqual(flav_id, nova_utils.get_flavor_id(self.nova_client,
                                                           flav_id))
        self.assertRaises(exception.FlavorMissing, nova_utils.get_flavor_id,
                          self.nova_client, 'noflavor')
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
            'notakey').AndRaise(fakes.fake_exception())
        self.m.ReplayAll()
        self.assertEqual(my_key, nova_utils.get_keypair(self.nova_client,
                                                        my_key_name))
        self.assertRaises(exception.UserKeyPairMissing, nova_utils.get_keypair,
                          self.nova_client, 'notakey')
        self.m.VerifyAll()

    def test_delete_server(self):
        server = mock.Mock()
        server.status = "DELETED"
        task = scheduler.TaskRunner(nova_utils.delete_server, server)
        self.assertIsNone(task())

    def test_delete_server_notfound(self):
        server = mock.Mock()
        server.delete.side_effect = nova_exceptions.NotFound(404)
        task = scheduler.TaskRunner(nova_utils.delete_server, server)
        self.assertIsNone(task())

    def test_delete_noserver(self):
        task = scheduler.TaskRunner(nova_utils.delete_server, None)
        self.assertIsNone(task())

    def test_delete_servererror(self):
        server = mock.Mock()
        server.name = "myserver"
        server.status = "ERROR"
        server.fault = {
            "message": "test error",
        }
        task = scheduler.TaskRunner(nova_utils.delete_server, server)
        err = self.assertRaises(exception.Error, task)
        self.assertIn("myserver delete failed: (None) test error",
                      six.text_type(err))


class NovaUtilsRefreshServerTests(HeatTestCase):

    def setUp(self):
        super(NovaUtilsRefreshServerTests, self).setUp()
        self.mock_warnings = mock.patch(
            'heat.engine.resources.nova_utils.warnings')
        self.mock_warnings.start()
        self.addCleanup(self.mock_warnings.stop)

    def test_successful_refresh(self):
        server = self.m.CreateMockAnything()
        server.get().AndReturn(None)
        self.m.ReplayAll()

        self.assertIsNone(nova_utils.refresh_server(server))
        self.m.VerifyAll()

    def test_overlimit_error(self):
        server = mock.Mock()
        server.get.side_effect = fakes.fake_exception(413)
        self.assertIsNone(nova_utils.refresh_server(server))

    def test_500_error(self):
        server = self.m.CreateMockAnything()
        server.get().AndRaise(fakes.fake_exception(500))
        self.m.ReplayAll()

        self.assertIsNone(nova_utils.refresh_server(server))
        self.m.VerifyAll()

    def test_503_error(self):
        server = self.m.CreateMockAnything()
        server.get().AndRaise(fakes.fake_exception(503))
        self.m.ReplayAll()

        self.assertIsNone(nova_utils.refresh_server(server))
        self.m.VerifyAll()

    def test_unhandled_exception(self):
        server = self.m.CreateMockAnything()
        server.get().AndRaise(fakes.fake_exception(501))
        self.m.ReplayAll()

        self.assertRaises(nova_exceptions.ClientException,
                          nova_utils.refresh_server, server)
        self.m.VerifyAll()


class NovaUtilsUserdataTests(HeatTestCase):

    def setUp(self):
        super(NovaUtilsUserdataTests, self).setUp()
        self.nova_client = self.m.CreateMockAnything()
        self.mock_warnings = mock.patch(
            'heat.engine.resources.nova_utils.warnings')
        self.mock_warnings.start()
        self.addCleanup(self.mock_warnings.stop)

    def test_build_userdata(self):
        """Tests the build_userdata function."""
        resource = self.m.CreateMockAnything()
        resource.metadata_get().AndReturn({})
        self.m.StubOutWithMock(nova_utils.cfg, 'CONF')
        cnf = nova_utils.cfg.CONF
        cnf.heat_metadata_server_url = 'http://server.test:123'
        cnf.heat_watch_server_url = 'http://server.test:345'
        cnf.instance_connection_is_secure = False
        cnf.instance_connection_https_validate_certificates = False
        self.m.ReplayAll()
        data = nova_utils.build_userdata(resource)
        self.assertIn("Content-Type: text/cloud-config;", data)
        self.assertIn("Content-Type: text/cloud-boothook;", data)
        self.assertIn("Content-Type: text/part-handler;", data)
        self.assertIn("Content-Type: text/x-cfninitdata;", data)
        self.assertIn("Content-Type: text/x-shellscript;", data)
        self.assertIn("http://server.test:345", data)
        self.assertIn("http://server.test:123", data)
        self.assertIn("[Boto]", data)
        self.m.VerifyAll()

    def test_build_userdata_without_instance_user(self):
        """Don't add a custom instance user when not requested."""
        resource = self.m.CreateMockAnything()
        resource.metadata_get().AndReturn({})
        self.m.StubOutWithMock(nova_utils.cfg, 'CONF')
        cnf = nova_utils.cfg.CONF
        cnf.instance_user = 'config_instance_user'
        cnf.heat_metadata_server_url = 'http://server.test:123'
        cnf.heat_watch_server_url = 'http://server.test:345'
        self.m.ReplayAll()
        data = nova_utils.build_userdata(resource, instance_user=None)
        self.assertNotIn('user: ', data)
        self.assertNotIn('useradd', data)
        self.assertNotIn('config_instance_user', data)
        self.m.VerifyAll()

    def test_build_userdata_with_instance_user(self):
        """Add the custom instance user when requested."""
        resource = self.m.CreateMockAnything()
        resource.metadata_get().AndReturn(None)
        self.m.StubOutWithMock(nova_utils.cfg, 'CONF')
        cnf = nova_utils.cfg.CONF
        cnf.instance_user = 'config_instance_user'
        cnf.heat_metadata_server_url = 'http://server.test:123'
        cnf.heat_watch_server_url = 'http://server.test:345'
        self.m.ReplayAll()
        data = nova_utils.build_userdata(resource,
                                         instance_user="custominstanceuser")
        self.assertNotIn('config_instance_user', data)
        self.assertIn("custominstanceuser", data)
        self.m.VerifyAll()


class NovaUtilsMetadataTests(HeatTestCase):

    def setUp(self):
        super(NovaUtilsMetadataTests, self).setUp()
        self.mock_warnings = mock.patch(
            'heat.engine.resources.nova_utils.warnings')
        self.mock_warnings.start()
        self.addCleanup(self.mock_warnings.stop)

    def test_serialize_string(self):
        original = {'test_key': 'simple string value'}
        self.assertEqual(original, nova_utils.meta_serialize(original))

    def test_serialize_int(self):
        original = {'test_key': 123}
        expected = {'test_key': '123'}
        self.assertEqual(expected, nova_utils.meta_serialize(original))

    def test_serialize_list(self):
        original = {'test_key': [1, 2, 3]}
        expected = {'test_key': '[1, 2, 3]'}
        self.assertEqual(expected, nova_utils.meta_serialize(original))

    def test_serialize_dict(self):
        original = {'test_key': {'a': 'b', 'c': 'd'}}
        expected = {'test_key': '{"a": "b", "c": "d"}'}
        self.assertEqual(expected, nova_utils.meta_serialize(original))

    def test_serialize_none(self):
        original = {'test_key': None}
        expected = {'test_key': 'null'}
        self.assertEqual(expected, nova_utils.meta_serialize(original))

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

        self.assertEqual(expected, nova_utils.meta_serialize(original))
