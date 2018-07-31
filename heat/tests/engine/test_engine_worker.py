# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
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

from heat.db.sqlalchemy import api as db_api
from heat.engine import check_resource
from heat.engine import stack as parser
from heat.engine import template as templatem
from heat.engine import worker
from heat.objects import stack as stack_objects
from heat.rpc import worker_client as wc
from heat.tests import common
from heat.tests import utils


class WorkerServiceTest(common.HeatTestCase):
    def test_make_sure_rpc_version(self):
        self.assertEqual(
            '1.4',
            worker.WorkerService.RPC_API_VERSION,
            ('RPC version is changed, please update this test to new version '
             'and make sure additional test cases are added for RPC APIs '
             'added in new version'))

    @mock.patch('heat.common.messaging.get_rpc_server',
                return_value=mock.Mock())
    @mock.patch('oslo_messaging.Target',
                return_value=mock.Mock())
    @mock.patch('heat.rpc.worker_client.WorkerClient',
                return_value=mock.Mock())
    def test_service_start(self,
                           rpc_client_class,
                           target_class,
                           rpc_server_method
                           ):

        self.worker = worker.WorkerService('host-1',
                                           'topic-1',
                                           'engine_id',
                                           mock.Mock())
        self.worker.start()

        # Make sure target is called with proper parameters
        target_class.assert_called_once_with(
            version=worker.WorkerService.RPC_API_VERSION,
            server=self.worker.engine_id,
            topic=self.worker.topic)

        # Make sure rpc server creation with proper target
        # and WorkerService is initialized with it
        target = target_class.return_value
        rpc_server_method.assert_called_once_with(target,
                                                  self.worker)
        rpc_server = rpc_server_method.return_value
        self.assertEqual(rpc_server,
                         self.worker._rpc_server,
                         "Failed to create RPC server")

        # Make sure rpc server is started.
        rpc_server.start.assert_called_once_with()

        # Make sure rpc client is created and initialized in WorkerService
        rpc_client = rpc_client_class.return_value
        rpc_client_class.assert_called_once_with()
        self.assertEqual(rpc_client,
                         self.worker._rpc_client,
                         "Failed to create RPC client")

    def test_service_stop(self):
        self.worker = worker.WorkerService('host-1',
                                           'topic-1',
                                           'engine_id',
                                           mock.Mock())
        with mock.patch.object(self.worker, '_rpc_server') as mock_rpc_server:
            self.worker.stop()
            mock_rpc_server.stop.assert_called_once_with()
            mock_rpc_server.wait.assert_called_once_with()

    @mock.patch.object(check_resource, 'load_resource')
    @mock.patch.object(check_resource.CheckResource, 'check')
    def test_check_resource_adds_and_removes_msg_queue(self,
                                                       mock_check,
                                                       mock_load_resource):
        mock_tgm = mock.MagicMock()
        mock_tgm.add_msg_queue = mock.Mock(return_value=None)
        mock_tgm.remove_msg_queue = mock.Mock(return_value=None)
        self.worker = worker.WorkerService('host-1',
                                           'topic-1',
                                           'engine_id',
                                           mock_tgm)
        ctx = utils.dummy_context()
        current_traversal = 'something'
        fake_res = mock.MagicMock()
        fake_res.current_traversal = current_traversal
        mock_load_resource.return_value = (fake_res, fake_res, fake_res)
        self.worker.check_resource(ctx, mock.Mock(), current_traversal,
                                   {}, mock.Mock(), mock.Mock())
        self.assertTrue(mock_tgm.add_msg_queue.called)
        self.assertTrue(mock_tgm.remove_msg_queue.called)

    @mock.patch.object(check_resource, 'load_resource')
    @mock.patch.object(check_resource.CheckResource, 'check')
    def test_check_resource_adds_and_removes_msg_queue_on_exception(
            self, mock_check, mock_load_resource):
        # even if the check fails; the message should be removed
        mock_tgm = mock.MagicMock()
        mock_tgm.add_msg_queue = mock.Mock(return_value=None)
        mock_tgm.remove_msg_queue = mock.Mock(return_value=None)
        self.worker = worker.WorkerService('host-1',
                                           'topic-1',
                                           'engine_id',
                                           mock_tgm)
        ctx = utils.dummy_context()
        current_traversal = 'something'
        fake_res = mock.MagicMock()
        fake_res.current_traversal = current_traversal
        mock_load_resource.return_value = (fake_res, fake_res, fake_res)
        mock_check.side_effect = BaseException
        self.assertRaises(BaseException, self.worker.check_resource,
                          ctx, mock.Mock(), current_traversal, {},
                          mock.Mock(), mock.Mock())
        self.assertTrue(mock_tgm.add_msg_queue.called)
        # ensure remove is also called
        self.assertTrue(mock_tgm.remove_msg_queue.called)

    @mock.patch.object(worker, '_wait_for_cancellation')
    @mock.patch.object(worker, '_cancel_check_resource')
    @mock.patch.object(wc.WorkerClient, 'cancel_check_resource')
    @mock.patch.object(db_api, 'engine_get_all_locked_by_stack')
    def test_cancel_workers_when_no_resource_found(self, mock_get_locked,
                                                   mock_ccr, mock_wccr,
                                                   mock_wc):
        mock_tgm = mock.Mock()
        _worker = worker.WorkerService('host-1', 'topic-1', 'engine-001',
                                       mock_tgm)
        stack = mock.MagicMock()
        stack.id = 'stack_id'
        mock_get_locked.return_value = []
        worker._cancel_workers(stack, mock_tgm, 'engine-001',
                               _worker._rpc_client)
        self.assertFalse(mock_wccr.called)
        self.assertFalse(mock_ccr.called)

    @mock.patch.object(worker, '_wait_for_cancellation')
    @mock.patch.object(worker, '_cancel_check_resource')
    @mock.patch.object(wc.WorkerClient, 'cancel_check_resource')
    @mock.patch.object(db_api, 'engine_get_all_locked_by_stack')
    def test_cancel_workers_with_resources_found(self, mock_get_locked,
                                                 mock_ccr, mock_wccr,
                                                 mock_wc):
        mock_tgm = mock.Mock()
        _worker = worker.WorkerService('host-1', 'topic-1', 'engine-001',
                                       mock_tgm)
        stack = mock.MagicMock()
        stack.id = 'stack_id'
        mock_get_locked.return_value = ['engine-001', 'engine-007',
                                        'engine-008']
        worker._cancel_workers(stack, mock_tgm, 'engine-001',
                               _worker._rpc_client)
        mock_wccr.assert_called_once_with(stack.id, 'engine-001', mock_tgm)
        self.assertEqual(2, mock_ccr.call_count)
        calls = [mock.call(stack.context, stack.id, 'engine-007'),
                 mock.call(stack.context, stack.id, 'engine-008')]
        mock_ccr.assert_has_calls(calls, any_order=True)
        self.assertTrue(mock_wc.called)

    @mock.patch.object(worker, '_stop_traversal')
    def test_stop_traversal_stops_nested_stack(self, mock_st):
        mock_tgm = mock.Mock()
        ctx = utils.dummy_context()
        tmpl = templatem.Template.create_empty_template()
        stack1 = parser.Stack(ctx, 'stack1', tmpl,
                              current_traversal='123')
        stack1.store()
        stack2 = parser.Stack(ctx, 'stack2', tmpl,
                              owner_id=stack1.id, current_traversal='456')
        stack2.store()
        _worker = worker.WorkerService('host-1', 'topic-1', 'engine-001',
                                       mock_tgm)
        _worker.stop_traversal(stack1)
        self.assertEqual(2, mock_st.call_count)
        call1, call2 = mock_st.call_args_list
        call_args1, call_args2 = call1[0][0], call2[0][0]
        self.assertEqual('stack1', call_args1.name)
        self.assertEqual('stack2', call_args2.name)

    @mock.patch.object(worker, '_cancel_workers')
    @mock.patch.object(worker.WorkerService, 'stop_traversal')
    def test_stop_all_workers_when_stack_in_progress(self, mock_st, mock_cw):
        mock_tgm = mock.Mock()
        _worker = worker.WorkerService('host-1', 'topic-1', 'engine-001',
                                       mock_tgm)
        stack = mock.MagicMock()
        stack.IN_PROGRESS = 'IN_PROGRESS'
        stack.status = stack.IN_PROGRESS
        stack.id = 'stack_id'
        stack.rollback = mock.MagicMock()
        _worker.stop_all_workers(stack)
        mock_st.assert_not_called()
        mock_cw.assert_called_once_with(stack, mock_tgm, 'engine-001',
                                        _worker._rpc_client)
        self.assertFalse(stack.rollback.called)

    @mock.patch.object(worker, '_cancel_workers')
    @mock.patch.object(worker.WorkerService, 'stop_traversal')
    def test_stop_all_workers_when_stack_not_in_progress(self, mock_st,
                                                         mock_cw):
        mock_tgm = mock.Mock()
        _worker = worker.WorkerService('host-1', 'topic-1', 'engine-001',
                                       mock_tgm)
        stack = mock.MagicMock()
        stack.FAILED = 'FAILED'
        stack.status = stack.FAILED
        stack.id = 'stack_id'
        stack.rollback = mock.MagicMock()
        _worker.stop_all_workers(stack)
        self.assertFalse(mock_st.called)
        mock_cw.assert_called_once_with(stack, mock_tgm, 'engine-001',
                                        _worker._rpc_client)
        self.assertFalse(stack.rollback.called)

        # test when stack complete
        stack.FAILED = 'FAILED'
        stack.status = stack.FAILED
        _worker.stop_all_workers(stack)
        self.assertFalse(mock_st.called)
        mock_cw.assert_called_with(stack, mock_tgm, 'engine-001',
                                   _worker._rpc_client)
        self.assertFalse(stack.rollback.called)

    @mock.patch.object(stack_objects.Stack, 'select_and_update')
    def test_update_current_traversal(self, mock_sau):
        stack = mock.MagicMock()
        stack.current_traversal = 'some-thing'
        old_trvsl = stack.current_traversal
        worker._update_current_traversal(stack)
        self.assertNotEqual(old_trvsl, stack.current_traversal)
        mock_sau.assert_called_once_with(mock.ANY, stack.id, mock.ANY,
                                         exp_trvsl=old_trvsl)
