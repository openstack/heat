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

import monascaclient

from heat.common import exception as heat_exception
from heat.engine.clients.os import monasca as client_plugin
from heat.tests import common
from heat.tests import utils


class MonascaNotificationConstraintTest(common.HeatTestCase):
    def test_expected_exceptions(self):
        self.assertEqual(
            (heat_exception.EntityNotFound,),
            client_plugin.MonascaNotificationConstraint.expected_exceptions,
            "MonascaNotificationConstraint expected exceptions error")

    def test_constraint(self):
        constraint = client_plugin.MonascaNotificationConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_notification.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constraint.validate_with_client(client_mock,
                                                          'notification_1'))
        client_plugin_mock.get_notification.assert_called_once_with(
            'notification_1')


class MonascaClientPluginTest(common.HeatTestCase):
    def test_client(self):
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('monasca')
        client = plugin.client()
        self.assertIsNotNone(client.metrics)

    @mock.patch.object(monascaclient.client, '_session')
    def test_client_uses_session(self, mock_session):
        context = mock.MagicMock()
        monasca_client = client_plugin.MonascaClientPlugin(context=context)
        self.assertIsNotNone(monasca_client._create())


class MonascaClientPluginNotificationTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'test-notification'

    def _get_mock_notification(self):
        notification = dict()
        notification['id'] = self.sample_uuid
        notification['name'] = self.sample_name
        return notification

    def setUp(self):
        super(MonascaClientPluginNotificationTest, self).setUp()
        self._client = mock.MagicMock()
        self.client_plugin = client_plugin.MonascaClientPlugin(
            context=mock.MagicMock()
        )

    @mock.patch.object(client_plugin.MonascaClientPlugin, 'client')
    def test_get_notification(self, client_monasca):
        mock_notification = self._get_mock_notification()
        self._client.notifications.get.return_value = mock_notification
        client_monasca.return_value = self._client

        self.assertEqual(self.sample_uuid,
                         self.client_plugin.get_notification(
                             self.sample_uuid))
        self._client.notifications.get.assert_called_once_with(
            notification_id=self.sample_uuid)

    @mock.patch.object(client_plugin.MonascaClientPlugin, 'client')
    def test_get_notification_not_found(self, client_monasca):
        self._client.notifications.get.side_effect = (
            client_plugin.monasca_exc.NotFound)
        client_monasca.return_value = self._client

        ex = self.assertRaises(heat_exception.EntityNotFound,
                               self.client_plugin.get_notification,
                               self.sample_uuid)
        msg = ("The Monasca Notification (%(name)s) could not be found." %
               {'name': self.sample_uuid})
        self.assertEqual(msg, six.text_type(ex))
        self._client.notifications.get.assert_called_once_with(
            notification_id=self.sample_uuid)
