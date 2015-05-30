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
import six

from keystoneclient import exceptions as keystone_exceptions

from heat.common import exception
from heat.engine.clients.os import keystone as client
from heat.tests import common


class KeystoneRoleConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual((exception.KeystoneRoleNotFound,),
                         client.KeystoneRoleConstraint.expected_exceptions,
                         "KeystoneRoleConstraint expected exceptions error")

    def test_constrain(self):
        constrain = client.KeystoneRoleConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_role_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constrain.validate_with_client(client_mock,
                                                         'role_1'))

        client_plugin_mock.get_role_id.assert_called_once_with('role_1')


class KeystoneProjectConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual((exception.KeystoneProjectNotFound,),
                         client.KeystoneProjectConstraint.expected_exceptions,
                         "KeystoneProjectConstraint expected exceptions error")

    def test_constrain(self):
        constrain = client.KeystoneProjectConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_project_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constrain.validate_with_client(client_mock,
                                                         'project_1'))

        client_plugin_mock.get_project_id.assert_called_once_with('project_1')


class KeystoneGroupConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual((exception.KeystoneGroupNotFound,),
                         client.KeystoneGroupConstraint.expected_exceptions,
                         "KeystoneGroupConstraint expected exceptions error")

    def test_constrain(self):
        constrain = client.KeystoneGroupConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_group_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constrain.validate_with_client(client_mock,
                                                         'group_1'))

        client_plugin_mock.get_group_id.assert_called_once_with('group_1')


class KeystoneDomainConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual((exception.KeystoneDomainNotFound,),
                         client.KeystoneDomainConstraint.expected_exceptions,
                         "KeystoneDomainConstraint expected exceptions error")

    def test_constrain(self):
        constrain = client.KeystoneDomainConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_domain_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constrain.validate_with_client(client_mock,
                                                         'domain_1'))

        client_plugin_mock.get_domain_id.assert_called_once_with('domain_1')


class KeystoneServiceConstraintTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

    def test_expected_exceptions(self):
        self.assertEqual((exception.KeystoneServiceNotFound,
                          exception.KeystoneServiceNameConflict,),
                         client.KeystoneServiceConstraint.expected_exceptions,
                         "KeystoneServiceConstraint expected exceptions error")

    def test_constrain(self):
        constrain = client.KeystoneServiceConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_service_id.return_value = self.sample_uuid
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constrain.validate_with_client(client_mock,
                                                         self.sample_uuid))

        client_plugin_mock.get_service_id.assert_called_once_with(
            self.sample_uuid
        )


class KeystoneClientPluginServiceTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'sample_service'

    def _get_mock_service(self):
        srv = mock.MagicMock()
        srv.id = self.sample_uuid
        srv.name = self.sample_name
        return srv

    def setUp(self):
        super(KeystoneClientPluginServiceTest, self).setUp()
        self._client = mock.MagicMock()
        self._client.client = mock.MagicMock()
        self._client.client.services = mock.MagicMock()

    @mock.patch.object(client.KeystoneClientPlugin, 'client')
    def test_get_service_id(self, client_keystone):

        self._client.client.services.get.return_value = (self
                                                         ._get_mock_service())

        client_keystone.return_value = self._client
        client_plugin = client.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_service_id(self.sample_uuid))

    @mock.patch.object(client.KeystoneClientPlugin, 'client')
    def test_get_service_id_with_name(self, client_keystone):
        self._client.client.services.get.side_effect = (keystone_exceptions
                                                        .NotFound)
        self._client.client.services.list.return_value = [
            self._get_mock_service()
        ]

        client_keystone.return_value = self._client
        client_plugin = client.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_service_id(self.sample_name))

    @mock.patch.object(client.KeystoneClientPlugin, 'client')
    def test_get_service_id_with_name_conflict(self, client_keystone):
        self._client.client.services.get.side_effect = (keystone_exceptions
                                                        .NotFound)
        self._client.client.services.list.return_value = [
            self._get_mock_service(),
            self._get_mock_service()
        ]

        client_keystone.return_value = self._client
        client_plugin = client.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.KeystoneServiceNameConflict,
                               client_plugin.get_service_id,
                               self.sample_name)
        msg = ("Keystone has more than one service with same name "
               "%s. Please use service id instead of name" %
               self.sample_name)
        self.assertEqual(msg, six.text_type(ex))

    @mock.patch.object(client.KeystoneClientPlugin, 'client')
    def test_get_service_id_not_found(self, client_keystone):
        self._client.client.services.get.side_effect = (keystone_exceptions
                                                        .NotFound)
        self._client.client.services.list.return_value = [
        ]

        client_keystone.return_value = self._client
        client_plugin = client.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.KeystoneServiceNotFound,
                               client_plugin.get_service_id,
                               self.sample_name)
        msg = ("Keystone service %s not found" %
               self.sample_name)
        self.assertEqual(msg, six.text_type(ex))
