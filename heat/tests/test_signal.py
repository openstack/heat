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
import uuid

from keystoneclient import exceptions as kc_exceptions
import mox
import six
from six.moves.urllib import parse as urlparse

from heat.common import exception
from heat.common import template_format
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.objects import resource_data as resource_data_object
from heat.tests import common
from heat.tests import fakes
from heat.tests import generic_resource
from heat.tests import utils


test_cfn_template_signal = '''
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

test_heat_template_signal = '''
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

test_swift_template_signal = '''
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

test_zaqar_template_signal = '''
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

    def setUp(self):
        super(SignalTest, self).setUp()
        self.stack_id = 'STACKABCD1234'

    def tearDown(self):
        super(SignalTest, self).tearDown()

    def create_stack(self, templ=test_cfn_template_signal,
                     stack_name='test_stack', stub=True):
        tpl = template.Template(template_format.parse(templ))
        ctx = utils.dummy_context()
        ctx.tenant_id = 'test_tenant'
        stack = parser.Stack(ctx, stack_name, tpl,
                             disable_rollback=True)

        # Stub out the stack ID so we have a known value
        with utils.UUIDStub(self.stack_id):
            stack.store()
        if stub:
            self.stub_keystoneclient()

        return stack

    def test_resource_data(self):
        self.stub_keystoneclient(
            access='anaccesskey',
            secret='verysecret',
            credential_id='mycredential')
        self.stack = self.create_stack(stack_name='resource_data_test',
                                       stub=False)
        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc._create_keypair()

        # Ensure the resource data has been stored correctly
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual('mycredential', rs_data.get('credential_id'))
        self.assertEqual('anaccesskey', rs_data.get('access_key'))
        self.assertEqual('verysecret', rs_data.get('secret_key'))
        self.assertEqual('1234', rs_data.get('user_id'))
        self.assertEqual(rsrc.resource_id, rs_data.get('user_id'))
        self.assertEqual(4, len(list(six.iterkeys(rs_data))))
        self.m.VerifyAll()

    def test_get_user_id(self):
        self.stack = self.create_stack(stack_name='resource_data_test',
                                       stub=False)
        self.stub_keystoneclient(access='anaccesskey', secret='verysecret')
        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Ensure the resource data has been stored correctly
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
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
        self.m.VerifyAll()

    def test_FnGetAtt_Alarm_Url(self):
        self.stack = self.create_stack()
        self.m.StubOutWithMock(self.stack.clients.client_plugin('heat'),
                               'get_heat_cfn_url')

        self.stack.clients.client_plugin('heat').get_heat_cfn_url().AndReturn(
            'http://server.test:8000/v1')

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        created_time = datetime.datetime(2012, 11, 29, 13, 49, 37)
        rsrc.created_time = created_time
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # url parameters come in unexpected order, so the conversion has to be
        # done for comparison
        expected_url_path = "".join([
            'http://server.test:8000/v1/signal/',
            'arn%3Aopenstack%3Aheat%3A%3Atest_tenant%3Astacks%2F',
            'test_stack%2FSTACKABCD1234%2Fresources%2F',
            'signal_handler'])
        expected_url_params = {
            'Timestamp': ['2012-11-29T13:49:37Z'],
            'SignatureMethod': ['HmacSHA256'],
            'AWSAccessKeyId': ['4567'],
            'SignatureVersion': ['2'],
            'Signature': ['VW4NyvRO4WhQdsQ4rxl5JMUr0AlefHN6OLsRz9oZyls=']}

        url = rsrc.FnGetAtt('AlarmUrl')
        url_path, url_params = url.split('?', 1)
        url_params = urlparse.parse_qs(url_params)
        self.assertEqual(expected_url_path, url_path)
        self.assertEqual(expected_url_params, url_params)
        self.m.VerifyAll()

    def test_FnGetAtt_Alarm_Url_is_cached(self):
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        first_url = rsrc.FnGetAtt('signal')
        second_url = rsrc.FnGetAtt('signal')
        self.assertEqual(first_url, second_url)
        self.m.VerifyAll()

    def test_FnGetAtt_Heat_Signal(self):
        self.stack = self.create_stack(test_heat_template_signal)
        self.m.StubOutWithMock(self.stack.clients.client_plugin('heat'),
                               'get_heat_url')

        self.stack.clients.client_plugin('heat').get_heat_url().AndReturn(
            'http://server.test:8004/v1')

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        signal = rsrc.FnGetAtt('signal')
        self.assertEqual('http://localhost:5000/v3', signal['auth_url'])
        self.assertEqual('aprojectid', signal['project_id'])
        self.assertEqual('1234', signal['user_id'])
        self.assertIn('username', signal)
        self.assertIn('password', signal)
        self.m.VerifyAll()

    def test_FnGetAtt_Heat_Signal_is_cached(self):
        self.stack = self.create_stack(test_heat_template_signal)

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        first_url = rsrc.FnGetAtt('signal')
        second_url = rsrc.FnGetAtt('signal')
        self.assertEqual(first_url, second_url)
        self.m.VerifyAll()

    def test_FnGetAtt_Zaqar_Signal(self):
        self.stack = self.create_stack(test_zaqar_template_signal)

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        signal = rsrc.FnGetAtt('signal')
        self.assertEqual('http://localhost:5000/v3', signal['auth_url'])
        self.assertEqual('aprojectid', signal['project_id'])
        self.assertEqual('1234', signal['user_id'])
        self.assertIn('username', signal)
        self.assertIn('password', signal)
        self.assertIn('queue_id', signal)
        self.m.VerifyAll()

    def test_FnGetAtt_Zaqar_Signal_is_cached(self):
        self.stack = self.create_stack(test_zaqar_template_signal)

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        first_url = rsrc.FnGetAtt('signal')
        second_url = rsrc.FnGetAtt('signal')
        self.assertEqual(first_url, second_url)
        self.m.VerifyAll()

    def test_FnGetAtt_Swift_Signal(self):
        self.stack = self.create_stack(test_swift_template_signal)
        self.m.StubOutWithMock(self.stack.clients.client('swift'),
                               'put_container')
        self.m.StubOutWithMock(self.stack.clients.client('swift'),
                               'put_object')
        self.m.StubOutWithMock(self.stack.clients.client_plugin('swift'),
                               'get_temp_url')

        self.stack.clients.client('swift').put_container(
            mox.IgnoreArg()).AndReturn(None)
        self.stack.clients.client_plugin('swift').get_temp_url(
            mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
            'http://192.0.2.1/v1/AUTH_aprojectid/foo/bar')
        self.stack.clients.client('swift').put_object(
            mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(None)

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertEqual('http://192.0.2.1/v1/AUTH_aprojectid/foo/bar',
                         rsrc.FnGetAtt('AlarmUrl'))
        self.m.VerifyAll()

    def test_FnGetAtt_Swift_Signal_is_cached(self):
        self.stack = self.create_stack(test_swift_template_signal)
        self.m.StubOutWithMock(self.stack.clients.client('swift'),
                               'put_container')
        self.m.StubOutWithMock(self.stack.clients.client('swift'),
                               'put_object')
        self.m.StubOutWithMock(self.stack.clients.client_plugin('swift'),
                               'get_temp_url')

        self.stack.clients.client('swift').put_container(
            mox.IgnoreArg()).AndReturn(None)
        self.stack.clients.client_plugin('swift').get_temp_url(
            mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
            'http://192.0.2.1/v1/AUTH_aprojectid/foo/' + uuid.uuid4().hex)
        self.stack.clients.client('swift').put_object(
            mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(None)

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        first_url = rsrc.FnGetAtt('signal')
        second_url = rsrc.FnGetAtt('signal')
        self.assertEqual(first_url, second_url)
        self.m.VerifyAll()

    def test_FnGetAtt_delete(self):
        self.stack = self.create_stack()
        self.m.StubOutWithMock(self.stack.clients.client_plugin('heat'),
                               'get_heat_cfn_url')
        self.stack.clients.client_plugin('heat').get_heat_cfn_url().AndReturn(
            'http://server.test:8000/v1')
        self.stack.clients.client_plugin('heat').get_heat_cfn_url().AndReturn(
            'http://server.test:8000/v1')

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        rsrc.resource_id_set('signal')
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertIn('http://server.test:8000/v1/signal',
                      rsrc.FnGetAtt('AlarmUrl'))

        scheduler.TaskRunner(rsrc.delete)()
        self.assertIn('http://server.test:8000/v1/signal',
                      rsrc.FnGetAtt('AlarmUrl'))

        self.m.VerifyAll()

    def test_FnGetAtt_Heat_Signal_delete(self):
        self.stack = self.create_stack(test_heat_template_signal)
        self.m.StubOutWithMock(self.stack.clients.client_plugin('heat'),
                               'get_heat_url')
        self.stack.clients.client_plugin('heat').get_heat_url().AndReturn(
            'http://server.test:8004/v1')
        self.stack.clients.client_plugin('heat').get_heat_url().AndReturn(
            'http://server.test:8004/v1')

        def validate_signal():
            signal = rsrc.FnGetAtt('signal')
            self.assertEqual('http://localhost:5000/v3', signal['auth_url'])
            self.assertEqual('aprojectid', signal['project_id'])
            self.assertEqual('1234', signal['user_id'])
            self.assertIn('username', signal)
            self.assertIn('password', signal)

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        validate_signal()
        scheduler.TaskRunner(rsrc.delete)()
        validate_signal()
        self.m.VerifyAll()

    def test_FnGetAtt_Swift_Signal_delete(self):
        self.stack = self.create_stack(test_swift_template_signal)
        self.m.StubOutWithMock(self.stack.clients.client('swift'),
                               'put_container')
        self.m.StubOutWithMock(self.stack.clients.client('swift'),
                               'put_object')
        self.m.StubOutWithMock(self.stack.clients.client_plugin('swift'),
                               'get_temp_url')
        self.m.StubOutWithMock(self.stack.clients.client('swift'),
                               'delete_object')
        self.m.StubOutWithMock(self.stack.clients.client('swift'),
                               'delete_container')
        self.m.StubOutWithMock(self.stack.clients.client('swift'),
                               'head_container')

        self.stack.clients.client('swift').put_container(
            mox.IgnoreArg()).AndReturn(None)
        self.stack.clients.client_plugin('swift').get_temp_url(
            mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
            'http://server.test/v1/AUTH_aprojectid/foo/bar')
        self.stack.clients.client('swift').put_object(
            mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(None)

        self.stack.clients.client('swift').put_container(
            mox.IgnoreArg()).AndReturn(None)
        self.stack.clients.client_plugin('swift').get_temp_url(
            mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
            'http://server.test/v1/AUTH_aprojectid/foo/bar')
        self.stack.clients.client('swift').put_object(
            mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(None)
        self.stack.clients.client('swift').delete_object(
            mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(None)
        self.stack.clients.client('swift').head_container(
            mox.IgnoreArg()).AndReturn({'x-container-object-count': 0})
        self.stack.clients.client('swift').delete_container(
            mox.IgnoreArg()).AndReturn(None)

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertEqual('http://server.test/v1/AUTH_aprojectid/foo/bar',
                         rsrc.FnGetAtt('AlarmUrl'))

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual('http://server.test/v1/AUTH_aprojectid/foo/bar',
                         rsrc.FnGetAtt('AlarmUrl'))

        self.m.VerifyAll()

    def test_FnGetAtt_Zaqar_Signal_delete(self):
        self.stack = self.create_stack(test_zaqar_template_signal)
        rsrc = self.stack['signal_handler']
        self.m.StubOutWithMock(rsrc, '_delete_zaqar_signal_queue')
        rsrc._delete_zaqar_signal_queue().AndReturn(None)

        self.m.ReplayAll()
        self.stack.create()

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        signal = rsrc.FnGetAtt('signal')
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
        self.m.VerifyAll()

    def test_delete_not_found(self):
        self.stack = self.create_stack(stack_name='test_delete_not_found',
                                       stub=False)

        class FakeKeystoneClientFail(fakes.FakeKeystoneClient):
            def delete_stack_user(self, name):
                raise kc_exceptions.NotFound()
        self.stub_keystoneclient(fake_client=FakeKeystoneClientFail())

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_signal(self):
        test_d = {'Data': 'foo', 'Reason': 'bar',
                  'Status': 'SUCCESS', 'UniqueId': '123'}

        self.stack = self.create_stack()

        # to confirm we get a call to handle_signal
        self.m.StubOutWithMock(generic_resource.SignalResource,
                               'handle_signal')
        generic_resource.SignalResource.handle_signal(test_d).AndReturn(None)

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertTrue(rsrc.requires_deferred_auth)

        rsrc.signal(details=test_d)

        self.m.VerifyAll()

    def test_signal_no_action(self):
        test_d = {'Data': 'foo', 'Reason': 'bar',
                  'Status': 'SUCCESS', 'UniqueId': '123'}

        self.stack = self.create_stack()
        self.stack.create()

        # mock a NoActionRequired from handle_signal()
        self.m.StubOutWithMock(generic_resource.SignalResource,
                               'handle_signal')
        generic_resource.SignalResource.handle_signal(test_d).AndRaise(
            exception.NoActionRequired())

        # _add_event should not be called.
        self.m.StubOutWithMock(generic_resource.SignalResource,
                               '_add_event')

        self.m.ReplayAll()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertTrue(rsrc.requires_deferred_auth)

        rsrc.signal(details=test_d)

        self.m.VerifyAll()

    def test_signal_different_reason_types(self):
        self.stack = self.create_stack()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertTrue(rsrc.requires_deferred_auth)

        ceilo_details = {'current': 'foo', 'reason': 'apples',
                         'previous': 'SUCCESS'}
        ceilo_expected = 'alarm state changed from SUCCESS to foo (apples)'

        watch_details = {'state': 'go_for_it'}
        watch_expected = 'alarm state changed to go_for_it'

        str_details = 'a string details'
        str_expected = str_details

        none_details = None
        none_expected = 'No signal details provided'

        # to confirm we get a string reason
        self.m.StubOutWithMock(generic_resource.SignalResource,
                               '_add_event')
        generic_resource.SignalResource._add_event(
            'SIGNAL', 'COMPLETE', ceilo_expected).AndReturn(None)
        generic_resource.SignalResource._add_event(
            'SIGNAL', 'COMPLETE', watch_expected).AndReturn(None)
        generic_resource.SignalResource._add_event(
            'SIGNAL', 'COMPLETE', str_expected).AndReturn(None)
        generic_resource.SignalResource._add_event(
            'SIGNAL', 'COMPLETE', none_expected).AndReturn(None)

        self.m.ReplayAll()

        for test_d in (ceilo_details, watch_details, str_details,
                       none_details):
            rsrc.signal(details=test_d)

        self.m.VerifyAll()

    def test_signal_plugin_reason(self):
        # Ensure if handle_signal returns data, we use it as the reason
        self.stack = self.create_stack()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.StubOutWithMock(generic_resource.SignalResource,
                               'handle_signal')
        signal_details = {'status': 'COMPLETE'}
        ret_expected = "Received COMPLETE signal"
        generic_resource.SignalResource.handle_signal(
            signal_details).AndReturn(ret_expected)

        self.m.StubOutWithMock(generic_resource.SignalResource,
                               '_add_event')
        generic_resource.SignalResource._add_event(
            'SIGNAL', 'COMPLETE', 'Signal: %s' % ret_expected).AndReturn(None)
        self.m.ReplayAll()

        rsrc.signal(details=signal_details)
        self.m.VerifyAll()

    def test_signal_wrong_resource(self):
        # assert that we get the correct exception when calling a
        # resource.signal() that does not have a handle_signal()
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['resource_X']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        err_metadata = {'Data': 'foo', 'Status': 'SUCCESS', 'UniqueId': '123'}
        self.assertRaises(exception.ResourceActionNotSupported, rsrc.signal,
                          details=err_metadata)

        self.m.VerifyAll()

    def _test_signal_not_supported_action(self, action='DELETE'):
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        # manually override the action to DELETE
        rsrc.action = action

        err_metadata = {'Data': 'foo', 'Status': 'SUCCESS', 'UniqueId': '123'}
        msg = 'Signal resource during %s is not supported.' % action
        exc = self.assertRaises(exception.NotSupported, rsrc.signal,
                                details=err_metadata)
        self.assertEqual(msg, six.text_type(exc))
        self.m.VerifyAll()

    def test_signal_in_delete_state(self):
        # assert that we get the correct exception when calling a
        # resource.signal() that is in delete action.
        self._test_signal_not_supported_action()

    def test_signal_in_suspend_state(self):
        # assert that we get the correct exception when calling a
        # resource.signal() that is in suspend action.
        self._test_signal_not_supported_action(action='SUSPEND')

    def test_signal_reception_failed_call(self):
        # assert that we get the correct exception from resource.signal()
        # when resource.handle_signal() raises an exception.
        self.stack = self.create_stack()

        test_d = {'Data': 'foo', 'Reason': 'bar',
                  'Status': 'SUCCESS', 'UniqueId': '123'}

        # to confirm we get a call to handle_signal
        self.m.StubOutWithMock(generic_resource.SignalResource,
                               'handle_signal')
        generic_resource.SignalResource.handle_signal(test_d).AndRaise(
            ValueError)

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertRaises(exception.ResourceFailure,
                          rsrc.signal, details=test_d)

        self.m.VerifyAll()
