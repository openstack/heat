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

import six
import time
import uuid

from heat.common import identifier
from heat.common import template_format
from heat.db import api as db_api
from heat.engine.clients.os import heat_plugin
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources.openstack import wait_condition_handle as heat_wch
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

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

test_template_update_waithandle = '''
heat_template_version: 2013-05-23
resources:
    update_wait_handle:
        type: OS::Heat::UpdateWaitConditionHandle
'''


class HeatWaitConditionTest(common.HeatTestCase):

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
            self.m.StubOutWithMock(heat_wch.HeatWaitConditionHandle,
                                   'identifier')
            heat_wch.HeatWaitConditionHandle.\
                identifier().MultipleTimes().AndReturn(id)

        if stub_status:
            self.m.StubOutWithMock(heat_wch.HeatWaitConditionHandle,
                                   'get_status')

        return stack

    def test_post_complete_to_handle(self):
        self.stack = self.create_stack()
        heat_wch.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        heat_wch.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS',
                                                                 'SUCCESS'])
        heat_wch.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS',
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
        heat_wch.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        heat_wch.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS',
                                                                 'SUCCESS'])
        heat_wch.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS',
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
        heat_wch.HeatWaitConditionHandle.get_status().AndReturn([])
        scheduler.wallclock().AndReturn(st + 4.1)
        heat_wch.HeatWaitConditionHandle.get_status().AndReturn([])
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
        heat_wch.HeatWaitConditionHandle.get_status().AndReturn(['SUCCESS'])

        self.m.ReplayAll()
        self.stack.create()

        rsrc = self.stack['wait_condition']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual(six.text_type({}), wc_att)

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

    def test_create_update_updatehandle(self):
        self.stack = self.create_stack(
            template=test_template_update_waithandle, stub_status=False)
        self.m.ReplayAll()
        self.stack.create()

        handle = self.stack['update_wait_handle']
        self.assertEqual((handle.CREATE, handle.COMPLETE), handle.state)
        self.assertRaises(
            resource.UpdateReplace, handle.update, None, None)
