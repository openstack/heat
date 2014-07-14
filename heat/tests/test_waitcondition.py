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

import copy
import datetime
import json
import six
import time
import uuid

import mox
from oslo.config import cfg

from heat.common import identifier
from heat.common import template_format
from heat.db import api as db_api
from heat.engine.clients.os import heat_plugin
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources import wait_condition as wc
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
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


test_template_heat_waitcondition = '''
heat_template_version: 2013-05-23
resources:
    wait_condition:
        type: OS::Heat::WaitCondition
        properties:
            handle: {get_resource: wait_handle}
            timeout: 5
    wait_handle:
        type: OS::Heat::WaitConditionHandle
'''

test_template_heat_waitcondition_count = '''
heat_template_version: 2013-05-23
resources:
    wait_condition:
        type: OS::Heat::WaitCondition
        properties:
            handle: {get_resource: wait_handle}
            count: 3
            timeout: 5
    wait_handle:
        type: OS::Heat::WaitConditionHandle
'''


test_template_heat_waithandle = '''
heat_template_version: 2013-05-23
resources:
    wait_handle:
        type: OS::Heat::WaitConditionHandle
'''


class WaitConditionTest(HeatTestCase):

    def setUp(self):
        super(WaitConditionTest, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()

    def create_stack(self, stack_id=None,
                     template=test_template_waitcondition, params=None,
                     stub=True, stub_status=True):
        params = params or {}
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
            id = identifier.ResourceIdentifier('test_tenant', stack.name,
                                               stack.id, '', 'WaitHandle')
            self.m.StubOutWithMock(wc.WaitConditionHandle, 'identifier')
            wc.WaitConditionHandle.identifier().MultipleTimes().AndReturn(id)

        if stub_status:
            self.m.StubOutWithMock(wc.WaitConditionHandle,
                                   'get_status')

        return stack

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
        ret = handle.handle_signal(test_metadata)
        wc_att = rsrc.FnGetAtt('Data')
        self.assertEqual('{"123": "foo"}', wc_att)
        self.assertEqual('status:SUCCESS reason:bar', ret)

        test_metadata = {'Data': 'dog', 'Reason': 'cat',
                         'Status': 'SUCCESS', 'UniqueId': '456'}
        ret = handle.handle_signal(test_metadata)
        wc_att = rsrc.FnGetAtt('Data')
        self.assertEqual(u'{"123": "foo", "456": "dog"}', wc_att)
        self.assertEqual('status:SUCCESS reason:cat', ret)
        self.m.VerifyAll()

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
        self.stub_keystoneclient()

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

        id = identifier.ResourceIdentifier('test_tenant', stack.name,
                                           stack.id, '', 'WaitHandle')
        self.m.StubOutWithMock(wc.WaitConditionHandle, 'identifier')
        wc.WaitConditionHandle.identifier().MultipleTimes().AndReturn(id)

        self.m.ReplayAll()
        stack.create()

        return stack

    def test_handle(self):
        stack_id = 'STACKABCD1234'
        stack_name = 'test_stack2'
        created_time = datetime.datetime(2012, 11, 29, 13, 49, 37)
        self.stack = self.create_stack(stack_id=stack_id,
                                       stack_name=stack_name)

        rsrc = self.stack['WaitHandle']
        # clear the url
        rsrc.data_set('ec2_signed_url', None, False)

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
        self.m.VerifyAll()

    def test_handle_signal(self):
        self.stack = self.create_stack()
        rsrc = self.stack['WaitHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        rsrc.handle_signal(test_metadata)
        handle_metadata = {u'123': {u'Data': u'foo',
                                    u'Reason': u'bar',
                                    u'Status': u'SUCCESS'}}
        self.assertEqual(handle_metadata, rsrc.metadata_get())
        self.m.VerifyAll()

    def test_handle_signal_invalid(self):
        self.stack = self.create_stack()
        rsrc = self.stack['WaitHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # handle_signal should raise a ValueError if the metadata
        # is missing any of the expected keys
        err_metadata = {'Data': 'foo', 'Status': 'SUCCESS', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.handle_signal,
                          err_metadata)

        err_metadata = {'Data': 'foo', 'Reason': 'bar', 'UniqueId': '1234'}
        self.assertRaises(ValueError, rsrc.handle_signal,
                          err_metadata)

        err_metadata = {'Data': 'foo', 'Reason': 'bar', 'UniqueId': '1234'}
        self.assertRaises(ValueError, rsrc.handle_signal,
                          err_metadata)

        err_metadata = {'data': 'foo', 'reason': 'bar',
                        'status': 'SUCCESS', 'uniqueid': '1234'}
        self.assertRaises(ValueError, rsrc.handle_signal,
                          err_metadata)

        # Also any Status other than SUCCESS or FAILURE should be rejected
        err_metadata = {'Data': 'foo', 'Reason': 'bar',
                        'Status': 'UCCESS', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.handle_signal,
                          err_metadata)
        err_metadata = {'Data': 'foo', 'Reason': 'bar',
                        'Status': 'wibble', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.handle_signal,
                          err_metadata)
        err_metadata = {'Data': 'foo', 'Reason': 'bar',
                        'Status': 'success', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.handle_signal,
                          err_metadata)
        err_metadata = {'Data': 'foo', 'Reason': 'bar',
                        'Status': 'FAIL', 'UniqueId': '123'}
        self.assertRaises(ValueError, rsrc.handle_signal,
                          err_metadata)
        self.m.VerifyAll()

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
        ret = rsrc.handle_signal(test_metadata)
        self.assertEqual(['SUCCESS'], rsrc.get_status())
        self.assertEqual('status:SUCCESS reason:bar', ret)

        test_metadata = {'Data': 'foo', 'Reason': 'bar2',
                         'Status': 'SUCCESS', 'UniqueId': '456'}
        ret = rsrc.handle_signal(test_metadata)
        self.assertEqual(['SUCCESS', 'SUCCESS'], rsrc.get_status())
        self.assertEqual('status:SUCCESS reason:bar2', ret)

    def test_get_status_reason(self):
        self.stack = self.create_stack()
        rsrc = self.stack['WaitHandle']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        test_metadata = {'Data': 'foo', 'Reason': 'bar',
                         'Status': 'SUCCESS', 'UniqueId': '123'}
        ret = rsrc.handle_signal(test_metadata)
        self.assertEqual(['bar'], rsrc.get_status_reason('SUCCESS'))
        self.assertEqual('status:SUCCESS reason:bar', ret)

        test_metadata = {'Data': 'dog', 'Reason': 'cat',
                         'Status': 'SUCCESS', 'UniqueId': '456'}
        ret = rsrc.handle_signal(test_metadata)
        self.assertEqual(['bar', 'cat'], rsrc.get_status_reason('SUCCESS'))
        self.assertEqual('status:SUCCESS reason:cat', ret)

        test_metadata = {'Data': 'boo', 'Reason': 'hoo',
                         'Status': 'FAILURE', 'UniqueId': '789'}
        ret = rsrc.handle_signal(test_metadata)
        self.assertEqual(['hoo'], rsrc.get_status_reason('FAILURE'))
        self.assertEqual('status:FAILURE reason:hoo', ret)
        self.m.VerifyAll()


class WaitConditionUpdateTest(HeatTestCase):
    def setUp(self):
        super(WaitConditionUpdateTest, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()
        scheduler.ENABLE_SLEEP = False

    def tearDown(self):
        super(WaitConditionUpdateTest, self).tearDown()
        scheduler.ENABLE_SLEEP = True

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
        self._handle_signal(wait_condition_handle, test_metadata, 5)

        uprops = copy.copy(rsrc.properties.data)
        uprops['Count'] = '5'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      uprops)

        updater = scheduler.TaskRunner(rsrc.update, update_snippet)
        updater()

        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

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
        self._handle_signal(wait_condition_handle, test_metadata, 5)

        prop_diff = {"Count": 5}
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        update_defn = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                   props)
        updater = rsrc.handle_update(update_defn, {}, prop_diff)
        updater.run_to_completion()

        self.assertEqual(5, rsrc.properties['Count'])
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

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
        self._handle_signal(wait_condition_handle, test_metadata, 2)

        self.stack.store()
        self.stack = self.get_stack(self.stack_id)
        rsrc = self.stack['WaitForTheHandle']

        self._handle_signal(wait_condition_handle, test_metadata, 3)
        prop_diff = {"Count": 5}
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        update_defn = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                   props)
        updater = rsrc.handle_update(update_defn, {}, prop_diff)
        updater.run_to_completion()

        self.assertEqual(5, rsrc.properties['Count'])
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    def _handle_signal(self, rsrc, metadata, times=1):
        for time in range(times):
            metadata['UniqueId'] = metadata['UniqueId'] * 2
            ret = rsrc.handle_signal(metadata)
            self.assertEqual("status:%s reason:%s" %
                             (metadata[rsrc.STATUS], metadata[rsrc.REASON]),
                             ret)

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

        prop_diff = {"Count": 5}
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        update_defn = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                   props)
        updater = rsrc.handle_update(update_defn, {}, prop_diff)
        self.assertEqual(5, rsrc.properties['Count'])
        ex = self.assertRaises(wc.WaitConditionTimeout,
                               updater.run_to_completion)
        self.assertEqual("0 of 5 received", six.text_type(ex))
        self.m.VerifyAll()
        self.m.UnsetStubs()

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


class HeatWaitConditionTest(HeatTestCase):

    def setUp(self):
        super(HeatWaitConditionTest, self).setUp()
        self.stub_keystoneclient()
        self.tenant_id = 'test_tenant'

    def create_stack(self, stack_id=None,
                     template=test_template_heat_waitcondition_count,
                     params={},
                     stub=True, stub_status=True):
        temp = template_format.parse(template)
        template = parser.Template(temp)
        ctx = utils.dummy_context(tenant_id=self.tenant_id)
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
            id = identifier.ResourceIdentifier('test_tenant', stack.name,
                                               stack.id, '', 'wait_handle')
            self.m.StubOutWithMock(wc.HeatWaitConditionHandle, 'identifier')
            wc.HeatWaitConditionHandle.identifier().MultipleTimes().AndReturn(
                id)

        if stub_status:
            self.m.StubOutWithMock(wc.HeatWaitConditionHandle,
                                   'get_status')

        return stack

    def test_post_complete_to_handle(self):
        self.stack = self.create_stack()
        wc.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        wc.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS',
                                                           'SUCCESS'])
        wc.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS',
                                                           'SUCCESS',
                                                           'SUCCESS'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['wait_condition']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE),
                         rsrc.state)

        r = db_api.resource_get_by_name_and_stack(None, 'wait_handle',
                                                  self.stack.id)
        self.assertEqual('wait_handle', r.name)
        self.m.VerifyAll()

    def test_post_failed_to_handle(self):
        self.stack = self.create_stack()
        wc.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        wc.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS',
                                                           'SUCCESS'])
        wc.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS',
                                                           'SUCCESS',
                                                           'FAILURE'])

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['wait_condition']
        self.assertEqual((rsrc.CREATE, rsrc.FAILED),
                         rsrc.state)
        reason = rsrc.status_reason
        self.assertTrue(reason.startswith('WaitConditionFailure:'))

        r = db_api.resource_get_by_name_and_stack(None, 'wait_handle',
                                                  self.stack.id)
        self.assertEqual('wait_handle', r.name)
        self.m.VerifyAll()

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
        wc.HeatWaitConditionHandle.get_status().AndReturn([])
        scheduler.wallclock().AndReturn(st + 4.1)
        wc.HeatWaitConditionHandle.get_status().AndReturn([])
        scheduler.wallclock().AndReturn(st + 5.1)

        self.m.ReplayAll()

        self.stack.create()

        rsrc = self.stack['wait_condition']

        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        reason = rsrc.status_reason
        self.assertTrue(reason.startswith('WaitConditionTimeout:'))

        self.m.VerifyAll()

    def _create_heat_wc_and_handle(self):
        self.stack = self.create_stack(
            template=test_template_heat_waitcondition)
        wc.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS'])

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['wait_condition']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual(unicode({}), wc_att)

        handle = self.stack['wait_handle']
        self.assertEqual((handle.CREATE, handle.COMPLETE), handle.state)
        return (rsrc, handle)

    def test_data(self):
        rsrc, handle = self._create_heat_wc_and_handle()
        test_metadata = {'data': 'foo', 'reason': 'bar',
                         'status': 'SUCCESS', 'id': '123'}
        ret = handle.handle_signal(details=test_metadata)
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual('{"123": "foo"}', wc_att)
        self.assertEqual('status:SUCCESS reason:bar', ret)

        test_metadata = {'data': 'dog', 'reason': 'cat',
                         'status': 'SUCCESS', 'id': '456'}
        ret = handle.handle_signal(details=test_metadata)
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual(u'{"123": "foo", "456": "dog"}', wc_att)
        self.assertEqual('status:SUCCESS reason:cat', ret)
        self.m.VerifyAll()

    def test_data_noid(self):
        rsrc, handle = self._create_heat_wc_and_handle()
        test_metadata = {'data': 'foo', 'reason': 'bar',
                         'status': 'SUCCESS'}
        ret = handle.handle_signal(details=test_metadata)
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual('{"1": "foo"}', wc_att)
        self.assertEqual('status:SUCCESS reason:bar', ret)

        test_metadata = {'data': 'dog', 'reason': 'cat',
                         'status': 'SUCCESS'}
        ret = handle.handle_signal(details=test_metadata)
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual(u'{"1": "foo", "2": "dog"}', wc_att)
        self.assertEqual('status:SUCCESS reason:cat', ret)
        self.m.VerifyAll()

    def test_data_nodata(self):
        rsrc, handle = self._create_heat_wc_and_handle()
        ret = handle.handle_signal()
        expected = 'status:SUCCESS reason:Signal 1 received'
        self.assertEqual(expected, ret)
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual('{"1": null}', wc_att)

        handle.handle_signal()
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual(u'{"1": null, "2": null}', wc_att)
        self.m.VerifyAll()

    def test_data_partial_complete(self):
        rsrc, handle = self._create_heat_wc_and_handle()
        test_metadata = {'status': 'SUCCESS'}
        ret = handle.handle_signal(details=test_metadata)
        expected = 'status:SUCCESS reason:Signal 1 received'
        self.assertEqual(expected, ret)
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual('{"1": null}', wc_att)

        test_metadata = {'status': 'SUCCESS'}
        ret = handle.handle_signal(details=test_metadata)
        expected = 'status:SUCCESS reason:Signal 2 received'
        self.assertEqual(expected, ret)
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual(u'{"1": null, "2": null}', wc_att)
        self.m.VerifyAll()

    def _create_heat_handle(self):
        self.stack = self.create_stack(
            template=test_template_heat_waithandle, stub_status=False)

        self.m.ReplayAll()
        self.stack.create()

        handle = self.stack['wait_handle']
        self.assertEqual((handle.CREATE, handle.COMPLETE), handle.state)
        return handle

    def test_get_status_none_complete(self):
        handle = self._create_heat_handle()

        ret = handle.handle_signal()
        expected = 'status:SUCCESS reason:Signal 1 received'
        self.assertEqual(expected, ret)
        self.assertEqual(['SUCCESS'], handle.get_status())
        md_expected = {'1': {'data': None, 'reason': 'Signal 1 received',
                       'status': 'SUCCESS'}}
        self.assertEqual(md_expected, handle.metadata_get())
        self.m.VerifyAll()

    def test_get_status_partial_complete(self):
        handle = self._create_heat_handle()
        test_metadata = {'status': 'SUCCESS'}
        ret = handle.handle_signal(details=test_metadata)
        expected = 'status:SUCCESS reason:Signal 1 received'
        self.assertEqual(expected, ret)
        self.assertEqual(['SUCCESS'], handle.get_status())
        md_expected = {'1': {'data': None, 'reason': 'Signal 1 received',
                       'status': 'SUCCESS'}}
        self.assertEqual(md_expected, handle.metadata_get())

        self.m.VerifyAll()

    def test_get_status_failure(self):
        handle = self._create_heat_handle()
        test_metadata = {'status': 'FAILURE'}
        ret = handle.handle_signal(details=test_metadata)
        expected = 'status:FAILURE reason:Signal 1 received'
        self.assertEqual(expected, ret)
        self.assertEqual(['FAILURE'], handle.get_status())
        md_expected = {'1': {'data': None, 'reason': 'Signal 1 received',
                       'status': 'FAILURE'}}
        self.assertEqual(md_expected, handle.metadata_get())

        self.m.VerifyAll()

    def test_getatt_token(self):
        handle = self._create_heat_handle()
        self.assertEqual('adomainusertoken', handle.FnGetAtt('token'))
        self.m.VerifyAll()

    def test_getatt_endpoint(self):
        self.m.StubOutWithMock(heat_plugin.HeatClientPlugin, 'get_heat_url')
        heat_plugin.HeatClientPlugin.get_heat_url().AndReturn(
            'foo/%s' % self.tenant_id)
        self.m.ReplayAll()
        handle = self._create_heat_handle()
        expected = ('foo/aprojectid/stacks/test_stack/%s/resources/'
                    'wait_handle/signal'
                    % self.stack_id)
        self.assertEqual(expected, handle.FnGetAtt('endpoint'))
        self.m.VerifyAll()

    def test_getatt_curl_cli(self):
        self.m.StubOutWithMock(heat_plugin.HeatClientPlugin, 'get_heat_url')
        heat_plugin.HeatClientPlugin.get_heat_url().AndReturn(
            'foo/%s' % self.tenant_id)
        self.m.ReplayAll()
        handle = self._create_heat_handle()
        expected = ("curl -i -X POST -H 'X-Auth-Token: adomainusertoken' "
                    "-H 'Content-Type: application/json' "
                    "-H 'Accept: application/json' "
                    "foo/aprojectid/stacks/test_stack/%s/resources/wait_handle"
                    "/signal" % self.stack_id)
        self.assertEqual(expected, handle.FnGetAtt('curl_cli'))
        self.m.VerifyAll()
