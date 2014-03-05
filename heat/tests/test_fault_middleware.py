
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

from heat.common import exception as heat_exc
from heat.openstack.common.rpc import common as rpc_common
from heat.tests.common import HeatTestCase
from oslo.config import cfg

import heat.api.middleware.fault as fault


class StackNotFoundChild(heat_exc.StackNotFound):
    pass


class FaultMiddlewareTest(HeatTestCase):

    def test_openstack_exception_with_kwargs(self):
        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(heat_exc.StackNotFound(stack_name='a'))
        expected = {'code': 404,
                    'error': {'message': 'The Stack (a) could not be found.',
                              'traceback': None,
                              'type': 'StackNotFound'},
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
        error = heat_exc.StackNotFound(stack_name='a')
        exc_info = (type(error), error, None)
        serialized = rpc_common.serialize_remote_exception(exc_info)
        remote_error = rpc_common.deserialize_remote_exception(cfg.CONF,
                                                               serialized)
        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(remote_error)
        expected_message, expected_traceback = str(remote_error).split('\n', 1)
        expected = {'code': 404,
                    'error': {'message': expected_message,
                              'traceback': expected_traceback,
                              'type': 'StackNotFound'},
                    'explanation': 'The resource could not be found.',
                    'title': 'Not Found'}
        self.assertEqual(expected, msg)

    def test_should_not_ignore_parent_classes(self):
        wrapper = fault.FaultWrapper(None)

        msg = wrapper._error(StackNotFoundChild(stack_name='a'))
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
                    'error': {'message': u'A message',
                              'traceback': None,
                              'type': 'NotMappedException'},
                    'explanation': ('The server has either erred or is '
                                    'incapable of performing the requested '
                                    'operation.'),
                    'title': 'Internal Server Error'}
        self.assertEqual(expected, msg)

    def test_should_not_ignore_parent_classes_even_for_remote_ones(self):
        # We want tracebacks
        cfg.CONF.set_override('debug', True)
        cfg.CONF.set_override('allowed_rpc_exception_modules',
                              ['heat.tests.test_fault_middleware'])

        error = StackNotFoundChild(stack_name='a')
        exc_info = (type(error), error, None)
        serialized = rpc_common.serialize_remote_exception(exc_info)
        remote_error = rpc_common.deserialize_remote_exception(cfg.CONF,
                                                               serialized)

        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(remote_error)
        expected_message, expected_traceback = str(remote_error).split('\n', 1)
        expected = {'code': 404,
                    'error': {'message': expected_message,
                              'traceback': expected_traceback,
                              'type': 'StackNotFoundChild'},
                    'explanation': 'The resource could not be found.',
                    'title': 'Not Found'}
        self.assertEqual(expected, msg)
