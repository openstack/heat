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

from heat.common import exception
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.clients.os import monasca as client_plugin
from heat.engine.resources.openstack.monasca import notification
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


sample_template = {
    'heat_template_version': '2015-10-15',
    'resources': {
        'test_resource': {
            'type': 'OS::Monasca::Notification',
            'properties': {
                'name': 'test-notification',
                'type': 'webhook',
                'address': 'http://localhost:80/',
                'period': 60
            }
        }
    }
}


class MonascaNotificationTest(common.HeatTestCase):

    def setUp(self):
        super(MonascaNotificationTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack',
            template.Template(sample_template)
        )

        self.test_resource = self.stack['test_resource']

        # Mock client
        self.test_client = mock.MagicMock()
        self.test_resource.client = mock.MagicMock(
            return_value=self.test_client)

        # Mock client plugin
        self.test_client_plugin = client_plugin.MonascaClientPlugin(self.ctx)
        self.test_client_plugin._create = mock.MagicMock(
            return_value=self.test_client)
        self.test_resource.client_plugin = mock.MagicMock(
            return_value=self.test_client_plugin)

    def _get_mock_resource(self):
        value = dict(id='477e8273-60a7-4c41-b683-fdb0bc7cd152')

        return value

    def test_validate_success_no_period(self):
        self.test_resource.properties.data.pop('period')
        self.test_resource.validate()

    def test_validate_invalid_type_with_period(self):
        self.test_resource.properties.data['type'] = self.test_resource.EMAIL
        self.assertRaises(exception.StackValidationFailed,
                          self.test_resource.validate)

    def test_validate_no_scheme_address_for_get_attr(self):
        self.test_resource.properties.data['type'] = self.test_resource.WEBHOOK
        self.patchobject(cfn_funcs, 'GetAtt', return_value=None)
        get_att = cfn_funcs.GetAtt(self.stack, 'Fn::GetAtt',
                                   ["ResourceA", "abc"])
        self.test_resource.properties.data['address'] = get_att
        self.assertIsNone(self.test_resource.validate())

    def test_validate_no_scheme_address_for_webhook(self):
        self.test_resource.properties.data['type'] = self.test_resource.WEBHOOK
        self.test_resource.properties.data['address'] = 'abc@def.com'
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.test_resource.validate)
        self.assertEqual('Address "abc@def.com" doesn\'t have '
                         'required URL scheme', six.text_type(ex))

    def test_validate_no_netloc_address_for_webhook(self):
        self.test_resource.properties.data['type'] = self.test_resource.WEBHOOK
        self.test_resource.properties.data['address'] = 'https://'
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.test_resource.validate)
        self.assertEqual('Address "https://" doesn\'t have '
                         'required network location', six.text_type(ex))

    def test_validate_prohibited_address_for_webhook(self):
        self.test_resource.properties.data['type'] = self.test_resource.WEBHOOK
        self.test_resource.properties.data['address'] = 'ftp://127.0.0.1'
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.test_resource.validate)
        self.assertEqual('Address "ftp://127.0.0.1" doesn\'t satisfies '
                         'allowed schemes: http, https', six.text_type(ex))

    def test_validate_incorrect_address_for_email(self):
        self.test_resource.properties.data['type'] = self.test_resource.EMAIL
        self.test_resource.properties.data['address'] = 'abc#def.com'
        self.test_resource.properties.data.pop('period')
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.test_resource.validate)
        self.assertEqual('Address "abc#def.com" doesn\'t satisfies allowed '
                         'format for "email" type of "type" property',
                         six.text_type(ex))

    def test_validate_invalid_address_parsing(self):
        self.test_resource.properties.data['type'] = self.test_resource.WEBHOOK
        self.test_resource.properties.data['address'] = "https://example.com]"
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.test_resource.validate)
        self.assertEqual('Address "https://example.com]" should have correct '
                         'format required by "webhook" type of "type" '
                         'property', six.text_type(ex))

    def test_resource_handle_create(self):
        mock_notification_create = self.test_client.notifications.create
        mock_resource = self._get_mock_resource()
        mock_notification_create.return_value = mock_resource

        # validate the properties
        self.assertEqual(
            'test-notification',
            self.test_resource.properties.get(
                notification.MonascaNotification.NAME))
        self.assertEqual(
            'webhook',
            self.test_resource.properties.get(
                notification.MonascaNotification.TYPE))
        self.assertEqual(
            'http://localhost:80/',
            self.test_resource.properties.get(
                notification.MonascaNotification.ADDRESS))
        self.assertEqual(
            60, self.test_resource.properties.get(
                notification.MonascaNotification.PERIOD))

        self.test_resource.data_set = mock.Mock()
        self.test_resource.handle_create()

        args = dict(
            name='test-notification',
            type='webhook',
            address='http://localhost:80/',
            period=60
        )

        mock_notification_create.assert_called_once_with(**args)

        # validate physical resource id
        self.assertEqual(mock_resource['id'], self.test_resource.resource_id)

    def test_resource_handle_create_default_period(self):
        self.test_resource.properties.data.pop('period')
        mock_notification_create = self.test_client.notifications.create
        self.test_resource.handle_create()

        args = dict(
            name='test-notification',
            type='webhook',
            address='http://localhost:80/',
            period=60
        )
        mock_notification_create.assert_called_once_with(**args)

    def test_resource_handle_create_no_period(self):
        self.test_resource.properties.data.pop('period')
        self.test_resource.properties.data['type'] = 'email'
        self.test_resource.properties.data['address'] = 'abc@def.com'
        mock_notification_create = self.test_client.notifications.create
        self.test_resource.handle_create()

        args = dict(
            name='test-notification',
            type='email',
            address='abc@def.com'
        )
        mock_notification_create.assert_called_once_with(**args)

    def test_resource_handle_update(self):
        mock_notification_update = self.test_client.notifications.update
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {notification.MonascaNotification.ADDRESS:
                     'http://localhost:1234/',
                     notification.MonascaNotification.NAME: 'name-updated',
                     notification.MonascaNotification.TYPE: 'webhook',
                     notification.MonascaNotification.PERIOD: 0}

        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        args = dict(
            notification_id=self.test_resource.resource_id,
            name='name-updated',
            type='webhook',
            address='http://localhost:1234/',
            period=0
        )
        mock_notification_update.assert_called_once_with(**args)

    def test_resource_handle_update_default_period(self):
        mock_notification_update = self.test_client.notifications.update
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.test_resource.properties.data.pop('period')

        prop_diff = {notification.MonascaNotification.ADDRESS:
                     'http://localhost:1234/',
                     notification.MonascaNotification.NAME: 'name-updated',
                     notification.MonascaNotification.TYPE: 'webhook'}

        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        args = dict(
            notification_id=self.test_resource.resource_id,
            name='name-updated',
            type='webhook',
            address='http://localhost:1234/',
            period=60
        )
        mock_notification_update.assert_called_once_with(**args)

    def test_resource_handle_update_no_period(self):
        mock_notification_update = self.test_client.notifications.update
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.test_resource.properties.data.pop('period')

        prop_diff = {notification.MonascaNotification.ADDRESS:
                     'abc@def.com',
                     notification.MonascaNotification.NAME: 'name-updated',
                     notification.MonascaNotification.TYPE: 'email'}

        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        args = dict(
            notification_id=self.test_resource.resource_id,
            name='name-updated',
            type='email',
            address='abc@def.com'
        )
        mock_notification_update.assert_called_once_with(**args)

    def test_resource_handle_delete(self):
        mock_notification_delete = self.test_client.notifications.delete
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_notification_delete.return_value = None

        self.assertIsNone(self.test_resource.handle_delete())
        mock_notification_delete.assert_called_once_with(
            notification_id=self.test_resource.resource_id
        )

    def test_resource_handle_delete_resource_id_is_none(self):
        self.test_resource.resource_id = None
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resource_handle_delete_not_found(self):
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_notification_delete = self.test_client.notifications.delete
        mock_notification_delete.side_effect = (
            client_plugin.monasca_exc.NotFound)

        self.assertIsNone(self.test_resource.handle_delete())
