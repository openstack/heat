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

from heat.common import exception as heat_exc
from heat.openstack.common.rpc import common as rpc_common
from heat.tests.common import HeatTestCase
from oslo.config import cfg

import heat.api.middleware.fault as fault


class FaultMiddlewareTest(HeatTestCase):

    def test_openstack_exception_with_kwargs(self):
        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(heat_exc.StackNotFound(stack_name='a'))
        expected = {'code': 404,
                    'error': {'message': 'The Stack (a) could not be found.',
                              'traceback': 'None\n',
                              'type': 'StackNotFound'},
                    'explanation': 'The resource could not be found.',
                    'title': 'Not Found'}
        self.assertEqual(msg, expected)

    def test_openstack_exception_without_kwargs(self):
        wrapper = fault.FaultWrapper(None)
        msg = wrapper._error(heat_exc.NoServiceEndpoint())
        expected = {'code': 500,
                    'error': {'message': 'Response from Keystone does '
                                         'not contain a Heat endpoint.',
                              'traceback': 'None\n',
                              'type': 'NoServiceEndpoint'},
                    'explanation': 'The server has either erred or is '
                                   'incapable of performing the requested '
                                   'operation.',
                    'title': 'Internal Server Error'}
        self.assertEqual(msg, expected)

    def test_remote_exception(self):
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
        self.assertEqual(msg, expected)
