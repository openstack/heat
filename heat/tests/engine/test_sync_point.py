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

from unittest import mock

from oslo_db import exception

from heat.engine import stack as parser
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

        sender = parser.ConvergenceNode(4, True)
        resource_key = parser.ConvergenceNode(resource.id, True)
        mock_callback = mock.Mock()
        sync_point.sync(ctx, resource.id, stack.current_traversal, True,
                        mock_callback, set(graph[resource_key]),
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

        sender = parser.ConvergenceNode(3, True)
        resource_key = parser.ConvergenceNode(resource.id, True)
        mock_callback = mock.Mock()
        sync_point.sync(ctx, resource.id, stack.current_traversal, True,
                        mock_callback, set(graph[resource_key]),
                        {sender: None})
        updated_sync_point = sync_point.get(ctx, resource.id,
                                            stack.current_traversal, True)
        input_data = sync_point.deserialize_input_data(
            updated_sync_point.input_data)
        self.assertEqual({sender: None}, input_data)
        self.assertTrue(mock_callback.called)

    def test_serialize_input_data(self):
        res = sync_point.serialize_input_data({(3, 8): None})
        self.assertEqual({'input_data': {'tuple:(3, 8)': None}}, res)

    @mock.patch('heat.engine.sync_point.update_input_data', return_value=None)
    @mock.patch('time.sleep', side_effect=exception.DBError)
    def sync_with_sleep(self, ctx, stack, mock_sleep_time, mock_uid):
        resource = stack['C']
        graph = stack.convergence_dependencies.graph()

        mock_callback = mock.Mock()
        sender = parser.ConvergenceNode(3, True)
        resource_key = parser.ConvergenceNode(resource.id, True)
        self.assertRaises(exception.DBError, sync_point.sync, ctx, resource.id,
                          stack.current_traversal, True, mock_callback,
                          set(graph[resource_key]), {sender: None})
        return mock_sleep_time

    def test_sync_with_time_throttle(self):
        ctx = utils.dummy_context()
        stack = tools.get_stack('test_stack', utils.dummy_context(),
                                template=tools.string_template_five,
                                convergence=True)
        stack.converge_stack(stack.t, action=stack.CREATE)
        mock_sleep_time = self.sync_with_sleep(ctx, stack)
        self.assertTrue(mock_sleep_time.called)

    def test_serialize_extra_data(self):
        """Test serialization of extra_data."""
        extra = {'resource_failures': {'A': 'error'}}
        res = sync_point.serialize_extra_data(extra)
        self.assertEqual({'extra_data': extra}, res)

    def test_deserialize_extra_data(self):
        """Test deserialization of extra_data."""
        db_data = {'extra_data': {'resource_failures': {'A': 'error'}}}
        res = sync_point.deserialize_extra_data(db_data)
        self.assertEqual({'resource_failures': {'A': 'error'}}, res)

    def test_deserialize_extra_data_empty(self):
        """Test deserialization of empty extra_data."""
        res = sync_point.deserialize_extra_data({})
        self.assertEqual({}, res)

    def test_update_sync_point_with_resource_failures(self):
        """Test update_sync_point stores resource failures."""
        ctx = utils.dummy_context()
        stack = tools.get_stack('test_stack', utils.dummy_context(),
                                template=tools.string_template_five,
                                convergence=True)
        stack.converge_stack(stack.t, action=stack.CREATE)
        resource = stack['A']

        predecessors = set()
        new_failures = {'resource_B': 'Check failed'}

        result = sync_point.update_sync_point(
            ctx, resource.id, stack.current_traversal, True,
            predecessors, new_data={}, new_resource_failures=new_failures)

        self.assertIsNotNone(result)
        input_data, rsrc_failures, skip_propagate = result
        self.assertEqual({'resource_B': 'Check failed'}, rsrc_failures)

    def test_update_sync_point_with_skip_flag(self):
        """Test update_sync_point stores skip_propagate flag."""
        ctx = utils.dummy_context()
        stack = tools.get_stack('test_stack', utils.dummy_context(),
                                template=tools.string_template_five,
                                convergence=True)
        stack.converge_stack(stack.t, action=stack.CREATE)
        resource = stack['A']

        predecessors = set()

        result = sync_point.update_sync_point(
            ctx, resource.id, stack.current_traversal, True,
            predecessors, new_data={}, is_skip=True)

        self.assertIsNotNone(result)
        input_data, rsrc_failures, skip_propagate = result
        self.assertTrue(skip_propagate)

    def test_sync_propagates_failures_and_skip(self):
        """Test sync passes failures and skip_propagate to callback."""
        ctx = utils.dummy_context()
        stack = tools.get_stack('test_stack', utils.dummy_context(),
                                template=tools.string_template_five,
                                convergence=True)
        stack.converge_stack(stack.t, action=stack.CREATE)
        resource = stack['A']  # A has no predecessors (leaf)
        graph = stack.convergence_dependencies.graph()

        sender = parser.ConvergenceNode(3, True)
        resource_key = parser.ConvergenceNode(resource.id, True)
        captured_args = {}

        def callback(entity_id, data, rsrc_failures, skip_propagate):
            captured_args['entity_id'] = entity_id
            captured_args['rsrc_failures'] = rsrc_failures
            captured_args['skip_propagate'] = skip_propagate

        sync_point.sync(ctx, resource.id, stack.current_traversal, True,
                        callback, set(graph[resource_key]),
                        {sender: None},
                        new_resource_failures={'B': 'failed'},
                        is_skip=True)

        # Callback should be called since A has no predecessors
        self.assertEqual(resource.id, captured_args['entity_id'])
        self.assertEqual({'B': 'failed'}, captured_args['rsrc_failures'])
        self.assertTrue(captured_args['skip_propagate'])
