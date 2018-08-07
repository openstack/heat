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
import json
import uuid

import mock
from oslo_utils import timeutils
import six
from swiftclient import client as swiftclient_client
from swiftclient import exceptions as swiftclient_exceptions
from testtools import matchers

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import swift
from heat.engine import node_data
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack
from heat.engine import template as templatem
from heat.tests import common
from heat.tests import utils


swiftsignal_template = '''
heat_template_version: 2013-05-23

resources:
  test_wait_condition:
    type: "OS::Heat::SwiftSignal"
    properties:
      handle: { get_resource: test_wait_condition_handle }
      timeout: 1
      count: 2

  test_wait_condition_handle:
    type: "OS::Heat::SwiftSignalHandle"
'''

swiftsignalhandle_template = '''
heat_template_version: 2013-05-23

resources:
  test_wait_condition_handle:
    type: "OS::Heat::SwiftSignalHandle"
'''

container_header = {
    'content-length': '2',
    'x-container-object-count': '0',
    'accept-ranges': 'bytes',
    'date': 'Fri, 25 Jul 2014 16:02:03 GMT',
    'x-timestamp': '1405019787.66969',
    'x-trans-id': 'tx6651b005324341f685e71-0053d27f7bdfw1',
    'x-container-bytes-used': '0',
    'content-type': 'application/json; charset=utf-8',
    'x-versions-location': 'test'
}

obj_header = {
    'content-length': '5',
    'accept-ranges': 'bytes',
    'last-modified': 'Fri, 25 Jul 2014 16:05:26 GMT',
    'etag': '5a105e8b9d40e1329780d62ea2265d8a',
    'x-timestamp': '1406304325.40094',
    'x-trans-id': 'tx2f40ff2b4daa4015917fc-0053d28045dfw1',
    'date': 'Fri, 25 Jul 2014 16:05:25 GMT',
    'content-type': 'application/octet-stream'
}


def create_stack(template, stack_id=None, cache_data=None):
    tmpl = template_format.parse(template)
    template = templatem.Template(tmpl)
    ctx = utils.dummy_context(tenant_id='test_tenant')
    st = stack.Stack(ctx, 'test_st', template,
                     disable_rollback=True, cache_data=cache_data)

    # Stub out the stack ID so we have a known value
    if stack_id is None:
        stack_id = str(uuid.uuid4())
    with utils.UUIDStub(stack_id):
        st.store()
    st.id = stack_id

    return st


def cont_index(obj_name, num_version_hist):
    objects = [{'bytes': 11,
                'last_modified': '2014-07-03T19:42:03.281640',
                'hash': '9214b4e4460fcdb9f3a369941400e71e',
                'name': "02b" + obj_name + '/1404416326.51383',
                'content_type': 'application/octet-stream'}] * num_version_hist
    objects.append({'bytes': 8,
                    'last_modified': '2014-07-03T19:42:03.849870',
                    'hash': '9ab7c0738852d7dd6a2dc0b261edc300',
                    'name': obj_name,
                    'content_type': 'application/x-www-form-urlencoded'})
    return (container_header, objects)


class SwiftSignalHandleTest(common.HeatTestCase):

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_create(self, mock_name, mock_swift):
        st = create_stack(swiftsignalhandle_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': "1234"
        }
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 2)
        mock_swift_object.get_object.return_value = (obj_header, '{"id": "1"}')

        st.create()
        handle = st.resources['test_wait_condition_handle']
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        regexp = ("http://fake-host.com:8080/v1/AUTH_test_tenant/%s/test_st-"
                  "test_wait_condition_handle-abcdefghijkl"
                  r"\?temp_url_sig=[0-9a-f]{40}&temp_url_expires=[0-9]{10}"
                  % st.id)
        res_id = st.resources['test_wait_condition_handle'].resource_id
        self.assertEqual(res_id, handle.physical_resource_name())
        self.assertThat(handle.FnGetRefId(), matchers.MatchesRegex(regexp))

        # Since the account key is mocked out above
        self.assertFalse(mock_swift_object.post_account.called)

        header = {'x-versions-location': st.id}
        self.assertEqual({'headers': header},
                         mock_swift_object.put_container.call_args[1])

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_delete_empty_container(self, mock_name, mock_swift):
        st = create_stack(swiftsignalhandle_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': "1234"
        }
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        st.create()

        exc = swiftclient_exceptions.ClientException("Object DELETE failed",
                                                     http_status=404)
        mock_swift_object.delete_object.side_effect = (None, None, None, exc)
        exc = swiftclient_exceptions.ClientException("Container DELETE failed",
                                                     http_status=404)
        mock_swift_object.delete_container.side_effect = exc
        rsrc = st.resources['test_wait_condition_handle']
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual(('DELETE', 'COMPLETE'), rsrc.state)
        self.assertEqual(4, mock_swift_object.delete_object.call_count)

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_delete_object_error(self, mock_name, mock_swift):
        st = create_stack(swiftsignalhandle_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': "1234"
        }
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        st.create()

        exc = swiftclient_exceptions.ClientException("Overlimit",
                                                     http_status=413)
        mock_swift_object.delete_object.side_effect = (None, None, None, exc)
        rsrc = st.resources['test_wait_condition_handle']
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(rsrc.delete))
        self.assertEqual('ClientException: '
                         'resources.test_wait_condition_handle: '
                         'Overlimit: 413', six.text_type(exc))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_delete_container_error(self, mock_name, mock_swift):
        st = create_stack(swiftsignalhandle_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': "1234"
        }
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        st.create()

        exc = swiftclient_exceptions.ClientException("Object DELETE failed",
                                                     http_status=404)
        mock_swift_object.delete_object.side_effect = (None, None, None, exc)

        exc = swiftclient_exceptions.ClientException("Overlimit",
                                                     http_status=413)
        mock_swift_object.delete_container.side_effect = (exc,)

        rsrc = st.resources['test_wait_condition_handle']
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(rsrc.delete))
        self.assertEqual('ClientException: '
                         'resources.test_wait_condition_handle: '
                         'Overlimit: 413', six.text_type(exc))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_delete_non_empty_container(self, mock_name, mock_swift):
        st = create_stack(swiftsignalhandle_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': "1234"
        }
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        st.create()

        exc = swiftclient_exceptions.ClientException("Object DELETE failed",
                                                     http_status=404)
        mock_swift_object.delete_object.side_effect = (None, None, None, exc)
        exc = swiftclient_exceptions.ClientException("Container DELETE failed",
                                                     http_status=409)
        mock_swift_object.delete_container.side_effect = exc
        rsrc = st.resources['test_wait_condition_handle']
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual(('DELETE', 'COMPLETE'), rsrc.state)
        self.assertEqual(4, mock_swift_object.delete_object.call_count)

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    def test_handle_update(self, mock_swift):
        st = create_stack(swiftsignalhandle_template)
        handle = st['test_wait_condition_handle']
        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': "1234"
        }
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        st.create()
        rsrc = st.resources['test_wait_condition_handle']
        old_url = rsrc.FnGetRefId()
        update_snippet = rsrc_defn.ResourceDefinition(handle.name,
                                                      handle.type(),
                                                      handle.properties.data)
        scheduler.TaskRunner(handle.update, update_snippet)()
        self.assertEqual(old_url, rsrc.FnGetRefId())

    def test_swift_handle_refid_convergence_cache_data(self):
        cache_data = {
            'test_wait_condition_handle': node_data.NodeData.from_dict({
                'uuid': mock.ANY,
                'id': mock.ANY,
                'action': 'CREATE',
                'status': 'COMPLETE',
                'reference_id': 'convg_xyz'
            })
        }
        st = create_stack(swiftsignalhandle_template, cache_data=cache_data)
        rsrc = st.defn['test_wait_condition_handle']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())


class SwiftSignalTest(common.HeatTestCase):

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_create(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 2)
        mock_swift_object.get_object.return_value = (obj_header, '')

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)

    @mock.patch.object(swift.SwiftClientPlugin, 'get_signal_url')
    def test_validate_handle_url_bad_tempurl(self, mock_handle_url):
        mock_handle_url.return_value = (
            "http://fake-host.com:8080/v1/my-container/"
            "test_st-test_wait_condition_handle?temp_url_sig="
            "12d8f9f2c923fbeb555041d4ed63d83de6768e95&"
            "temp_url_expires=1404762741")
        st = create_stack(swiftsignal_template)

        st.create()
        self.assertIn('not a valid SwiftSignalHandle.  The Swift TempURL path',
                      six.text_type(st.status_reason))

    @mock.patch.object(swift.SwiftClientPlugin, 'get_signal_url')
    def test_validate_handle_url_bad_container_name(self, mock_handle_url):
        mock_handle_url.return_value = (
            "http://fake-host.com:8080/v1/AUTH_test_tenant/my-container/"
            "test_st-test_wait_condition_handle?temp_url_sig="
            "12d8f9f2c923fbeb555041d4ed63d83de6768e95&"
            "temp_url_expires=1404762741")
        st = create_stack(swiftsignal_template)

        st.create()
        self.assertIn('not a valid SwiftSignalHandle.  The container name',
                      six.text_type(st.status_reason))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_multiple_signals_same_id_complete(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 2)
        mock_swift_object.get_object.side_effect = (
            (obj_header, json.dumps({'id': 1})),
            (obj_header, json.dumps({'id': 1})),
            (obj_header, json.dumps({'id': 1})),

            (obj_header, json.dumps({'id': 1})),
            (obj_header, json.dumps({'id': 2})),
            (obj_header, json.dumps({'id': 3})),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_multiple_signals_same_id_timeout(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 2)
        mock_swift_object.get_object.return_value = (obj_header,
                                                     json.dumps({'id': 1}))

        time_now = timeutils.utcnow()
        time_series = [datetime.timedelta(0, t) + time_now
                       for t in six.moves.xrange(1, 100)]
        timeutils.set_time_override(time_series)
        self.addCleanup(timeutils.clear_time_override)

        st.create()
        self.assertIn("SwiftSignalTimeout: resources.test_wait_condition: "
                      "1 of 2 received - Signal 1 received",
                      st.status_reason)
        wc = st['test_wait_condition']
        self.assertEqual("SwiftSignalTimeout: resources.test_wait_condition: "
                         "1 of 2 received - Signal 1 received",
                         wc.status_reason)

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_post_complete_to_handle(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 2)
        mock_swift_object.get_object.side_effect = (
            (obj_header, json.dumps({'id': 1, 'status': "SUCCESS"})),
            (obj_header, json.dumps({'id': 1, 'status': "SUCCESS"})),
            (obj_header, json.dumps({'id': 2, 'status': "SUCCESS"})),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_post_failed_to_handle(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)
        mock_swift_object.get_object.side_effect = (
            # Create
            (obj_header, json.dumps({'id': 1, 'status': "FAILURE",
                                     'reason': "foo"})),
            (obj_header, json.dumps({'id': 2, 'status': "FAILURE",
                                     'reason': "bar"})),

            # SwiftSignalFailure
            (obj_header, json.dumps({'id': 1, 'status': "FAILURE",
                                     'reason': "foo"})),
            (obj_header, json.dumps({'id': 2, 'status': "FAILURE",
                                     'reason': "bar"})),
        )

        st.create()
        self.assertEqual(('CREATE', 'FAILED'), st.state)
        wc = st['test_wait_condition']
        self.assertEqual("SwiftSignalFailure: resources.test_wait_condition: "
                         "foo;bar", wc.status_reason)

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_data(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 2)

        mock_swift_object.get_object.side_effect = (
            # st create
            (obj_header, json.dumps({'id': 1, 'data': "foo"})),
            (obj_header, json.dumps({'id': 2, 'data': "bar"})),
            (obj_header, json.dumps({'id': 3, 'data': "baz"})),

            # FnGetAtt call
            (obj_header, json.dumps({'id': 1, 'data': "foo"})),
            (obj_header, json.dumps({'id': 2, 'data': "bar"})),
            (obj_header, json.dumps({'id': 3, 'data': "baz"})),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)
        wc = st['test_wait_condition']
        self.assertEqual(json.dumps({1: 'foo', 2: 'bar', 3: 'baz'}),
                         wc.FnGetAtt('data'))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_data_noid(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)

        mock_swift_object.get_object.side_effect = (
            # st create
            (obj_header, json.dumps({'data': "foo", 'reason': "bar",
                                     'status': "SUCCESS"})),
            (obj_header, json.dumps({'data': "dog", 'reason': "cat",
                                     'status': "SUCCESS"})),

            # FnGetAtt call
            (obj_header, json.dumps({'data': "foo", 'reason': "bar",
                                     'status': "SUCCESS"})),
            (obj_header, json.dumps({'data': "dog", 'reason': "cat",
                                     'status': "SUCCESS"})),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)
        wc = st['test_wait_condition']
        self.assertEqual(json.dumps({1: 'foo', 2: 'dog'}), wc.FnGetAtt('data'))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_data_nodata(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)

        mock_swift_object.get_object.side_effect = (
            # st create
            (obj_header, ''),
            (obj_header, ''),

            # FnGetAtt call
            (obj_header, ''),
            (obj_header, ''),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)
        wc = st['test_wait_condition']
        self.assertEqual(json.dumps({1: None, 2: None}), wc.FnGetAtt('data'))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_data_partial_complete(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']
        wc = st['test_wait_condition']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)
        mock_swift_object.get_object.return_value = (
            obj_header, json.dumps({'status': 'SUCCESS'}))

        st.create()
        self.assertEqual(['SUCCESS', 'SUCCESS'], wc.get_status())
        expected = [{'status': 'SUCCESS', 'reason': 'Signal 1 received',
                     'data': None, 'id': 1},
                    {'status': 'SUCCESS', 'reason': 'Signal 2 received',
                     'data': None, 'id': 2}]
        self.assertEqual(expected, wc.get_signals())

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_get_status_none_complete(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']
        wc = st['test_wait_condition']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)
        mock_swift_object.get_object.return_value = (obj_header, '')

        st.create()
        self.assertEqual(['SUCCESS', 'SUCCESS'], wc.get_status())
        expected = [{'status': 'SUCCESS', 'reason': 'Signal 1 received',
                     'data': None, 'id': 1},
                    {'status': 'SUCCESS', 'reason': 'Signal 2 received',
                     'data': None, 'id': 2}]
        self.assertEqual(expected, wc.get_signals())

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_get_status_partial_complete(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']
        wc = st['test_wait_condition']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)
        mock_swift_object.get_object.return_value = (
            obj_header, json.dumps({'id': 1, 'status': "SUCCESS"}))

        st.create()
        self.assertEqual(['SUCCESS'], wc.get_status())
        expected = [{'status': 'SUCCESS', 'reason': 'Signal 1 received',
                     'data': None, 'id': 1}]
        self.assertEqual(expected, wc.get_signals())

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_get_status_failure(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']
        wc = st['test_wait_condition']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)
        mock_swift_object.get_object.return_value = (
            obj_header, json.dumps({'id': 1, 'status': "FAILURE"}))

        st.create()
        self.assertEqual(('CREATE', 'FAILED'), st.state)
        self.assertEqual(['FAILURE'], wc.get_status())
        expected = [{'status': 'FAILURE', 'reason': 'Signal 1 received',
                     'data': None, 'id': 1}]
        self.assertEqual(expected, wc.get_signals())

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_getatt_token(self, mock_name, mock_swift):
        st = create_stack(swiftsignalhandle_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)

        mock_swift_object.get_object.side_effect = (
            # st create
            (obj_header, ''),
            (obj_header, ''),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)
        self.assertEqual('', handle.FnGetAtt('token'))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_getatt_endpoint(self, mock_name, mock_swift):
        st = create_stack(swiftsignalhandle_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)

        mock_swift_object.get_object.side_effect = (
            # st create
            (obj_header, ''),
            (obj_header, ''),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)
        expected = ('http://fake-host.com:8080/v1/AUTH_test_tenant/%s/'
                    r'test_st-test_wait_condition_handle-abcdefghijkl\?temp_'
                    'url_sig=[0-9a-f]{40}&temp_url_expires=[0-9]{10}') % st.id
        self.assertThat(handle.FnGetAtt('endpoint'),
                        matchers.MatchesRegex(expected))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_getatt_curl_cli(self, mock_name, mock_swift):
        st = create_stack(swiftsignalhandle_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)

        mock_swift_object.get_object.side_effect = (
            # st create
            (obj_header, ''),
            (obj_header, ''),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)
        expected = ("curl -i -X PUT 'http://fake-host.com:8080/v1/"
                    "AUTH_test_tenant/%s/test_st-test_wait_condition_"
                    r"handle-abcdefghijkl\?temp_url_sig=[0-9a-f]{40}&"
                    "temp_url_expires=[0-9]{10}'") % st.id
        self.assertThat(handle.FnGetAtt('curl_cli'),
                        matchers.MatchesRegex(expected))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_invalid_json_data(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)

        mock_swift_object.get_object.side_effect = (
            # st create
            (obj_header, '{"status": "SUCCESS"'),
            (obj_header, '{"status": "FAI'),
        )

        st.create()
        self.assertEqual(('CREATE', 'FAILED'), st.state)
        wc = st['test_wait_condition']
        self.assertEqual('Error: resources.test_wait_condition: '
                         'Failed to parse JSON data: {"status": '
                         '"SUCCESS"', wc.status_reason)

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_unknown_status(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 1)

        mock_swift_object.get_object.return_value = (
            obj_header, '{"status": "BOO"}')

        st.create()
        self.assertEqual(('CREATE', 'FAILED'), st.state)
        wc = st['test_wait_condition']
        self.assertEqual('Error: resources.test_wait_condition: '
                         'Unknown status: BOO', wc.status_reason)

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_swift_objects_deleted(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.side_effect = (
            cont_index(obj_name, 2),  # Objects are there during create
            (container_header, []),   # The user deleted the objects
        )
        mock_swift_object.get_object.side_effect = (
            (obj_header, json.dumps({'id': 1})),  # Objects there during create
            (obj_header, json.dumps({'id': 2})),
            (obj_header, json.dumps({'id': 3})),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)
        wc = st['test_wait_condition']
        self.assertEqual("null", wc.FnGetAtt('data'))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_swift_objects_invisible(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name

        mock_swift_object.get_container.side_effect = (
            (container_header, []),   # Just-created objects aren't visible yet
            (container_header, []),
            (container_header, []),
            (container_header, []),
            cont_index(obj_name, 1),
        )
        mock_swift_object.get_object.side_effect = (
            (obj_header, json.dumps({'id': 1})),
            (obj_header, json.dumps({'id': 2})),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_swift_container_deleted(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.side_effect = [
            cont_index(obj_name, 2),  # Objects are there during create
            swiftclient_client.ClientException("Container GET failed",
                                               http_status=404)  # User deleted
        ]
        mock_swift_object.get_object.side_effect = (
            (obj_header, json.dumps({'id': 1})),  # Objects there during create
            (obj_header, json.dumps({'id': 2})),
            (obj_header, json.dumps({'id': 3})),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)
        wc = st['test_wait_condition']
        self.assertEqual("null", wc.FnGetAtt('data'))

    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    @mock.patch.object(resource.Resource, 'physical_resource_name')
    def test_swift_get_object_404(self, mock_name, mock_swift):
        st = create_stack(swiftsignal_template)
        handle = st['test_wait_condition_handle']

        mock_swift_object = mock.Mock()
        mock_swift.return_value = mock_swift_object
        mock_swift_object.url = "http://fake-host.com:8080/v1/AUTH_1234"
        mock_swift_object.head_account.return_value = {
            'x-account-meta-temp-url-key': '123456'
        }
        obj_name = "%s-%s-abcdefghijkl" % (st.name, handle.name)
        mock_name.return_value = obj_name
        mock_swift_object.get_container.return_value = cont_index(obj_name, 2)
        mock_swift_object.get_object.side_effect = (
            swiftclient_client.ClientException(
                "Object %s not found" % obj_name, http_status=404),
            (obj_header, '{"id": 1}'),
            (obj_header, '{"id": 2}'),
        )

        st.create()
        self.assertEqual(('CREATE', 'COMPLETE'), st.state)
