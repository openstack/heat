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

import datetime

from keystoneauth1 import exceptions as kc_exceptions
import mock
import six
from six.moves.urllib import parse as urlparse

from heat.common import exception
from heat.common import template_format
from heat.db.sqlalchemy import models
from heat.engine.clients.os import heat_plugin
from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine.clients.os import swift
from heat.engine import scheduler
from heat.engine import stack as stk
from heat.engine import template
from heat.objects import resource_data as resource_data_object
from heat.tests import common
from heat.tests import generic_resource
from heat.tests import utils


TEMPLATE_CFN_SIGNAL = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a test.",
  "Parameters" : {},
  "Resources" : {
    "signal_handler" : {"Type" : "SignalResourceType",
                        "Properties": {"signal_transport": "CFN_SIGNAL"}},
    "resource_X" : {"Type" : "GenericResourceType"}
  }
}
'''

TEMPLATE_HEAT_TEMPLATE_SIGNAL = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a test.",
  "Parameters" : {},
  "Resources" : {
    "signal_handler" : {"Type" : "SignalResourceType",
                        "Properties": {"signal_transport": "HEAT_SIGNAL"}},
    "resource_X" : {"Type" : "GenericResourceType"}
  }
}
'''

TEMPLATE_SWIFT_SIGNAL = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a test.",
  "Parameters" : {},
  "Resources" : {
    "signal_handler" : {"Type" : "SignalResourceType",
                        "Properties": {"signal_transport": "TEMP_URL_SIGNAL"}},
    "resource_X" : {"Type" : "GenericResourceType"}
  }
}
'''

TEMPLATE_ZAQAR_SIGNAL = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a test.",
  "Parameters" : {},
  "Resources" : {
    "signal_handler" : {"Type" : "SignalResourceType",
                        "Properties": {"signal_transport": "ZAQAR_SIGNAL"}},
    "resource_X" : {"Type" : "GenericResourceType"}
  }
}
'''


class SignalTest(common.HeatTestCase):

    @staticmethod
    def _create_stack(template_string, stack_name=None,
                      stack_id=None):
        stack_name = stack_name or utils.random_name()
        stack_id = stack_id or utils.random_name()

        tpl = template.Template(template_format.parse(template_string))
        ctx = utils.dummy_context()
        ctx.tenant = 'test_tenant'
        stack = stk.Stack(ctx, stack_name, tpl, disable_rollback=True)
        with utils.UUIDStub(stack_id):
            stack.store()
        stack.create()
        return stack

    def test_resource_data(self):
        # Setup
        self.stub_keystoneclient(access='anaccesskey', secret='verysecret',
                                 credential_id='mycredential')
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)

        rsrc = stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc._create_keypair()

        # Test
        rs_data = resource_data_object.ResourceData.get_all(rsrc)

        # Verify
        self.assertEqual('mycredential', rs_data.get('credential_id'))
        self.assertEqual('anaccesskey', rs_data.get('access_key'))
        self.assertEqual('verysecret', rs_data.get('secret_key'))
        self.assertEqual('1234', rs_data.get('user_id'))
        self.assertEqual('password', rs_data.get('password'))
        self.assertEqual(rsrc.resource_id, rs_data.get('user_id'))
        self.assertEqual(5, len(rs_data))

    def test_get_user_id(self):
        # Setup
        self.stub_keystoneclient(access='anaccesskey', secret='verysecret')
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)
        rsrc = stack['signal_handler']

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        rs_data = resource_data_object.ResourceData.get_all(rsrc)

        # Verify
        self.assertEqual('1234', rs_data.get('user_id'))
        self.assertEqual('1234', rsrc.resource_id)
        self.assertEqual('1234', rsrc._get_user_id())

        # Check user id can still be fetched from resource_id
        # if the resource data is not there.
        resource_data_object.ResourceData.delete(rsrc, 'user_id')
        self.assertRaises(
            exception.NotFound, resource_data_object.ResourceData.get_val,
            rsrc, 'user_id')
        self.assertEqual('1234', rsrc._get_user_id())

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'get_heat_cfn_url')
    def test_FnGetAtt_alarm_url(self, mock_get):
        # Setup
        stack_id = stack_name = 'FnGetAtt-alarm-url'
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL,
                                   stack_name=stack_name,
                                   stack_id=stack_id)

        mock_get.return_value = 'http://server.test:8000/v1'

        rsrc = stack['signal_handler']
        created_time = datetime.datetime(2012, 11, 29, 13, 49, 37)
        rsrc.created_time = created_time

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        url = rsrc.FnGetAtt('AlarmUrl')

        # Verify
        # url parameters come in unexpected order, so the conversion has to be
        # done for comparison
        expected_url_path = "".join([
            'http://server.test:8000/v1/signal/',
            'arn%3Aopenstack%3Aheat%3A%3Atest_tenant%3Astacks/',
            'FnGetAtt-alarm-url/FnGetAtt-alarm-url/resources/',
            'signal_handler'])
        expected_url_params = {
            'Timestamp': ['2012-11-29T13:49:37Z'],
            'SignatureMethod': ['HmacSHA256'],
            'AWSAccessKeyId': ['4567'],
            'SignatureVersion': ['2'],
            'Signature': ['JWGilkQ4gHS+Y4+zhL41xSAC7+cUCwDsaIxq9xPYPKE=']}

        url_path, url_params = url.split('?', 1)
        url_params = urlparse.parse_qs(url_params)
        self.assertEqual(expected_url_path, url_path)
        self.assertEqual(expected_url_params, url_params)

        mock_get.assert_called_once_with()

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'get_heat_cfn_url')
    def test_FnGetAtt_alarm_url_is_cached(self, mock_get):
        # Setup
        stack_id = stack_name = 'FnGetAtt-alarm-url'
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL,
                                   stack_name=stack_name,
                                   stack_id=stack_id)

        mock_get.return_value = 'http://server.test:8000/v1'

        rsrc = stack['signal_handler']
        created_time = datetime.datetime(2012, 11, 29, 13, 49, 37)
        rsrc.created_time = created_time

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        first_url = rsrc.FnGetAtt('signal')
        second_url = rsrc.FnGetAtt('signal')

        # Verify
        self.assertEqual(first_url, second_url)
        mock_get.assert_called_once_with()

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'get_heat_url')
    def test_FnGetAtt_heat_signal(self, mock_get):
        # Setup
        stack = self._create_stack(TEMPLATE_HEAT_TEMPLATE_SIGNAL)

        mock_get.return_value = 'http://server.test:8004/v1'
        rsrc = stack['signal_handler']

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        signal = rsrc.FnGetAtt('signal')

        # Verify
        self.assertEqual('http://localhost:5000/v3', signal['auth_url'])
        self.assertEqual('aprojectid', signal['project_id'])
        self.assertEqual('1234', signal['user_id'])
        self.assertIn('username', signal)
        self.assertIn('password', signal)
        mock_get.assert_called_once_with()

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'get_heat_url')
    def test_FnGetAtt_heat_signal_is_cached(self, mock_get):
        # Setup
        stack = self._create_stack(TEMPLATE_HEAT_TEMPLATE_SIGNAL)

        mock_get.return_value = 'http://server.test:8004/v1'
        rsrc = stack['signal_handler']

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        first_url = rsrc.FnGetAtt('signal')
        second_url = rsrc.FnGetAtt('signal')

        # Verify
        self.assertEqual(first_url, second_url)
        mock_get.assert_called_once_with()

    @mock.patch('zaqarclient.queues.v2.queues.Queue.signed_url')
    def test_FnGetAtt_zaqar_signal(self, mock_signed_url):
        # Setup
        stack = self._create_stack(TEMPLATE_ZAQAR_SIGNAL)
        rsrc = stack['signal_handler']

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        signal = rsrc.FnGetAtt('signal')

        # Verify
        self.assertEqual('http://localhost:5000/v3', signal['auth_url'])
        self.assertEqual('aprojectid', signal['project_id'])
        self.assertEqual('1234', signal['user_id'])
        self.assertIn('username', signal)
        self.assertIn('password', signal)
        self.assertIn('queue_id', signal)
        mock_signed_url.assert_called_once_with(
            ['messages'], methods=['GET', 'DELETE'])

    @mock.patch('zaqarclient.queues.v2.queues.Queue.signed_url')
    def test_FnGetAtt_zaqar_signal_is_cached(self, mock_signed_url):
        # Setup
        stack = self._create_stack(TEMPLATE_ZAQAR_SIGNAL)
        rsrc = stack['signal_handler']

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        first_url = rsrc.FnGetAtt('signal')
        second_url = rsrc.FnGetAtt('signal')

        # Verify
        self.assertEqual(first_url, second_url)
        mock_signed_url.assert_called_once_with(
            ['messages'], methods=['GET', 'DELETE'])

    @mock.patch('swiftclient.client.Connection.put_container')
    @mock.patch('swiftclient.client.Connection.put_object')
    @mock.patch.object(swift.SwiftClientPlugin, 'get_temp_url')
    def test_FnGetAtt_swift_signal(self, mock_get_url,
                                   mock_put_object, mock_put_container):
        # Setup
        mock_get_url.return_value = (
            'http://192.0.2.1/v1/AUTH_aprojectid/foo/bar')
        stack = self._create_stack(TEMPLATE_SWIFT_SIGNAL)
        rsrc = stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        found_url = rsrc.FnGetAtt('AlarmUrl')

        # Verify
        self.assertEqual('http://192.0.2.1/v1/AUTH_aprojectid/foo/bar',
                         found_url)

        self.assertEqual(1, mock_put_container.call_count)
        self.assertEqual(1, mock_put_object.call_count)
        self.assertEqual(1, mock_get_url.call_count)

    @mock.patch('swiftclient.client.Connection.put_container')
    @mock.patch('swiftclient.client.Connection.put_object')
    @mock.patch.object(swift.SwiftClientPlugin, 'get_temp_url')
    def test_FnGetAtt_swift_signal_is_cached(self, mock_get_url,
                                             mock_put_object,
                                             mock_put_container):
        # Setup
        mock_get_url.return_value = (
            'http://192.0.2.1/v1/AUTH_aprojectid/foo/bar')
        stack = self._create_stack(TEMPLATE_SWIFT_SIGNAL)
        rsrc = stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        first_url = rsrc.FnGetAtt('AlarmUrl')
        second_url = rsrc.FnGetAtt('AlarmUrl')

        # Verify
        self.assertEqual(first_url, second_url)

        self.assertEqual(1, mock_put_container.call_count)
        self.assertEqual(1, mock_put_object.call_count)
        self.assertEqual(1, mock_get_url.call_count)

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'get_heat_cfn_url')
    def test_FnGetAtt_delete(self, mock_get):
        # Setup
        mock_get.return_value = 'http://server.test:8000/v1'
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)

        rsrc = stack['signal_handler']
        rsrc.resource_id_set('signal')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertIn('http://server.test:8000/v1/signal',
                      rsrc.FnGetAtt('AlarmUrl'))

        # Test
        scheduler.TaskRunner(rsrc.delete)()

        # Verify
        self.assertIn('http://server.test:8000/v1/signal',
                      rsrc.FnGetAtt('AlarmUrl'))

        self.assertEqual(2, mock_get.call_count)

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'get_heat_url')
    def test_FnGetAtt_heat_signal_delete(self, mock_get):
        # Setup
        mock_get.return_value = 'http://server.test:8004/v1'
        stack = self._create_stack(TEMPLATE_HEAT_TEMPLATE_SIGNAL)
        rsrc = stack['signal_handler']

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        def validate_signal():
            signal = rsrc.FnGetAtt('signal')
            self.assertEqual('http://localhost:5000/v3', signal['auth_url'])
            self.assertEqual('aprojectid', signal['project_id'])
            self.assertEqual('1234', signal['user_id'])
            self.assertIn('username', signal)
            self.assertIn('password', signal)

        # Test
        validate_signal()
        scheduler.TaskRunner(rsrc.delete)()
        validate_signal()

        self.assertEqual(2, mock_get.call_count)

    @mock.patch('swiftclient.client.Connection.delete_container')
    @mock.patch('swiftclient.client.Connection.delete_object')
    @mock.patch('swiftclient.client.Connection.get_container')
    @mock.patch.object(swift.SwiftClientPlugin, 'get_temp_url')
    @mock.patch('swiftclient.client.Connection.head_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    @mock.patch('swiftclient.client.Connection.put_object')
    def test_FnGetAtt_swift_signal_delete(self, mock_put_object,
                                          mock_put_container, mock_head,
                                          mock_get_temp, mock_get_container,
                                          mock_delete_object,
                                          mock_delete_container):
        # Setup
        stack = self._create_stack(TEMPLATE_SWIFT_SIGNAL)

        mock_get_temp.return_value = (
            'http://server.test/v1/AUTH_aprojectid/foo/bar')
        mock_get_container.return_value = ({}, [{'name': 'bar'}])
        mock_head.return_value = {'x-container-object-count': 0}

        rsrc = stack['signal_handler']
        mock_name = mock.MagicMock()
        mock_name.return_value = 'bar'
        rsrc.physical_resource_name = mock_name

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertEqual('http://server.test/v1/AUTH_aprojectid/foo/bar',
                         rsrc.FnGetAtt('AlarmUrl'))

        # Test
        scheduler.TaskRunner(rsrc.delete)()

        # Verify
        self.assertEqual('http://server.test/v1/AUTH_aprojectid/foo/bar',
                         rsrc.FnGetAtt('AlarmUrl'))

        self.assertEqual(2, mock_put_container.call_count)
        self.assertEqual(2, mock_get_temp.call_count)
        self.assertEqual(2, mock_put_object.call_count)
        self.assertEqual(2, mock_put_container.call_count)
        self.assertEqual(1, mock_get_container.call_count)
        self.assertEqual(1, mock_delete_object.call_count)
        self.assertEqual(1, mock_delete_container.call_count)
        self.assertEqual(1, mock_head.call_count)

    @mock.patch('zaqarclient.queues.v2.queues.Queue.signed_url')
    def test_FnGetAtt_zaqar_signal_delete(self, mock_signed_url):
        # Setup
        stack = self._create_stack(TEMPLATE_ZAQAR_SIGNAL)

        mock_delete = mock.MagicMock()

        rsrc = stack['signal_handler']
        rsrc._delete_zaqar_signal_queue = mock_delete

        stack.create()

        # Test
        signal = rsrc.FnGetAtt('signal')

        # Verify
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('http://localhost:5000/v3', signal['auth_url'])
        self.assertEqual('aprojectid', signal['project_id'])
        self.assertEqual('1234', signal['user_id'])
        self.assertIn('username', signal)
        self.assertIn('password', signal)
        self.assertIn('queue_id', signal)

        scheduler.TaskRunner(rsrc.delete)()

        self.assertEqual('http://localhost:5000/v3', signal['auth_url'])
        self.assertEqual('aprojectid', signal['project_id'])
        self.assertEqual('1234', signal['user_id'])
        self.assertIn('username', signal)
        self.assertIn('password', signal)
        self.assertIn('queue_id', signal)

        mock_delete.assert_called_once_with()

    def test_delete_not_found(self):
        # Setup
        class FakeKeystoneClientFail(fake_ks.FakeKeystoneClient):
            def delete_stack_user(self, name):
                raise kc_exceptions.NotFound()
        self.stub_keystoneclient(fake_client=FakeKeystoneClientFail())

        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)
        rsrc = stack['signal_handler']

        # Test
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

    @mock.patch.object(generic_resource.SignalResource, 'handle_signal')
    def test_signal(self, mock_handle):
        # Setup
        test_d = {'Data': 'foo', 'Reason': 'bar',
                  'Status': 'SUCCESS', 'UniqueId': '123'}

        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)
        rsrc = stack['signal_handler']

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertTrue(rsrc.requires_deferred_auth)

        # Test
        result = rsrc.signal(details=test_d)
        mock_handle.assert_called_once_with(test_d)
        self.assertTrue(result)

    @mock.patch.object(generic_resource.SignalResource, 'handle_signal')
    def test_handle_signal_no_reraise_deleted(self, mock_handle):
        # Setup
        test_d = {'Data': 'foo', 'Reason': 'bar',
                  'Status': 'SUCCESS', 'UniqueId': '123'}

        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)

        mock_handle.side_effect = exception.ResourceNotAvailable(
            resource_name='test')
        rsrc = stack['signal_handler']

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # In the midst of handling a signal, an update happens on the
        # db resource concurrently, deleting it

        # Test exception not re-raised in DELETE case
        res_obj = stack.context.session.query(
            models.Resource).get(rsrc.id)
        res_obj.update({'action': 'DELETE'})
        rsrc._db_res_is_deleted = True
        rsrc._handle_signal(details=test_d)
        mock_handle.assert_called_once_with(test_d)

    @mock.patch.object(generic_resource.SignalResource, '_add_event')
    def test_signal_different_reason_types(self, mock_add):
        # Setup
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)

        rsrc = stack['signal_handler']

        # Verify
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertTrue(rsrc.requires_deferred_auth)

        ceilo_details = {'current': 'foo', 'reason': 'apples',
                         'previous': 'SUCCESS'}
        ceilo_expected = 'alarm state changed from SUCCESS to foo (apples)'

        str_details = 'a string details'
        str_expected = str_details

        none_details = None
        none_expected = 'No signal details provided'

        # Test
        for test_d in (ceilo_details, str_details, none_details):
            rsrc.signal(details=test_d)

        # Verify
        mock_add.assert_any_call('SIGNAL', 'COMPLETE', ceilo_expected)
        mock_add.assert_any_call('SIGNAL', 'COMPLETE', str_expected)
        mock_add.assert_any_call('SIGNAL', 'COMPLETE', none_expected)

    @mock.patch.object(generic_resource.SignalResource, 'handle_signal')
    @mock.patch.object(generic_resource.SignalResource, '_add_event')
    def test_signal_plugin_reason(self, mock_add, mock_handle):
        # Setup
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)

        rsrc = stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        signal_details = {'status': 'COMPLETE'}
        ret_expected = 'Received COMPLETE signal'
        mock_handle.return_value = ret_expected

        # Test
        rsrc.signal(details=signal_details)

        # Verify
        mock_handle.assert_called_once_with(signal_details)

        # Ensure if handle_signal returns data, we use it as the reason
        mock_add.assert_any_call('SIGNAL', 'COMPLETE',
                                 'Signal: %s' % ret_expected)

    def test_signal_wrong_resource(self):
        # Setup
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)

        rsrc = stack['resource_X']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        # assert that we get the correct exception when calling a
        # resource.signal() that does not have a handle_signal()
        err_metadata = {'Data': 'foo', 'Status': 'SUCCESS', 'UniqueId': '123'}
        self.assertRaises(exception.ResourceActionNotSupported, rsrc.signal,
                          details=err_metadata)

    @mock.patch.object(generic_resource.SignalResource, 'handle_signal')
    def test_signal_reception_failed_call(self, mock_handle):
        # Setup
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)

        test_d = {'Data': 'foo', 'Reason': 'bar',
                  'Status': 'SUCCESS', 'UniqueId': '123'}

        mock_handle.side_effect = ValueError()

        rsrc = stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Test
        # assert that we get the correct exception from resource.signal()
        # when resource.handle_signal() raises an exception.
        self.assertRaises(exception.ResourceFailure,
                          rsrc.signal, details=test_d)

        # Verify
        mock_handle.assert_called_once_with(test_d)

    def _run_test_signal_not_supported_action(self, action):
        # Setup
        stack = self._create_stack(TEMPLATE_CFN_SIGNAL)

        rsrc = stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.action = action

        # Test
        err_metadata = {'Data': 'foo', 'Status': 'SUCCESS', 'UniqueId': '123'}
        msg = 'Signal resource during %s is not supported.' % action
        exc = self.assertRaises(exception.NotSupported, rsrc.signal,
                                details=err_metadata)
        self.assertEqual(msg, six.text_type(exc))

    def test_signal_in_delete_state(self):
        # assert that we get the correct exception when calling a
        # resource.signal() that is in delete action.
        self._run_test_signal_not_supported_action('DELETE')

    def test_signal_in_suspend_state(self):
        # assert that we get the correct exception when calling a
        # resource.signal() that is in suspend action.
        self._run_test_signal_not_supported_action('SUSPEND')
