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

import inspect
import re

from oslo_config import cfg
from oslo_log import log
from oslo_messaging._drivers import common as rpc_common
import six
import webob

import heat.api.middleware.fault as fault
from heat.common import exception as heat_exc
from heat.common.i18n import _
from heat.tests import common


class StackNotFoundChild(heat_exc.EntityNotFound):
    pass


class ErrorWithNewline(webob.exc.HTTPBadRequest):
    pass


class FaultMiddlewareTest(common.HeatTestCase):
    def setUp(self):
        super(FaultMiddlewareTest, self).setUp()
        log.register_options(cfg.CONF)

    def test_disguised_http_exception_with_newline(self):
        wrapper = fault.FaultWrapper(None)
        newline_error = ErrorWithNewline('Error with \n newline')
        msg = wrapper._error(heat_exc.HTTPExceptionDisguise(newline_error))
        expected = {'code': 400,
                    'error': {'message': 'Error with \n newline',
                              'traceback': None,
                              'type': 'ErrorWithNewline'},
                    'explanation': ('The server could not comply with the '
                                    'request since it is either malformed '
                                    'or otherwise incorrect.'),
                    'title': 'Bad Request'}
        self.assertEqual(expected, msg)

    def test_http_exception_with_traceback(self):
        wrapper = fault.FaultWrapper(None)
        newline_error = ErrorWithNewline(
            'Error with \n newline\nTraceback (most recent call last):\nFoo')
        msg = wrapper._error(heat_exc.HTTPExceptionDisguise(newline_error))
        expected = {'code': 400,
                    'error': {'message': 'Error with \n newline',
                              'traceback': None,
                              'type': 'ErrorWithNewline'},
                    'explanation': ('The server could not comply with the '
                                    'request since it is either malformed '
                                    'or otherwise incorrect.'),
                    'title': 'Bad Request'}
        self.assertEqual(expected, msg)

    def test_openstack_exception_with_kwargs(self):
        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(heat_exc.EntityNotFound(entity='Stack', name='a'))
        expected = {'code': 404,
                    'error': {'message': 'The Stack (a) could not be found.',
                              'traceback': None,
                              'type': 'EntityNotFound'},
                    'explanation': 'The resource could not be found.',
                    'title': 'Not Found'}
        self.assertEqual(expected, msg)

    def test_openstack_exception_without_kwargs(self):
        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(heat_exc.StackResourceLimitExceeded())
        expected = {'code': 500,
                    'error': {'message': 'Maximum resources '
                                         'per stack exceeded.',
                              'traceback': None,
                              'type': 'StackResourceLimitExceeded'},
                    'explanation': 'The server has either erred or is '
                                   'incapable of performing the requested '
                                   'operation.',
                    'title': 'Internal Server Error'}
        self.assertEqual(expected, msg)

    def test_exception_with_non_ascii_chars(self):
        # We set debug to true to test the code path for serializing traces too
        cfg.CONF.set_override('debug', True)
        msg = u'Error with non-ascii chars \x80'

        class TestException(heat_exc.HeatException):
            msg_fmt = msg

        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(TestException())
        expected = {'code': 500,
                    'error': {'message': u'Error with non-ascii chars \x80',
                              'traceback': 'None\n',
                              'type': 'TestException'},
                    'explanation': ('The server has either erred or is '
                                    'incapable of performing the requested '
                                    'operation.'),
                    'title': 'Internal Server Error'}
        self.assertEqual(expected, msg)

    def test_remote_exception(self):
        # We want tracebacks
        cfg.CONF.set_override('debug', True)
        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        exc_info = (type(error), error, None)
        serialized = rpc_common.serialize_remote_exception(exc_info)
        remote_error = rpc_common.deserialize_remote_exception(
            serialized, ["heat.common.exception"])
        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(remote_error)
        expected_message, expected_traceback = six.text_type(
            remote_error).split('\n', 1)
        expected = {'code': 404,
                    'error': {'message': expected_message,
                              'traceback': expected_traceback,
                              'type': 'EntityNotFound'},
                    'explanation': 'The resource could not be found.',
                    'title': 'Not Found'}
        self.assertEqual(expected, msg)

    def remote_exception_helper(self, name, error):
        if six.PY3:
            error.args = ()
        exc_info = (type(error), error, None)

        serialized = rpc_common.serialize_remote_exception(exc_info)
        remote_error = rpc_common.deserialize_remote_exception(
            serialized, name)
        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(remote_error)
        expected = {'code': 500,
                    'error': {'traceback': None,
                              'type': 'RemoteError'},
                    'explanation': msg['explanation'],
                    'title': 'Internal Server Error'}
        self.assertEqual(expected, msg)

    def test_all_remote_exceptions(self):
        for name, obj in inspect.getmembers(
                heat_exc, lambda x: inspect.isclass(x) and issubclass(
                    x, heat_exc.HeatException)):

            if '__init__' in obj.__dict__:
                if obj == heat_exc.HeatException:  # manually ignore baseclass
                    continue
                elif obj == heat_exc.Error:
                    error = obj('Error')
                elif obj == heat_exc.NotFound:
                    error = obj()
                elif obj == heat_exc.ResourceFailure:
                    exc = heat_exc.Error(_('Error'))
                    error = obj(exc, None, 'CREATE')
                elif obj == heat_exc.ResourcePropertyConflict:
                    error = obj('%s' % 'a test prop')
                else:
                    continue
                self.remote_exception_helper(name, error)
                continue

            if hasattr(obj, 'msg_fmt'):
                kwargs = {}
                spec_names = re.findall(r'%\((\w+)\)([cdeEfFgGinorsxX])',
                                        obj.msg_fmt)

                for key, convtype in spec_names:
                    if convtype == 'r' or convtype == 's':
                        kwargs[key] = '"' + key + '"'
                    else:
                        # this is highly unlikely
                        raise Exception("test needs additional conversion"
                                        " type added due to %s exception"
                                        " using '%c' specifier" % (obj,
                                                                   convtype))

                error = obj(**kwargs)
                self.remote_exception_helper(name, error)

    def test_should_not_ignore_parent_classes(self):
        wrapper = fault.FaultWrapper(None)

        msg = wrapper._error(StackNotFoundChild(entity='Stack', name='a'))
        expected = {'code': 404,
                    'error': {'message': 'The Stack (a) could not be found.',
                              'traceback': None,
                              'type': 'StackNotFoundChild'},
                    'explanation': 'The resource could not be found.',
                    'title': 'Not Found'}
        self.assertEqual(expected, msg)

    def test_internal_server_error_when_exeption_and_parents_not_mapped(self):
        wrapper = fault.FaultWrapper(None)

        class NotMappedException(Exception):
            pass

        msg = wrapper._error(NotMappedException('A message'))
        expected = {'code': 500,
                    'error': {'traceback': None,
                              'type': 'NotMappedException'},
                    'explanation': ('The server has either erred or is '
                                    'incapable of performing the requested '
                                    'operation.'),
                    'title': 'Internal Server Error'}
        self.assertEqual(expected, msg)

    def test_should_not_ignore_parent_classes_even_for_remote_ones(self):
        # We want tracebacks
        cfg.CONF.set_override('debug', True)

        error = StackNotFoundChild(entity='Stack', name='a')
        exc_info = (type(error), error, None)
        serialized = rpc_common.serialize_remote_exception(exc_info)
        remote_error = rpc_common.deserialize_remote_exception(
            serialized, ["heat.tests.test_fault_middleware"])

        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(remote_error)
        expected_message, expected_traceback = six.text_type(
            remote_error).split('\n', 1)
        expected = {'code': 404,
                    'error': {'message': expected_message,
                              'traceback': expected_traceback,
                              'type': 'StackNotFoundChild'},
                    'explanation': 'The resource could not be found.',
                    'title': 'Not Found'}
        self.assertEqual(expected, msg)
