#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
from oslo_db import exception

from heat.engine import sync_point
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import utils


class SyncPointTestCase(common.HeatTestCase):
    def setUp(self):
        super(SyncPointTestCase, self).setUp()
        self.dummy_event = mock.MagicMock()
        self.dummy_event.ready.return_value = False

    def test_sync_waiting(self):
        ctx = utils.dummy_context()
        stack = tools.get_stack('test_stack', utils.dummy_context(),
                                template=tools.string_template_five,
                                convergence=True)
        stack.converge_stack(stack.t, action=stack.CREATE)
        resource = stack['C']
        graph = stack.convergence_dependencies.graph()

        sender = (4, True)
        mock_callback = mock.Mock()
        sync_point.sync(ctx, resource.id, stack.current_traversal, True,
                        mock_callback, set(graph[(resource.id, True)]),
                        {sender: None})
        updated_sync_point = sync_point.get(ctx, resource.id,
                                            stack.current_traversal, True)
        input_data = sync_point.deserialize_input_data(
            updated_sync_point.input_data)
        self.assertEqual({sender: None}, input_data)
        self.assertFalse(mock_callback.called)

    def test_sync_non_waiting(self):
        ctx = utils.dummy_context()
        stack = tools.get_stack('test_stack', utils.dummy_context(),
                                template=tools.string_template_five,
                                convergence=True)
        stack.converge_stack(stack.t, action=stack.CREATE)
        resource = stack['A']
        graph = stack.convergence_dependencies.graph()

        sender = (3, True)
        mock_callback = mock.Mock()
        sync_point.sync(ctx, resource.id, stack.current_traversal, True,
                        mock_callback, set(graph[(resource.id, True)]),
                        {sender: None})
        updated_sync_point = sync_point.get(ctx, resource.id,
                                            stack.current_traversal, True)
        input_data = sync_point.deserialize_input_data(
            updated_sync_point.input_data)
        self.assertEqual({sender: None}, input_data)
        self.assertTrue(mock_callback.called)

    def test_serialize_input_data(self):
        res = sync_point.serialize_input_data({(3, 8): None})
        self.assertEqual({'input_data': {u'tuple:(3, 8)': None}}, res)

    @mock.patch('heat.engine.sync_point.update_input_data', return_value=None)
    @mock.patch('time.sleep', side_effect=exception.DBError)
    def sync_with_sleep(self, ctx, stack, mock_sleep_time, mock_uid):
        resource = stack['C']
        graph = stack.convergence_dependencies.graph()

        mock_callback = mock.Mock()
        sender = (3, True)
        self.assertRaises(exception.DBError, sync_point.sync, ctx, resource.id,
                          stack.current_traversal, True, mock_callback,
                          set(graph[(resource.id, True)]), {sender: None})
        return mock_sleep_time

    def test_sync_with_time_throttle(self):
        ctx = utils.dummy_context()
        stack = tools.get_stack('test_stack', utils.dummy_context(),
                                template=tools.string_template_five,
                                convergence=True)
        stack.converge_stack(stack.t, action=stack.CREATE)
        mock_sleep_time = self.sync_with_sleep(ctx, stack)
        self.assertTrue(mock_sleep_time.called)
