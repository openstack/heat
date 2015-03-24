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
import testtools

from .. import client  # noqa
from .. import exceptions  # noqa


class KeystoneRoleConstraintTest(testtools.TestCase):

    def test_expected_exceptions(self):
        self.assertEqual((exceptions.KeystoneRoleNotFound,),
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


class KeystoneProjectConstraintTest(testtools.TestCase):

    def test_expected_exceptions(self):
        self.assertEqual((exceptions.KeystoneProjectNotFound,),
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


class KeystoneGroupConstraintTest(testtools.TestCase):

    def test_expected_exceptions(self):
        self.assertEqual((exceptions.KeystoneGroupNotFound,),
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


class KeystoneDomainConstraintTest(testtools.TestCase):

    def test_expected_exceptions(self):
        self.assertEqual((exceptions.KeystoneDomainNotFound,),
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
