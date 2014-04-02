
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

from keystoneclient import exceptions as kc_exceptions
from oslo.config import cfg

from heat.common import exception
from heat.common import template_format

from heat.db import api as db_api

from heat.engine import clients
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import stack_user

from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import generic_resource
from heat.tests import utils


test_template_signal = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a test.",
  "Parameters" : {},
  "Resources" : {
    "signal_handler" : {"Type" : "SignalResourceType"},
    "resource_X" : {"Type" : "GenericResourceType"}
  }
}
'''


class SignalTest(HeatTestCase):

    def setUp(self):
        super(SignalTest, self).setUp()
        utils.setup_dummy_db()

        resource._register_class('SignalResourceType',
                                 generic_resource.SignalResource)
        resource._register_class('GenericResourceType',
                                 generic_resource.GenericResource)

        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

        self.stack_id = 'STACKABCD1234'
        self.fc = fakes.FakeKeystoneClient()

    def tearDown(self):
        super(SignalTest, self).tearDown()
        utils.reset_dummy_db()

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the stack is properly cleaned up
    def create_stack(self, stack_name='test_stack', stub=True):
        temp = template_format.parse(test_template_signal)
        template = parser.Template(temp)
        ctx = utils.dummy_context()
        ctx.tenant_id = 'test_tenant'
        stack = parser.Stack(ctx, stack_name, template,
                             disable_rollback=True)

        # Stub out the stack ID so we have a known value
        with utils.UUIDStub(self.stack_id):
            stack.store()

        if stub:
            self.m.StubOutWithMock(stack_user.StackUser, 'keystone')
            stack_user.StackUser.keystone().MultipleTimes().AndReturn(
                self.fc)

        self.m.ReplayAll()

        return stack

    @utils.stack_delete_after
    def test_handle_create_fail_keypair_raise(self):
        self.stack = self.create_stack(stack_name='create_fail_keypair')

        self.m.StubOutWithMock(stack_user.StackUser, '_create_keypair')
        stack_user.StackUser._create_keypair().AndRaise(Exception('Failed'))
        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['signal_handler']
        rs_data = db_api.resource_data_get_all(rsrc)
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.assertIn('Failed', rsrc.status_reason)
        self.assertEqual('1234', rs_data.get('user_id'))
        self.assertIsNone(rsrc.resource_id)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_resource_data(self):
        self.stack = self.create_stack(stack_name='resource_data_test',
                                       stub=False)

        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        clients.OpenStackClients.keystone().MultipleTimes().AndReturn(
            fakes.FakeKeystoneClient(
                access='anaccesskey',
                secret='verysecret',
                credential_id='mycredential'))
        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Ensure the resource data has been stored correctly
        rs_data = db_api.resource_data_get_all(rsrc)
        self.assertEqual('mycredential', rs_data.get('credential_id'))
        self.assertEqual('anaccesskey', rs_data.get('access_key'))
        self.assertEqual('verysecret', rs_data.get('secret_key'))
        self.assertEqual('1234', rs_data.get('user_id'))
        self.assertEqual(rsrc.resource_id, rs_data.get('user_id'))
        self.assertEqual(4, len(rs_data.keys()))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_get_user_id(self):
        self.stack = self.create_stack(stack_name='resource_data_test',
                                       stub=False)

        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        clients.OpenStackClients.keystone().MultipleTimes().AndReturn(
            fakes.FakeKeystoneClient(
                access='anaccesskey', secret='verysecret'))
        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Ensure the resource data has been stored correctly
        rs_data = db_api.resource_data_get_all(rsrc)
        self.assertEqual('1234', rs_data.get('user_id'))
        self.assertEqual('1234', rsrc.resource_id)
        self.assertEqual('1234', rsrc._get_user_id())

        # Check user id can still be fetched from resource_id
        # if the resource data is not there.
        db_api.resource_data_delete(rsrc, 'user_id')
        self.assertRaises(
            exception.NotFound, db_api.resource_data_get, rsrc, 'user_id')
        self.assertEqual('1234', rsrc._get_user_id())
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_FnGetAtt_Alarm_Url(self):
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        created_time = datetime.datetime(2012, 11, 29, 13, 49, 37)
        rsrc.created_time = created_time
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        expected_url = "".join([
            'http://server.test:8000/v1/signal/',
            'arn%3Aopenstack%3Aheat%3A%3Atest_tenant%3Astacks%2F',
            'test_stack%2FSTACKABCD1234%2Fresources%2F',
            'signal_handler?',
            'Timestamp=2012-11-29T13%3A49%3A37Z&',
            'SignatureMethod=HmacSHA256&',
            'AWSAccessKeyId=4567&',
            'SignatureVersion=2&',
            'Signature=',
            'VW4NyvRO4WhQdsQ4rxl5JMUr0AlefHN6OLsRz9oZyls%3D'])

        self.assertEqual(expected_url, rsrc.FnGetAtt('AlarmUrl'))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_FnGetAtt_Alarm_Url_is_cached(self):
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        first_url = rsrc.FnGetAtt('AlarmUrl')
        second_url = rsrc.FnGetAtt('AlarmUrl')
        self.assertEqual(first_url, second_url)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_FnGetAtt_delete(self):
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertIn('http://server.test:8000/v1/signal',
                      rsrc.FnGetAtt('AlarmUrl'))

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual('None', rsrc.FnGetAtt('AlarmUrl'))

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_delete_not_found(self):
        self.stack = self.create_stack(stack_name='test_delete_not_found',
                                       stub=False)

        class FakeKeystoneClientFail(fakes.FakeKeystoneClient):
            def delete_stack_user(self, name):
                raise kc_exceptions.NotFound()

        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        clients.OpenStackClients.keystone().MultipleTimes().AndReturn(
            FakeKeystoneClientFail())
        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    @utils.stack_delete_after
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

    @utils.stack_delete_after
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

        # signal from a successful deployment
        sds_details = {'deploy_stdout': 'foo', 'deploy_stderr': 'bar',
                       'deploy_status_code': 0}
        sds_expected = 'deployment succeeded'

        # signal from a failed deployment
        sdf_details = {'deploy_stdout': 'foo', 'deploy_stderr': 'bar',
                       'deploy_status_code': -1}
        sdf_expected = 'deployment failed (-1)'

        # to confirm we get a string reason
        self.m.StubOutWithMock(generic_resource.SignalResource,
                               '_add_event')
        generic_resource.SignalResource._add_event(
            'signal', 'COMPLETE', ceilo_expected).AndReturn(None)
        generic_resource.SignalResource._add_event(
            'signal', 'COMPLETE', watch_expected).AndReturn(None)
        generic_resource.SignalResource._add_event(
            'signal', 'COMPLETE', str_expected).AndReturn(None)
        generic_resource.SignalResource._add_event(
            'signal', 'COMPLETE', none_expected).AndReturn(None)
        generic_resource.SignalResource._add_event(
            'signal', 'COMPLETE', sds_expected).AndReturn(None)
        generic_resource.SignalResource._add_event(
            'signal', 'COMPLETE', sdf_expected).AndReturn(None)

        self.m.ReplayAll()

        for test_d in (ceilo_details, watch_details, str_details,
                       none_details, sds_details, sdf_details):
            rsrc.signal(details=test_d)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        # Since we unset the stubs above we must re-stub keystone to keep the
        # test isolated from keystoneclient. The unset stubs is done so that we
        # do not have to mock out all of the deleting that the
        # stack_delete_after decorator will do during cleanup.
        self.m.StubOutWithMock(self.stack.clients, 'keystone')
        self.stack.clients.keystone().AndReturn(self.fc)

        self.m.ReplayAll()

    @utils.stack_delete_after
    def test_signal_wrong_resource(self):
        # assert that we get the correct exception when calling a
        # resource.signal() that does not have a handle_signal()
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['resource_X']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        err_metadata = {'Data': 'foo', 'Status': 'SUCCESS', 'UniqueId': '123'}
        self.assertRaises(exception.ResourceFailure, rsrc.signal,
                          details=err_metadata)

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_signal_reception_wrong_state(self):
        # assert that we get the correct exception when calling a
        # resource.signal() that is in having a destructive action.
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['signal_handler']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        # manually override the action to DELETE
        rsrc.action = rsrc.DELETE

        err_metadata = {'Data': 'foo', 'Status': 'SUCCESS', 'UniqueId': '123'}
        self.assertRaises(exception.ResourceFailure, rsrc.signal,
                          details=err_metadata)

        self.m.VerifyAll()

    @utils.stack_delete_after
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
