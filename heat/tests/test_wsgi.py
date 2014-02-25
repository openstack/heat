
# Copyright 2010-2011 OpenStack Foundation
# All Rights Reserved.
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
from oslo.config import cfg
import stubout
import webob

from heat.common import exception
from heat.common import wsgi
from heat.tests.common import HeatTestCase


class RequestTest(HeatTestCase):

    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        super(RequestTest, self).setUp()

    def test_content_type_missing(self):
        request = wsgi.Request.blank('/tests/123')
        self.assertRaises(exception.InvalidContentType,
                          request.get_content_type, ('application/xml'))

    def test_content_type_unsupported(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Content-Type"] = "text/html"
        self.assertRaises(exception.InvalidContentType,
                          request.get_content_type, ('application/xml'))

    def test_content_type_with_charset(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Content-Type"] = "application/json; charset=UTF-8"
        result = request.get_content_type(('application/json'))
        self.assertEqual("application/json", result)

    def test_content_type_from_accept_xml(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = "application/xml"
        result = request.best_match_content_type()
        self.assertEqual("application/json", result)

    def test_content_type_from_accept_json(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = "application/json"
        result = request.best_match_content_type()
        self.assertEqual("application/json", result)

    def test_content_type_from_accept_xml_json(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = "application/xml, application/json"
        result = request.best_match_content_type()
        self.assertEqual("application/json", result)

    def test_content_type_from_accept_json_xml_quality(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = ("application/json; q=0.3, "
                                     "application/xml; q=0.9")
        result = request.best_match_content_type()
        self.assertEqual("application/json", result)

    def test_content_type_accept_default(self):
        request = wsgi.Request.blank('/tests/123.unsupported')
        request.headers["Accept"] = "application/unsupported1"
        result = request.best_match_content_type()
        self.assertEqual("application/json", result)

    def test_best_match_language(self):
        # Test that we are actually invoking language negotiation by webop
        request = wsgi.Request.blank('/')
        accepted = 'unknown-lang'
        request.headers = {'Accept-Language': accepted}

        def fake_best_match(self, offers, default_match=None):
            # Best match on an unknown locale returns None
            return None

        self.stubs.SmartSet(request.accept_language,
                            'best_match', fake_best_match)

        self.assertIsNone(request.best_match_language())

        # If Accept-Language is missing or empty, match should be None
        request.headers = {'Accept-Language': ''}
        self.assertIsNone(request.best_match_language())
        request.headers.pop('Accept-Language')
        self.assertIsNone(request.best_match_language())


class ResourceTest(HeatTestCase):

    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        super(ResourceTest, self).setUp()

    def test_get_action_args(self):
        env = {
            'wsgiorg.routing_args': [
                None,
                {
                    'controller': None,
                    'format': None,
                    'action': 'update',
                    'id': 12,
                },
            ],
        }

        expected = {'action': 'update', 'id': 12}
        actual = wsgi.Resource(None, None, None).get_action_args(env)

        self.assertEqual(expected, actual)

    def test_get_action_args_invalid_index(self):
        env = {'wsgiorg.routing_args': []}
        expected = {}
        actual = wsgi.Resource(None, None, None).get_action_args(env)
        self.assertEqual(expected, actual)

    def test_get_action_args_del_controller_error(self):
        actions = {'format': None,
                   'action': 'update',
                   'id': 12}
        env = {'wsgiorg.routing_args': [None, actions]}
        expected = {'action': 'update', 'id': 12}
        actual = wsgi.Resource(None, None, None).get_action_args(env)
        self.assertEqual(expected, actual)

    def test_get_action_args_del_format_error(self):
        actions = {'action': 'update', 'id': 12}
        env = {'wsgiorg.routing_args': [None, actions]}
        expected = {'action': 'update', 'id': 12}
        actual = wsgi.Resource(None, None, None).get_action_args(env)
        self.assertEqual(expected, actual)

    def test_dispatch(self):
        class Controller(object):
            def index(self, shirt, pants=None):
                return (shirt, pants)

        resource = wsgi.Resource(None, None, None)
        actual = resource.dispatch(Controller(), 'index', 'on', pants='off')
        expected = ('on', 'off')
        self.assertEqual(expected, actual)

    def test_dispatch_default(self):
        class Controller(object):
            def default(self, shirt, pants=None):
                return (shirt, pants)

        resource = wsgi.Resource(None, None, None)
        actual = resource.dispatch(Controller(), 'index', 'on', pants='off')
        expected = ('on', 'off')
        self.assertEqual(expected, actual)

    def test_dispatch_no_default(self):
        class Controller(object):
            def show(self, shirt, pants=None):
                return (shirt, pants)

        resource = wsgi.Resource(None, None, None)
        self.assertRaises(AttributeError, resource.dispatch, Controller(),
                          'index', 'on', pants='off')

    def test_resource_call_error_handle(self):
        class Controller(object):
            def delete(self, req, identity):
                return (req, identity)

        actions = {'action': 'delete', 'id': 12, 'body': 'data'}
        env = {'wsgiorg.routing_args': [None, actions]}
        request = wsgi.Request.blank('/tests/123', environ=env)
        request.body = '{"foo" : "value"}'
        resource = wsgi.Resource(Controller(),
                                 wsgi.JSONRequestDeserializer(),
                                 None)
        # The Resource does not throw webob.HTTPExceptions, since they
        # would be considered responses by wsgi and the request flow would end,
        # instead they are wrapped so they can reach the fault application
        # where they are converted to a nice JSON/XML response
        e = self.assertRaises(exception.HTTPExceptionDisguise,
                              resource, request)
        self.assertIsInstance(e.exc, webob.exc.HTTPBadRequest)

    def test_resource_call_error_handle_localized(self):
        class Controller(object):
            def delete(self, req, identity):
                return (req, identity)

        actions = {'action': 'delete', 'id': 12, 'body': 'data'}
        env = {'wsgiorg.routing_args': [None, actions]}
        request = wsgi.Request.blank('/tests/123', environ=env)
        request.body = '{"foo" : "value"}'
        message_es = "No Encontrado"
        translated_ex = webob.exc.HTTPBadRequest(message_es)

        resource = wsgi.Resource(Controller(),
                                 wsgi.JSONRequestDeserializer(),
                                 None)

        def fake_translate_exception(ex, locale):
            return translated_ex

        self.stubs.SmartSet(wsgi,
                            'translate_exception', fake_translate_exception)

        e = self.assertRaises(exception.HTTPExceptionDisguise,
                              resource, request)
        self.assertEqual(message_es, str(e.exc))
        self.m.VerifyAll()


class ResourceExceptionHandlingTest(HeatTestCase):
    scenarios = [
        ('client_exceptions', dict(
            exception=exception.StackResourceLimitExceeded,
            exception_catch=exception.StackResourceLimitExceeded)),
        ('webob_bad_request', dict(
            exception=webob.exc.HTTPBadRequest,
            exception_catch=exception.HTTPExceptionDisguise)),
        ('webob_not_found', dict(
            exception=webob.exc.HTTPNotFound,
            exception_catch=exception.HTTPExceptionDisguise)),
    ]

    def test_resource_client_exceptions_dont_log_error(self):
        class Controller(object):
            def __init__(self, excpetion_to_raise):
                self.excpetion_to_raise = excpetion_to_raise

            def raise_exception(self, req, body):
                raise self.excpetion_to_raise()

        actions = {'action': 'raise_exception', 'body': 'data'}
        env = {'wsgiorg.routing_args': [None, actions]}
        request = wsgi.Request.blank('/tests/123', environ=env)
        request.body = '{"foo" : "value"}'
        resource = wsgi.Resource(Controller(self.exception),
                                 wsgi.JSONRequestDeserializer(),
                                 None)
        e = self.assertRaises(self.exception_catch, resource, request)
        e = e.exc if hasattr(e, 'exc') else e
        self.assertNotIn(str(e), self.logger.output)


class JSONResponseSerializerTest(HeatTestCase):

    def test_to_json(self):
        fixture = {"key": "value"}
        expected = '{"key": "value"}'
        actual = wsgi.JSONResponseSerializer().to_json(fixture)
        self.assertEqual(expected, actual)

    def test_to_json_with_date_format_value(self):
        fixture = {"date": datetime.datetime(1, 3, 8, 2)}
        expected = '{"date": "0001-03-08T02:00:00"}'
        actual = wsgi.JSONResponseSerializer().to_json(fixture)
        self.assertEqual(expected, actual)

    def test_to_json_with_more_deep_format(self):
        fixture = {"is_public": True, "name": [{"name1": "test"}]}
        expected = '{"is_public": true, "name": [{"name1": "test"}]}'
        actual = wsgi.JSONResponseSerializer().to_json(fixture)
        self.assertEqual(expected, actual)

    def test_default(self):
        fixture = {"key": "value"}
        response = webob.Response()
        wsgi.JSONResponseSerializer().default(response, fixture)
        self.assertEqual(200, response.status_int)
        content_types = filter(lambda h: h[0] == 'Content-Type',
                               response.headerlist)
        self.assertEqual(1, len(content_types))
        self.assertEqual('application/json', response.content_type)
        self.assertEqual('{"key": "value"}', response.body)


class JSONRequestDeserializerTest(HeatTestCase):

    def test_has_body_no_content_length(self):
        request = wsgi.Request.blank('/')
        request.method = 'POST'
        request.body = 'asdf'
        request.headers.pop('Content-Length')
        request.headers['Content-Type'] = 'application/json'
        self.assertFalse(wsgi.JSONRequestDeserializer().has_body(request))

    def test_has_body_zero_content_length(self):
        request = wsgi.Request.blank('/')
        request.method = 'POST'
        request.body = 'asdf'
        request.headers['Content-Length'] = 0
        request.headers['Content-Type'] = 'application/json'
        self.assertFalse(wsgi.JSONRequestDeserializer().has_body(request))

    def test_has_body_has_content_length_no_content_type(self):
        request = wsgi.Request.blank('/')
        request.method = 'POST'
        request.body = '{"key": "value"}'
        self.assertIn('Content-Length', request.headers)
        self.assertTrue(wsgi.JSONRequestDeserializer().has_body(request))

    def test_has_body_has_content_length_plain_content_type(self):
        request = wsgi.Request.blank('/')
        request.method = 'POST'
        request.body = '{"key": "value"}'
        self.assertIn('Content-Length', request.headers)
        request.headers['Content-Type'] = 'text/plain'
        self.assertTrue(wsgi.JSONRequestDeserializer().has_body(request))

    def test_has_body_has_content_type_malformed(self):
        request = wsgi.Request.blank('/')
        request.method = 'POST'
        request.body = 'asdf'
        self.assertIn('Content-Length', request.headers)
        request.headers['Content-Type'] = 'application/json'
        self.assertFalse(wsgi.JSONRequestDeserializer().has_body(request))

    def test_has_body_has_content_type(self):
        request = wsgi.Request.blank('/')
        request.method = 'POST'
        request.body = '{"key": "value"}'
        self.assertIn('Content-Length', request.headers)
        request.headers['Content-Type'] = 'application/json'
        self.assertTrue(wsgi.JSONRequestDeserializer().has_body(request))

    def test_has_body_has_wrong_content_type(self):
        request = wsgi.Request.blank('/')
        request.method = 'POST'
        request.body = '{"key": "value"}'
        self.assertIn('Content-Length', request.headers)
        request.headers['Content-Type'] = 'application/xml'
        self.assertFalse(wsgi.JSONRequestDeserializer().has_body(request))

    def test_has_body_has_aws_content_type_only(self):
        request = wsgi.Request.blank('/?ContentType=JSON')
        request.method = 'GET'
        request.body = '{"key": "value"}'
        self.assertIn('Content-Length', request.headers)
        self.assertTrue(wsgi.JSONRequestDeserializer().has_body(request))

    def test_has_body_respect_aws_content_type(self):
        request = wsgi.Request.blank('/?ContentType=JSON')
        request.method = 'GET'
        request.body = '{"key": "value"}'
        self.assertIn('Content-Length', request.headers)
        request.headers['Content-Type'] = 'application/xml'
        self.assertTrue(wsgi.JSONRequestDeserializer().has_body(request))

    def test_has_body_content_type_with_get(self):
        request = wsgi.Request.blank('/')
        request.method = 'GET'
        request.body = '{"key": "value"}'
        self.assertIn('Content-Length', request.headers)
        self.assertTrue(wsgi.JSONRequestDeserializer().has_body(request))

    def test_no_body_no_content_length(self):
        request = wsgi.Request.blank('/')
        self.assertFalse(wsgi.JSONRequestDeserializer().has_body(request))

    def test_from_json(self):
        fixture = '{"key": "value"}'
        expected = {"key": "value"}
        actual = wsgi.JSONRequestDeserializer().from_json(fixture)
        self.assertEqual(expected, actual)

    def test_from_json_malformed(self):
        fixture = 'kjasdklfjsklajf'
        self.assertRaises(webob.exc.HTTPBadRequest,
                          wsgi.JSONRequestDeserializer().from_json, fixture)

    def test_default_no_body(self):
        request = wsgi.Request.blank('/')
        actual = wsgi.JSONRequestDeserializer().default(request)
        expected = {}
        self.assertEqual(expected, actual)

    def test_default_with_body(self):
        request = wsgi.Request.blank('/')
        request.method = 'POST'
        request.body = '{"key": "value"}'
        actual = wsgi.JSONRequestDeserializer().default(request)
        expected = {"body": {"key": "value"}}
        self.assertEqual(expected, actual)

    def test_default_with_get_with_body(self):
        request = wsgi.Request.blank('/')
        request.method = 'GET'
        request.body = '{"key": "value"}'
        actual = wsgi.JSONRequestDeserializer().default(request)
        expected = {"body": {"key": "value"}}
        self.assertEqual(expected, actual)

    def test_default_with_get_with_body_with_aws(self):
        request = wsgi.Request.blank('/?ContentType=JSON')
        request.method = 'GET'
        request.body = '{"key": "value"}'
        actual = wsgi.JSONRequestDeserializer().default(request)
        expected = {"body": {"key": "value"}}
        self.assertEqual(expected, actual)

    def test_from_json_exceeds_max_json_mb(self):
        cfg.CONF.set_override('max_json_body_size', 10)
        body = json.dumps(['a'] * cfg.CONF.max_json_body_size)
        self.assertTrue(len(body) > cfg.CONF.max_json_body_size)
        error = self.assertRaises(exception.RequestLimitExceeded,
                                  wsgi.JSONRequestDeserializer().from_json,
                                  body)
        msg = 'Request limit exceeded: JSON body size ' + \
              '(%s bytes) exceeds maximum allowed size (%s bytes).' % \
              (len(body), cfg.CONF.max_json_body_size)
        self.assertEqual(msg, str(error))
