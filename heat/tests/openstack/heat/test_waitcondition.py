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

import mock
from oslo_serialization import jsonutils as json
from oslo_utils import timeutils
import six

from heat.common import identifier
from heat.common import template_format
from heat.engine.clients.os import heat_plugin
from heat.engine.clients.os import swift as swift_plugin
from heat.engine import environment
from heat.engine import resource
from heat.engine.resources.openstack.heat import wait_condition_handle as h_wch
from heat.engine import stack as parser
from heat.engine import template as tmpl
from heat.objects import resource as resource_objects
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

test_template_heat_waithandle_token = '''
heat_template_version: 2013-05-23
resources:
    wait_handle:
        type: OS::Heat::WaitConditionHandle
'''

test_template_heat_waithandle_heat = '''
heat_template_version: 2013-05-23
resources:
    wait_handle:
        type: OS::Heat::WaitConditionHandle
        properties:
            signal_transport: HEAT_SIGNAL
'''

test_template_heat_waithandle_swift = '''
heat_template_version: 2013-05-23
resources:
    wait_handle:
        type: OS::Heat::WaitConditionHandle
        properties:
            signal_transport: TEMP_URL_SIGNAL
'''

test_template_heat_waithandle_zaqar = '''
heat_template_version: 2013-05-23
resources:
    wait_handle:
        type: OS::Heat::WaitConditionHandle
        properties:
            signal_transport: ZAQAR_SIGNAL
'''

test_template_heat_waithandle_none = '''
heat_template_version: 2013-05-23
resources:
    wait_handle:
        type: OS::Heat::WaitConditionHandle
        properties:
            signal_transport: NO_SIGNAL
'''

test_template_update_waithandle = '''
heat_template_version: 2013-05-23
resources:
    update_wait_handle:
        type: OS::Heat::UpdateWaitConditionHandle
'''

test_template_waithandle_bad_type = '''
heat_template_version: 2013-05-23
resources:
    wait_condition:
        type: OS::Heat::WaitCondition
        properties:
            handle: {get_resource: wait_handle}
            timeout: 5
    wait_handle:
        type: OS::Heat::RandomString
'''

test_template_waithandle_bad_reference = '''
heat_template_version: pike
resources:
    wait_condition:
        type: OS::Heat::WaitCondition
        properties:
            handle: wait_handel
            timeout: 5
    wait_handle:
        type: OS::Heat::WaitConditionHandle
        properties:
            signal_transport: NO_SIGNAL
'''


class HeatWaitConditionTest(common.HeatTestCase):

    def setUp(self):
        super(HeatWaitConditionTest, self).setUp()
        self.tenant_id = 'test_tenant'

    def create_stack(self, stack_id=None,
                     template=test_template_heat_waitcondition_count,
                     params={},
                     stub=True, stub_status=True):
        temp = template_format.parse(template)
        template = tmpl.Template(temp,
                                 env=environment.Environment(params))
        ctx = utils.dummy_context(tenant_id=self.tenant_id)
        stack = parser.Stack(ctx, 'test_stack', template,
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
            self.patchobject(h_wch.HeatWaitConditionHandle, 'identifier',
                             return_value=id)

        if stub_status:
            self.patchobject(h_wch.HeatWaitConditionHandle, 'get_status')

        return stack

    def test_post_complete_to_handle(self):
        self.stack = self.create_stack()
        mock_get_status = h_wch.HeatWaitConditionHandle.get_status
        mock_get_status.side_effect = ([['SUCCESS'],
                                        ['SUCCESS', 'SUCCESS'],
                                        ['SUCCESS', 'SUCCESS', 'SUCCESS']])

        self.stack.create()

        rsrc = self.stack['wait_condition']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE),
                         rsrc.state)

        r = resource_objects.Resource.get_by_name_and_stack(
            self.stack.context, 'wait_handle', self.stack.id)
        self.assertEqual('wait_handle', r.name)
        self.assertEqual(3, mock_get_status.call_count)

    def test_post_failed_to_handle(self):
        self.stack = self.create_stack()
        mock_get_status = h_wch.HeatWaitConditionHandle.get_status
        mock_get_status.side_effect = ([['SUCCESS'],
                                        ['SUCCESS', 'SUCCESS'],
                                        ['SUCCESS', 'SUCCESS', 'FAILURE']])

        self.stack.create()

        rsrc = self.stack['wait_condition']
        self.assertEqual((rsrc.CREATE, rsrc.FAILED),
                         rsrc.state)
        reason = rsrc.status_reason
        self.assertTrue(reason.startswith('WaitConditionFailure:'))

        r = resource_objects.Resource.get_by_name_and_stack(
            self.stack.context, 'wait_handle', self.stack.id)
        self.assertEqual('wait_handle', r.name)
        self.assertEqual(3, mock_get_status.call_count)

    def _test_wait_handle_invalid(self, tmpl, handle_name):
        self.stack = self.create_stack(template=tmpl)
        self.stack.create()
        rsrc = self.stack['wait_condition']
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        reason = rsrc.status_reason
        error_msg = ('ValueError: resources.wait_condition: '
                     '%s is not a valid wait condition handle.') % handle_name
        self.assertEqual(reason, error_msg)

    def test_wait_handle_bad_type(self):
        self._test_wait_handle_invalid(test_template_waithandle_bad_type,
                                       'wait_handle')

    def test_wait_handle_bad_reference(self):
        self._test_wait_handle_invalid(
            test_template_waithandle_bad_reference, 'wait_handel')

    def test_timeout(self):
        self.stack = self.create_stack()

        # Avoid the stack create exercising the timeout code at the same time
        self.stack.timeout_secs = mock.Mock(return_value=None)

        now = timeutils.utcnow()
        periods = [0, 0.001, 0.1, 4.1, 5.1]
        periods.extend(range(10, 100, 5))
        fake_clock = [now + datetime.timedelta(0, t) for t in periods]
        timeutils.set_time_override(fake_clock)
        self.addCleanup(timeutils.clear_time_override)

        h_wch.HeatWaitConditionHandle.get_status(
        ).MultipleTimes().AndReturn([])

        self.stack.create()

        rsrc = self.stack['wait_condition']

        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        reason = rsrc.status_reason
        self.assertTrue(reason.startswith('WaitConditionTimeout:'))

    def _create_heat_wc_and_handle(self):
        self.stack = self.create_stack(
            template=test_template_heat_waitcondition)
        mock_get_status = h_wch.HeatWaitConditionHandle.get_status
        mock_get_status.side_effect = ([['SUCCESS']])

        self.stack.create()

        rsrc = self.stack['wait_condition']
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual(six.text_type({}), wc_att)

        handle = self.stack['wait_handle']
        self.assertEqual((handle.CREATE, handle.COMPLETE), handle.state)
        return (rsrc, handle, mock_get_status)

    def test_data(self):
        rsrc, handle, mock_get_status = self._create_heat_wc_and_handle()
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
        self.assertEqual(json.loads(u'{"123": "foo", "456": "dog"}'),
                         json.loads(wc_att))
        self.assertEqual('status:SUCCESS reason:cat', ret)
        mock_get_status.assert_called_once()

    def test_data_noid(self):
        rsrc, handle, mock_get_status = self._create_heat_wc_and_handle()
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
        self.assertEqual(json.loads(u'{"1": "foo", "2": "dog"}'),
                         json.loads(wc_att))
        self.assertEqual('status:SUCCESS reason:cat', ret)
        mock_get_status.assert_called_once()

    def test_data_nodata(self):
        rsrc, handle, mock_get_status = self._create_heat_wc_and_handle()
        ret = handle.handle_signal()
        expected = 'status:SUCCESS reason:Signal 1 received'
        self.assertEqual(expected, ret)
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual('{"1": null}', wc_att)

        handle.handle_signal()
        wc_att = rsrc.FnGetAtt('data')
        self.assertEqual(json.loads(u'{"1": null, "2": null}'),
                         json.loads(wc_att))
        mock_get_status.assert_called_once()

    def test_data_partial_complete(self):
        rsrc, handle, mock_get_status = self._create_heat_wc_and_handle()
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
        self.assertEqual(json.loads(u'{"1": null, "2": null}'),
                         json.loads(wc_att))
        mock_get_status.assert_called_once()

    def _create_heat_handle(self,
                            template=test_template_heat_waithandle_token):
        self.stack = self.create_stack(template=template, stub_status=False)

        self.stack.create()

        handle = self.stack['wait_handle']
        self.assertEqual((handle.CREATE, handle.COMPLETE), handle.state)
        self.assertIsNotNone(handle.password)
        self.assertEqual(handle.resource_id, handle.data().get('user_id'))
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

    def test_getatt_token(self):
        handle = self._create_heat_handle()
        self.assertEqual('adomainusertoken', handle.FnGetAtt('token'))

    def test_getatt_endpoint(self):
        self.patchobject(heat_plugin.HeatClientPlugin, 'get_heat_url',
                         return_value='foo/%s' % self.tenant_id)
        handle = self._create_heat_handle()
        expected = ('foo/aprojectid/stacks/test_stack/%s/resources/'
                    'wait_handle/signal'
                    % self.stack_id)
        self.assertEqual(expected, handle.FnGetAtt('endpoint'))

    def test_getatt_curl_cli(self):
        self.patchobject(heat_plugin.HeatClientPlugin, 'get_heat_url',
                         return_value='foo/%s' % self.tenant_id)
        self.patchobject(heat_plugin.HeatClientPlugin, 'get_insecure_option',
                         return_value=False)
        handle = self._create_heat_handle()
        expected = ("curl -i -X POST -H 'X-Auth-Token: adomainusertoken' "
                    "-H 'Content-Type: application/json' "
                    "-H 'Accept: application/json' "
                    "foo/aprojectid/stacks/test_stack/%s/resources/wait_handle"
                    "/signal" % self.stack_id)
        self.assertEqual(expected, handle.FnGetAtt('curl_cli'))

    def test_getatt_curl_cli_insecure_true(self):
        self.patchobject(heat_plugin.HeatClientPlugin, 'get_heat_url',
                         return_value='foo/%s' % self.tenant_id)
        self.patchobject(heat_plugin.HeatClientPlugin, 'get_insecure_option',
                         return_value=True)
        handle = self._create_heat_handle()
        expected = (
            "curl --insecure -i -X POST -H 'X-Auth-Token: adomainusertoken' "
            "-H 'Content-Type: application/json' "
            "-H 'Accept: application/json' "
            "foo/aprojectid/stacks/test_stack/%s/resources/wait_handle"
            "/signal" % self.stack_id)
        self.assertEqual(expected, handle.FnGetAtt('curl_cli'))

    def test_getatt_signal_heat(self):
        handle = self._create_heat_handle(
            template=test_template_heat_waithandle_heat)
        self.assertIsNone(handle.FnGetAtt('token'))
        self.assertIsNone(handle.FnGetAtt('endpoint'))
        self.assertIsNone(handle.FnGetAtt('curl_cli'))
        signal = json.loads(handle.FnGetAtt('signal'))
        self.assertIn('alarm_url', signal)
        self.assertIn('username', signal)
        self.assertIn('password', signal)
        self.assertIn('auth_url', signal)
        self.assertIn('project_id', signal)
        self.assertIn('domain_id', signal)

    def test_getatt_signal_swift(self):
        class mock_swift(object):
            @staticmethod
            def put_container(container, **kwargs):
                pass

            @staticmethod
            def put_object(container, object, contents, **kwargs):
                pass

        mock_tempurl = self.patchobject(swift_plugin.SwiftClientPlugin,
                                        'get_temp_url',
                                        return_value='foo')
        self.patchobject(swift_plugin.SwiftClientPlugin, 'client',
                         return_value=mock_swift)

        handle = self._create_heat_handle(
            template=test_template_heat_waithandle_swift)
        self.assertIsNone(handle.FnGetAtt('token'))
        self.assertIsNone(handle.FnGetAtt('endpoint'))
        self.assertIsNone(handle.FnGetAtt('curl_cli'))
        signal = json.loads(handle.FnGetAtt('signal'))
        self.assertIn('alarm_url', signal)
        mock_tempurl.assert_called_once()

    @mock.patch('zaqarclient.queues.v2.queues.Queue.signed_url')
    def test_getatt_signal_zaqar(self, mock_signed_url):
        handle = self._create_heat_handle(
            template=test_template_heat_waithandle_zaqar)
        self.assertIsNone(handle.FnGetAtt('token'))
        self.assertIsNone(handle.FnGetAtt('endpoint'))
        self.assertIsNone(handle.FnGetAtt('curl_cli'))
        signal = json.loads(handle.FnGetAtt('signal'))
        self.assertIn('queue_id', signal)
        self.assertIn('username', signal)
        self.assertIn('password', signal)
        self.assertIn('auth_url', signal)
        self.assertIn('project_id', signal)
        self.assertIn('domain_id', signal)

    def test_getatt_signal_none(self):
        handle = self._create_heat_handle(
            template=test_template_heat_waithandle_none)
        self.assertIsNone(handle.FnGetAtt('token'))
        self.assertIsNone(handle.FnGetAtt('endpoint'))
        self.assertIsNone(handle.FnGetAtt('curl_cli'))
        self.assertEqual('{}', handle.FnGetAtt('signal'))

    def test_create_update_updatehandle(self):
        self.stack = self.create_stack(
            template=test_template_update_waithandle, stub_status=False)
        self.stack.create()

        handle = self.stack['update_wait_handle']
        self.assertEqual((handle.CREATE, handle.COMPLETE), handle.state)
        self.assertRaises(
            resource.UpdateReplace, handle.update, None, None)
