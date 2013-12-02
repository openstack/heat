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

import json
import mock

from oslo.config import cfg
import webob.exc

from heat.common import identifier
from heat.openstack.common import rpc

from heat.common import exception as heat_exc
from heat.common.wsgi import Request
from heat.common import urlfetch
from heat.openstack.common.rpc import common as rpc_common
from heat.rpc import api as rpc_api
from heat.tests.common import HeatTestCase

import heat.api.openstack.v1 as api_v1
import heat.api.openstack.v1.stacks as stacks
import heat.api.openstack.v1.resources as resources
import heat.api.openstack.v1.events as events
import heat.api.openstack.v1.actions as actions
from heat.tests import utils

import heat.api.middleware.fault as fault


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
    remote_error = rpc_common.deserialize_remote_exception(cfg.CONF,
                                                           serialized)
    return remote_error


class InstantiationDataTest(HeatTestCase):

    def test_format_parse(self):
        data = {"key1": ["val1[0]", "val1[1]"], "key2": "val2"}
        json_repr = '{ "key1": [ "val1[0]", "val1[1]" ], "key2": "val2" }'
        parsed = stacks.InstantiationData.format_parse(json_repr, 'foo')
        self.assertEqual(parsed, data)

    def test_format_parse_invalid(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          stacks.InstantiationData.format_parse,
                          '!@#$%^&not json', 'Garbage')

    def test_stack_name(self):
        body = {'stack_name': 'wibble'}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.stack_name(), 'wibble')

    def test_stack_name_missing(self):
        body = {'not the stack_name': 'wibble'}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.stack_name)

    def test_template_inline(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'template': template}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.template(), template)

    def test_template_string_json(self):
        template = '{"foo": "bar", "blarg": "wibble"}'
        body = {'template': template}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.template(), json.loads(template))

    def test_template_string_yaml(self):
        template = '''foo: bar
blarg: wibble
'''
        parsed = {u'HeatTemplateFormatVersion': u'2012-12-12',
                  u'Mappings': {},
                  u'Outputs': {},
                  u'Parameters': {},
                  u'Resources': {},
                  u'blarg': u'wibble',
                  u'foo': u'bar'}

        body = {'template': template}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.template(), parsed)

    def test_template_url(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        url = 'http://example.com/template'
        body = {'template_url': url}
        data = stacks.InstantiationData(body)

        self.m.StubOutWithMock(urlfetch, 'get')
        urlfetch.get(url).AndReturn(json.dumps(template))
        self.m.ReplayAll()

        self.assertEqual(data.template(), template)
        self.m.VerifyAll()

    def test_template_priority(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        url = 'http://example.com/template'
        body = {'template': template, 'template_url': url}
        data = stacks.InstantiationData(body)

        self.m.StubOutWithMock(urlfetch, 'get')
        self.m.ReplayAll()

        self.assertEqual(data.template(), template)
        self.m.VerifyAll()

    def test_template_missing(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'not the template': template}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.template)

    def test_parameters(self):
        params = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'parameters': params,
                'resource_registry': {}}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.environment(), body)

    def test_environment_only_params(self):
        env = {'parameters': {'foo': 'bar', 'blarg': 'wibble'}}
        body = {'environment': env}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.environment(), env)

    def test_environment_and_parameters(self):
        body = {'parameters': {'foo': 'bar'},
                'environment': {'parameters': {'blarg': 'wibble'}}}
        expect = {'parameters': {'blarg': 'wibble',
                                 'foo': 'bar'},
                  'resource_registry': {}}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.environment(), expect)

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
                  'resource_registry': {}}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.environment(), expect)

    def test_environment_bad_format(self):
        env = {'somethingnotsupported': {'blarg': 'wibble'}}
        body = {'environment': json.dumps(env)}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.environment)

    def test_environment_missing(self):
        env = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'not the environment': env}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.environment(),
                         {'parameters': {},
                          'resource_registry': {}})

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
        self.assertEqual(data.args(), {'timeout_mins': 60})


class ControllerTest(object):
    """
    Common utilities for testing API Controllers.
    """

    def __init__(self, *args, **kwargs):
        super(ControllerTest, self).__init__(*args, **kwargs)

        cfg.CONF.set_default('host', 'host')
        self.topic = rpc_api.ENGINE_TOPIC
        self.api_version = '1.0'
        self.tenant = 't'

    def _environ(self, path):
        return {
            'SERVER_NAME': 'heat.example.com',
            'SERVER_PORT': 8004,
            'SCRIPT_NAME': '/v1',
            'PATH_INFO': '/%s' % self.tenant + path,
            'wsgi.url_scheme': 'http',
        }

    def _simple_request(self, path, method='GET'):
        environ = self._environ(path)
        environ['REQUEST_METHOD'] = method

        req = Request(environ)
        req.context = utils.dummy_context('api_test_user', self.tenant)
        return req

    def _get(self, path):
        return self._simple_request(path)

    def _delete(self, path):
        return self._simple_request(path, method='DELETE')

    def _data_request(self, path, data, content_type='application/json',
                      method='POST'):
        environ = self._environ(path)
        environ['REQUEST_METHOD'] = method

        req = Request(environ)
        req.context = utils.dummy_context('api_test_user', self.tenant)
        req.body = data
        return req

    def _post(self, path, data, content_type='application/json'):
        return self._data_request(path, data, content_type)

    def _put(self, path, data, content_type='application/json'):
        return self._data_request(path, data, content_type, method='PUT')

    def _url(self, id):
        host = 'heat.example.com:8004'
        path = '/v1/%(tenant)s/stacks/%(stack_name)s/%(stack_id)s%(path)s' % id
        return 'http://%s%s' % (host, path)


class StackControllerTest(ControllerTest, HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        super(StackControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig():
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = stacks.StackController(options=cfgopts)

    def test_index(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_stacks',
                  'args': {},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
        self.m.ReplayAll()

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
        self.assertEqual(result, expected)
        self.m.VerifyAll()

    def test_detail(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_stacks',
                  'args': {},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
        self.m.ReplayAll()

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

        self.assertEqual(result, expected)
        self.m.VerifyAll()

    def test_index_rmt_aterr(self):
        req = self._get('/stacks')

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_stacks',
                  'args': {},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(AttributeError()))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant)

        self.assertEqual(resp.json['code'], 400)
        self.assertEqual(resp.json['error']['type'], 'AttributeError')
        self.m.VerifyAll()

    def test_index_rmt_interr(self):
        req = self._get('/stacks')

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_stacks',
                  'args': {},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(Exception()))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant)

        self.assertEqual(resp.json['code'], 500)
        self.assertEqual(resp.json['error']['type'], 'Exception')
        self.m.VerifyAll()

    def test_create(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')
        template = {u'Foo': u'bar'}
        json_template = json.dumps(template)
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': identity.stack_name,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'create_stack',
                  'args': {'stack_name': identity.stack_name,
                           'template': template,
                           'params': {'parameters': parameters,
                                      'resource_registry': {}},
                           'files': {},
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndReturn(dict(identity))
        self.m.ReplayAll()

        response = self.controller.create(req,
                                          tenant_id=identity.tenant,
                                          body=body)

        expected = {'stack':
                    {'id': '1',
                     'links': [{'href': self._url(identity), 'rel': 'self'}]}}
        self.assertEqual(response, expected)

        self.m.VerifyAll()

    def test_create_with_files(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')
        template = {u'Foo': u'bar'}
        json_template = json.dumps(template)
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'stack_name': identity.stack_name,
                'parameters': parameters,
                'files': {'my.yaml': 'This is the file contents.'},
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'create_stack',
                  'args': {'stack_name': identity.stack_name,
                           'template': template,
                           'params': {'parameters': parameters,
                                      'resource_registry': {}},
                           'files': {'my.yaml': 'This is the file contents.'},
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndReturn(dict(identity))
        self.m.ReplayAll()

        result = self.controller.create(req,
                                        tenant_id=identity.tenant,
                                        body=body)
        expected = {'stack':
                    {'id': '1',
                     'links': [{'href': self._url(identity), 'rel': 'self'}]}}
        self.assertEqual(result, expected)

        self.m.VerifyAll()

    def test_create_err_rpcerr(self):
        stack_name = "wordpress"
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        json_template = json.dumps(template)
        body = {'template': template,
                'stack_name': stack_name,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        unknown_parameter = heat_exc.UnknownUserParameter(key='a')
        missing_parameter = heat_exc.UserParameterMissing(key='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'create_stack',
                  'args': {'stack_name': stack_name,
                           'template': template,
                           'params': {'parameters': parameters,
                                      'resource_registry': {}},
                           'files': {},
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(AttributeError()))
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'create_stack',
                  'args': {'stack_name': stack_name,
                           'template': template,
                           'params': {'parameters': parameters,
                                      'resource_registry': {}},
                           'files': {},
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(unknown_parameter))
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'create_stack',
                  'args': {'stack_name': stack_name,
                           'template': template,
                           'params': {'parameters': parameters,
                                      'resource_registry': {}},
                           'files': {},
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(missing_parameter))
        self.m.ReplayAll()
        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(resp.json['code'], 400)
        self.assertEqual(resp.json['error']['type'], 'AttributeError')

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(resp.json['code'], 400)
        self.assertEqual(resp.json['error']['type'], 'UnknownUserParameter')

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(resp.json['code'], 400)
        self.assertEqual(resp.json['error']['type'], 'UserParameterMissing')
        self.m.VerifyAll()

    def test_create_err_existing(self):
        stack_name = "wordpress"
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        json_template = json.dumps(template)
        body = {'template': template,
                'stack_name': stack_name,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        error = heat_exc.StackExists(stack_name='s')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'create_stack',
                  'args': {'stack_name': stack_name,
                           'template': template,
                           'params': {'parameters': parameters,
                                      'resource_registry': {}},
                           'files': {},
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(resp.json['code'], 409)
        self.assertEqual(resp.json['error']['type'], 'StackExists')
        self.m.VerifyAll()

    def test_create_err_engine(self):
        stack_name = "wordpress"
        template = {u'Foo': u'bar'}
        parameters = {u'InstanceType': u'm1.xlarge'}
        json_template = json.dumps(template)
        body = {'template': template,
                'stack_name': stack_name,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._post('/stacks', json.dumps(body))

        error = heat_exc.StackValidationFailed(message='')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'create_stack',
                  'args': {'stack_name': stack_name,
                           'template': template,
                           'params': {'parameters': parameters,
                                      'resource_registry': {}},
                           'files': {},
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.create,
                                       req, tenant_id=self.tenant, body=body)

        self.assertEqual(resp.json['code'], 400)
        self.assertEqual(resp.json['error']['type'], 'StackValidationFailed')
        self.m.VerifyAll()

    def test_create_err_stack_bad_reqest(self):
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
        self.assertEqual(resp.json['code'], 400)
        self.assertEqual(resp.json['error']['type'], 'HTTPBadRequest')
        self.assertIsNotNone(resp.json['error']['traceback'])

    def test_lookup(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks/%(stack_name)s' % identity)

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'identify_stack',
                  'args': {'stack_name': identity.stack_name},
                  'version': self.api_version},
                 None).AndReturn(identity)

        self.m.ReplayAll()

        try:
            result = self.controller.lookup(req, tenant_id=identity.tenant,
                                            stack_name=identity.stack_name)
        except webob.exc.HTTPFound as found:
            self.assertEqual(found.location, self._url(identity))
        else:
            self.fail('No redirect generated')
        self.m.VerifyAll()

    def test_lookup_arn(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks%s' % identity.arn_url_path())

        self.m.ReplayAll()

        try:
            result = self.controller.lookup(req, tenant_id=identity.tenant,
                                            stack_name=identity.arn())
        except webob.exc.HTTPFound as found:
            self.assertEqual(found.location, self._url(identity))
        else:
            self.fail('No redirect generated')
        self.m.VerifyAll()

    def test_lookup_nonexistant(self):
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s' % {
            'stack_name': stack_name})

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'identify_stack',
                  'args': {'stack_name': stack_name},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.lookup,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_name)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_lookup_resource(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks/%(stack_name)s/resources' % identity)

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'identify_stack',
                  'args': {'stack_name': identity.stack_name},
                  'version': self.api_version},
                 None).AndReturn(identity)

        self.m.ReplayAll()

        try:
            result = self.controller.lookup(req, tenant_id=identity.tenant,
                                            stack_name=identity.stack_name,
                                            path='resources')
        except webob.exc.HTTPFound as found:
            self.assertEqual(found.location,
                             self._url(identity) + '/resources')
        else:
            self.fail('No redirect generated')
        self.m.VerifyAll()

    def test_lookup_resource_nonexistant(self):
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s/resources' % {
            'stack_name': stack_name})

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'identify_stack',
                  'args': {'stack_name': stack_name},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.lookup,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_name,
                                       path='resources')

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_show(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'show_stack',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
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
        self.assertEqual(response, expected)
        self.m.VerifyAll()

    def test_show_notfound(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wibble', '6')

        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'show_stack',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_show_invalidtenant(self):
        identity = identifier.HeatIdentifier('wibble', 'wordpress', '6')

        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(resp.status_int, 403)
        self.assertIn('403 Forbidden', str(resp))
        self.m.VerifyAll()

    def test_get_template(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)
        template = {u'Foo': u'bar'}

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'get_template',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndReturn(template)
        self.m.ReplayAll()

        response = self.controller.template(req, tenant_id=identity.tenant,
                                            stack_name=identity.stack_name,
                                            stack_id=identity.stack_id)

        self.assertEqual(response, template)
        self.m.VerifyAll()

    def test_get_template_err_notfound(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'get_template',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))

        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.template,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_update(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        stack_name = u'wordpress'
        stack_id = u'6'
        template = {u'Foo': u'bar'}
        json_template = json.dumps(template)
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        json.dumps(body))

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'update_stack',
                  'args': {'stack_identity': dict(identity),
                           'template': template,
                           'params': {'parameters': parameters,
                                      'resource_registry': {}},
                           'files': {},
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndReturn(dict(identity))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPAccepted,
                          self.controller.update,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_update_bad_name(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wibble', '6')
        template = {u'Foo': u'bar'}
        json_template = json.dumps(template)
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'files': {},
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        json.dumps(body))

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'update_stack',
                  'args': {'stack_identity': dict(identity),
                           'template': template,
                           'params': {u'parameters': parameters,
                                      u'resource_registry': {}},
                           'files': {},
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.update,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id,
                                       body=body)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_delete(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        template = {u'Foo': u'bar'}
        json_template = json.dumps(template)
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._delete('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        self.m.StubOutWithMock(rpc, 'call')
        # Engine returns None when delete successful
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'delete_stack',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndReturn(None)
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNoContent,
                          self.controller.delete,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id)
        self.m.VerifyAll()

    def test_delete_bad_name(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wibble', '6')
        template = {u'Foo': u'bar'}
        json_template = json.dumps(template)
        parameters = {u'InstanceType': u'm1.xlarge'}
        body = {'template': template,
                'parameters': parameters,
                'timeout_mins': 30}

        req = self._delete('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        # Engine returns None when delete successful
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'delete_stack',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.delete,
                                       req, tenant_id=identity.tenant,
                                       stack_name=identity.stack_name,
                                       stack_id=identity.stack_id)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_validate_template(self):
        template = {u'Foo': u'bar'}
        json_template = json.dumps(template)
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

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'validate_template',
                  'args': {'template': template},
                  'version': self.api_version},
                 None).AndReturn(engine_response)
        self.m.ReplayAll()

        response = self.controller.validate_template(req,
                                                     tenant_id=self.tenant,
                                                     body=body)
        self.assertEqual(response, engine_response)
        self.m.VerifyAll()

    def test_validate_template_error(self):
        template = {u'Foo': u'bar'}
        json_template = json.dumps(template)
        body = {'template': template}

        req = self._post('/validate', json.dumps(body))

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'validate_template',
                  'args': {'template': template},
                  'version': self.api_version},
                 None).AndReturn({'Error': 'fubar'})
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_template,
                          req, tenant_id=self.tenant, body=body)
        self.m.VerifyAll()

    def test_list_resource_types(self):
        req = self._get('/resource_types')

        engine_response = ['AWS::EC2::Instance',
                           'AWS::EC2::EIP',
                           'AWS::EC2::EIPAssociation']

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_resource_types',
                  'args': {},
                  'version': self.api_version},
                 None).AndReturn(engine_response)
        self.m.ReplayAll()
        response = self.controller.list_resource_types(req,
                                                       tenant_id=self.tenant)
        self.assertEqual(response, {'resource_types': engine_response})
        self.m.VerifyAll()

    def test_list_resource_types_error(self):
        req = self._get('/resource_types')

        error = heat_exc.ServerError(body='')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_resource_types',
                  'args': {},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.list_resource_types,
                                       req, tenant_id=self.tenant)
        self.assertEqual(resp.json['code'], 500)
        self.assertEqual(resp.json['error']['type'], 'ServerError')
        self.m.VerifyAll()

    def test_resource_schema(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'resource_schema',
                  'args': {'type_name': type_name},
                  'version': self.api_version},
                 None).AndReturn(engine_response)
        self.m.ReplayAll()
        response = self.controller.resource_schema(req,
                                                   tenant_id=self.tenant,
                                                   type_name=type_name)
        self.assertEqual(response, engine_response)
        self.m.VerifyAll()

    def test_resource_schema_nonexist(self):
        req = self._get('/resource_types/BogusResourceType')
        type_name = 'BogusResourceType'

        error = heat_exc.ResourceTypeNotFound(type_name='BogusResourceType')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'resource_schema',
                  'args': {'type_name': type_name},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.resource_schema,
                                       req, tenant_id=self.tenant,
                                       type_name=type_name)
        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'ResourceTypeNotFound')
        self.m.VerifyAll()

    def test_generate_template(self):

        req = self._get('/resource_types/TEST_TYPE/template')

        engine_response = {'Type': 'TEST_TYPE'}

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'generate_template',
                  'args': {'type_name': 'TEST_TYPE'},
                  'version': self.api_version},
                 None).AndReturn(engine_response)
        self.m.ReplayAll()
        self.controller.generate_template(req, tenant_id=self.tenant,
                                          type_name='TEST_TYPE')
        self.m.VerifyAll()

    def test_generate_template_not_found(self):
        req = self._get('/resource_types/NOT_FOUND/template')

        error = heat_exc.ResourceTypeNotFound(type_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'generate_template',
                  'args': {'type_name': 'NOT_FOUND'},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()
        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.generate_template,
                                       req, tenant_id=self.tenant,
                                       type_name='NOT_FOUND')
        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'ResourceTypeNotFound')
        self.m.VerifyAll()


class StackSerializerTest(HeatTestCase):

    def setUp(self):
        super(StackSerializerTest, self).setUp()
        self.serializer = stacks.StackSerializer()

    def test_serialize_create(self):
        result = {'stack':
                  {'id': '1',
                   'links': [{'href': 'location', "rel": "self"}]}}
        response = webob.Response()
        response = self.serializer.create(response, result)
        self.assertEqual(response.status_int, 201)
        self.assertEqual(response.headers['Location'], 'location')
        self.assertEqual(response.headers['Content-Type'], 'application/json')


class ResourceControllerTest(ControllerTest, HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        super(ResourceControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig():
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = resources.ResourceController(options=cfgopts)

    def test_index(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_stack_resources',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
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

        self.assertEqual(result, expected)
        self.m.VerifyAll()

    def test_index_nonexist(self):
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')

        req = self._get(stack_identity._tenant_path() + '/resources')

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_stack_resources',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_show(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'describe_stack_resource',
                  'args': {'stack_identity': stack_identity,
                           'resource_name': res_name},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
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

        self.assertEqual(result, expected)
        self.m.VerifyAll()

    def test_show_nonexist(self):
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'describe_stack_resource',
                  'args': {'stack_identity': stack_identity,
                           'resource_name': res_name},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_show_nonexist_resource(self):
        res_name = 'Wibble'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        error = heat_exc.ResourceNotFound(stack_name='a', resource_name='b')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'describe_stack_resource',
                  'args': {'stack_identity': stack_identity,
                           'resource_name': res_name},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'ResourceNotFound')
        self.m.VerifyAll()

    def test_show_uncreated_resource(self):
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        error = heat_exc.ResourceNotAvailable(resource_name='')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'describe_stack_resource',
                  'args': {'stack_identity': stack_identity,
                           'resource_name': res_name},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'ResourceNotAvailable')
        self.m.VerifyAll()

    def test_metadata_show(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'describe_stack_resource',
                  'args': {'stack_identity': stack_identity,
                           'resource_name': res_name},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
        self.m.ReplayAll()

        result = self.controller.metadata(req, tenant_id=self.tenant,
                                          stack_name=stack_identity.stack_name,
                                          stack_id=stack_identity.stack_id,
                                          resource_name=res_name)

        expected = {'metadata': {u'ensureRunning': u'true'}}

        self.assertEqual(result, expected)
        self.m.VerifyAll()

    def test_metadata_show_nonexist(self):
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path() + '/metadata')

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'describe_stack_resource',
                  'args': {'stack_identity': stack_identity,
                           'resource_name': res_name},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.metadata,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_metadata_show_nonexist_resource(self):
        res_name = 'wibble'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path() + '/metadata')

        error = heat_exc.ResourceNotFound(stack_name='a', resource_name='b')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'describe_stack_resource',
                  'args': {'stack_identity': stack_identity,
                           'resource_name': res_name},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.metadata,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'ResourceNotFound')
        self.m.VerifyAll()


class EventControllerTest(ControllerTest, HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        super(EventControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig():
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = events.EventController(options=cfgopts)

    def test_resource_index(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_events',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
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

        self.assertEqual(result, expected)
        self.m.VerifyAll()

    def test_stack_index(self):
        event_id = '42'
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        ev_identity = identifier.EventIdentifier(event_id=event_id,
                                                 **res_identity)

        req = self._get(stack_identity._tenant_path() + '/events')

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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_events',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
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

        self.assertEqual(result, expected)
        self.m.VerifyAll()

    def test_index_stack_nonexist(self):
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wibble', '6')

        req = self._get(stack_identity._tenant_path() + '/events')

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_events',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.index,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()

    def test_index_resource_nonexist(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_events',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.index,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          resource_name=res_name)
        self.m.VerifyAll()

    def test_show(self):
        event_id = '42'
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_events',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
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

        self.assertEqual(result, expected)
        self.m.VerifyAll()

    def test_show_nonexist(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_events',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          resource_name=res_name, event_id=event_id)
        self.m.VerifyAll()

    def test_show_bad_resource(self):
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
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_events',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndReturn(engine_resp)
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          resource_name=res_name, event_id=event_id)
        self.m.VerifyAll()

    def test_show_stack_nonexist(self):
        event_id = '42'
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wibble', '6')

        req = self._get(stack_identity._tenant_path() +
                        '/resources/' + res_name + '/events/' + event_id)

        error = heat_exc.StackNotFound(stack_name='a')
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'list_events',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(error))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.show,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       resource_name=res_name,
                                       event_id=event_id)

        self.assertEqual(resp.json['code'], 404)
        self.assertEqual(resp.json['error']['type'], 'StackNotFound')
        self.m.VerifyAll()


class RoutesTest(HeatTestCase):

    def assertRoute(self, mapper, path, method, action, controller, params={}):
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


class ActionControllerTest(ControllerTest, HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        super(ActionControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig():
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = actions.ActionController(options=cfgopts)

    def test_action_suspend(self):
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'suspend': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'stack_suspend',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndReturn(None)
        self.m.ReplayAll()

        result = self.controller.action(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        body=body)
        self.assertEqual(result, None)
        self.m.VerifyAll()

    def test_action_resume(self):
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'resume': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'stack_resume',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndReturn(None)
        self.m.ReplayAll()

        result = self.controller.action(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        body=body)
        self.assertEqual(result, None)
        self.m.VerifyAll()

    def test_action_badaction(self):
        res_name = 'WikiDatabase'
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

    def test_action_badaction_empty(self):
        res_name = 'WikiDatabase'
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

    def test_action_badaction_multiple(self):
        res_name = 'WikiDatabase'
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

    def test_action_rmt_aterr(self):
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'suspend': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'namespace': None,
                  'method': 'stack_suspend',
                  'args': {'stack_identity': stack_identity},
                  'version': self.api_version},
                 None).AndRaise(to_remote_error(AttributeError()))
        self.m.ReplayAll()

        resp = request_with_middleware(fault.FaultWrapper,
                                       self.controller.action,
                                       req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id,
                                       body=body)

        self.assertEqual(resp.json['code'], 400)
        self.assertEqual(resp.json['error']['type'], 'AttributeError')
        self.m.VerifyAll()

    def test_action_badaction_ise(self):
        res_name = 'WikiDatabase'
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
