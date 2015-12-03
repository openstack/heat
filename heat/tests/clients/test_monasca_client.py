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

from heat.common import exception as heat_exception
from heat.engine.clients.os import monasca as client_plugin
from heat.tests import common


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
    @mock.patch('heat.engine.clients.os.monasca.client')
    @mock.patch.object(client_plugin.MonascaClientPlugin,
                       '_get_client_args')
    def test_client(self,
                    mock_get_client_args,
                    mock_monasca_client):
        with mock.patch.object(mock_monasca_client,
                               'Client') as mock_client:
            args = dict(
                os_endpoint='endpoint',
                endpoint_type='endpoint_type',
                auth_url='auth_url',
                project_id='project_id',
                token=lambda: '',
                service_type='service_type',
                cacert='os_cacert',
                cert_file='cert_file',
                insecure='insecure',
                key_file='key_file'
            )

            mock_get_client_args.return_value = args

            _plugin = client_plugin.MonascaClientPlugin(
                context=mock.MagicMock()
            )
            _plugin.client()

            # Make sure the right args are created
            mock_get_client_args.assert_called_once_with(
                service_name='monasca',
                service_type='monitoring'
            )

            # Make sure proper client_plugin is created with expected args
            mock_client.assert_called_once_with(
                '2_0',
                endpoint=args['os_endpoint'],
                endpoint_type=args['endpoint_type'],
                auth_url=args['auth_url'],
                token=args['token'](),
                project_id=args['project_id'],
                service_type=args['service_type'],
                os_cacert=args['cacert'],
                cert_file=args['cert_file'],
                key_file=args['key_file'],
                insecure=args['insecure']
            )


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
