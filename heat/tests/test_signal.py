# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.config import cfg

from heat.tests import generic_resource
from heat.tests import fakes
from heat.tests.common import HeatTestCase
from heat.tests import utils

from heat.common import context
from heat.common import exception
from heat.common import template_format

from heat.engine import parser
from heat.engine import resource
from heat.engine import signal_responder as sr


test_template_signal = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a test.",
  "Parameters" : {},
  "Resources" : {
    "signal_handler" : {"Type" : "SignalResourceType"},
    "resource_X" : {"Type" : "GenericResourceType"}
  },
  "Outputs": {
    "signed_url": {"Fn::GetAtt": ["signal_handler", "AlarmUrl"]}
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
                             'http://127.0.0.1:8000/v1/waitcondition')

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
        ctx = context.get_admin_context()
        ctx.tenant_id = 'test_tenant'
        stack = parser.Stack(ctx, stack_name, template,
                             disable_rollback=True)

        # Stub out the stack ID so we have a known value
        with utils.UUIDStub(self.stack_id):
            stack.store()

        if stub:
            self.m.StubOutWithMock(sr.SignalResponder, 'keystone')
            sr.SignalResponder.keystone().MultipleTimes().AndReturn(
                self.fc)
        return stack

    @utils.stack_delete_after
    def test_FnGetAtt_Alarm_Url(self):
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack.resources['signal_handler']
        created_time = datetime.datetime(2012, 11, 29, 13, 49, 37)
        rsrc.created_time = created_time
        self.assertEqual(rsrc.state, (rsrc.CREATE, rsrc.COMPLETE))

        expected_url = "".join([
            'http://127.0.0.1:8000/v1/signal/',
            'arn%3Aopenstack%3Aheat%3A%3Atest_tenant%3Astacks%2F',
            'test_stack%2FSTACKABCD1234%2Fresources%2F',
            'signal_handler?',
            'Timestamp=2012-11-29T13%3A49%3A37Z&',
            'SignatureMethod=HmacSHA256&',
            'AWSAccessKeyId=4567&',
            'SignatureVersion=2&',
            'Signature=',
            'MJIFh7LKCpVlK6pCxe2WfYrRsfO7FU3Wt%2BzQFo2rYSY%3D'])

        self.assertEqual(expected_url, rsrc.FnGetAtt('AlarmUrl'))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_FnGetAtt_Alarm_Url_is_cached(self):
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack.resources['signal_handler']
        self.assertEqual(rsrc.state, (rsrc.CREATE, rsrc.COMPLETE))

        first_url = rsrc.FnGetAtt('AlarmUrl')
        second_url = rsrc.FnGetAtt('AlarmUrl')
        self.assertEqual(first_url, second_url)
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

        rsrc = self.stack.resources['signal_handler']
        self.assertEqual(rsrc.state, (rsrc.CREATE, rsrc.COMPLETE))

        rsrc.signal(details=test_d)

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_signal_wrong_resource(self):
        # assert that we get the correct exception when calling a
        # resource.signal() that does not have a handle_signal()
        self.stack = self.create_stack()

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack.resources['resource_X']
        self.assertEqual(rsrc.state, (rsrc.CREATE, rsrc.COMPLETE))

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

        rsrc = self.stack.resources['signal_handler']
        self.assertEqual(rsrc.state, (rsrc.CREATE, rsrc.COMPLETE))
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

        rsrc = self.stack.resources['signal_handler']
        self.assertEqual(rsrc.state, (rsrc.CREATE, rsrc.COMPLETE))

        self.assertRaises(exception.ResourceFailure,
                          rsrc.signal, details=test_d)

        self.m.VerifyAll()
