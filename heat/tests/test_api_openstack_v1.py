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


import sys
import socket
import nose
import mox
import json
import unittest
from nose.plugins.attrib import attr

import httplib
import urlparse
import webob.exc

from heat.common import config
from heat.common import context
from heat.engine import auth
from heat.engine import identifier
from heat.openstack.common import cfg
from heat.openstack.common import rpc
import heat.openstack.common.rpc.common as rpc_common
from heat.common.wsgi import Request

import heat.api.openstack.v1.stacks as stacks


@attr(tag=['unit', 'api-openstack-v1-stacks'])
@attr(speed='fast')
class InstantiationDataTest(unittest.TestCase):

    def setUp(self):
        self.m = mox.Mox()

    def tearDown(self):
        self.m.UnsetStubs()

    def test_json_parse(self):
        data = {"key1": ["val1[0]", "val1[1]"], "key2": "val2"}
        json_repr = '{ "key1": [ "val1[0]", "val1[1]" ], "key2": "val2" }'
        parsed = stacks.InstantiationData.json_parse(json_repr, 'foo')
        self.assertEqual(parsed, data)

    def test_json_parse_invalid(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          stacks.InstantiationData.json_parse,
                          'not json', 'Garbage')

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

    def test_template_url(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        url = 'http://example.com/template'
        body = {'template_url': url}
        data = stacks.InstantiationData(body)

        self.m.StubOutWithMock(data, '_load_template')
        data._load_template(url).AndReturn(template)
        self.m.ReplayAll()

        self.assertEqual(data.template(), template)
        self.m.VerifyAll()

    def test_template_priority(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        url = 'http://example.com/template'
        body = {'template': template, 'template_url': url}
        data = stacks.InstantiationData(body)

        self.m.StubOutWithMock(data, '_load_template')
        self.m.ReplayAll()

        self.assertEqual(data.template(), template)
        self.m.VerifyAll()

    def test_template_missing(self):
        template = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'not the template': template}
        data = stacks.InstantiationData(body)
        self.assertRaises(webob.exc.HTTPBadRequest, data.template)

    def test_user_params(self):
        params = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'parameters': params}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.user_params(), params)

    def test_user_params_missing(self):
        params = {'foo': 'bar', 'blarg': 'wibble'}
        body = {'not the parameters': params}
        data = stacks.InstantiationData(body)
        self.assertEqual(data.user_params(), {})

    def test_args(self):
        body = {
            'parameters': {},
            'stack_name': 'foo',
            'template': {},
            'template_url': 'http://example.com/',
            'timeout_mins': 60,
        }
        data = stacks.InstantiationData(body)
        self.assertEqual(data.args(), {'timeout_mins': 60})


@attr(tag=['unit', 'api-openstack-v1-stacks', 'StackController'])
@attr(speed='fast')
class StackControllerTest(unittest.TestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        self.maxDiff = None
        self.m = mox.Mox()

        config.register_engine_opts()
        cfg.CONF.set_default('engine_topic', 'engine')
        cfg.CONF.set_default('host', 'host')
        self.topic = '%s.%s' % (cfg.CONF.engine_topic, cfg.CONF.host)
        self.api_version = '1.0'
        self.tenant = 't'

        # Create WSGI controller instance
        class DummyConfig():
            bind_port = 8004
        cfgopts = DummyConfig()
        self.controller = stacks.StackController(options=cfgopts)

    def tearDown(self):
        self.m.UnsetStubs()

    def _create_context(self, user='api_test_user'):
        ctx = context.get_admin_context()
        self.m.StubOutWithMock(ctx, 'username')
        ctx.username = user
        self.m.StubOutWithMock(auth, 'authenticate')
        return ctx

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
        req.context = self._create_context()
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
        req.context = self._create_context()
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

    def test_index(self):
        req = self._get('/stacks')

        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        engine_resp = {
            u'stacks': [
                {
                    u'stack_identity': dict(identity),
                    u'updated_time': u'2012-07-09T09:13:11Z',
                    u'template_description': u'blah',
                    u'description': u'blah',
                    u'stack_status_reason': u'Stack successfully created',
                    u'creation_time': u'2012-07-09T09:12:45Z',
                    u'stack_name': identity.stack_name,
                    u'stack_status': u'CREATE_COMPLETE',
                    u'parameters': {},
                    u'outputs': [],
                    u'notification_topics': [],
                    u'capabilities': [],
                    u'disable_rollback': True,
                    u'timeout_mins': 60,
                }
            ]
        }
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'show_stack',
                  'args': {'stack_identity': None},
                           'version': self.api_version},
                 None).AndReturn(engine_resp)
        self.m.ReplayAll()

        result = self.controller.index(req, tenant_id=identity.tenant)

        expected = {
            'stacks': [
                {
                    'URL': self._url(identity),
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

    def test_index_rmt_aterr(self):
        req = self._get('/stacks')

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'show_stack',
                  'args': {'stack_identity': None},
                           'version': self.api_version},
                 None).AndRaise(rpc_common.RemoteError("AttributeError"))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req, tenant_id=self.tenant)
        self.m.VerifyAll()

    def test_index_rmt_interr(self):
        req = self._get('/stacks')

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'show_stack',
                  'args': {'stack_identity': None},
                           'version': self.api_version},
                 None).AndRaise(rpc_common.RemoteError("Exception"))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.index,
                          req, tenant_id=self.tenant)
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
                 {'method': 'create_stack',
                  'args': {'stack_name': identity.stack_name,
                           'template': template,
                           'params': parameters,
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndReturn(dict(identity))
        self.m.ReplayAll()

        try:
            response = self.controller.create(req,
                                              tenant_id=identity.tenant,
                                              body=body)
        except webob.exc.HTTPCreated as created:
            self.assertEqual(created.location, self._url(identity))
        else:
            self.fail('HTTPCreated not raised')
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

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'create_stack',
                  'args': {'stack_name': stack_name,
                           'template': template,
                           'params': parameters,
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndRaise(rpc_common.RemoteError("AttributeError"))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req, tenant_id=self.tenant, body=body)
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

        self.m.StubOutWithMock(rpc, 'call')
        engine_err = {'Description': 'Something went wrong'}
        rpc.call(req.context, self.topic,
                 {'method': 'create_stack',
                  'args': {'stack_name': stack_name,
                           'template': template,
                           'params': parameters,
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndReturn(engine_err)
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req, tenant_id=self.tenant, body=body)
        self.m.VerifyAll()

    def test_lookup(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '1')

        req = self._get('/stacks/%(stack_name)s' % identity)

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'identify_stack',
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

    def test_lookup_nonexistant(self):
        stack_name = 'wibble'

        req = self._get('/stacks/%(stack_name)s' % locals())

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'identify_stack',
                  'args': {'stack_name': stack_name},
                           'version': self.api_version},
                 None).AndRaise(rpc_common.RemoteError("AttributeError"))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound, self.controller.lookup,
                          req, tenant_id=self.tenant, stack_name=stack_name)
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

        engine_resp = {
            u'stacks': [
                {
                    u'stack_identity': dict(identity),
                    u'updated_time': u'2012-07-09T09:13:11Z',
                    u'parameters': parameters,
                    u'outputs': outputs,
                    u'stack_status_reason': u'Stack successfully created',
                    u'creation_time': u'2012-07-09T09:12:45Z',
                    u'stack_name': identity.stack_name,
                    u'notification_topics': [],
                    u'stack_status': u'CREATE_COMPLETE',
                    u'description': u'blah',
                    u'disable_rollback': True,
                    u'timeout_mins':60,
                    u'capabilities': [],
                }
            ]
        }
        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'show_stack',
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
                'URL': self._url(identity),
                u'updated_time': u'2012-07-09T09:13:11Z',
                u'parameters': json.dumps(parameters),
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

    def test_show_aterr(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')

        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'show_stack',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndRaise(rpc_common.RemoteError("AttributeError"))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id)
        self.m.VerifyAll()

    def test_get_template(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)
        template = {u'Foo': u'bar'}

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'get_template',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndReturn(template)
        self.m.ReplayAll()

        response = self.controller.template(req, tenant_id=identity.tenant,
                                            stack_name=identity.stack_name,
                                            stack_id=identity.stack_id)

        self.assertEqual(response, json.dumps(template))
        self.m.VerifyAll()

    def test_get_template_err_rpcerr(self):
        identity = identifier.HeatIdentifier(self.tenant, 'wordpress', '6')
        req = self._get('/stacks/%(stack_name)s/%(stack_id)s' % identity)
        template = {u'Foo': u'bar'}

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'get_template',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndRaise(rpc_common.RemoteError("AttributeError"))

        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.template,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id)
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
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        json.dumps(body))

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'update_stack',
                  'args': {'stack_identity': dict(identity),
                           'template': template,
                           'params': parameters,
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
                'timeout_mins': 30}

        req = self._put('/stacks/%(stack_name)s/%(stack_id)s' % identity,
                        json.dumps(body))

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'update_stack',
                  'args': {'stack_identity': dict(identity),
                           'template': template,
                           'params': parameters,
                           'args': {'timeout_mins': 30}},
                  'version': self.api_version},
                 None).AndRaise(rpc_common.RemoteError("AttributeError"))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id,
                          body=body)
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
                 {'method': 'delete_stack',
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

        self.m.StubOutWithMock(rpc, 'call')
        # Engine returns None when delete successful
        rpc.call(req.context, self.topic,
                 {'method': 'delete_stack',
                  'args': {'stack_identity': dict(identity)},
                  'version': self.api_version},
                 None).AndRaise(rpc_common.RemoteError("AttributeError"))
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete,
                          req, tenant_id=identity.tenant,
                          stack_name=identity.stack_name,
                          stack_id=identity.stack_id)
        self.m.VerifyAll()

    def test_validate_template(self):
        template = {u'Foo': u'bar'}
        json_template = json.dumps(template)
        body = {'template': template}

        req = self._post('/validate', json.dumps(body))

        engine_response = {
            u'ValidateTemplateResult': {
                u'Description': u'blah',
                u'Parameters': [
                    {
                        u'NoEcho': u'false',
                        u'ParameterKey': u'InstanceType',
                        u'Description': u'Instance type'
                    }
                ]

            }
        }

        self.m.StubOutWithMock(rpc, 'call')
        rpc.call(req.context, self.topic,
                 {'method': 'validate_template',
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
                 {'method': 'validate_template',
                  'args': {'template': template},
                  'version': self.api_version},
                 None).AndReturn({'Error': 'fubar'})
        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_template,
                          req, tenant_id=self.tenant, body=body)
        self.m.VerifyAll()


if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
