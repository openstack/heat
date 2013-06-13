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

import mox

import datetime
import time
import json
import uuid

from oslo.config import cfg

from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests.utils import stack_delete_after
from heat.tests.utils import setup_dummy_db

import heat.db.api as db_api
from heat.common import template_format
from heat.common import identifier
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.engine.resources import wait_condition as wc
from heat.common import config
from heat.common import context

test_template_waitcondition = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a WaitCondition.",
  "Parameters" : {},
  "Resources" : {
    "WaitHandle" : {
      "Type" : "AWS::CloudFormation::WaitConditionHandle"
    },
    "WaitForTheHandle" : {
      "Type" : "AWS::CloudFormation::WaitCondition",
      "Properties" : {
        "Handle" : {"Ref" : "WaitHandle"},
        "Timeout" : "5"
      }
    }
  }
}
'''

test_template_wc_count = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a WaitCondition.",
  "Parameters" : {},
  "Resources" : {
    "WaitHandle" : {
      "Type" : "AWS::CloudFormation::WaitConditionHandle"
    },
    "WaitForTheHandle" : {
      "Type" : "AWS::CloudFormation::WaitCondition",
      "Properties" : {
        "Handle" : {"Ref" : "WaitHandle"},
        "Timeout" : "5",
        "Count" : "3"
      }
    }
  }
}
'''


class UUIDStub(object):
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.uuid4 = uuid.uuid4
        uuid_stub = lambda: self.value
        uuid.uuid4 = uuid_stub

    def __exit__(self, *exc_info):
        uuid.uuid4 = self.uuid4


class WaitConditionTest(HeatTestCase):

    def setUp(self):
        super(WaitConditionTest, self).setUp()
        config.register_engine_opts()
        setup_dummy_db()
        self.m.StubOutWithMock(wc.WaitConditionHandle,
                               'get_status')
        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://127.0.0.1:8000/v1/waitcondition')

        self.stack_id = 'STACKABCD1234'
        self.fc = fakes.FakeKeystoneClient()

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the stack is properly cleaned up
    def create_stack(self, stack_name='test_stack',
                     template=test_template_waitcondition, params={},
                     stub=True):
        temp = template_format.parse(template)
        template = parser.Template(temp)
        parameters = parser.Parameters(stack_name, template, params)
        ctx = context.get_admin_context()
        ctx.tenant_id = 'test_tenant'
        stack = parser.Stack(ctx, stack_name, template, parameters,
                             disable_rollback=True)

        # Stub out the stack ID so we have a known value
        with UUIDStub(self.stack_id):
            stack.store()

        if stub:
            scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)

            self.m.StubOutWithMock(wc.WaitConditionHandle, 'keystone')
            wc.WaitConditionHandle.keystone().MultipleTimes().AndReturn(
                self.fc)

            id = identifier.ResourceIdentifier('test_tenant', stack.name,
                                               stack.id, '', 'WaitHandle')
            self.m.StubOutWithMock(wc.WaitConditionHandle, 'identifier')
            wc.WaitConditionHandle.identifier().MultipleTimes().AndReturn(id)

        return stack

    @stack_delete_after
    def test_post_success_to_handle(self):
        self.stack = self.create_stack()
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertEqual(rsrc.state,
                         'CREATE_COMPLETE')

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  self.stack.id)
        self.assertEqual(r.name, 'WaitHandle')
        self.m.VerifyAll()

    @stack_delete_after
    def test_post_failure_to_handle(self):
        self.stack = self.create_stack()
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        wc.WaitConditionHandle.get_status().AndReturn(['FAILURE'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertEqual(rsrc.state, rsrc.CREATE_FAILED)
        reason = rsrc.state_description
        self.assertTrue(reason.startswith('WaitConditionFailure:'))

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  self.stack.id)
        self.assertEqual(r.name, 'WaitHandle')
        self.m.VerifyAll()

    @stack_delete_after
    def test_post_success_to_handle_count(self):
        self.stack = self.create_stack(template=test_template_wc_count)
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS', 'SUCCESS'])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS', 'SUCCESS',
                                                       'SUCCESS'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertEqual(rsrc.state,
                         'CREATE_COMPLETE')

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  self.stack.id)
        self.assertEqual(r.name, 'WaitHandle')
        self.m.VerifyAll()

    @stack_delete_after
    def test_post_failure_to_handle_count(self):
        self.stack = self.create_stack(template=test_template_wc_count)
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS', 'FAILURE'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertEqual(rsrc.state, rsrc.CREATE_FAILED)
        reason = rsrc.state_description
        self.assertTrue(reason.startswith('WaitConditionFailure:'))

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  self.stack.id)
        self.assertEqual(r.name, 'WaitHandle')
        self.m.VerifyAll()

    @stack_delete_after
    def test_timeout(self):
        st = time.time()

        self.stack = self.create_stack()

        # Avoid the stack create exercising the timeout code at the same time
        self.m.StubOutWithMock(self.stack, 'timeout_secs')
        self.stack.timeout_secs().AndReturn(None)

        self.m.StubOutWithMock(scheduler, 'wallclock')

        scheduler.wallclock().AndReturn(st)
        scheduler.wallclock().AndReturn(st + 0.001)
        scheduler.wallclock().AndReturn(st + 0.1)
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        scheduler.wallclock().AndReturn(st + 4.1)
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
        scheduler.wallclock().AndReturn(st + 5.1)

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack.resources['WaitForTheHandle']

        self.assertEqual(rsrc.state, rsrc.CREATE_FAILED)
        reason = rsrc.state_description
        self.assertTrue(reason.startswith('WaitConditionTimeout:'))

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})
        self.m.VerifyAll()

    @stack_delete_after
    def test_FnGetAtt(self):
        self.stack = self.create_stack()
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertEqual(rsrc.state, 'CREATE_COMPLETE')

        wc_att = rsrc.FnGetAtt('Data')
        self.assertEqual(wc_att, unicode({}))

        handle = self.stack.resources['WaitHandle']
        self.assertEqual(handle.state, 'CREATE_COMPLETE')

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        handle.metadata_update(new_metadata=test_metadata)
        wc_att = rsrc.FnGetAtt('Data')
        self.assertEqual(wc_att, '{"123": "foo"}')

        test_metadata = {'Data': 'dog', 'Reason': 'cat',
                         'Status': 'SUCCESS', 'UniqueId': '456'}
        handle.metadata_update(new_metadata=test_metadata)
        wc_att = rsrc.FnGetAtt('Data')
        self.assertEqual(wc_att, u'{"123": "foo", "456": "dog"}')
        self.m.VerifyAll()

    @stack_delete_after
    def test_validate_handle_url_bad_stackid(self):
        self.m.ReplayAll()

        t = json.loads(test_template_waitcondition)
        badhandle = ("http://127.0.0.1:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3Atest_tenant" +
                     "%3Astacks%2Ftest_stack%2F" +
                     "bad1" +
                     "%2Fresources%2FWaitHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(template=json.dumps(t), stub=False)
        self.m.ReplayAll()

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()

    @stack_delete_after
    def test_validate_handle_url_bad_stackname(self):
        self.m.ReplayAll()

        t = json.loads(test_template_waitcondition)
        badhandle = ("http://127.0.0.1:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3Atest_tenant" +
                     "%3Astacks%2FBAD_stack%2F" +
                     self.stack_id + "%2Fresources%2FWaitHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(template=json.dumps(t), stub=False)

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()

    @stack_delete_after
    def test_validate_handle_url_bad_tenant(self):
        self.m.ReplayAll()

        t = json.loads(test_template_waitcondition)
        badhandle = ("http://127.0.0.1:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3ABAD_tenant" +
                     "%3Astacks%2Ftest_stack%2F" +
                     self.stack_id + "%2Fresources%2FWaitHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(template=json.dumps(t), stub=False)

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()

    @stack_delete_after
    def test_validate_handle_url_bad_resource(self):
        self.m.ReplayAll()

        t = json.loads(test_template_waitcondition)
        badhandle = ("http://127.0.0.1:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3Atest_tenant" +
                     "%3Astacks%2Ftest_stack%2F" +
                     self.stack_id + "%2Fresources%2FBADHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(template=json.dumps(t), stub=False)

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()

    @stack_delete_after
    def test_validate_handle_url_bad_resource_type(self):
        self.m.ReplayAll()

        t = json.loads(test_template_waitcondition)
        badhandle = ("http://127.0.0.1:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3Atest_tenant" +
                     "%3Astacks%2Ftest_stack%2F" +
                     self.stack_id + "%2Fresources%2FWaitForTheHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(template=json.dumps(t), stub=False)

        rsrc = self.stack.resources['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()


class WaitConditionHandleTest(HeatTestCase):
    def setUp(self):
        super(WaitConditionHandleTest, self).setUp()
        config.register_engine_opts()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://127.0.0.1:8000/v1/waitcondition')

        self.fc = fakes.FakeKeystoneClient()
        setup_dummy_db()
        self.stack = self.create_stack()

    def create_stack(self, stack_name='test_stack2', params={}):
        temp = template_format.parse(test_template_waitcondition)
        template = parser.Template(temp)
        parameters = parser.Parameters(stack_name, template, params)
        ctx = context.get_admin_context()
        ctx.tenant_id = 'test_tenant'
        stack = parser.Stack(ctx, stack_name, template, parameters,
                             disable_rollback=True)
        # Stub out the UUID for this test, so we can get an expected signature
        with UUIDStub('STACKABCD1234'):
            stack.store()

        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)

        # Stub waitcondition status so all goes CREATE_COMPLETE
        self.m.StubOutWithMock(wc.WaitConditionHandle, 'get_status')
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])

        # Stub keystone() with fake client
        self.m.StubOutWithMock(wc.WaitConditionHandle, 'keystone')
        wc.WaitConditionHandle.keystone().MultipleTimes().AndReturn(self.fc)

        id = identifier.ResourceIdentifier('test_tenant', stack.name,
                                           stack.id, '', 'WaitHandle')
        self.m.StubOutWithMock(wc.WaitConditionHandle, 'identifier')
        wc.WaitConditionHandle.identifier().MultipleTimes().AndReturn(id)

        self.m.ReplayAll()
        stack.create()

        return stack

    @stack_delete_after
    def test_handle(self):
        created_time = datetime.datetime(2012, 11, 29, 13, 49, 37)

        rsrc = self.stack.resources['WaitHandle']
        rsrc.created_time = created_time
        self.assertEqual(rsrc.state, 'CREATE_COMPLETE')

        expected_url = "".join([
            'http://127.0.0.1:8000/v1/waitcondition/',
            'arn%3Aopenstack%3Aheat%3A%3Atest_tenant%3Astacks%2F',
            'test_stack2%2FSTACKABCD1234%2Fresources%2F',
            'WaitHandle?',
            'Timestamp=2012-11-29T13%3A49%3A37Z&',
            'SignatureMethod=HmacSHA256&',
            'AWSAccessKeyId=4567&',
            'SignatureVersion=2&',
            'Signature=',
            'ePyTwmC%2F1kSigeo%2Fha7kP8Avvb45G9Y7WOQWe4F%2BnXM%3D'])

        self.assertEqual(expected_url, rsrc.FnGetRefId())

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})
        self.m.VerifyAll()

    @stack_delete_after
    def test_metadata_update(self):
        rsrc = self.stack.resources['WaitHandle']
        self.assertEqual(rsrc.state, 'CREATE_COMPLETE')

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        rsrc.metadata_update(new_metadata=test_metadata)
        handle_metadata = {u'123': {u'Data': u'foo',
                                    u'Reason': u'bar',
                                    u'Status': u'SUCCESS'}}
        self.assertEqual(rsrc.metadata, handle_metadata)
        self.m.VerifyAll()

    @stack_delete_after
    def test_metadata_update_invalid(self):
        rsrc = self.stack.resources['WaitHandle']
        self.assertEqual(rsrc.state, 'CREATE_COMPLETE')

        # metadata_update should raise a ValueError if the metadata
        # is missing any of the expected keys
        err_metadata = {'Data': 'foo', 'Status': 'SUCCESS', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.metadata_update,
                          new_metadata=err_metadata)

        err_metadata = {'Data': 'foo', 'Reason': 'bar', 'UniqueId': '1234'}
        self.assertRaises(ValueError, rsrc.metadata_update,
                          new_metadata=err_metadata)

        err_metadata = {'Data': 'foo', 'Reason': 'bar', 'UniqueId': '1234'}
        self.assertRaises(ValueError, rsrc.metadata_update,
                          new_metadata=err_metadata)

        err_metadata = {'data': 'foo', 'reason': 'bar',
                        'status': 'SUCCESS', 'uniqueid': '1234'}
        self.assertRaises(ValueError, rsrc.metadata_update,
                          new_metadata=err_metadata)

        # Also any Status other than SUCCESS or FAILURE should be rejected
        err_metadata = {'Data': 'foo', 'Reason': 'bar',
                        'Status': 'UCCESS', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.metadata_update,
                          new_metadata=err_metadata)
        err_metadata = {'Data': 'foo', 'Reason': 'bar',
                        'Status': 'wibble', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.metadata_update,
                          new_metadata=err_metadata)
        err_metadata = {'Data': 'foo', 'Reason': 'bar',
                        'Status': 'success', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.metadata_update,
                          new_metadata=err_metadata)
        err_metadata = {'Data': 'foo', 'Reason': 'bar',
                        'Status': 'FAIL', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.metadata_update,
                          new_metadata=err_metadata)
        self.m.VerifyAll()

    @stack_delete_after
    def test_get_status(self):
        rsrc = self.stack.resources['WaitHandle']
        self.assertEqual(rsrc.state, 'CREATE_COMPLETE')

        # UnsetStubs, don't want get_status stubbed anymore..
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.assertEqual(rsrc.get_status(), [])

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual(rsrc.get_status(), ['SUCCESS'])

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '456'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual(rsrc.get_status(), ['SUCCESS', 'SUCCESS'])

        # re-stub keystone() with fake client or stack delete fails
        self.m.StubOutWithMock(wc.WaitConditionHandle, 'keystone')
        wc.WaitConditionHandle.keystone().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

    @stack_delete_after
    def test_get_status_reason(self):
        rsrc = self.stack.resources['WaitHandle']
        self.assertEqual(rsrc.state, 'CREATE_COMPLETE')

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual(rsrc.get_status_reason('SUCCESS'), 'bar')

        test_metadata = {'Data': 'dog', 'Reason': 'cat',
                         'Status': 'SUCCESS', 'UniqueId': '456'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual(rsrc.get_status_reason('SUCCESS'), 'bar;cat')

        test_metadata = {'Data': 'boo', 'Reason': 'hoo',
                         'Status': 'FAILURE', 'UniqueId': '789'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual(rsrc.get_status_reason('FAILURE'), 'hoo')
        self.m.VerifyAll()
