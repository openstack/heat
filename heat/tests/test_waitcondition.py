
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
import json
import time
import uuid

import mox
from oslo.config import cfg

from heat.common import identifier
from heat.common import template_format
import heat.db.api as db_api
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources import wait_condition as wc
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils

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

test_template_update_waitcondition = '''
{
  "HeatTemplateFormatVersion" : "2012-12-12",
  "Description" : "Updatable Wait Condition",
  "Parameters" : {},
  "Resources" : {
    "WaitHandle" : {
      "Type" : "OS::Heat::UpdateWaitConditionHandle"
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


class WaitConditionTest(HeatTestCase):

    def setUp(self):
        super(WaitConditionTest, self).setUp()
        utils.setup_dummy_db()
        self.m.StubOutWithMock(wc.WaitConditionHandle,
                               'get_status')

        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

        self.fc = fakes.FakeKeystoneClient()

    def tearDown(self):
        super(WaitConditionTest, self).tearDown()
        utils.reset_dummy_db()

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the stack is properly cleaned up
    def create_stack(self, stack_id=None,
                     template=test_template_waitcondition, params={},
                     stub=True):
        temp = template_format.parse(template)
        template = parser.Template(temp)
        ctx = utils.dummy_context(tenant_id='test_tenant')
        stack = parser.Stack(ctx, 'test_stack', template,
                             environment.Environment(params),
                             disable_rollback=True)

        # Stub out the stack ID so we have a known value
        if stack_id is None:
            stack_id = str(uuid.uuid4())

        self.stack_id = stack_id
        with utils.UUIDStub(self.stack_id):
            stack.store()

        if stub:
            self.m.StubOutWithMock(wc.WaitConditionHandle, 'keystone')
            wc.WaitConditionHandle.keystone().MultipleTimes().AndReturn(
                self.fc)

            id = identifier.ResourceIdentifier('test_tenant', stack.name,
                                               stack.id, '', 'WaitHandle')
            self.m.StubOutWithMock(wc.WaitConditionHandle, 'identifier')
            wc.WaitConditionHandle.identifier().MultipleTimes().AndReturn(id)

        return stack

    @utils.stack_delete_after
    def test_post_success_to_handle(self):
        self.stack = self.create_stack()
        wc.WaitConditionHandle.get_status().AndReturn([])
        wc.WaitConditionHandle.get_status().AndReturn([])
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE),
                         rsrc.state)

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  self.stack.id)
        self.assertEqual('WaitHandle', r.name)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_post_failure_to_handle(self):
        self.stack = self.create_stack()
        wc.WaitConditionHandle.get_status().AndReturn([])
        wc.WaitConditionHandle.get_status().AndReturn([])
        wc.WaitConditionHandle.get_status().AndReturn(['FAILURE'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        reason = rsrc.status_reason
        self.assertTrue(reason.startswith('WaitConditionFailure:'))

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  self.stack.id)
        self.assertEqual('WaitHandle', r.name)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_post_success_to_handle_count(self):
        self.stack = self.create_stack(template=test_template_wc_count)
        wc.WaitConditionHandle.get_status().AndReturn([])
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS', 'SUCCESS'])
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS', 'SUCCESS',
                                                       'SUCCESS'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE),
                         rsrc.state)

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  self.stack.id)
        self.assertEqual('WaitHandle', r.name)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_post_failure_to_handle_count(self):
        self.stack = self.create_stack(template=test_template_wc_count)
        wc.WaitConditionHandle.get_status().AndReturn([])
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS', 'FAILURE'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        reason = rsrc.status_reason
        self.assertTrue(reason.startswith('WaitConditionFailure:'))

        r = db_api.resource_get_by_name_and_stack(None, 'WaitHandle',
                                                  self.stack.id)
        self.assertEqual('WaitHandle', r.name)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_timeout(self):
        st = time.time()

        self.stack = self.create_stack()

        # Avoid the stack create exercising the timeout code at the same time
        self.m.StubOutWithMock(self.stack, 'timeout_secs')
        self.stack.timeout_secs().MultipleTimes().AndReturn(None)

        self.m.StubOutWithMock(scheduler, 'wallclock')

        scheduler.wallclock().AndReturn(st)
        scheduler.wallclock().AndReturn(st + 0.001)
        scheduler.wallclock().AndReturn(st + 0.1)
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.wallclock().AndReturn(st + 4.1)
        wc.WaitConditionHandle.get_status().AndReturn([])
        scheduler.wallclock().AndReturn(st + 5.1)

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']

        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        reason = rsrc.status_reason
        self.assertTrue(reason.startswith('WaitConditionTimeout:'))

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_FnGetAtt(self):
        self.stack = self.create_stack()
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        wc_att = rsrc.FnGetAtt('Data')
        self.assertEqual(unicode({}), wc_att)

        handle = self.stack['WaitHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), handle.state)

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        handle.metadata_update(new_metadata=test_metadata)
        wc_att = rsrc.FnGetAtt('Data')
        self.assertEqual('{"123": "foo"}', wc_att)

        test_metadata = {'Data': 'dog', 'Reason': 'cat',
                         'Status': 'SUCCESS', 'UniqueId': '456'}
        handle.metadata_update(new_metadata=test_metadata)
        wc_att = rsrc.FnGetAtt('Data')
        self.assertEqual(u'{"123": "foo", "456": "dog"}', wc_att)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_validate_handle_url_bad_stackid(self):
        self.m.ReplayAll()

        stack_id = 'STACK_HUBSID_1234'
        t = json.loads(test_template_waitcondition)
        badhandle = ("http://server.test:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3Atest_tenant" +
                     "%3Astacks%2Ftest_stack%2F" +
                     "bad1" +
                     "%2Fresources%2FWaitHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(template=json.dumps(t), stub=False,
                                       stack_id=stack_id)
        self.m.ReplayAll()

        rsrc = self.stack['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_validate_handle_url_bad_stackname(self):
        self.m.ReplayAll()

        stack_id = 'STACKABCD1234'
        t = json.loads(test_template_waitcondition)
        badhandle = ("http://server.test:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3Atest_tenant" +
                     "%3Astacks%2FBAD_stack%2F" +
                     stack_id + "%2Fresources%2FWaitHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(template=json.dumps(t), stub=False,
                                       stack_id=stack_id)

        rsrc = self.stack['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_validate_handle_url_bad_tenant(self):
        self.m.ReplayAll()

        stack_id = 'STACKABCD1234'
        t = json.loads(test_template_waitcondition)
        badhandle = ("http://server.test:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3ABAD_tenant" +
                     "%3Astacks%2Ftest_stack%2F" +
                     stack_id + "%2Fresources%2FWaitHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(stack_id=stack_id,
                                       template=json.dumps(t), stub=False)

        rsrc = self.stack['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_validate_handle_url_bad_resource(self):
        self.m.ReplayAll()

        stack_id = 'STACK_HUBR_1234'
        t = json.loads(test_template_waitcondition)
        badhandle = ("http://server.test:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3Atest_tenant" +
                     "%3Astacks%2Ftest_stack%2F" +
                     stack_id + "%2Fresources%2FBADHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(stack_id=stack_id,
                                       template=json.dumps(t), stub=False)

        rsrc = self.stack['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_validate_handle_url_bad_resource_type(self):
        self.m.ReplayAll()
        stack_id = 'STACKABCD1234'
        t = json.loads(test_template_waitcondition)
        badhandle = ("http://server.test:8000/v1/waitcondition/" +
                     "arn%3Aopenstack%3Aheat%3A%3Atest_tenant" +
                     "%3Astacks%2Ftest_stack%2F" +
                     stack_id + "%2Fresources%2FWaitForTheHandle")
        t['Resources']['WaitForTheHandle']['Properties']['Handle'] = badhandle
        self.stack = self.create_stack(stack_id=stack_id,
                                       template=json.dumps(t), stub=False)

        rsrc = self.stack['WaitForTheHandle']
        self.assertRaises(ValueError, rsrc.handle_create)

        self.m.VerifyAll()


class WaitConditionHandleTest(HeatTestCase):
    def setUp(self):
        super(WaitConditionHandleTest, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

        self.fc = fakes.FakeKeystoneClient()
        utils.setup_dummy_db()

    def tearDown(self):
        super(WaitConditionHandleTest, self).tearDown()
        utils.reset_dummy_db()

    def create_stack(self, stack_name=None, stack_id=None):
        temp = template_format.parse(test_template_waitcondition)
        template = parser.Template(temp)
        ctx = utils.dummy_context(tenant_id='test_tenant')
        if stack_name is None:
            stack_name = utils.random_name()
        stack = parser.Stack(ctx, stack_name, template,
                             disable_rollback=True)
        # Stub out the UUID for this test, so we can get an expected signature
        if stack_id is not None:
            with utils.UUIDStub(stack_id):
                stack.store()
        else:
            stack.store()
        self.stack_id = stack.id

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

    @utils.stack_delete_after
    def test_handle(self):
        stack_id = 'STACKABCD1234'
        stack_name = 'test_stack2'
        created_time = datetime.datetime(2012, 11, 29, 13, 49, 37)
        self.stack = self.create_stack(stack_id=stack_id,
                                       stack_name=stack_name)

        rsrc = self.stack['WaitHandle']
        # clear the url
        db_api.resource_data_set(rsrc, 'ec2_signed_url', None, False)

        rsrc.created_time = created_time
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        expected_url = "".join([
            'http://server.test:8000/v1/waitcondition/',
            'arn%3Aopenstack%3Aheat%3A%3Atest_tenant%3Astacks%2F',
            'test_stack2%2F', stack_id, '%2Fresources%2F',
            'WaitHandle?',
            'Timestamp=2012-11-29T13%3A49%3A37Z&',
            'SignatureMethod=HmacSHA256&',
            'AWSAccessKeyId=4567&',
            'SignatureVersion=2&',
            'Signature=',
            'fHyt3XFnHq8%2FSwYaVcHdJka1hz6jdK5mHtgbo8OOKbQ%3D'])

        self.assertEqual(unicode(expected_url), rsrc.FnGetRefId())

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_metadata_update(self):
        self.stack = self.create_stack()
        rsrc = self.stack['WaitHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        rsrc.metadata_update(new_metadata=test_metadata)
        handle_metadata = {u'123': {u'Data': u'foo',
                                    u'Reason': u'bar',
                                    u'Status': u'SUCCESS'}}
        self.assertEqual(handle_metadata, rsrc.metadata)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_metadata_update_invalid(self):
        self.stack = self.create_stack()
        rsrc = self.stack['WaitHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

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

    @utils.stack_delete_after
    def test_get_status(self):
        self.stack = self.create_stack()
        rsrc = self.stack['WaitHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # UnsetStubs, don't want get_status stubbed anymore..
        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.assertEqual([], rsrc.get_status())

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual(['SUCCESS'], rsrc.get_status())

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '456'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual(['SUCCESS', 'SUCCESS'], rsrc.get_status())

        # re-stub keystone() with fake client or stack delete fails
        self.m.StubOutWithMock(wc.WaitConditionHandle, 'keystone')
        wc.WaitConditionHandle.keystone().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

    @utils.stack_delete_after
    def test_get_status_reason(self):
        self.stack = self.create_stack()
        rsrc = self.stack['WaitHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual('bar', rsrc.get_status_reason('SUCCESS'))

        test_metadata = {'Data': 'dog', 'Reason': 'cat',
                         'Status': 'SUCCESS', 'UniqueId': '456'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual('bar;cat', rsrc.get_status_reason('SUCCESS'))

        test_metadata = {'Data': 'boo', 'Reason': 'hoo',
                         'Status': 'FAILURE', 'UniqueId': '789'}
        rsrc.metadata_update(new_metadata=test_metadata)
        self.assertEqual('hoo', rsrc.get_status_reason('FAILURE'))
        self.m.VerifyAll()


class WaitConditionUpdateTest(HeatTestCase):
    def setUp(self):
        super(WaitConditionUpdateTest, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

        self.fc = fakes.FakeKeystoneClient()
        utils.setup_dummy_db()
        scheduler.ENABLE_SLEEP = False

    def tearDown(self):
        super(WaitConditionUpdateTest, self).tearDown()
        utils.reset_dummy_db()
        scheduler.ENABLE_SLEEP = True

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the stack is properly cleaned up
    def create_stack(self, tmpl=None):
        if tmpl is None:
            tmpl = test_template_wc_count
        temp = template_format.parse(tmpl)
        template = parser.Template(temp)
        ctx = utils.dummy_context(tenant_id='test_tenant')
        stack = parser.Stack(ctx, 'test_stack', template,
                             environment.Environment({}),
                             disable_rollback=True)

        stack_id = str(uuid.uuid4())
        self.stack_id = stack_id
        with utils.UUIDStub(self.stack_id):
            stack.store()

        self.m.StubOutWithMock(wc.WaitConditionHandle, 'keystone')
        wc.WaitConditionHandle.keystone().MultipleTimes().AndReturn(
            self.fc)

        self.m.StubOutWithMock(wc.WaitConditionHandle, 'get_status')
        wc.WaitConditionHandle.get_status().AndReturn([])
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS', 'SUCCESS'])
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS', 'SUCCESS',
                                                       'SUCCESS'])

        return stack

    def get_stack(self, stack_id):
        ctx = utils.dummy_context(tenant_id='test_tenant')
        stack = parser.Stack.load(ctx, stack_id)
        self.stack_id = stack_id
        return stack

    @utils.stack_delete_after
    def test_update(self):
        self.stack = self.create_stack()
        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        wait_condition_handle = self.stack['WaitHandle']
        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '1'}
        self._metadata_update(wait_condition_handle, test_metadata, 5)

        update_snippet = rsrc.parsed_template()
        update_snippet['Properties']['Count'] = '5'

        updater = scheduler.TaskRunner(rsrc.update, update_snippet)
        updater()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

    @utils.stack_delete_after
    def test_handle_update(self):
        self.stack = self.create_stack()
        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        wait_condition_handle = self.stack['WaitHandle']
        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '1'}
        self._metadata_update(wait_condition_handle, test_metadata, 5)

        update_snippet = {"Type": "AWS::CloudFormation::WaitCondition",
                          "Properties": {
                              "Handle": {"Ref": "WaitHandle"},
                              "Timeout": "5",
                              "Count": "5"}}
        prop_diff = {"Count": 5}
        parsed_snippet = self.stack.resolve_static_data(update_snippet)
        updater = rsrc.handle_update(parsed_snippet, {}, prop_diff)
        updater.run_to_completion()

        self.assertEqual(5, rsrc.properties['Count'])
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    @utils.stack_delete_after
    def test_handle_update_restored_from_db(self):
        self.stack = self.create_stack()
        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        wait_condition_handle = self.stack['WaitHandle']
        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '1'}
        self._metadata_update(wait_condition_handle, test_metadata, 2)

        self.stack.store()
        self.stack = self.get_stack(self.stack_id)
        rsrc = self.stack['WaitForTheHandle']

        self._metadata_update(wait_condition_handle, test_metadata, 3)
        update_snippet = {"Type": "AWS::CloudFormation::WaitCondition",
                          "Properties": {
                              "Handle": {"Ref": "WaitHandle"},
                              "Timeout": "5",
                              "Count": "5"}}
        prop_diff = {"Count": 5}
        parsed_snippet = self.stack.resolve_static_data(update_snippet)
        updater = rsrc.handle_update(parsed_snippet, {}, prop_diff)
        updater.run_to_completion()

        self.assertEqual(5, rsrc.properties['Count'])
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    def _metadata_update(self, rsrc, metadata, times=1):
        for time in range(times):
            metadata['UniqueId'] = metadata['UniqueId'] * 2
            rsrc.metadata_update(new_metadata=metadata)

    @utils.stack_delete_after
    def test_handle_update_timeout(self):
        self.stack = self.create_stack()
        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
        self.m.UnsetStubs()

        st = time.time()

        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        scheduler.TaskRunner._sleep(mox.IgnoreArg()).MultipleTimes().AndReturn(
            None)

        self.m.StubOutWithMock(scheduler, 'wallclock')

        scheduler.wallclock().AndReturn(st)
        scheduler.wallclock().AndReturn(st + 0.001)
        scheduler.wallclock().AndReturn(st + 0.1)
        scheduler.wallclock().AndReturn(st + 4.1)
        scheduler.wallclock().AndReturn(st + 5.1)

        self.m.ReplayAll()

        update_snippet = {"Type": "AWS::CloudFormation::WaitCondition",
                          "Properties": {
                              "Handle": {"Ref": "WaitHandle"},
                              "Timeout": "5",
                              "Count": "5"}}
        prop_diff = {"Count": 5}
        parsed_snippet = self.stack.resolve_static_data(update_snippet)
        updater = rsrc.handle_update(parsed_snippet, {}, prop_diff)
        self.assertEqual(5, rsrc.properties['Count'])
        self.assertRaises(wc.WaitConditionTimeout, updater.run_to_completion)

        self.m.VerifyAll()
        self.m.UnsetStubs()

    @utils.stack_delete_after
    def test_update_updatehandle(self):
        self.stack = self.create_stack(test_template_update_waitcondition)
        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['WaitForTheHandle']
        self.assertEqual(rsrc.state, (rsrc.CREATE, rsrc.COMPLETE))

        self.m.VerifyAll()
        self.m.UnsetStubs()

        wait_condition_handle = self.stack['WaitHandle']
        self.assertRaises(
            resource.UpdateReplace, wait_condition_handle.update, None, None)
