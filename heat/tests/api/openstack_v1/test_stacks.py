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
import six
import webob.exc

import heat.api.middleware.fault as fault
import heat.api.openstack.v1.stacks as stacks
from heat.api.openstack.v1.views import stacks_view
from heat.common import context
from heat.common import exception as heat_exc
from heat.common import identifier
from heat.common import policy
from heat.common import template_format
from heat.common import urlfetch
from heat.rpc import api as rpc_api
from heat.rpc import client as rpc_client
from heat.tests.api.openstack_v1 import tools
from heat.tests import common


class InstantiationDataTest(common.HeatTestCase):

    def test_parse_error_success(self):
        with stacks.InstantiationData.parse_error_check('Garbage'):
            pass

    def test_parse_error(self):
        def generate_error():
            with stacks.InstantiationData.parse_error_check('Garbage'):
                raise ValueError

        self.assertRaises(webob.exc.HTTPBadRequest, generate_error)

    def test_parse_error_message(self):
        # make sure the parser error gets through to the caller.
        bad_temp = '''
heat_template_version: '2013-05-23'
parameters:
  KeyName:
     type: string
    description: bla
        '''

        def generate_error():
            with stacks.InstantiationData.parse_error_check('foo'):
                template_format.parse(bad_temp)

        parse_ex = self.assertRaises(webob.exc.HTTPBadRequest, generate_error)
        self.assertIn('foo', six.text_type(parse_ex))

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

    def test_template_int(self):
        template = '42'
        body = {'template': template}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.template)

    def test_template_url(self):
        template = {'heat_template_version': '2013-05-23',
                    'foo': 'bar',
                    'blarg': 'wibble'}
        url = 'http://example.com/template'
        body = {'template_url': url}
        data = stacks.InstantiationData(body)

        mock_get = self.patchobject(urlfetch, 'get',
                                    return_value=json.dumps(template))

        self.assertEqual(template, data.template())
        mock_get.assert_called_once_with(url)

    def test_template_priority(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        url = 'http://example.com/template'
        body = {'template': template, 'template_url': url}
        data = stacks.InstantiationData(body)

        mock_get = self.patchobject(urlfetch, 'get')

        self.assertEqual(template, data.template())
        mock_get.assert_not_called()

    def test_template_missing(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'not the template': template}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.template)

    def test_template_exceeds_max_template_size(self):
        cfg.CONF.set_override('max_template_size', 10)
        template = json.dumps(['a'] * cfg.CONF.max_template_size)
        body = {'template': template}
        data = stacks.InstantiationData(body)
        error = self.assertRaises(heat_exc.RequestLimitExceeded,
                                  data.template)

        msg = ('Request limit exceeded: Template size (%(actual_len)s '
               'bytes) exceeds maximum allowed size (%(limit)s bytes).') % {
                   'actual_len': len(str(template)),
                   'limit': cfg.CONF.max_template_size}
        self.assertEqual(msg, six.text_type(error))

    def test_parameters(self):
        params = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'parameters': params,
                'encrypted_param_names': [],
                'parameter_defaults': {},
                'event_sinks': [],
                'resource_registry': {}}
        data = stacks.InstantiationData(body)
        self.assertEqual(body, data.environment())

    def test_environment_only_params(self):
        env = {'parameters': {'foo': 'bar', 'blarg': 'wibble'}}
        body = {'environment': env}
        data = stacks.InstantiationData(body)
        self.assertEqual(env, data.environment())

    def test_environment_with_env_files(self):
        env = {'parameters': {'foo': 'bar', 'blarg': 'wibble'}}
        body = {'environment': env, 'environment_files': ['env.yaml']}
        expect = {'parameters': {},
                  'encrypted_param_names': [],
                  'parameter_defaults': {},
                  'event_sinks': [],
                  'resource_registry': {}}
        data = stacks.InstantiationData(body)
        self.assertEqual(expect, data.environment())

    def test_environment_and_parameters(self):
        body = {'parameters': {'foo': 'bar'},
                'environment': {'parameters': {'blarg': 'wibble'}}}
        expect = {'parameters': {'blarg': 'wibble',
                                 'foo': 'bar'},
                  'encrypted_param_names': [],
                  'parameter_defaults': {},
                  'event_sinks': [],
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
                  'encrypted_param_names': [],
                  'parameter_defaults': {},
                  'event_sinks': [],
                  'resource_registry': {}}
        data = stacks.InstantiationData(body)
        self.assertEqual(expect, data.environment())

    def test_environment_empty_params(self):
        env = {'parameters': None}
        body = {'environment': env}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.environment)

    def test_environment_bad_format(self):
        env = {'somethingnotsupported': {'blarg': 'wibble'}}
        body = {'environment': json.dumps(env)}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.environment)

    def test_environment_missing(self):
        env = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'not the environment': env}
        data = stacks.InstantiationData(body)
        self.assertEqual({'parameters': {}, 'encrypted_param_names': [],
                          'parameter_defaults': {}, 'resource_registry': {},
                          'event_sinks': []},
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


@mock.patch.object(policy.Enforcer, 'enforce')
class StackControllerTest(tools.ControllerTest, common.HeatTestCase):
    """Tests the API class StackController.

    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    """

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
                        'sort_dir': None, 'filters': None,
                        'show_deleted': False, 'show_nested': False,
                        'show_hidden': False, 'tags': None,
                        'tags_any': None, 'not_tags': None,
                        'not_tags_any': None}
        mock_call.assert_called_once_with(
            req.context, ('list_stacks', default_args), version='1.33')

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
        self.assertEqual(12, len(engine_args))
        self.assertIn('limit', engine_args)
        self.assertIn('sort_keys', engine_args)
        self.assertIn('marker', engine_args)
        self.assertIn('sort_dir', engine_args)
        self.assertIn('filters', engine_args)
        self.assertNotIn('balrog', engine_args)

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_limit_not_int(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {'limit': 'not-an-int'}
        req = self._get('/stacks', params=params)

        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.index, req,
                               tenant_id=self.tenant)
        self.assertEqual("Only integer is acceptable by 'limit'.",
                         six.text_type(ex))
        self.assertFalse(mock_call.called)

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_whitelist_filter_params(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {
            'id': 'fake id',
            'status': 'fake status',
            'name': 'fake name',
            'action': 'fake action',
            'username': 'fake username',
            'tenant': 'fake tenant',
            'owner_id': 'fake owner-id',
            'stack_name': 'fake stack name',
            'stack_identity': 'fake identity',
            'creation_time': 'create timestamp',
            'updated_time': 'update timestamp',
            'deletion_time': 'deletion timestamp',
            'notification_topics': 'fake topic',
            'description': 'fake description',
            'template_description': 'fake description',
            'parameters': 'fake params',
            'outputs': 'fake outputs',
            'stack_action': 'fake action',
            'stack_status': 'fake status',
            'stack_status_reason': 'fake status reason',
            'capabilities': 'fake capabilities',
            'disable_rollback': 'fake value',
            'timeout_mins': 'fake timeout',
            'stack_owner': 'fake owner',
            'parent': 'fake parent',
            'stack_user_project_id': 'fake project id',
            'tags': 'fake tags',
            'barlog': 'you shall not pass!'
        }
        req = self._get('/stacks', params=params)
        mock_call.return_value = []

        self.controller.index(req, tenant_id=self.tenant)

        rpc_call_args, _ = mock_call.call_args
        engine_args = rpc_call_args[1][1]
        self.assertIn('filters', engine_args)

        filters = engine_args['filters']
        self.assertEqual(16, len(filters))
        for key in ('id', 'status', 'name', 'action', 'username', 'tenant',
                    'owner_id', 'stack_name', 'stack_action', 'stack_status',
                    'stack_status_reason', 'disable_rollback', 'timeout_mins',
                    'stack_owner', 'parent', 'stack_user_project_id'):
            self.assertIn(key, filters)

        for key in ('stack_identity', 'creation_time', 'updated_time',
                    'deletion_time', 'notification_topics', 'description',
                    'template_description', 'parameters', 'outputs',
                    'capabilities', 'tags', 'barlog'):
            self.assertNotIn(key, filters)

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
        self.assertFalse(engine.count_stacks.called)

    def test_index_with_count_is_invalid(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        params = {'with_count': 'invalid_value'}
        req = self._get('/stacks', params=params)

        exc = self.assertRaises(webob.exc.HTTPBadRequest,
                                self.controller.index,
                                req, tenant_id=self.tenant)
        excepted = ('Unrecognized value "invalid_value" for "with_count", '
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
                                        is_registered_policy=True,
                                        context=self.context)

    def test_global_index_uses_admin_context(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        mock_admin_ctxt = self.patchobject(context, 'get_admin_context')
        params = {'global_tenant': 'True'}
        req = self._get('/stacks', params=params)
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY)
        self.assertEqual(1, mock_admin_ctxt.call_count)

    def test_index_with_admin_context(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()
        view_collection_mock = self.patchobject(stacks_view, 'collection')
        req = self._get('/stacks')
        req.context.is_admin = True
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY)
        view_collection_mock.assert_called_once_with(mock.ANY,
                                                     stacks=mock.ANY,
                                                     count=mock.ANY,
                                                     include_project=True)

    def test_global_index_show_deleted_false(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        params = {'show_deleted': 'False'}
        req = self._get('/stacks', params=params)
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
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
                                                       show_nested=True)

    def test_global_index_show_hidden_true(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        params = {'show_hidden': 'True'}
        req = self._get('/stacks', params=params)
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
                                                       show_hidden=True)

    def test_global_index_show_hidden_false(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        params = {'show_hidden': 'false'}
        req = self._get('/stacks', params=params)
        self.controller.index(req, tenant_id=self.tenant)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
                                                       show_hidden=False)

    def test_index_show_deleted_True_with_count_false(self, mock_enforce):
        rpc_client = self.controller.rpc_client
        rpc_client.list_stacks = mock.Mock(return_value=[])
        rpc_client.count_stacks = mock.Mock()

        params = {'show_deleted': 'True',
                  'with_count': 'false'}
        req = self._get('/stacks', params=params)
        result = self.controller.index(req, tenant_id=self.tenant)
        self.assertNotIn('count', result)
        rpc_client.list_stacks.assert_called_once_with(mock.ANY,
                                                       filters=mock.ANY,
                                                       show_deleted=True)
        self.assertFalse(rpc_client.count_stacks.called)

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
                                                       show_deleted=True)
        rpc_client.count_stacks.assert_called_once_with(mock.ANY,
                                                        filters=mock.ANY,
                                                        show_deleted=True,
                                                        show_nested=False,
                                                        show_hidden=False,
                                                        tags=None,
                                                        tags_any=None,
                                                        not_tags=None,
                                                        not_tags_any=None)

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
                        'sort_dir': None, 'filters': None,
                        'show_deleted': False, 'show_nested': False,
                        'show_hidden': False, 'tags': None,
                        'tags_any': None, 'not_tags': None,
                        'not_tags_any': None}
        mock_call.assert_called_once_with(
            req.context, ('list_stacks', default_args), version='1.33')

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_rmt_aterr(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        req = self._get('/stacks')

        mock_call.side_effect = tools.to_remote_error(AttributeError())

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.index,
                                             req, tenant_id=self.tenant)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('AttributeError', resp.json['error']['type'])
        mock_call.assert_called_once_with(
            req.context, ('list_stacks', mock.ANY), version='1.33')

    def test_index_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', False)

        req = self._get('/stacks')

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.index,
                                             req, tenant_id=self.tenant)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_index_rmt_interr(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        req = self._get('/stacks')

        mock_call.side_effect = tools.to_remote_error(Exception())

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.index,
                                             req, tenant_id=self.tenant)

        self.assertEqual(500, resp.json['code'])
        self.assertEqual('Exception', resp.json['error']['type'])
        mock_call.assert_called_once_with(
            req.context, ('list_stacks', mock.ANY), version='1.33')

    def test_create(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': identity.stack_name,
                'parameters': parameters,
                'environment_files': ['foo.yaml'],
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        response = self.controller.create(req,
                                          tenant_id=identity.tenant,
                                          body=body)

        expected = {'stack':
                    {'id': '1',
                     'links': [{'href': self._url(identity), 'rel': 'self'}]}}
        self.assertEqual(expected, response)

        mock_call.assert_called_once_with(
            req.context,
            ('create_stack',
             {'stack_name': identity.stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': ['foo.yaml'],
              'files_container': None,
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'parent_resource_name': None,
              'stack_user_project_id': None,
              'template_id': None}),
            version='1.36'
        )

    def test_create_with_tags(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': identity.stack_name,
                'parameters': parameters,
                'tags': 'tag1,tag2',
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        response = self.controller.create(req,
                                          tenant_id=identity.tenant,
                                          body=body)

        expected = {'stack':
                    {'id': '1',
                     'links': [{'href': self._url(identity), 'rel': 'self'}]}}
        self.assertEqual(expected, response)

        mock_call.assert_called_once_with(
            req.context,
            ('create_stack',
             {'stack_name': identity.stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30, 'tags': ['tag1', 'tag2']},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'parent_resource_name': None,
              'stack_user_project_id': None,
              'template_id': None}),
            version='1.36'
        )

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

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        response = self.controller.create(req,
                                          tenant_id=identity.tenant,
                                          body=body)

        expected = {'stack':
                    {'id': '1',
                     'links': [{'href': self._url(identity), 'rel': 'self'}]}}
        self.assertEqual(expected, response)

        mock_call.assert_called_once_with(
            req.context,
            ('create_stack',
             {'stack_name': identity.stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30,
                       'adopt_stack_data': str(adopt_data)},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'parent_resource_name': None,
              'stack_user_project_id': None,
              'template_id': None}),
            version='1.36'
        )

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
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.create, req,
                               tenant_id=self.tenant, body=body)

        self.assertEqual("Only integer is acceptable by 'timeout_mins'.",
                         six.text_type(ex))
        mock_call.assert_not_called()

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

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.create,
                                             req, tenant_id=self.tenant,
                                             body=body)
        self.assertEqual(400, resp.status_code)
        self.assertEqual('400 Bad Request', resp.status)
        self.assertIn('Invalid adopt data', resp.text)

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

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        result = self.controller.create(req,
                                        tenant_id=identity.tenant,
                                        body=body)
        expected = {'stack':
                    {'id': '1',
                     'links': [{'href': self._url(identity), 'rel': 'self'}]}}
        self.assertEqual(expected, result)

        mock_call.assert_called_once_with(
            req.context,
            ('create_stack',
             {'stack_name': identity.stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {'my.yaml': 'This is the file contents.'},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'parent_resource_name': None,
              'stack_user_project_id': None,
              'template_id': None}),
            version='1.36'
        )

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
        mock_call = self.patchobject(
            rpc_client.EngineClient, 'call',
            side_effect=[
                tools.to_remote_error(AttributeError()),
                tools.to_remote_error(unknown_parameter),
                tools.to_remote_error(missing_parameter),
            ])

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.create,
                                             req, tenant_id=self.tenant,
                                             body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('AttributeError', resp.json['error']['type'])

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.create,
                                             req, tenant_id=self.tenant,
                                             body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('UnknownUserParameter', resp.json['error']['type'])

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.create,
                                             req, tenant_id=self.tenant,
                                             body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('UserParameterMissing', resp.json['error']['type'])

        mock_call.assert_called_with(
            req.context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'parent_resource_name': None,
              'stack_user_project_id': None,
              'template_id': None}),
            version='1.36'
        )
        self.assertEqual(3, mock_call.call_count)

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
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.create,
                                             req, tenant_id=self.tenant,
                                             body=body)

        self.assertEqual(409, resp.json['code'])
        self.assertEqual('StackExists', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'parent_resource_name': None,
              'stack_user_project_id': None,
              'template_id': None}),
            version='1.36'
        )

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
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.create, req,
                               tenant_id=self.tenant, body=body)

        self.assertEqual("Only integer is acceptable by 'timeout_mins'.",
                         six.text_type(ex))
        mock_call.assert_not_called()

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

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.create,
                                             req, tenant_id=self.tenant,
                                             body=body)

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
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.create,
                                             req, tenant_id=self.tenant,
                                             body=body)
        self.assertEqual(400, resp.json['code'])
        self.assertEqual('StackValidationFailed', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30},
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'parent_resource_name': None,
              'stack_user_project_id': None,
              'template_id': None}),
            version='1.36'
        )

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

        resp = tools.request_with_middleware(fault.FaultWrapper,
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
        body = {'stack_name': 'foo', 'template': {}, 'parameters': {}}
        req = self._post('/stacks/preview', json.dumps(body))
        mock_call.return_value = {}
        mock_format.return_value = 'formatted_stack'

        result = self.controller.preview(req, tenant_id=self.tenant, body=body)

        self.assertEqual({'stack': 'formatted_stack'}, result)

    @mock.patch.object(rpc_client.EngineClient, 'call')
    @mock.patch.object(stacks.stacks_view, 'format_stack')
    def test_preview_with_tags_timeout(self, mock_format, mock_call,
                                       mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'preview', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': identity.stack_name,
                'parameters': parameters,
                'tags': 'tag1,tag2',
                'timeout_mins': 30}

        req = self._post('/stacks/preview', json.dumps(body))
        mock_call.return_value = {}
        mock_format.return_value = 'formatted_stack_preview'
        response = self.controller.preview(req,
                                           tenant_id=identity.tenant,
                                           body=body)
        rpc_client.EngineClient.call.assert_called_once_with(
            req.context,
            ('preview_stack',
             {'stack_name': identity.stack_name,
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30, 'tags': ['tag1', 'tag2']}}),
            version='1.36'
        )

        self.assertEqual({'stack': 'formatted_stack_preview'}, response)

    def test_preview_update_stack(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'preview_update', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s/preview' %
                        identity, json.dumps(body))
        resource_changes = {'updated': [],
                            'deleted': [],
                            'unchanged': [],
                            'added': [],
                            'replaced': []}

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=resource_changes)

        result = self.controller.preview_update(req, tenant_id=identity.tenant,
                                                stack_name=identity.stack_name,
                                                stack_id=identity.stack_id,
                                                body=body)
        self.assertEqual({'resource_changes': resource_changes}, result)

        mock_call.assert_called_once_with(
            req.context,
            ('preview_update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30}}),
            version='1.36'
        )

    def test_preview_update_stack_patch(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'preview_update_patch', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': None,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 30}

        req = self._patch('/stacks/%(stack_name)s/%(stack_id)s/preview' %
                          identity, json.dumps(body))
        resource_changes = {'updated': [],
                            'deleted': [],
                            'unchanged': [],
                            'added': [],
                            'replaced': []}

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=resource_changes)

        result = self.controller.preview_update_patch(
            req, tenant_id=identity.tenant, stack_name=identity.stack_name,
            stack_id=identity.stack_id, body=body)
        self.assertEqual({'resource_changes': resource_changes}, result)

        mock_call.assert_called_once_with(
            req.context,
            ('preview_update_stack',
             {'stack_identity': dict(identity),
              'template': None,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {rpc_api.PARAM_EXISTING: True,
                       'timeout_mins': 30}}),
            version='1.36'
        )

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_update_immutable_parameter(self, mock_call, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'param1': u'bar'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' %
                        identity, json.dumps(body))

        error = heat_exc.ImmutableParameterModified(keys='param1')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.update,
                                             req, tenant_id=identity.tenant,
                                             stack_name=identity.stack_name,
                                             stack_id=identity.stack_id,
                                             body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('ImmutableParameterModified',
                         resp.json['error']['type'])
        self.assertIn("The following parameters are immutable",
                      six.text_type(resp.json['error']['message']))

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {u'parameters': parameters,
                         u'encrypted_param_names': [],
                         u'parameter_defaults': {},
                         u'event_sinks': [],
                         u'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30},
              'template_id': None}),
            version='1.36'
        )

    def test_lookup(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks/%(stack_name)s' % identity)

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        found = self.assertRaises(
            webob.exc.HTTPFound, self.controller.lookup, req,
            tenant_id=identity.tenant, stack_name=identity.stack_name)
        self.assertEqual(self._url(identity), found.location)

        mock_call.assert_called_once_with(
            req.context,
            ('identify_stack', {'stack_name': identity.stack_name})
        )

    def test_lookup_arn(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks%s' % identity.arn_url_path())

        found = self.assertRaises(
            webob.exc.HTTPFound, self.controller.lookup,
            req, tenant_id=identity.tenant, stack_name=identity.arn())
        self.assertEqual(self._url(identity), found.location)

    def test_lookup_nonexistent(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s' % {
            'stack_name': stack_name})

        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.lookup,
                                             req, tenant_id=self.tenant,
                                             stack_name=stack_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('identify_stack', {'stack_name': stack_name})
        )

    def test_lookup_err_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', False)
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s' % {
            'stack_name': stack_name})

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.lookup,
                                             req, tenant_id=self.tenant,
                                             stack_name=stack_name)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_lookup_resource(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks/%(stack_name)s/resources' % identity)

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        found = self.assertRaises(
            webob.exc.HTTPFound, self.controller.lookup, req,
            tenant_id=identity.tenant, stack_name=identity.stack_name,
            path='resources')
        self.assertEqual(self._url(identity) + '/resources',
                         found.location)

        mock_call.assert_called_once_with(
            req.context,
            ('identify_stack', {'stack_name': identity.stack_name})
        )

    def test_lookup_resource_nonexistent(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', True)
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s/resources' % {
            'stack_name': stack_name})

        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.lookup,
                                             req, tenant_id=self.tenant,
                                             stack_name=stack_name,
                                             path='resources')

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('identify_stack', {'stack_name': stack_name})
        )

    def test_lookup_resource_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'lookup', False)
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s/resources' % {
            'stack_name': stack_name})

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.lookup,
                                             req, tenant_id=self.tenant,
                                             stack_name=stack_name,
                                             path='resources')

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        params={'resolve_outputs': True})

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
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_resp)

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

        mock_call.assert_called_once_with(
            req.context,
            ('show_stack', {'stack_identity': dict(identity),
                            'resolve_outputs': True}),
            version='1.20'
        )

    def test_show_without_resolve_outputs(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        params={'resolve_outputs': False})

        parameters = {u'DBUsername': u'admin',
                      u'LinuxDistribution': u'F17',
                      u'InstanceType': u'm1.large',
                      u'DBRootPassword': u'admin',
                      u'DBPassword': u'admin',
                      u'DBName': u'wordpress'}

        engine_resp = [
            {
                u'stack_identity': dict(identity),
                u'updated_time': u'2012-07-09T09:13:11Z',
                u'parameters': parameters,
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
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_resp)

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

        mock_call.assert_called_once_with(
            req.context,
            ('show_stack', {'stack_identity': dict(identity),
                            'resolve_outputs': False}),
            version='1.20'
        )

    def test_show_notfound(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wibble', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.show,
                                             req, tenant_id=identity.tenant,
                                             stack_name=identity.stack_name,
                                             stack_id=identity.stack_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('show_stack', {'stack_identity': dict(identity),
                            'resolve_outputs': True}),
            version='1.20'
        )

    def test_show_invalidtenant(self, mock_enforce):
        identity = identifier.HeatIdentifier('wibble', 'wordpress', '6')

        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.show,
                                             req, tenant_id=identity.tenant,
                                             stack_name=identity.stack_name,
                                             stack_id=identity.stack_id)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_show_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', False)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        resp = tools.request_with_middleware(fault.FaultWrapper,
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

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=template)

        response = self.controller.template(req, tenant_id=identity.tenant,
                                            stack_name=identity.stack_name,
                                            stack_id=identity.stack_id)

        self.assertEqual(template, response)

        mock_call.assert_called_once_with(
            req.context,
            ('get_template', {'stack_identity': dict(identity)})
        )

    def test_get_environment(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'environment', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)
        env = {'parameters': {'Foo': 'bar'}}

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=env)

        response = self.controller.environment(req, tenant_id=identity.tenant,
                                               stack_name=identity.stack_name,
                                               stack_id=identity.stack_id)

        self.assertEqual(env, response)

        mock_call.assert_called_once_with(
            req.context,
            ('get_environment', {'stack_identity': dict(identity)},),
            version='1.28',
        )

    def test_get_files(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'files', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)
        files = {'foo.yaml': 'i am yaml'}

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=files)

        response = self.controller.files(req, tenant_id=identity.tenant,
                                         stack_name=identity.stack_name,
                                         stack_id=identity.stack_id)

        self.assertEqual(files, response)

        mock_call.assert_called_once_with(
            req.context,
            ('get_files', {'stack_identity': dict(identity)},),
            version='1.32',
        )

    def test_get_template_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'template', False)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s/template'
                        % identity)

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.template,
                                             req, tenant_id=identity.tenant,
                                             stack_name=identity.stack_name,
                                             stack_id=identity.stack_id)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_get_template_err_notfound(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'template', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.template,
                                             req, tenant_id=identity.tenant,
                                             stack_name=identity.stack_name,
                                             stack_id=identity.stack_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('get_template', {'stack_identity': dict(identity)})
        )

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

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30},
              'template_id': None}),
            version='1.36'
        )

    def test_update_with_tags(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'tags': 'tag1,tag2',
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30, 'tags': ['tag1', 'tag2']},
              'template_id': None}),
            version='1.36'
        )

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

        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.update,
                                             req, tenant_id=identity.tenant,
                                             stack_name=identity.stack_name,
                                             stack_id=identity.stack_id,
                                             body=body)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {u'parameters': parameters,
                         u'encrypted_param_names': [],
                         u'parameter_defaults': {},
                         u'event_sinks': [],
                         u'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {'timeout_mins': 30},
              'template_id': None}),
            version='1.36'
        )

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
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
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

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.update,
                                             req, tenant_id=identity.tenant,
                                             stack_name=identity.stack_name,
                                             stack_id=identity.stack_id,
                                             body=body)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_update_with_existing_template(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update_patch', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        body = {'template': None,
                'parameters': {},
                'files': {},
                'timeout_mins': 30}

        req = self._patch('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                          json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': None,
              'params': {'parameters': {},
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {rpc_api.PARAM_EXISTING: True,
                       'timeout_mins': 30},
              'template_id': None}),
            version='1.36'
        )

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

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': {},
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {rpc_api.PARAM_EXISTING: True,
                       'timeout_mins': 30},
              'template_id': None}),
            version='1.36'
        )

    def test_update_with_existing_parameters_with_tags(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update_patch', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        body = {'template': template,
                'parameters': {},
                'files': {},
                'tags': 'tag1,tag2',
                'timeout_mins': 30}

        req = self._patch('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                          json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': {},
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {rpc_api.PARAM_EXISTING: True,
                       'timeout_mins': 30,
                       'tags': ['tag1', 'tag2']},
              'template_id': None}),
            version='1.36'
        )

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

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {rpc_api.PARAM_EXISTING: True,
                       'timeout_mins': 30},
              'template_id': None}),
            version='1.36'
        )

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
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
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

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': {},
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {rpc_api.PARAM_EXISTING: True,
                       'clear_parameters': clear_params,
                       'timeout_mins': 30},
              'template_id': None}),
            version='1.36'
        )

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

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=dict(identity))

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update_patch,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)

        mock_call.assert_called_once_with(
            req.context,
            ('update_stack',
             {'stack_identity': dict(identity),
              'template': template,
              'params': {'parameters': parameters,
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'args': {rpc_api.PARAM_EXISTING: True,
                       'clear_parameters': clear_params,
                       'timeout_mins': 30},
              'template_id': None}),
            version='1.36'
        )

    def test_delete(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._delete('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        # Engine returns None when delete successful
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=None)

        self.assertRaises(webob.exc.HTTPNoContent,
                          self.controller.delete,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id)

        mock_call.assert_called_once_with(
            req.context,
            ('delete_stack', {'stack_identity': dict(identity)})
        )

    def test_delete_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete', False)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._delete('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.delete,
                                             req, tenant_id=self.tenant,
                                             stack_name=identity.stack_name,
                                             stack_id=identity.stack_id)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_export(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'export', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s/export' %
                        identity)

        # Engine returns json data
        expected = {"name": "test", "id": "123"}
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=expected)

        ret = self.controller.export(req,
                                     tenant_id=identity.tenant,
                                     stack_name=identity.stack_name,
                                     stack_id=identity.stack_id)
        self.assertEqual(expected, ret)

        mock_call.assert_called_once_with(
            req.context,
            ('export_stack', {'stack_identity': dict(identity)}),
            version='1.22'
        )

    def test_abandon(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'abandon', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._abandon('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        # Engine returns json data on abandon completion
        expected = {"name": "test", "id": "123"}
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=expected)

        ret = self.controller.abandon(req,
                                      tenant_id=identity.tenant,
                                      stack_name=identity.stack_name,
                                      stack_id=identity.stack_id)
        self.assertEqual(expected, ret)

        mock_call.assert_called_once_with(
            req.context,
            ('abandon_stack', {'stack_identity': dict(identity)})
        )

    def test_abandon_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'abandon', False)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._abandon('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        resp = tools.request_with_middleware(fault.FaultWrapper,
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

        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        # Engine returns None when delete successful
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.delete,
                                             req, tenant_id=identity.tenant,
                                             stack_name=identity.stack_name,
                                             stack_id=identity.stack_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('delete_stack', {'stack_identity': dict(identity)})
        )

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

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_response)

        response = self.controller.validate_template(req,
                                                     tenant_id=self.tenant,
                                                     body=body)
        self.assertEqual(engine_response, response)

        mock_call.assert_called_once_with(
            req.context,
            ('validate_template',
             {'template': template,
              'params': {'parameters': {},
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'show_nested': False,
              'ignorable_errors': None}),
            version='1.36'
        )

    def test_validate_template_error(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'validate_template', True)
        template = {u'Foo': u'bar'}
        body = {'template': template}

        req = self._post('/validate', json.dumps(body))

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value={'Error': 'fubar'})

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_template,
                          req, tenant_id=self.tenant, body=body)

        mock_call.assert_called_once_with(
            req.context,
            ('validate_template',
             {'template': template,
              'params': {'parameters': {},
                         'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'resource_registry': {}},
              'files': {},
              'environment_files': None,
              'files_container': None,
              'show_nested': False,
              'ignorable_errors': None}),
            version='1.36'
        )

    def test_validate_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'validate_template', False)
        template = {u'Foo': u'bar'}
        body = {'template': template}

        req = self._post('/validate', json.dumps(body))

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.validate_template,
            req, tenant_id=self.tenant, body=body)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_list_resource_types(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'list_resource_types', True)
        req = self._get('/resource_types')

        engine_response = ['AWS::EC2::Instance',
                           'AWS::EC2::EIP',
                           'AWS::EC2::EIPAssociation']

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_response)

        response = self.controller.list_resource_types(req,
                                                       tenant_id=self.tenant)
        self.assertEqual({'resource_types': engine_response}, response)

        mock_call.assert_called_once_with(
            req.context,
            ('list_resource_types',
             {
                 'support_status': None,
                 'type_name': None,
                 'heat_version': None,
                 'with_description': False
             }),
            version="1.30"
        )

    def test_list_resource_types_error(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'list_resource_types', True)
        req = self._get('/resource_types')

        error = heat_exc.EntityNotFound(entity='Resource Type', name='')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.list_resource_types,
            req, tenant_id=self.tenant)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('list_resource_types',
             {
                 'support_status': None,
                 'type_name': None,
                 'heat_version': None,
                 'with_description': False
             }),
            version="1.30"
        )

    def test_list_resource_types_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'list_resource_types', False)
        req = self._get('/resource_types')
        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.list_resource_types,
            req, tenant_id=self.tenant)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_list_outputs(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'list_outputs', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)
        outputs = [
            {'output_key': 'key1', 'description': 'description'},
            {'output_key': 'key2', 'description': 'description1'}
        ]

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=outputs)

        response = self.controller.list_outputs(req, tenant_id=identity.tenant,
                                                stack_name=identity.stack_name,
                                                stack_id=identity.stack_id)

        self.assertEqual({'outputs': outputs}, response)

        mock_call.assert_called_once_with(
            req.context,
            ('list_outputs', {'stack_identity': dict(identity)}),
            version='1.19'
        )

    def test_show_output(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show_output', True)
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s/key' % identity)
        output = {'output_key': 'key',
                  'output_value': 'val',
                  'description': 'description'}

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=output)

        response = self.controller.show_output(req, tenant_id=identity.tenant,
                                               stack_name=identity.stack_name,
                                               stack_id=identity.stack_id,
                                               output_key='key')

        self.assertEqual({'output': output}, response)
        mock_call.assert_called_once_with(
            req.context,
            ('show_output', {'output_key': 'key',
                             'stack_identity': dict(identity)}),
            version='1.19'
        )

    def test_list_template_versions(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'list_template_versions', True)
        req = self._get('/template_versions')

        engine_response = [
            {'version': 'heat_template_version.2013-05-23', 'type': 'hot'},
            {'version': 'AWSTemplateFormatVersion.2010-09-09', 'type': 'cfn'}]
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_response)

        response = self.controller.list_template_versions(
            req, tenant_id=self.tenant)
        self.assertEqual({'template_versions': engine_response}, response)

        mock_call.assert_called_once_with(
            req.context, ('list_template_versions', {}),
            version="1.11"
        )

    def _test_list_template_functions(self, mock_enforce, req, engine_response,
                                      with_condition=False):
        self._mock_enforce_setup(mock_enforce, 'list_template_functions', True)
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_response)

        response = self.controller.list_template_functions(
            req, tenant_id=self.tenant, template_version='t1')
        self.assertEqual({'template_functions': engine_response}, response)

        mock_call.assert_called_once_with(
            req.context, (
                'list_template_functions',
                {'template_version': 't1', 'with_condition': with_condition}),
            version="1.35"
        )

    def test_list_template_functions(self, mock_enforce):
        req = self._get('/template_versions/t1/functions')
        engine_response = [
            {'functions': 'func1', 'description': 'desc1'},
        ]

        self._test_list_template_functions(mock_enforce, req, engine_response)

    def test_list_template_funcs_includes_condition_funcs(self, mock_enforce):
        params = {'with_condition_func': 'true'}
        req = self._get('/template_versions/t1/functions', params=params)

        engine_response = [
            {'functions': 'func1', 'description': 'desc1'},
            {'functions': 'condition_func', 'description': 'desc2'}
        ]

        self._test_list_template_functions(mock_enforce, req, engine_response,
                                           with_condition=True)

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
            'support_status': {
                'status': 'SUPPORTED',
                'version': None,
                'message': None,
            },
        }
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_response)

        response = self.controller.resource_schema(req,
                                                   tenant_id=self.tenant,
                                                   type_name=type_name)
        self.assertEqual(engine_response, response)

        mock_call.assert_called_once_with(
            req.context,
            ('resource_schema', {'type_name': type_name,
                                 'with_description': False}),
            version='1.30'
        )

    def test_resource_schema_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'resource_schema', True)
        req = self._get('/resource_types/BogusResourceType')
        type_name = 'BogusResourceType'

        error = heat_exc.EntityNotFound(entity='Resource Type',
                                        name='BogusResourceType')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.resource_schema,
                                             req, tenant_id=self.tenant,
                                             type_name=type_name)
        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('resource_schema', {'type_name': type_name,
                                 'with_description': False}),
            version='1.30'
        )

    def test_resource_schema_faulty_template(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'resource_schema', True)
        req = self._get('/resource_types/FaultyTemplate')
        type_name = 'FaultyTemplate'

        error = heat_exc.InvalidGlobalResource(type_name='FaultyTemplate')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.resource_schema,
                                             req, tenant_id=self.tenant,
                                             type_name=type_name)
        self.assertEqual(500, resp.json['code'])
        self.assertEqual('InvalidGlobalResource', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('resource_schema', {'type_name': type_name,
                                 'with_description': False}),
            version='1.30'
        )

    def test_resource_schema_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'resource_schema', False)
        req = self._get('/resource_types/BogusResourceType')
        type_name = 'BogusResourceType'

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.resource_schema,
                                             req, tenant_id=self.tenant,
                                             type_name=type_name)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_generate_template(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'generate_template', True)
        req = self._get('/resource_types/TEST_TYPE/template')

        engine_response = {'Type': 'TEST_TYPE'}
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_response)

        self.controller.generate_template(req, tenant_id=self.tenant,
                                          type_name='TEST_TYPE')

        mock_call.assert_called_once_with(
            req.context,
            ('generate_template', {'type_name': 'TEST_TYPE',
                                   'template_type': 'cfn'}),
            version='1.9'
        )

    def test_generate_template_invalid_template_type(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'generate_template', True)
        params = {'template_type': 'invalid'}
        mock_call = self.patchobject(rpc_client.EngineClient, 'call')

        req = self._get('/resource_types/TEST_TYPE/template',
                        params=params)

        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.generate_template,
                               req, tenant_id=self.tenant,
                               type_name='TEST_TYPE')
        self.assertIn('Template type is not supported: Invalid template '
                      'type "invalid", valid types are: cfn, hot.',
                      six.text_type(ex))
        self.assertFalse(mock_call.called)

    def test_generate_template_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'generate_template', True)
        req = self._get('/resource_types/NOT_FOUND/template')

        error = heat_exc.EntityNotFound(entity='Resource Type', name='a')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(fault.FaultWrapper,
                                             self.controller.generate_template,
                                             req, tenant_id=self.tenant,
                                             type_name='NOT_FOUND')
        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('generate_template', {'type_name': 'NOT_FOUND',
                                   'template_type': 'cfn'}),
            version='1.9'
        )

    def test_generate_template_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'generate_template', False)
        req = self._get('/resource_types/NOT_FOUND/template')

        resp = tools.request_with_middleware(fault.FaultWrapper,
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
