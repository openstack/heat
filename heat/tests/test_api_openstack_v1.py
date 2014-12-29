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

import json

import mock
from oslo_config import cfg
from oslo_log import log
from oslo_messaging._drivers import common as rpc_common
from oslo_messaging import exceptions
import six
import webob.exc

import heat.api.middleware.fault as fault
import heat.api.openstack.v1 as api_v1
import heat.api.openstack.v1.actions as actions
import heat.api.openstack.v1.build_info as build_info
import heat.api.openstack.v1.events as events
import heat.api.openstack.v1.resources as resources
import heat.api.openstack.v1.services as services
import heat.api.openstack.v1.software_configs as software_configs
import heat.api.openstack.v1.software_deployments as software_deployments
import heat.api.openstack.v1.stacks as stacks
from heat.common import exception as heat_exc
from heat.common import identifier
from heat.common import policy
from heat.common import urlfetch
from heat.common import wsgi
from heat.rpc import api as rpc_api
from heat.rpc import client as rpc_client
from heat.tests import common
from heat.tests import utils


def request_with_middleware(middleware, func, req, *args, **kwargs):

    @webob.dec.wsgify
    def _app(req):
        return func(req, *args, **kwargs)

    resp = middleware(_app).process_request(req)
    return resp


def to_remote_error(error):
    """Converts the given exception to the one with the _Remote suffix.
    """
    exc_info = (type(error), error, None)
    serialized = rpc_common.serialize_remote_exception(exc_info)
    remote_error = rpc_common.deserialize_remote_exception(
        serialized, ["heat.common.exception"])
    return remote_error


class InstantiationDataTest(common.HeatTestCase):

    def test_format_parse(self):
        data = {"AWSTemplateFormatVersion": "2010-09-09",
                "key1": ["val1[0]", "val1[1]"],
                "key2": "val2"}
        json_repr = ('{"AWSTemplateFormatVersion" : "2010-09-09",'
                     '"key1": [ "val1[0]", "val1[1]" ], '
                     '"key2": "val2" }')
        parsed = stacks.InstantiationData.format_parse(json_repr, 'foo')
        self.assertEqual(data, parsed)

    def test_format_parse_invalid(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          stacks.InstantiationData.format_parse,
                          '!@#$%^&not json', 'Garbage')

    def test_format_parse_invalid_message(self):
        # make sure the parser error gets through to the caller.
        bad_temp = '''
heat_template_version: '2013-05-23'
parameters:
  KeyName:
     type: string
    description: bla
        '''

        parse_ex = self.assertRaises(webob.exc.HTTPBadRequest,
                                     stacks.InstantiationData.format_parse,
                                     bad_temp, 'foo')
        self.assertIn('line 4, column 3', six.text_type(parse_ex))

    def test_stack_name(self):
        body = {'stack_name': 'wibble'}
        data = stacks.InstantiationData(body)
        self.assertEqual('wibble', data.stack_name())

    def test_stack_name_missing(self):
        body = {'not the stack_name': 'wibble'}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.stack_name)

    def test_template_inline(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'template': template}
        data = stacks.InstantiationData(body)
        self.assertEqual(template, data.template())

    def test_template_string_json(self):
        template = ('{"heat_template_version": "2013-05-23",'
                    '"foo": "bar", "blarg": "wibble"}')
        body = {'template': template}
        data = stacks.InstantiationData(body)
        self.assertEqual(json.loads(template), data.template())

    def test_template_string_yaml(self):
        template = '''HeatTemplateFormatVersion: 2012-12-12
foo: bar
blarg: wibble
'''
        parsed = {u'HeatTemplateFormatVersion': u'2012-12-12',
                  u'blarg': u'wibble',
                  u'foo': u'bar'}

        body = {'template': template}
        data = stacks.InstantiationData(body)
        self.assertEqual(parsed, data.template())

    def test_template_url(self):
        template = {'heat_template_version': '2013-05-23',
                    'foo': 'bar',
                    'blarg': 'wibble'}
        url = 'http://example.com/template'
        body = {'template_url': url}
        data = stacks.InstantiationData(body)

        self.m.StubOutWithMock(urlfetch, 'get')
        urlfetch.get(url).AndReturn(json.dumps(template))
        self.m.ReplayAll()

        self.assertEqual(template, data.template())
        self.m.VerifyAll()

    def test_template_priority(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        url = 'http://example.com/template'
        body = {'template': template, 'template_url': url}
        data = stacks.InstantiationData(body)

        self.m.StubOutWithMock(urlfetch, 'get')
        self.m.ReplayAll()

        self.assertEqual(template, data.template())
        self.m.VerifyAll()

    def test_template_missing(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'not the template': template}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.template)

    def test_parameters(self):
        params = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'parameters': params,
                'parameter_defaults': {},
                'resource_registry': {}}
        data = stacks.InstantiationData(body)
        self.assertEqual(body, data.environment())

    def test_environment_only_params(self):
        env = {'parameters': {'foo': 'bar', 'blarg': 'wibble'}}
        body = {'environment': env}
        data = stacks.InstantiationData(body)
        self.assertEqual(env, data.environment())

    def test_environment_and_parameters(self):
        body = {'parameters': {'foo': 'bar'},
                'environment': {'parameters': {'blarg': 'wibble'}}}
        expect = {'parameters': {'blarg': 'wibble',
                                 'foo': 'bar'},
                  'parameter_defaults': {},
                  'resource_registry': {}}
        data = stacks.InstantiationData(body)
        self.assertEqual(expect, data.environment())

    def test_parameters_override_environment(self):
        # This tests that the cli parameters will override
        # any parameters in the environment.
        body = {'parameters': {'foo': 'bar',
                               'tester': 'Yes'},
                'environment': {'parameters': {'blarg': 'wibble',
                                               'tester': 'fail'}}}
        expect = {'parameters': {'blarg': 'wibble',
                                 'foo': 'bar',
                                 'tester': 'Yes'},
                  'parameter_defaults': {},
                  'resource_registry': {}}
        data = stacks.InstantiationData(body)
        self.assertEqual(expect, data.environment())

    def test_environment_bad_format(self):
        env = {'somethingnotsupported': {'blarg': 'wibble'}}
        body = {'environment': json.dumps(env)}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.environment)

    def test_environment_missing(self):
        env = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'not the environment': env}
        data = stacks.InstantiationData(body)
        self.assertEqual({'parameters': {}, 'parameter_defaults': {},
                          'resource_registry': {}},
                         data.environment())

    def test_args(self):
        body = {
            'parameters': {},
            'environment': {},
            'stack_name': 'foo',
            'template': {},
            'template_url': 'http://example.com/',
            'timeout_mins': 60,
        }
        data = stacks.InstantiationData(body)
        self.assertEqual({'timeout_mins': 60}, data.args())


class ControllerTest(object):
    """
    Common utilities for testing API Controllers.
    """

    def __init__(self, *args, **kwargs):
        super(ControllerTest, self).__init__(*args, **kwargs)

        cfg.CONF.set_default('host', 'server.test')
        self.topic = rpc_api.ENGINE_TOPIC
        self.api_version = '1.0'
        self.tenant = 't'
        self.mock_enforce = None
        log.register_options(cfg.CONF)

    def _environ(self, path):
        return {
            'SERVER_NAME': 'server.test',
            'SERVER_PORT': 8004,
            'SCRIPT_NAME': '/v1',
            'PATH_INFO': '/%s' % self.tenant + path,
            'wsgi.url_scheme': 'http',
        }

    def _simple_request(self, path, params=None, method='GET'):
        environ = self._environ(path)
        environ['REQUEST_METHOD'] = method

        if params:
            qs = "&".join(["=".join([k, str(params[k])]) for k in params])
            environ['QUERY_STRING'] = qs

        req = wsgi.Request(environ)
        req.context = utils.dummy_context('api_test_user', self.tenant)
        self.context = req.context
        return req

    def _get(self, path, params=None):
        return self._simple_request(path, params=params)

    def _delete(self, path):
        return self._simple_request(path, method='DELETE')

    def _abandon(self, path):
        return self._simple_request(path, method='DELETE')

    def _data_request(self, path, data, content_type='application/json',
                      method='POST'):
        environ = self._environ(path)
        environ['REQUEST_METHOD'] = method

        req = wsgi.Request(environ)
        req.context = utils.dummy_context('api_test_user', self.tenant)
        self.context = req.context
        req.body = data
        return req

    def _post(self, path, data, content_type='application/json'):
        return self._data_request(path, data, content_type)

    def _put(self, path, data, content_type='application/json'):
        return self._data_request(path, data, content_type, method='PUT')

    def _patch(self, path, data, content_type='application/json'):
        return self._data_request(path, data, content_type, method='PATCH')

    def _url(self, id):
        host = 'server.test:8004'
        path = '/v1/%(tenant)s/stacks/%(stack_name)s/%(stack_id)s%(path)s' % id
        return 'http://%s%s' % (host, path)

    def tearDown(self):
        # Common tearDown to assert that policy enforcement happens for all
        # controller actions
        if self.mock_enforce:
            self.mock_enforce.assert_called_with(
                action=self.action,
                context=self.context,
                scope=self.controller.REQUEST_SCOPE)
            self.assertEqual(self.expected_request_count,
                             len(self.mock_enforce.call_args_list))
        super(ControllerTest, self).tearDown()

    def _mock_enforce_setup(self, mocker, action, allowed=True,
                            expected_request_count=1):
        self.mock_enforce = mocker
        self.action = action
        self.mock_enforce.return_value = allowed
        self.expected_request_count = expected_request_count


@mock.patch.object(policy.Enforcer, 'enforce')
class StackControllerTest(ControllerTest, common.HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        super(StackControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig(object):
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = stacks.StackController(options=cfgopts)

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        req = self._get('/stacks')

        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        engine_resp = [
            {
                u'stack_identity': dict(identity),
                u'updated_time': u'2012-07-09T09:13:11Z',
                u'template_description': u'blah',
                u'description': u'blah',
                u'stack_status_reason': u'Stack successfully created',
                u'creation_time': u'2012-07-09T09:12:45Z',
                u'stack_name': identity.stack_name,
                u'stack_action': u'CREATE',
                u'stack_status': u'COMPLETE',
                u'parameters': {},
                u'outputs': [],
                u'notification_topics': [],
                u'capabilities': [],
                u'disable_rollback': True,
                u'timeout_mins': 60,
            }
        ]
        mock_call.return_value = engine_resp

        result = self.controller.index(req, tenant_id=identity.tenant)

        expected = {
            'stacks': [
                {
                    'links': [{"href": self._url(identity),
                               "rel": "self"}],
                    'id': '1',
                    u'updated_time': u'2012-07-09T09:13:11Z',
                    u'description': u'blah',
                    u'stack_status_reason': u'Stack successfully created',
                    u'creation_time': u'2012-07-09T09:12:45Z',
                    u'stack_name': u'wordpress',
                    u'stack_status': u'CREATE_COMPLETE'
                }
            ]
        }
        self.assertEqual(expected, result)
        default_args = {'limit': None, 'sort_keys': None, 'marker': None,
                        'sort_dir': None, 'filters': None, 'tenant_safe': True,
                        'show_deleted': False, 'show_nested': False,
                        'show_hidden': False}
        mock_call.assert_called_once_with(
            req.context, ('list_stacks', default_args))

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_whitelists_pagination_params(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {
            'limit': 10,
            'sort_keys': 'fake sort keys',
            'marker': 'fake marker',
            'sort_dir': 'fake sort dir',
            'balrog': 'you shall not pass!'
        }
        req = self._get('/stacks', params=params)
        mock_call.return_value = []

        self.controller.index(req, tenant_id=self.tenant)

        rpc_call_args, _ = mock_call.call_args
        engine_args = rpc_call_args[1][1]
        self.assertEqual(9, len(engine_args))
        self.assertIn('limit', engine_args)
        self.assertIn('sort_keys', engine_args)
        self.assertIn('marker', engine_args)
        self.assertIn('sort_dir', engine_args)
        self.assertIn('filters', engine_args)
        self.assertIn('tenant_safe', engine_args)
        self.assertNotIn('balrog', engine_args)

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_limit_not_int(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {'limit': 'not-an-int'}
        req = self._get('/stacks', params=params)

        ex = self.assertRaises(ValueError,
                               self.controller.index, req,
                               tenant_id=self.tenant)
        self.assertEqual("Only integer is acceptable by 'limit'.",
                         six.text_type(ex))
        self.assertFalse(mock_call.called)

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_whitelist_filter_params(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {
            'status': 'fake status',
            'name': 'fake name',
            'action': 'fake action',
            'username': 'fake username',
            'tenant': 'fake tenant',
            'owner_id': 'fake owner-id',
            'balrog': 'you shall not pass!'
        }
        req = self._get('/stacks', params=params)
        mock_call.return_value = []

        self.controller.index(req, tenant_id=self.tenant)

        rpc_call_args, _ = mock_call.call_args
        engine_args = rpc_call_args[1][1]
        self.assertIn('filters', engine_args)

        filters = engine_args['filters']
        self.assertEqual(6, len(filters))
        self.assertIn('status', filters)
        self.assertIn('name', filters)
        self.assertIn('action', filters)
        self.assertIn('username', filters)
        self.assertIn('tenant', filters)
        self.assertIn('owner_id', filters)
        self.assertNotIn('balrog', filters)

    def test_index_returns_stack_count_if_with_count_is_true(
            self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {'with_count': 'True'}
        req = self._get('/stacks', params=params)
        engine = self.controller.rpc_client

        engine.list_stacks = mock.Mock(return_value=[])
        engine.count_stacks = mock.Mock(return_value=0)

        result = self.controller.index(req, tenant_id=self.tenant)
        self.assertEqual(0, result['count'])

    def test_index_doesnt_return_stack_count_if_with_count_is_false(
            self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {'with_count': 'false'}
        req = self._get('/stacks', params=params)
        engine = self.controller.rpc_client

        engine.list_stacks = mock.Mock(return_value=[])
        engine.count_stacks = mock.Mock()

        result = self.controller.index(req, tenant_id=self.tenant)
        self.assertNotIn('count', result)
        assert not engine.count_stacks.called

    def test_index_with_count_is_invalid(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {'with_count': 'invalid_value'}
        req = self._get('/stacks', params=params)

        exc = self.assertRaises(ValueError, self.controller.index,
                                req, tenant_id=self.tenant)
        excepted = ('Unrecognized value "invalid_value", '
                    'acceptable values are: true, false')
        self.assertIn(excepted, six.text_type(exc))

    @mock.patch.object(rpc_client.EngineClient, 'count_stacks')
    def test_index_doesnt_break_with_old_engine(self, mock_count_stacks,
                                                mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {'with_count': 'True'}
        req = self._get('/stacks', params=params)
        engine = self.controller.rpc_client

        engine.list_stacks = mock.Mock(return_value=[])
        mock_count_stacks.side_effect = AttributeError("Should not exist")

        result = self.controller.index(req, tenant_id=self.tenant)
        self.assertNotIn('count', result)

    def test_index_enforces_global_index_if_global_tenant(self, mock_enforce):
        params = {'global_tenant': 'True'}
        req = self._get('/stacks', params=params)
        rpc_client = self.controller.rpc_client

        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        self.controller.index(req, tenant_id=self.tenant)
        mock_enforce.assert_called_with(action='global_index',
                                        scope=self.controller.REQUEST_SCOPE,
                                        context=self.context)

    def test_global_index_sets_tenant_safe_to_false(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        params = {'global_tenant': 'True'}
        req = self._get('/stacks', params=params)
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
                                                       tenant_safe=False)

    def test_global_index_show_deleted_false(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        params = {'show_deleted': 'False'}
        req = self._get('/stacks', params=params)
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
                                                       tenant_safe=True,
                                                       show_deleted=False)

    def test_global_index_show_deleted_true(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        params = {'show_deleted': 'True'}
        req = self._get('/stacks', params=params)
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
                                                       tenant_safe=True,
                                                       show_deleted=True)

    def test_global_index_show_nested_false(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        params = {'show_nested': 'False'}
        req = self._get('/stacks', params=params)
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
                                                       tenant_safe=True,
                                                       show_nested=False)

    def test_global_index_show_nested_true(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        params = {'show_nested': 'True'}
        req = self._get('/stacks', params=params)
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
                                                       tenant_safe=True,
                                                       show_nested=True)

    def test_index_show_deleted_True_with_count_True(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock(return_value=0)

        params = {'show_deleted': 'True',
                  'with_count': 'True'}
        req = self._get('/stacks', params=params)
        result = self.controller.index(req, tenant_id=self.tenant)
        self.assertEqual(0, result['count'])
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
                                                       tenant_safe=True,
                                                       show_deleted=True)
        rpc_client.count_stacks.assert_called_once_with(mock.ANY,
                                                        filters=mock.ANY,
                                                        tenant_safe=True,
                                                        show_deleted=True,
                                                        show_nested=False)

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_detail(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'detail', True)
        req = self._get('/stacks/detail')

        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        engine_resp = [
            {
                u'stack_identity': dict(identity),
                u'updated_time': u'2012-07-09T09:13:11Z',
                u'template_description': u'blah',
                u'description': u'blah',
                u'stack_status_reason': u'Stack successfully created',
                u'creation_time': u'2012-07-09T09:12:45Z',
                u'stack_name': identity.stack_name,
                u'stack_action': u'CREATE',
                u'stack_status': u'COMPLETE',
                u'parameters': {'foo': 'bar'},
                u'outputs': ['key', 'value'],
                u'notification_topics': [],
                u'capabilities': [],
                u'disable_rollback': True,
                u'timeout_mins': 60,
            }
        ]
        mock_call.return_value = engine_resp

        result = self.controller.detail(req, tenant_id=identity.tenant)

        expected = {
            'stacks': [
                {
                    'links': [{"href": self._url(identity),
                               "rel": "self"}],
                    'id': '1',
                    u'updated_time': u'2012-07-09T09:13:11Z',
                    u'template_description': u'blah',
                    u'description': u'blah',
                    u'stack_status_reason': u'Stack successfully created',
                    u'creation_time': u'2012-07-09T09:12:45Z',
                    u'stack_name': identity.stack_name,
                    u'stack_status': u'CREATE_COMPLETE',
                    u'parameters': {'foo': 'bar'},
                    u'outputs': ['key', 'value'],
                    u'notification_topics': [],
                    u'capabilities': [],
                    u'disable_rollback': True,
                    u'timeout_mins': 60,
                }
            ]
        }

        self.assertEqual(expected, result)
        default_args = {'limit': None, 'sort_keys': None, 'marker': None,
                        'sort_dir': None, 'filters': None, 'tenant_safe': True,
                        'show_deleted': False, 'show_nested': False,
                        'show_hidden': False}
        mock_call.assert_called_once_with(
            req.context, ('list_stacks', default_args))

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_rmt_aterr(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        req = self._get('/stacks')

        mock_call.side_effect = to_remote_error(AttributeError())

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('AttributeError', resp.json['error']['type'])
        mock_call.assert_called_once_with(
            req.context, ('list_stacks', mock.ANY))

    def test_index_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', False)

        req = self._get('/stacks')

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_rmt_interr(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        req = self._get('/stacks')

        mock_call.side_effect = to_remote_error(Exception())

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant)

        self.assertEqual(500, resp.json['code'])
        self.assertEqual('Exception', resp.json['error']['type'])
        mock_call.assert_called_once_with(
            req.context, ('list_stacks', mock.ANY))

    def test_create(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': identity.stack_name,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('create_stack',
             {'stack_name': identity.stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndReturn(dict(identity))
        self.m.ReplayAll()

        response = self.controller.create(req,
                                          tenant_id=identity.tenant,
                                          body=body)

        expected = {'stack':
                    {'id': '1',
                     'links': [{'href': self._url(identity), 'rel': 'self'}]}}
        self.assertEqual(expected, response)

        self.m.VerifyAll()

    def test_adopt(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')
        template = {
            "heat_template_version": "2013-05-23",
            "parameters": {"app_dbx": {"type": "string"}},
            "resources": {"res1": {"type": "GenericResourceType"}}}

        parameters = {"app_dbx": "test"}
        adopt_data = {
            "status": "COMPLETE",
            "name": "rtrove1",
            "parameters": parameters,
            "template": template,
            "action": "CREATE",
            "id": "8532f0d3-ea84-444e-b2bb-2543bb1496a4",
            "resources": {"res1": {
                    "status": "COMPLETE",
                    "name": "database_password",
                    "resource_id": "yBpuUROjfGQ2gKOD",
                    "action": "CREATE",
                    "type": "GenericResourceType",
                    "metadata": {}}}}
        body = {'template': None,
                'stack_name': identity.stack_name,
                'parameters': parameters,
                'timeout_mins': 30,
                'adopt_stack_data': str(adopt_data)}

        req = self._post('/stacks', json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('create_stack',
             {'stack_name': identity.stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {'timeout_mins': 30,
                       'adopt_stack_data': str(adopt_data)},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndReturn(dict(identity))
        self.m.ReplayAll()

        response = self.controller.create(req,
                                          tenant_id=identity.tenant,
                                          body=body)

        expected = {'stack':
                    {'id': '1',
                     'links': [{'href': self._url(identity), 'rel': 'self'}]}}
        self.assertEqual(expected, response)
        self.m.VerifyAll()

    def test_adopt_timeout_not_int(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        body = {'template': None,
                'stack_name': identity.stack_name,
                'parameters': {},
                'timeout_mins': 'not-an-int',
                'adopt_stack_data': 'does not matter'}

        req = self._post('/stacks', json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call')
        ex = self.assertRaises(ValueError,
                               self.controller.create, req,
                               tenant_id=self.tenant, body=body)

        self.assertEqual("Only integer is acceptable by 'timeout_mins'.",
                         six.text_type(ex))
        self.assertFalse(mock_call.called)

    def test_adopt_error(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')
        parameters = {"app_dbx": "test"}
        adopt_data = ["Test"]
        body = {'template': None,
                'stack_name': identity.stack_name,
                'parameters': parameters,
                'timeout_mins': 30,
                'adopt_stack_data': str(adopt_data)}

        req = self._post('/stacks', json.dumps(body))

        self.m.ReplayAll()
        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant,
                                       body=body)
        self.assertEqual(400, resp.status_code)
        self.assertEqual('400 Bad Request', resp.status)
        self.assertIn('Invalid adopt data', resp.text)
        self.m.VerifyAll()

    def test_create_with_files(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': identity.stack_name,
                'parameters': parameters,
                'files': {'my.yaml': 'This is the file contents.'},
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('create_stack',
             {'stack_name': identity.stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {'my.yaml': 'This is the file contents.'},
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndReturn(dict(identity))
        self.m.ReplayAll()

        result = self.controller.create(req,
                                        tenant_id=identity.tenant,
                                        body=body)
        expected = {'stack':
                    {'id': '1',
                     'links': [{'href': self._url(identity), 'rel': 'self'}]}}
        self.assertEqual(expected, result)

        self.m.VerifyAll()

    def test_create_err_rpcerr(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True, 3)
        stack_name = "wordpress"
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': stack_name,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        unknown_parameter = heat_exc.UnknownUserParameter(key='a')
        missing_parameter = heat_exc.UserParameterMissing(key='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndRaise(to_remote_error(AttributeError()))
        rpc_client.EngineClient.call(
            req.context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndRaise(to_remote_error(unknown_parameter))
        rpc_client.EngineClient.call(
            req.context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndRaise(to_remote_error(missing_parameter))
        self.m.ReplayAll()
        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('AttributeError', resp.json['error']['type'])

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('UnknownUserParameter', resp.json['error']['type'])

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('UserParameterMissing', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_create_err_existing(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        stack_name = "wordpress"
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': stack_name,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        error = heat_exc.StackExists(stack_name='s')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(409, resp.json['code'])
        self.assertEqual('StackExists', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_create_timeout_not_int(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        stack_name = "wordpress"
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': stack_name,
                'parameters': parameters,
                'timeout_mins': 'not-an-int'}

        req = self._post('/stacks', json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call')
        ex = self.assertRaises(ValueError,
                               self.controller.create, req,
                               tenant_id=self.tenant, body=body)

        self.assertEqual("Only integer is acceptable by 'timeout_mins'.",
                         six.text_type(ex))
        self.assertFalse(mock_call.called)

    def test_create_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', False)
        stack_name = "wordpress"
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': stack_name,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_create_err_engine(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        stack_name = "wordpress"
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': stack_name,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        error = heat_exc.StackValidationFailed(message='')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('StackValidationFailed', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_create_err_stack_bad_reqest(self, mock_enforce):
        cfg.CONF.set_override('debug', True)
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        error = heat_exc.HTTPExceptionDisguise(webob.exc.HTTPBadRequest())
        self.controller.create = mock.MagicMock(side_effect=error)

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create, req, body)

        # When HTTP disguised exceptions reach the fault app, they are
        # converted into regular responses, just like non-HTTP exceptions
        self.assertEqual(400, resp.json['code'])
        self.assertEqual('HTTPBadRequest', resp.json['error']['type'])
        self.assertIsNotNone(resp.json['error']['traceback'])

    @mock.patch.object(rpc_client.EngineClient, 'call')
    @mock.patch.object(stacks.stacks_view, 'format_stack')
    def test_preview_stack(self, mock_format, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'preview', True)
        body = {'stack_name': 'foo', 'template': {}}
        req = self._get('/stacks/preview', params={})
        mock_call.return_value = {}
        mock_format.return_value = 'formatted_stack'

        result = self.controller.preview(req, tenant_id=self.tenant, body=body)

        self.assertEqual({'stack': 'formatted_stack'}, result)

    def test_lookup(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks/%(stack_name)s' % identity)

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('identify_stack', {'stack_name': identity.stack_name})
        ).AndReturn(identity)

        self.m.ReplayAll()

        found = self.assertRaises(
            webob.exc.HTTPFound, self.controller.lookup, req,
            tenant_id=identity.tenant, stack_name=identity.stack_name)
        self.assertEqual(self._url(identity), found.location)

        self.m.VerifyAll()

    def test_lookup_arn(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks%s' % identity.arn_url_path())

        self.m.ReplayAll()

        found = self.assertRaises(
            webob.exc.HTTPFound, self.controller.lookup,
            req, tenant_id=identity.tenant, stack_name=identity.arn())
        self.assertEqual(self._url(identity), found.location)

        self.m.VerifyAll()

    def test_lookup_nonexistent(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s' % {
            'stack_name': stack_name})

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.lookup,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_lookup_err_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', False)
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s' % {
            'stack_name': stack_name})

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.lookup,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_name)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_lookup_resource(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks/%(stack_name)s/resources' % identity)

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('identify_stack', {'stack_name': identity.stack_name})
        ).AndReturn(identity)

        self.m.ReplayAll()

        found = self.assertRaises(
            webob.exc.HTTPFound, self.controller.lookup, req,
            tenant_id=identity.tenant, stack_name=identity.stack_name,
            path='resources')
        self.assertEqual(self._url(identity) + '/resources',
                         found.location)

        self.m.VerifyAll()

    def test_lookup_resource_nonexistent(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s/resources' % {
            'stack_name': stack_name})

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.lookup,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_name,
                                       path='resources')

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_lookup_resource_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', False)
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s/resources' % {
            'stack_name': stack_name})

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.lookup,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_name,
                                       path='resources')

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        parameters = {u'DBUsername': u'admin',
                      u'LinuxDistribution': u'F17',
                      u'InstanceType': u'm1.large',
                      u'DBRootPassword': u'admin',
                      u'DBPassword': u'admin',
                      u'DBName': u'wordpress'}
        outputs = [{u'output_key': u'WebsiteURL',
                    u'description': u'URL for Wordpress wiki',
                    u'output_value': u'http://10.0.0.8/wordpress'}]

        engine_resp = [
            {
                u'stack_identity': dict(identity),
                u'updated_time': u'2012-07-09T09:13:11Z',
                u'parameters': parameters,
                u'outputs': outputs,
                u'stack_status_reason': u'Stack successfully created',
                u'creation_time': u'2012-07-09T09:12:45Z',
                u'stack_name': identity.stack_name,
                u'notification_topics': [],
                u'stack_action': u'CREATE',
                u'stack_status': u'COMPLETE',
                u'description': u'blah',
                u'disable_rollback': True,
                u'timeout_mins':60,
                u'capabilities': [],
            }
        ]
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('show_stack', {'stack_identity': dict(identity)})
        ).AndReturn(engine_resp)
        self.m.ReplayAll()

        response = self.controller.show(req,
                                        tenant_id=identity.tenant,
                                        stack_name=identity.stack_name,
                                        stack_id=identity.stack_id)

        expected = {
            'stack': {
                'links': [{"href": self._url(identity),
                           "rel": "self"}],
                'id': '6',
                u'updated_time': u'2012-07-09T09:13:11Z',
                u'parameters': parameters,
                u'outputs': outputs,
                u'description': u'blah',
                u'stack_status_reason': u'Stack successfully created',
                u'creation_time': u'2012-07-09T09:12:45Z',
                u'stack_name': identity.stack_name,
                u'stack_status': u'CREATE_COMPLETE',
                u'capabilities': [],
                u'notification_topics': [],
                u'disable_rollback': True,
                u'timeout_mins': 60,
            }
        }
        self.assertEqual(expected, response)
        self.m.VerifyAll()

    def test_show_notfound(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wibble', '6')

        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('show_stack', {'stack_identity': dict(identity)})
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_show_invalidtenant(self, mock_enforce):
        identity = identifier.HeatIdentifier('wibble', 'wordpress', '6')

        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))
        self.m.VerifyAll()

    def test_show_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', False)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_get_template(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'template', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)
        template = {u'Foo': u'bar'}

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('get_template', {'stack_identity': dict(identity)})
        ).AndReturn(template)
        self.m.ReplayAll()

        response = self.controller.template(req, tenant_id=identity.tenant,
                                            stack_name=identity.stack_name,
                                            stack_id=identity.stack_id)

        self.assertEqual(template, response)
        self.m.VerifyAll()

    def test_get_template_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'template', False)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s/template'
                        % identity)

        self.m.ReplayAll()
        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.template,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))
        self.m.VerifyAll()

    def test_get_template_err_notfound(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'template', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('get_template', {'stack_identity': dict(identity)})
        ).AndRaise(to_remote_error(error))

        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.template,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_update(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {'timeout_mins': 30}})
        ).AndReturn(dict(identity))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_update_bad_name(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wibble', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        json.dumps(body))

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {u'parameters': parameters,
                         u'parameter_defaults': {},
                         u'resource_registry': {}},
              'files': {},
              'args': {'timeout_mins': 30}})
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.update,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id,
                                       body=body)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_update_timeout_not_int(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wibble', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 'not-int'}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call')
        ex = self.assertRaises(ValueError,
                               self.controller.update, req,
                               tenant_id=identity.tenant,
                               stack_name=identity.stack_name,
                               stack_id=identity.stack_id,
                               body=body)
        self.assertEqual("Only integer is acceptable by 'timeout_mins'.",
                         six.text_type(ex))
        self.assertFalse(mock_call.called)

    def test_update_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update', False)
        identity = identifier.HeatIdentifier(self.tenant, 'wibble', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        json.dumps(body))

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.update,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id,
                                       body=body)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_update_with_existing_parameters(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update_patch', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        body = {'template': template,
                'parameters': {},
                'files': {},
                'timeout_mins': 30}

        req = self._patch('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                          json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': {},
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {rpc_api.PARAM_EXISTING: True,
                       'timeout_mins': 30}})
        ).AndReturn(dict(identity))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_update_with_patched_existing_parameters(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update_patch', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 30}

        req = self._patch('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                          json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {rpc_api.PARAM_EXISTING: True,
                       'timeout_mins': 30}})
        ).AndReturn(dict(identity))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_update_with_patch_timeout_not_int(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update_patch', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 'not-int'}

        req = self._patch('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                          json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call')
        ex = self.assertRaises(ValueError,
                               self.controller.update_patch, req,
                               tenant_id=identity.tenant,
                               stack_name=identity.stack_name,
                               stack_id=identity.stack_id,
                               body=body)
        self.assertEqual("Only integer is acceptable by 'timeout_mins'.",
                         six.text_type(ex))
        self.assertFalse(mock_call.called)

    def test_update_with_existing_and_default_parameters(
            self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update_patch', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        clear_params = [u'DBUsername', u'DBPassword', u'LinuxDistribution']
        body = {'template': template,
                'parameters': {},
                'clear_parameters': clear_params,
                'files': {},
                'timeout_mins': 30}

        req = self._patch('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                          json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': {},
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {rpc_api.PARAM_EXISTING: True,
                       'clear_parameters': clear_params,
                       'timeout_mins': 30}})
        ).AndReturn(dict(identity))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_update_with_patched_and_default_parameters(
            self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update_patch', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        clear_params = [u'DBUsername', u'DBPassword', u'LinuxDistribution']
        body = {'template': template,
                'parameters': parameters,
                'clear_parameters': clear_params,
                'files': {},
                'timeout_mins': 30}

        req = self._patch('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                          json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': parameters,
                         'parameter_defaults': {},
                         'resource_registry': {}},
              'files': {},
              'args': {rpc_api.PARAM_EXISTING: True,
                       'clear_parameters': clear_params,
                       'timeout_mins': 30}})
        ).AndReturn(dict(identity))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_delete(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._delete('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        # Engine returns None when delete successful
        rpc_client.EngineClient.call(
            req.context,
            ('delete_stack', {'stack_identity': dict(identity)})
        ).AndReturn(None)
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNoContent,
                          self.controller.delete,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id)
        self.m.VerifyAll()

    def test_delete_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete', False)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._delete('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.delete,
                                       req, tenant_id=self.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_abandon(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'abandon', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._abandon('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        # Engine returns json data on abandon completion
        expected = {"name": "test", "id": "123"}
        rpc_client.EngineClient.call(
            req.context,
            ('abandon_stack', {'stack_identity': dict(identity)})
        ).AndReturn(expected)
        self.m.ReplayAll()

        ret = self.controller.abandon(req,
                                      tenant_id=identity.tenant,
                                      stack_name=identity.stack_name,
                                      stack_id=identity.stack_id)
        self.assertEqual(expected, ret)
        self.m.VerifyAll()

    def test_abandon_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'abandon', False)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._abandon('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.abandon,
                                       req, tenant_id=self.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_delete_bad_name(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wibble', '6')

        req = self._delete('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        # Engine returns None when delete successful
        rpc_client.EngineClient.call(
            req.context,
            ('delete_stack', {'stack_identity': dict(identity)})
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.delete,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_validate_template(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'validate_template', True)
        template = {u'Foo': u'bar'}
        body = {'template': template}

        req = self._post('/validate', json.dumps(body))

        engine_response = {
            u'Description': u'blah',
            u'Parameters': [
                {
                    u'NoEcho': u'false',
                    u'ParameterKey': u'InstanceType',
                    u'Description': u'Instance type'
                }
            ]
        }

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('validate_template',
             {'template': template,
              'params': {'parameters': {},
                         'parameter_defaults': {},
                         'resource_registry': {}}})
        ).AndReturn(engine_response)
        self.m.ReplayAll()

        response = self.controller.validate_template(req,
                                                     tenant_id=self.tenant,
                                                     body=body)
        self.assertEqual(engine_response, response)
        self.m.VerifyAll()

    def test_validate_template_error(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'validate_template', True)
        template = {u'Foo': u'bar'}
        body = {'template': template}

        req = self._post('/validate', json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('validate_template',
             {'template': template,
              'params': {'parameters': {},
                         'parameter_defaults': {},
                         'resource_registry': {}}})
        ).AndReturn({'Error': 'fubar'})
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_template,
                          req, tenant_id=self.tenant, body=body)
        self.m.VerifyAll()

    def test_validate_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'validate_template', False)
        template = {u'Foo': u'bar'}
        body = {'template': template}

        req = self._post('/validate', json.dumps(body))

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.validate_template,
                                       req, tenant_id=self.tenant,
                                       body=body)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_list_resource_types(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'list_resource_types', True)
        req = self._get('/resource_types')

        engine_response = ['AWS::EC2::Instance',
                           'AWS::EC2::EIP',
                           'AWS::EC2::EIPAssociation']

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context, ('list_resource_types', {'support_status': None}),
            version="1.1"
        ).AndReturn(engine_response)
        self.m.ReplayAll()
        response = self.controller.list_resource_types(req,
                                                       tenant_id=self.tenant)
        self.assertEqual({'resource_types': engine_response}, response)
        self.m.VerifyAll()

    def test_list_resource_types_error(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'list_resource_types', True)
        req = self._get('/resource_types')

        error = heat_exc.ResourceTypeNotFound(type_name='')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('list_resource_types',
             {'support_status': None},
             ), version="1.1"
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.list_resource_types,
                                       req, tenant_id=self.tenant)
        self.assertEqual(404, resp.json['code'])
        self.assertEqual('ResourceTypeNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_list_resource_types_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'list_resource_types', False)
        req = self._get('/resource_types')
        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.list_resource_types,
                                       req, tenant_id=self.tenant)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_resource_schema(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'resource_schema', True)
        req = self._get('/resource_types/ResourceWithProps')
        type_name = 'ResourceWithProps'

        engine_response = {
            'resource_type': type_name,
            'properties': {
                'Foo': {'type': 'string', 'required': False},
            },
            'attributes': {
                'foo': {'description': 'A generic attribute'},
                'Foo': {'description': 'Another generic attribute'},
            },
        }
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('resource_schema', {'type_name': type_name})
        ).AndReturn(engine_response)
        self.m.ReplayAll()
        response = self.controller.resource_schema(req,
                                                   tenant_id=self.tenant,
                                                   type_name=type_name)
        self.assertEqual(engine_response, response)
        self.m.VerifyAll()

    def test_resource_schema_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'resource_schema', True)
        req = self._get('/resource_types/BogusResourceType')
        type_name = 'BogusResourceType'

        error = heat_exc.ResourceTypeNotFound(type_name='BogusResourceType')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('resource_schema', {'type_name': type_name})
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.resource_schema,
                                       req, tenant_id=self.tenant,
                                       type_name=type_name)
        self.assertEqual(404, resp.json['code'])
        self.assertEqual('ResourceTypeNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_resource_schema_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'resource_schema', False)
        req = self._get('/resource_types/BogusResourceType')
        type_name = 'BogusResourceType'

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.resource_schema,
                                       req, tenant_id=self.tenant,
                                       type_name=type_name)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_generate_template(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'generate_template', True)
        req = self._get('/resource_types/TEST_TYPE/template')

        engine_response = {'Type': 'TEST_TYPE'}

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('generate_template', {'type_name': 'TEST_TYPE'})
        ).AndReturn(engine_response)
        self.m.ReplayAll()
        self.controller.generate_template(req, tenant_id=self.tenant,
                                          type_name='TEST_TYPE')
        self.m.VerifyAll()

    def test_generate_template_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'generate_template', True)
        req = self._get('/resource_types/NOT_FOUND/template')

        error = heat_exc.ResourceTypeNotFound(type_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('generate_template', {'type_name': 'NOT_FOUND'})
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()
        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.generate_template,
                                       req, tenant_id=self.tenant,
                                       type_name='NOT_FOUND')
        self.assertEqual(404, resp.json['code'])
        self.assertEqual('ResourceTypeNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_generate_template_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'generate_template', False)
        req = self._get('/resource_types/NOT_FOUND/template')

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.generate_template,
                                       req, tenant_id=self.tenant,
                                       type_name='blah')
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))


class StackSerializerTest(common.HeatTestCase):

    def setUp(self):
        super(StackSerializerTest, self).setUp()
        self.serializer = stacks.StackSerializer()

    def test_serialize_create(self):
        result = {'stack':
                  {'id': '1',
                   'links': [{'href': 'location', "rel": "self"}]}}
        response = webob.Response()
        response = self.serializer.create(response, result)
        self.assertEqual(201, response.status_int)
        self.assertEqual('location', response.headers['Location'])
        self.assertEqual('application/json', response.headers['Content-Type'])


@mock.patch.object(policy.Enforcer, 'enforce')
class ResourceControllerTest(ControllerTest, common.HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        super(ResourceControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig(object):
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = resources.ResourceController(options=cfgopts)

    def test_index(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(stack_identity._tenant_path() + '/resources')

        engine_resp = [
            {
                u'resource_identity': dict(res_identity),
                u'stack_name': stack_identity.stack_name,
                u'resource_name': res_name,
                u'resource_status_reason': None,
                u'updated_time': u'2012-07-23T13:06:00Z',
                u'stack_identity': stack_identity,
                u'resource_action': u'CREATE',
                u'resource_status': u'COMPLETE',
                u'physical_resource_id':
                u'a3455d8c-9f88-404d-a85b-5315293e67de',
                u'resource_type': u'AWS::EC2::Instance',
            }
        ]
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('list_stack_resources', {'stack_identity': stack_identity,
                                      'nested_depth': 0})
        ).AndReturn(engine_resp)
        self.m.ReplayAll()

        result = self.controller.index(req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        expected = {
            'resources': [{'links': [{'href': self._url(res_identity),
                                      'rel': 'self'},
                                     {'href': self._url(stack_identity),
                                      'rel': 'stack'}],
                           u'resource_name': res_name,
                           u'logical_resource_id': res_name,
                           u'resource_status_reason': None,
                           u'updated_time': u'2012-07-23T13:06:00Z',
                           u'resource_status': u'CREATE_COMPLETE',
                           u'physical_resource_id':
                           u'a3455d8c-9f88-404d-a85b-5315293e67de',
                           u'resource_type': u'AWS::EC2::Instance'}]}

        self.assertEqual(expected, result)
        self.m.VerifyAll()

    def test_index_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')

        req = self._get(stack_identity._tenant_path() + '/resources')

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('list_stack_resources', {'stack_identity': stack_identity,
                                      'nested_depth': 0})
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_index_nested_depth(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')

        req = self._get(stack_identity._tenant_path() + '/resources',
                        {'nested_depth': '99'})

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('list_stack_resources', {'stack_identity': stack_identity,
                                      'nested_depth': 99})
        ).AndReturn([])
        self.m.ReplayAll()

        result = self.controller.index(req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        self.assertEqual([], result['resources'])
        self.m.VerifyAll()

    def test_index_nested_depth_not_int(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')

        req = self._get(stack_identity._tenant_path() + '/resources',
                        {'nested_depth': 'non-int'})

        mock_call = self.patchobject(rpc_client.EngineClient, 'call')
        ex = self.assertRaises(ValueError,
                               self.controller.index, req,
                               tenant_id=self.tenant,
                               stack_name=stack_identity.stack_name,
                               stack_id=stack_identity.stack_id)

        self.assertEqual("Only integer is acceptable by 'nested_depth'.",
                         six.text_type(ex))
        self.assertFalse(mock_call.called)

    def test_index_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', False)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        identifier.ResourceIdentifier(resource_name=res_name,
                                      **stack_identity)

        req = self._get(stack_identity._tenant_path() + '/resources')

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(stack_identity._tenant_path())

        engine_resp = {
            u'description': u'',
            u'resource_identity': dict(res_identity),
            u'stack_name': stack_identity.stack_name,
            u'resource_name': res_name,
            u'resource_status_reason': None,
            u'updated_time': u'2012-07-23T13:06:00Z',
            u'stack_identity': dict(stack_identity),
            u'resource_action': u'CREATE',
            u'resource_status': u'COMPLETE',
            u'physical_resource_id':
            u'a3455d8c-9f88-404d-a85b-5315293e67de',
            u'resource_type': u'AWS::EC2::Instance',
            u'metadata': {u'ensureRunning': u'true'}
        }
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        ).AndReturn(engine_resp)
        self.m.ReplayAll()

        result = self.controller.show(req, tenant_id=self.tenant,
                                      stack_name=stack_identity.stack_name,
                                      stack_id=stack_identity.stack_id,
                                      resource_name=res_name)

        expected = {
            'resource': {
                'links': [
                    {'href': self._url(res_identity), 'rel': 'self'},
                    {'href': self._url(stack_identity), 'rel': 'stack'},
                ],
                u'description': u'',
                u'resource_name': res_name,
                u'logical_resource_id': res_name,
                u'resource_status_reason': None,
                u'updated_time': u'2012-07-23T13:06:00Z',
                u'resource_status': u'CREATE_COMPLETE',
                u'physical_resource_id':
                u'a3455d8c-9f88-404d-a85b-5315293e67de',
                u'resource_type': u'AWS::EC2::Instance',
            }
        }

        self.assertEqual(expected, result)
        self.m.VerifyAll()

    def test_show_with_nested_stack(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        nested_stack_identity = identifier.HeatIdentifier(self.tenant,
                                                          'nested', 'some_id')

        req = self._get(stack_identity._tenant_path())

        engine_resp = {
            u'description': u'',
            u'resource_identity': dict(res_identity),
            u'stack_name': stack_identity.stack_name,
            u'resource_name': res_name,
            u'resource_status_reason': None,
            u'updated_time': u'2012-07-23T13:06:00Z',
            u'stack_identity': dict(stack_identity),
            u'resource_action': u'CREATE',
            u'resource_status': u'COMPLETE',
            u'physical_resource_id':
            u'a3455d8c-9f88-404d-a85b-5315293e67de',
            u'resource_type': u'AWS::EC2::Instance',
            u'metadata': {u'ensureRunning': u'true'},
            u'nested_stack_id': dict(nested_stack_identity)
        }
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        ).AndReturn(engine_resp)
        self.m.ReplayAll()

        result = self.controller.show(req, tenant_id=self.tenant,
                                      stack_name=stack_identity.stack_name,
                                      stack_id=stack_identity.stack_id,
                                      resource_name=res_name)

        expected = [{'href': self._url(res_identity), 'rel': 'self'},
                    {'href': self._url(stack_identity), 'rel': 'stack'},
                    {'href': self._url(nested_stack_identity), 'rel': 'nested'}
                    ]

        self.assertEqual(expected, result['resource']['links'])
        self.assertIsNone(result.get(rpc_api.RES_NESTED_STACK_ID))
        self.m.VerifyAll()

    def test_show_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_show_with_single_attribute(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant, 'foo', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        mock_describe = mock.Mock(return_value={'foo': 'bar'})
        self.controller.rpc_client.describe_stack_resource = mock_describe

        req = self._get(res_identity._tenant_path(), {'with_attr': 'baz'})
        resp = self.controller.show(req, tenant_id=self.tenant,
                                    stack_name=stack_identity.stack_name,
                                    stack_id=stack_identity.stack_id,
                                    resource_name=res_name)

        self.assertEqual({'resource': {'foo': 'bar'}}, resp)
        args, kwargs = mock_describe.call_args
        self.assertIn('baz', kwargs['with_attr'])

    def test_show_with_multiple_attributes(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant, 'foo', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        mock_describe = mock.Mock(return_value={'foo': 'bar'})
        self.controller.rpc_client.describe_stack_resource = mock_describe

        req = self._get(res_identity._tenant_path())
        req.environ['QUERY_STRING'] = 'with_attr=a1&with_attr=a2&with_attr=a3'
        resp = self.controller.show(req, tenant_id=self.tenant,
                                    stack_name=stack_identity.stack_name,
                                    stack_id=stack_identity.stack_id,
                                    resource_name=res_name)

        self.assertEqual({'resource': {'foo': 'bar'}}, resp)
        args, kwargs = mock_describe.call_args
        self.assertIn('a1', kwargs['with_attr'])
        self.assertIn('a2', kwargs['with_attr'])
        self.assertIn('a3', kwargs['with_attr'])

    def test_show_nonexist_resource(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'Wibble'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        error = heat_exc.ResourceNotFound(stack_name='a', resource_name='b')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('ResourceNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_show_uncreated_resource(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        error = heat_exc.ResourceNotAvailable(resource_name='')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('ResourceNotAvailable', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_show_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', False)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_metadata_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'metadata', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(stack_identity._tenant_path())

        engine_resp = {
            u'description': u'',
            u'resource_identity': dict(res_identity),
            u'stack_name': stack_identity.stack_name,
            u'resource_name': res_name,
            u'resource_status_reason': None,
            u'updated_time': u'2012-07-23T13:06:00Z',
            u'stack_identity': dict(stack_identity),
            u'resource_action': u'CREATE',
            u'resource_status': u'COMPLETE',
            u'physical_resource_id':
            u'a3455d8c-9f88-404d-a85b-5315293e67de',
            u'resource_type': u'AWS::EC2::Instance',
            u'metadata': {u'ensureRunning': u'true'}
        }
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        ).AndReturn(engine_resp)
        self.m.ReplayAll()

        result = self.controller.metadata(req, tenant_id=self.tenant,
                                          stack_name=stack_identity.stack_name,
                                          stack_id=stack_identity.stack_id,
                                          resource_name=res_name)

        expected = {'metadata': {u'ensureRunning': u'true'}}

        self.assertEqual(expected, result)
        self.m.VerifyAll()

    def test_metadata_show_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'metadata', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path() + '/metadata')

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.metadata,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_metadata_show_nonexist_resource(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'metadata', True)
        res_name = 'wibble'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path() + '/metadata')

        error = heat_exc.ResourceNotFound(stack_name='a', resource_name='b')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.metadata,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('ResourceNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_metadata_show_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'metadata', False)
        res_name = 'wibble'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path() + '/metadata')

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.metadata,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_signal(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'signal', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')

        req = self._get(stack_identity._tenant_path())

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('resource_signal', {'stack_identity': stack_identity,
                                 'resource_name': res_name,
                                 'details': 'Signal content',
                                 'sync_call': False}),
            version='1.3')
        self.m.ReplayAll()

        result = self.controller.signal(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        resource_name=res_name,
                                        body="Signal content")

        self.assertIsNone(result)
        self.m.VerifyAll()


@mock.patch.object(policy.Enforcer, 'enforce')
class EventControllerTest(ControllerTest, common.HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        super(EventControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig(object):
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = events.EventController(options=cfgopts)

    def test_resource_index_event_id_integer(self, mock_enforce):
        self._test_resource_index('42', mock_enforce)

    def test_resource_index_event_id_uuid(self, mock_enforce):
        self._test_resource_index('a3455d8c-9f88-404d-a85b-5315293e67de',
                                  mock_enforce)

    def _test_resource_index(self, event_id, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        ev_identity = identifier.EventIdentifier(event_id=event_id,
                                                 **res_identity)

        req = self._get(stack_identity._tenant_path() +
                        '/resources/' + res_name + '/events')

        kwargs = {'stack_identity': stack_identity,
                  'limit': None, 'sort_keys': None, 'marker': None,
                  'sort_dir': None, 'filters': None}

        engine_resp = [
            {
                u'stack_name': u'wordpress',
                u'event_time': u'2012-07-23T13:05:39Z',
                u'stack_identity': dict(stack_identity),
                u'resource_name': res_name,
                u'resource_status_reason': u'state changed',
                u'event_identity': dict(ev_identity),
                u'resource_action': u'CREATE',
                u'resource_status': u'IN_PROGRESS',
                u'physical_resource_id': None,
                u'resource_properties': {u'UserData': u'blah'},
                u'resource_type': u'AWS::EC2::Instance',
            },
            {
                u'stack_name': u'wordpress',
                u'event_time': u'2012-07-23T13:05:39Z',
                u'stack_identity': dict(stack_identity),
                u'resource_name': 'SomeOtherResource',
                u'logical_resource_id': 'SomeOtherResource',
                u'resource_status_reason': u'state changed',
                u'event_identity': dict(ev_identity),
                u'resource_action': u'CREATE',
                u'resource_status': u'IN_PROGRESS',
                u'physical_resource_id': None,
                u'resource_properties': {u'UserData': u'blah'},
                u'resource_type': u'AWS::EC2::Instance',
            }
        ]
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context, ('list_events', kwargs)
        ).AndReturn(engine_resp)
        self.m.ReplayAll()

        result = self.controller.index(req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        expected = {
            'events': [
                {
                    'id': event_id,
                    'links': [
                        {'href': self._url(ev_identity), 'rel': 'self'},
                        {'href': self._url(res_identity), 'rel': 'resource'},
                        {'href': self._url(stack_identity), 'rel': 'stack'},
                    ],
                    u'resource_name': res_name,
                    u'logical_resource_id': res_name,
                    u'resource_status_reason': u'state changed',
                    u'event_time': u'2012-07-23T13:05:39Z',
                    u'resource_status': u'CREATE_IN_PROGRESS',
                    u'physical_resource_id': None,
                }
            ]
        }

        self.assertEqual(expected, result)
        self.m.VerifyAll()

    def test_stack_index_event_id_integer(self, mock_enforce):
        self._test_stack_index('42', mock_enforce)

    def test_stack_index_event_id_uuid(self, mock_enforce):
        self._test_stack_index('a3455d8c-9f88-404d-a85b-5315293e67de',
                               mock_enforce)

    def _test_stack_index(self, event_id, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        ev_identity = identifier.EventIdentifier(event_id=event_id,
                                                 **res_identity)

        req = self._get(stack_identity._tenant_path() + '/events')

        kwargs = {'stack_identity': stack_identity,
                  'limit': None, 'sort_keys': None, 'marker': None,
                  'sort_dir': None, 'filters': None}

        engine_resp = [
            {
                u'stack_name': u'wordpress',
                u'event_time': u'2012-07-23T13:05:39Z',
                u'stack_identity': dict(stack_identity),
                u'resource_name': res_name,
                u'resource_status_reason': u'state changed',
                u'event_identity': dict(ev_identity),
                u'resource_action': u'CREATE',
                u'resource_status': u'IN_PROGRESS',
                u'physical_resource_id': None,
                u'resource_properties': {u'UserData': u'blah'},
                u'resource_type': u'AWS::EC2::Instance',
            }
        ]
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('list_events', kwargs)
        ).AndReturn(engine_resp)
        self.m.ReplayAll()

        result = self.controller.index(req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        expected = {
            'events': [
                {
                    'id': event_id,
                    'links': [
                        {'href': self._url(ev_identity), 'rel': 'self'},
                        {'href': self._url(res_identity), 'rel': 'resource'},
                        {'href': self._url(stack_identity), 'rel': 'stack'},
                    ],
                    u'resource_name': res_name,
                    u'logical_resource_id': res_name,
                    u'resource_status_reason': u'state changed',
                    u'event_time': u'2012-07-23T13:05:39Z',
                    u'resource_status': u'CREATE_IN_PROGRESS',
                    u'physical_resource_id': None,
                }
            ]
        }

        self.assertEqual(expected, result)
        self.m.VerifyAll()

    def test_index_stack_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wibble', '6')

        req = self._get(stack_identity._tenant_path() + '/events')

        kwargs = {'stack_identity': stack_identity,
                  'limit': None, 'sort_keys': None, 'marker': None,
                  'sort_dir': None, 'filters': None}

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('list_events', kwargs)
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_index_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', False)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wibble', '6')

        req = self._get(stack_identity._tenant_path() + '/events')

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_index_resource_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        event_id = '42'
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        ev_identity = identifier.EventIdentifier(event_id=event_id,
                                                 **res_identity)

        req = self._get(stack_identity._tenant_path() +
                        '/resources/' + res_name + '/events')

        kwargs = {'stack_identity': stack_identity,
                  'limit': None, 'sort_keys': None, 'marker': None,
                  'sort_dir': None, 'filters': None}

        engine_resp = [
            {
                u'stack_name': u'wordpress',
                u'event_time': u'2012-07-23T13:05:39Z',
                u'stack_identity': dict(stack_identity),
                u'resource_name': 'SomeOtherResource',
                u'resource_status_reason': u'state changed',
                u'event_identity': dict(ev_identity),
                u'resource_action': u'CREATE',
                u'resource_status': u'IN_PROGRESS',
                u'physical_resource_id': None,
                u'resource_properties': {u'UserData': u'blah'},
                u'resource_type': u'AWS::EC2::Instance',
            }
        ]
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('list_events', kwargs)
        ).AndReturn(engine_resp)
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.index,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          resource_name=res_name)
        self.m.VerifyAll()

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_whitelists_pagination_params(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {
            'limit': 10,
            'sort_keys': 'fake sort keys',
            'marker': 'fake marker',
            'sort_dir': 'fake sort dir',
            'balrog': 'you shall not pass!'
        }
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wibble', '6')

        req = self._get(stack_identity._tenant_path() + '/events',
                        params=params)

        mock_call.return_value = []

        self.controller.index(req, tenant_id=self.tenant,
                              stack_name=stack_identity.stack_name,
                              stack_id=stack_identity.stack_id)

        rpc_call_args, _ = mock_call.call_args
        engine_args = rpc_call_args[1][1]
        self.assertEqual(6, len(engine_args))
        self.assertIn('limit', engine_args)
        self.assertEqual(10, engine_args['limit'])
        self.assertIn('sort_keys', engine_args)
        self.assertEqual(['fake sort keys'], engine_args['sort_keys'])
        self.assertIn('marker', engine_args)
        self.assertEqual('fake marker', engine_args['marker'])
        self.assertIn('sort_dir', engine_args)
        self.assertEqual('fake sort dir', engine_args['sort_dir'])
        self.assertIn('filters', engine_args)
        self.assertIsNone(engine_args['filters'])
        self.assertNotIn('balrog', engine_args)

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_limit_not_int(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        sid = identifier.HeatIdentifier(self.tenant, 'wibble', '6')

        req = self._get(sid._tenant_path() + '/events',
                        params={'limit': 'not-an-int'})

        ex = self.assertRaises(ValueError,
                               self.controller.index, req,
                               tenant_id=self.tenant,
                               stack_name=sid.stack_name,
                               stack_id=sid.stack_id)
        self.assertEqual("Only integer is acceptable by 'limit'.",
                         six.text_type(ex))
        self.assertFalse(mock_call.called)

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_whitelist_filter_params(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {
            'resource_status': 'COMPLETE',
            'resource_action': 'CREATE',
            'resource_name': 'my_server',
            'resource_type': 'OS::Nova::Server',
            'balrog': 'you shall not pass!'
        }
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wibble', '6')

        req = self._get(stack_identity._tenant_path() + '/events',
                        params=params)

        mock_call.return_value = []

        self.controller.index(req, tenant_id=self.tenant,
                              stack_name=stack_identity.stack_name,
                              stack_id=stack_identity.stack_id)

        rpc_call_args, _ = mock_call.call_args
        engine_args = rpc_call_args[1][1]
        self.assertIn('filters', engine_args)

        filters = engine_args['filters']
        self.assertEqual(4, len(filters))
        self.assertIn('resource_status', filters)
        self.assertEqual('COMPLETE', filters['resource_status'])
        self.assertIn('resource_action', filters)
        self.assertEqual('CREATE', filters['resource_action'])
        self.assertIn('resource_name', filters)
        self.assertEqual('my_server', filters['resource_name'])
        self.assertIn('resource_type', filters)
        self.assertEqual('OS::Nova::Server', filters['resource_type'])
        self.assertNotIn('balrog', filters)

    def test_show_event_id_integer(self, mock_enforce):
        self._test_show('42', mock_enforce)

    def test_show_event_id_uuid(self, mock_enforce):
        self._test_show('a3455d8c-9f88-404d-a85b-5315293e67de', mock_enforce)

    def _test_show(self, event_id, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        ev1_identity = identifier.EventIdentifier(event_id='41',
                                                  **res_identity)
        ev_identity = identifier.EventIdentifier(event_id=event_id,
                                                 **res_identity)

        req = self._get(stack_identity._tenant_path() +
                        '/resources/' + res_name + '/events/' + event_id)

        kwargs = {'stack_identity': stack_identity,
                  'limit': None, 'sort_keys': None, 'marker': None,
                  'sort_dir': None, 'filters': None}

        engine_resp = [
            {
                u'stack_name': u'wordpress',
                u'event_time': u'2012-07-23T13:05:39Z',
                u'stack_identity': dict(stack_identity),
                u'resource_name': res_name,
                u'resource_status_reason': u'state changed',
                u'event_identity': dict(ev1_identity),
                u'resource_action': u'CREATE',
                u'resource_status': u'IN_PROGRESS',
                u'physical_resource_id': None,
                u'resource_properties': {u'UserData': u'blah'},
                u'resource_type': u'AWS::EC2::Instance',
            },
            {
                u'stack_name': u'wordpress',
                u'event_time': u'2012-07-23T13:06:00Z',
                u'stack_identity': dict(stack_identity),
                u'resource_name': res_name,
                u'resource_status_reason': u'state changed',
                u'event_identity': dict(ev_identity),
                u'resource_action': u'CREATE',
                u'resource_status': u'COMPLETE',
                u'physical_resource_id':
                u'a3455d8c-9f88-404d-a85b-5315293e67de',
                u'resource_properties': {u'UserData': u'blah'},
                u'resource_type': u'AWS::EC2::Instance',
            }
        ]
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('list_events', kwargs)
        ).AndReturn(engine_resp)
        self.m.ReplayAll()

        result = self.controller.show(req, tenant_id=self.tenant,
                                      stack_name=stack_identity.stack_name,
                                      stack_id=stack_identity.stack_id,
                                      resource_name=res_name,
                                      event_id=event_id)

        expected = {
            'event': {
                'id': event_id,
                'links': [
                    {'href': self._url(ev_identity), 'rel': 'self'},
                    {'href': self._url(res_identity), 'rel': 'resource'},
                    {'href': self._url(stack_identity), 'rel': 'stack'},
                ],
                u'resource_name': res_name,
                u'logical_resource_id': res_name,
                u'resource_status_reason': u'state changed',
                u'event_time': u'2012-07-23T13:06:00Z',
                u'resource_status': u'CREATE_COMPLETE',
                u'physical_resource_id':
                u'a3455d8c-9f88-404d-a85b-5315293e67de',
                u'resource_type': u'AWS::EC2::Instance',
                u'resource_properties': {u'UserData': u'blah'},
            }
        }

        self.assertEqual(expected, result)
        self.m.VerifyAll()

    def test_show_nonexist_event_id_integer(self, mock_enforce):
        self._test_show_nonexist('42', '41', mock_enforce)

    def test_show_nonexist_event_id_uuid(self, mock_enforce):
        self._test_show_nonexist('a3455d8c-9f88-404d-a85b-5315293e67de',
                                 'x3455x8x-9x88-404x-x85x-5315293x67xx',
                                 mock_enforce)

    def _test_show_nonexist(self, event_id, search_event_id, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        ev_identity = identifier.EventIdentifier(event_id=search_event_id,
                                                 **res_identity)

        req = self._get(stack_identity._tenant_path() +
                        '/resources/' + res_name + '/events/' + event_id)

        kwargs = {'stack_identity': stack_identity,
                  'limit': None, 'sort_keys': None, 'marker': None,
                  'sort_dir': None, 'filters': None}

        engine_resp = [
            {
                u'stack_name': u'wordpress',
                u'event_time': u'2012-07-23T13:05:39Z',
                u'stack_identity': dict(stack_identity),
                u'resource_name': res_name,
                u'resource_status_reason': u'state changed',
                u'event_identity': dict(ev_identity),
                u'resource_action': u'CREATE',
                u'resource_status': u'IN_PROGRESS',
                u'physical_resource_id': None,
                u'resource_properties': {u'UserData': u'blah'},
                u'resource_type': u'AWS::EC2::Instance',
            }
        ]
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context, ('list_events', kwargs)).AndReturn(engine_resp)
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          resource_name=res_name, event_id=event_id)
        self.m.VerifyAll()

    def test_show_bad_resource(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        event_id = '42'
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        ev_identity = identifier.EventIdentifier(event_id='41',
                                                 **res_identity)

        req = self._get(stack_identity._tenant_path() +
                        '/resources/' + res_name + '/events/' + event_id)

        kwargs = {'stack_identity': stack_identity,
                  'limit': None, 'sort_keys': None, 'marker': None,
                  'sort_dir': None, 'filters': None}

        engine_resp = [
            {
                u'stack_name': u'wordpress',
                u'event_time': u'2012-07-23T13:05:39Z',
                u'stack_identity': dict(stack_identity),
                u'resource_name': 'SomeOtherResourceName',
                u'resource_status_reason': u'state changed',
                u'event_identity': dict(ev_identity),
                u'resource_action': u'CREATE',
                u'resource_status': u'IN_PROGRESS',
                u'physical_resource_id': None,
                u'resource_properties': {u'UserData': u'blah'},
                u'resource_type': u'AWS::EC2::Instance',
            }
        ]
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context, ('list_events', kwargs)).AndReturn(engine_resp)
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          resource_name=res_name, event_id=event_id)
        self.m.VerifyAll()

    def test_show_stack_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        event_id = '42'
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wibble', '6')

        req = self._get(stack_identity._tenant_path() +
                        '/resources/' + res_name + '/events/' + event_id)

        kwargs = {'stack_identity': stack_identity,
                  'limit': None, 'sort_keys': None, 'marker': None,
                  'sort_dir': None, 'filters': None}

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context, ('list_events', kwargs)
        ).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name,
                                       event_id=event_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('StackNotFound', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_show_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', False)
        event_id = '42'
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wibble', '6')

        req = self._get(stack_identity._tenant_path() +
                        '/resources/' + res_name + '/events/' + event_id)

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name,
                                       event_id=event_id)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))


class RoutesTest(common.HeatTestCase):

    def assertRoute(self, mapper, path, method, action, controller,
                    params=None):
        params = params or {}
        route = mapper.match(path, {'REQUEST_METHOD': method})
        self.assertIsNotNone(route)
        self.assertEqual(action, route['action'])
        self.assertEqual(
            controller, route['controller'].controller.__class__.__name__)
        del(route['action'])
        del(route['controller'])
        self.assertEqual(params, route)

    def setUp(self):
        super(RoutesTest, self).setUp()
        self.m = api_v1.API({}).map

    def test_template_handling(self):
        self.assertRoute(
            self.m,
            '/aaaa/resource_types',
            'GET',
            'list_resource_types',
            'StackController',
            {
                'tenant_id': 'aaaa',
            })

        self.assertRoute(
            self.m,
            '/aaaa/resource_types/test_type',
            'GET',
            'resource_schema',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'type_name': 'test_type'
            })

        self.assertRoute(
            self.m,
            '/aaaa/resource_types/test_type/template',
            'GET',
            'generate_template',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'type_name': 'test_type'
            })

        self.assertRoute(
            self.m,
            '/aaaa/validate',
            'POST',
            'validate_template',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })

    def test_stack_collection(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks',
            'GET',
            'index',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks',
            'POST',
            'create',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/preview',
            'POST',
            'preview',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/detail',
            'GET',
            'detail',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })

    def test_stack_data(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/arn:openstack:heat::6548ab64fbda49deb188851a3b7d8c8b'
            ':stacks/stack-1411-06/1c5d9bb2-3464-45e2-a728-26dfa4e1d34a',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'arn:openstack:heat:'
                ':6548ab64fbda49deb188851a3b7d8c8b:stacks/stack-1411-06/'
                '1c5d9bb2-3464-45e2-a728-26dfa4e1d34a'
            })

        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/resources',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'path': 'resources'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/events',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'path': 'events'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb',
            'GET',
            'show',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })

    def test_stack_snapshot(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots',
            'POST',
            'snapshot',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots/cccc',
            'GET',
            'show_snapshot',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'snapshot_id': 'cccc'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots/cccc',
            'DELETE',
            'delete_snapshot',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'snapshot_id': 'cccc'
            })

        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots',
            'GET',
            'list_snapshots',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb'
            })

        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots/cccc/restore',
            'POST',
            'restore_snapshot',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'snapshot_id': 'cccc'
            })

    def test_stack_data_template(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/template',
            'GET',
            'template',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/template',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'path': 'template'
            })

    def test_stack_post_actions(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/actions',
            'POST',
            'action',
            'ActionController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })

    def test_stack_post_actions_lookup_redirect(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/actions',
            'POST',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'path': 'actions'
            })

    def test_stack_update_delete(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb',
            'PUT',
            'update',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb',
            'DELETE',
            'delete',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })

    def test_resources(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources',
            'GET',
            'index',
            'ResourceController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc',
            'GET',
            'show',
            'ResourceController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc/metadata',
            'GET',
            'metadata',
            'ResourceController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc/signal',
            'POST',
            'signal',
            'ResourceController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc'
            })

    def test_events(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/events',
            'GET',
            'index',
            'EventController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc/events',
            'GET',
            'index',
            'EventController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc/events/dddd',
            'GET',
            'show',
            'EventController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc',
                'event_id': 'dddd'
            })

    def test_software_configs(self):
        self.assertRoute(
            self.m,
            '/aaaa/software_configs',
            'POST',
            'create',
            'SoftwareConfigController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_configs/bbbb',
            'GET',
            'show',
            'SoftwareConfigController',
            {
                'tenant_id': 'aaaa',
                'config_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_configs/bbbb',
            'DELETE',
            'delete',
            'SoftwareConfigController',
            {
                'tenant_id': 'aaaa',
                'config_id': 'bbbb'
            })

    def test_software_deployments(self):
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments',
            'GET',
            'index',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments',
            'POST',
            'create',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments/bbbb',
            'GET',
            'show',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa',
                'deployment_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments/bbbb',
            'PUT',
            'update',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa',
                'deployment_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments/bbbb',
            'DELETE',
            'delete',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa',
                'deployment_id': 'bbbb'
            })

    def test_build_info(self):
        self.assertRoute(
            self.m,
            '/fake_tenant/build_info',
            'GET',
            'build_info',
            'BuildInfoController',
            {'tenant_id': 'fake_tenant'}
        )

    def test_405(self):
        self.assertRoute(
            self.m,
            '/fake_tenant/validate',
            'GET',
            'reject',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'allowed_methods': 'POST'}
        )
        self.assertRoute(
            self.m,
            '/fake_tenant/stacks',
            'PUT',
            'reject',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'allowed_methods': 'GET,POST'}
        )
        self.assertRoute(
            self.m,
            '/fake_tenant/stacks/fake_stack/stack_id',
            'POST',
            'reject',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'stack_name': 'fake_stack',
             'stack_id': 'stack_id', 'allowed_methods': 'GET,PUT,PATCH,DELETE'}
        )

    def test_options(self):
        self.assertRoute(
            self.m,
            '/fake_tenant/validate',
            'OPTIONS',
            'options',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'allowed_methods': 'POST'}
        )
        self.assertRoute(
            self.m,
            '/fake_tenant/stacks/fake_stack/stack_id',
            'OPTIONS',
            'options',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'stack_name': 'fake_stack',
             'stack_id': 'stack_id', 'allowed_methods': 'GET,PUT,PATCH,DELETE'}
        )

    def test_services(self):
        self.assertRoute(
            self.m,
            '/aaaa/services',
            'GET',
            'index',
            'ServiceController',
            {
                'tenant_id': 'aaaa'
            })


@mock.patch.object(policy.Enforcer, 'enforce')
class ActionControllerTest(ControllerTest, common.HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        super(ActionControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig(object):
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = actions.ActionController(options=cfgopts)

    def test_action_suspend(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'suspend': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('stack_suspend', {'stack_identity': stack_identity})
        ).AndReturn(None)
        self.m.ReplayAll()

        result = self.controller.action(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        body=body)
        self.assertIsNone(result)
        self.m.VerifyAll()

    def test_action_resume(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'resume': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('stack_resume', {'stack_identity': stack_identity})
        ).AndReturn(None)
        self.m.ReplayAll()

        result = self.controller.action(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        body=body)
        self.assertIsNone(result)
        self.m.VerifyAll()

    def test_action_cancel_update(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'cancel_update': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('stack_cancel_update', {'stack_identity': stack_identity})
        ).AndReturn(None)
        self.m.ReplayAll()

        result = self.controller.action(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        body=body)
        self.assertIsNone(result)
        self.m.VerifyAll()

    def test_action_badaction(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'notallowed': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.action,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_action_badaction_empty(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.action,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_action_badaction_multiple(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'one': None, 'two': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.action,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_action_rmt_aterr(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'suspend': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('stack_suspend', {'stack_identity': stack_identity})
        ).AndRaise(to_remote_error(AttributeError()))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.action,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('AttributeError', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_action_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', False)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'suspend': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.action,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       body=body)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_action_badaction_ise(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'oops': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.ReplayAll()

        self.controller.ACTIONS = (SUSPEND, NEW) = ('suspend', 'oops')

        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.action,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          body=body)
        self.m.VerifyAll()


@mock.patch.object(policy.Enforcer, 'enforce')
class BuildInfoControllerTest(ControllerTest, common.HeatTestCase):

    def setUp(self):
        super(BuildInfoControllerTest, self).setUp()
        self.controller = build_info.BuildInfoController({})

    def test_theres_a_default_api_build_revision(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'build_info', True)
        req = self._get('/build_info')
        self.controller.rpc_client = mock.Mock()

        response = self.controller.build_info(req, tenant_id=self.tenant)
        self.assertIn('api', response)
        self.assertIn('revision', response['api'])
        self.assertEqual('unknown', response['api']['revision'])

    @mock.patch.object(build_info.cfg, 'CONF')
    def test_response_api_build_revision_from_config_file(
            self, mock_conf, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'build_info', True)
        req = self._get('/build_info')
        mock_engine = mock.Mock()
        mock_engine.get_revision.return_value = 'engine_revision'
        self.controller.rpc_client = mock_engine
        mock_conf.revision = {'heat_revision': 'test'}

        response = self.controller.build_info(req, tenant_id=self.tenant)
        self.assertEqual('test', response['api']['revision'])

    def test_retrieves_build_revision_from_the_engine(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'build_info', True)
        req = self._get('/build_info')
        mock_engine = mock.Mock()
        mock_engine.get_revision.return_value = 'engine_revision'
        self.controller.rpc_client = mock_engine

        response = self.controller.build_info(req, tenant_id=self.tenant)
        self.assertIn('engine', response)
        self.assertIn('revision', response['engine'])
        self.assertEqual('engine_revision', response['engine']['revision'])

    def test_build_info_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'build_info', False)
        req = self._get('/build_info')

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.build_info,
                                       req, tenant_id=self.tenant)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))


class SoftwareConfigControllerTest(ControllerTest, common.HeatTestCase):

    def setUp(self):
        super(SoftwareConfigControllerTest, self).setUp()
        self.controller = software_configs.SoftwareConfigController({})

    def test_default(self):
        self.assertRaises(
            webob.exc.HTTPNotFound, self.controller.default, None)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._get('/software_configs/%s' % config_id)
        return_value = {
            'id': config_id,
            'name': 'config_mysql',
            'group': 'Heat::Shell',
            'config': '#!/bin/bash',
            'inputs': [],
            'ouputs': [],
            'options': []}

        expected = {'software_config': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'show_software_config',
                return_value=return_value):
            resp = self.controller.show(
                req, config_id=config_id, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_show_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._get('/software_configs/%s' % config_id)

        error = heat_exc.NotFound('Not found %s' % config_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'show_software_config',
                side_effect=to_remote_error(error)):
            resp = request_with_middleware(fault.FaultWrapper,
                                           self.controller.show,
                                           req, config_id=config_id,
                                           tenant_id=self.tenant)
            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_create(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create')
        body = {
            'name': 'config_mysql',
            'group': 'Heat::Shell',
            'config': '#!/bin/bash',
            'inputs': [],
            'ouputs': [],
            'options': []}
        return_value = body.copy()
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        return_value['id'] = config_id
        req = self._post('/software_configs', json.dumps(body))

        expected = {'software_config': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'create_software_config',
                return_value=return_value):
            resp = self.controller.create(
                req, body=body, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_configs/%s' % config_id)
        return_value = None
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_config',
                return_value=return_value):
            self.assertRaises(
                webob.exc.HTTPNoContent, self.controller.delete,
                req, config_id=config_id, tenant_id=self.tenant)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete_error(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_configs/%s' % config_id)
        error = Exception('something wrong')
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_config',
                side_effect=to_remote_error(error)):
            resp = request_with_middleware(
                fault.FaultWrapper, self.controller.delete,
                req, config_id=config_id, tenant_id=self.tenant)

            self.assertEqual(500, resp.json['code'])
            self.assertEqual('Exception', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_configs/%s' % config_id)
        error = heat_exc.NotFound('Not found %s' % config_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_config',
                side_effect=to_remote_error(error)):
            resp = request_with_middleware(
                fault.FaultWrapper, self.controller.delete,
                req, config_id=config_id, tenant_id=self.tenant)

            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])


class SoftwareDeploymentControllerTest(ControllerTest, common.HeatTestCase):

    def setUp(self):
        super(SoftwareDeploymentControllerTest, self).setUp()
        self.controller = software_deployments.SoftwareDeploymentController({})

    def test_default(self):
        self.assertRaises(
            webob.exc.HTTPNotFound, self.controller.default, None)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_index(self, mock_enforce):
        self._mock_enforce_setup(
            mock_enforce, 'index', expected_request_count=2)
        req = self._get('/software_deployments')
        return_value = []
        with mock.patch.object(
                self.controller.rpc_client,
                'list_software_deployments',
                return_value=return_value) as mock_call:
            resp = self.controller.index(req, tenant_id=self.tenant)
            self.assertEqual(
                {'software_deployments': []}, resp)
            whitelist = mock_call.call_args[1]
            self.assertEqual({}, whitelist)
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        req = self._get('/software_deployments', {'server_id': server_id})
        with mock.patch.object(
                self.controller.rpc_client,
                'list_software_deployments',
                return_value=return_value) as mock_call:
            resp = self.controller.index(req, tenant_id=self.tenant)
            self.assertEqual(
                {'software_deployments': []}, resp)
            whitelist = mock_call.call_args[1]
            self.assertEqual({'server_id': server_id}, whitelist)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show')
        deployment_id = '38eccf10-97e5-4ae8-9d37-b577c9801750'
        config_id = 'd00ba4aa-db33-42e1-92f4-2a6469260107'
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        req = self._get('/software_deployments/%s' % deployment_id)
        return_value = {
            'id': deployment_id,
            'server_id': server_id,
            'input_values': {},
            'output_values': {},
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': None,
            'config_id': config_id,
            'config': '#!/bin/bash',
            'name': 'config_mysql',
            'group': 'Heat::Shell',
            'inputs': [],
            'outputs': [],
            'options': []}

        expected = {'software_deployment': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'show_software_deployment',
                return_value=return_value):
            resp = self.controller.show(
                req, deployment_id=config_id, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_show_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show')
        deployment_id = '38eccf10-97e5-4ae8-9d37-b577c9801750'
        req = self._get('/software_deployments/%s' % deployment_id)

        error = heat_exc.NotFound('Not found %s' % deployment_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'show_software_deployment',
                side_effect=to_remote_error(error)):
            resp = request_with_middleware(
                fault.FaultWrapper, self.controller.show,
                req, deployment_id=deployment_id, tenant_id=self.tenant)

            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_create(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create')
        config_id = 'd00ba4aa-db33-42e1-92f4-2a6469260107'
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        body = {
            'server_id': server_id,
            'input_values': {},
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': None,
            'config_id': config_id}
        return_value = body.copy()
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        return_value['id'] = deployment_id
        req = self._post('/software_deployments', json.dumps(body))

        expected = {'software_deployment': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'create_software_deployment',
                return_value=return_value):
            resp = self.controller.create(
                req, body=body, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_update(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update')
        config_id = 'd00ba4aa-db33-42e1-92f4-2a6469260107'
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        body = {
            'input_values': {},
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': None,
            'config_id': config_id}
        return_value = body.copy()
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        return_value['id'] = deployment_id
        req = self._put('/software_deployments/%s' % deployment_id,
                        json.dumps(body))
        return_value['server_id'] = server_id
        expected = {'software_deployment': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'update_software_deployment',
                return_value=return_value):
            resp = self.controller.update(
                req, deployment_id=deployment_id,
                body=body, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_update_no_input_values(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update')
        config_id = 'd00ba4aa-db33-42e1-92f4-2a6469260107'
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        body = {
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': None,
            'config_id': config_id}
        return_value = body.copy()
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        return_value['id'] = deployment_id
        req = self._put('/software_deployments/%s' % deployment_id,
                        json.dumps(body))
        return_value['server_id'] = server_id
        expected = {'software_deployment': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'update_software_deployment',
                return_value=return_value):
            resp = self.controller.update(
                req, deployment_id=deployment_id,
                body=body, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_update_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update')
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._put('/software_deployments/%s' % deployment_id,
                        '{}')
        error = heat_exc.NotFound('Not found %s' % deployment_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'update_software_deployment',
                side_effect=to_remote_error(error)):
            resp = request_with_middleware(
                fault.FaultWrapper, self.controller.update,
                req, deployment_id=deployment_id,
                body={}, tenant_id=self.tenant)
            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_deployments/%s' % deployment_id)
        return_value = None
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_deployment',
                return_value=return_value):
            self.assertRaises(
                webob.exc.HTTPNoContent, self.controller.delete,
                req, deployment_id=deployment_id, tenant_id=self.tenant)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete_error(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_deployments/%s' % deployment_id)
        error = Exception('something wrong')
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_deployment',
                side_effect=to_remote_error(error)):
            resp = request_with_middleware(
                fault.FaultWrapper, self.controller.delete,
                req, deployment_id=deployment_id, tenant_id=self.tenant)
            self.assertEqual(500, resp.json['code'])
            self.assertEqual('Exception', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_deployments/%s' % deployment_id)
        error = heat_exc.NotFound('Not Found %s' % deployment_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_deployment',
                side_effect=to_remote_error(error)):
            resp = request_with_middleware(
                fault.FaultWrapper, self.controller.delete,
                req, deployment_id=deployment_id, tenant_id=self.tenant)
            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])


class ServiceControllerTest(ControllerTest, common.HeatTestCase):

    def setUp(self):
        super(ServiceControllerTest, self).setUp()
        self.controller = services.ServiceController({})

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_index(self, mock_enforce):
        self._mock_enforce_setup(
            mock_enforce, 'index')
        req = self._get('/services')
        return_value = []
        with mock.patch.object(
                self.controller.rpc_client,
                'list_services',
                return_value=return_value):
            resp = self.controller.index(req, tenant_id=self.tenant)
            self.assertEqual(
                {'services': []}, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_index_503(self, mock_enforce):
        self._mock_enforce_setup(
            mock_enforce, 'index')
        req = self._get('/services')
        with mock.patch.object(
                self.controller.rpc_client,
                'list_services',
                side_effect=exceptions.MessagingTimeout()):
            self.assertRaises(
                webob.exc.HTTPServiceUnavailable,
                self.controller.index, req, tenant_id=self.tenant)
