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

from heat.engine import resource
from heat.engine import stack
from heat.engine import sync_point
from heat.engine import worker
from heat.rpc import worker_client
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import utils


class WorkerServiceTest(common.HeatTestCase):
    def setUp(self):
        super(WorkerServiceTest, self).setUp()
        thread_group_mgr = mock.Mock()
        self.worker = worker.WorkerService('host-1',
                                           'topic-1',
                                           'engine_id',
                                           thread_group_mgr)

    def test_make_sure_rpc_version(self):
        self.assertEqual(
            '1.1',
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
        self.worker.start()

        # Make sure target is called with proper parameters
        target_class.assert_called_once_with(
            version=worker.WorkerService.RPC_API_VERSION,
            server=self.worker.host,
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
        with mock.patch.object(self.worker, '_rpc_server') as mock_rpc_server:
            self.worker.stop()
            mock_rpc_server.stop.assert_called_once_with()
            mock_rpc_server.wait.assert_called_once_with()


@mock.patch.object(worker, 'construct_input_data')
@mock.patch.object(worker, 'check_stack_complete')
@mock.patch.object(worker, 'propagate_check_resource')
@mock.patch.object(worker, 'check_resource_cleanup')
@mock.patch.object(worker, 'check_resource_update')
class CheckWorkflowUpdateTest(common.HeatTestCase):
    @mock.patch.object(worker_client.WorkerClient, 'check_resource',
                       lambda *_: None)
    def setUp(self):
        super(CheckWorkflowUpdateTest, self).setUp()
        thread_group_mgr = mock.Mock()
        self.worker = worker.WorkerService('host-1',
                                           'topic-1',
                                           'engine_id',
                                           thread_group_mgr)
        self.worker._rpc_client = worker_client.WorkerClient()
        self.ctx = utils.dummy_context()
        self.stack = tools.get_stack(
            'check_workflow_create_stack', self.ctx,
            template=tools.string_template_five, convergence=True)
        self.stack.converge_stack(self.stack.t)
        self.resource = self.stack['A']
        self.is_update = True
        self.graph_key = (self.resource.id, self.is_update)

    def test_resource_not_available(
            self, mock_cru, mock_crc, mock_pcr, mock_csc, mock_cid):
        self.worker.check_resource(
            self.ctx, 'non-existant-id', self.stack.current_traversal, {},
            True)
        for mocked in [mock_cru, mock_crc, mock_pcr, mock_csc, mock_cid]:
            self.assertFalse(mocked.called)

    def test_stale_traversal(
            self, mock_cru, mock_crc, mock_pcr, mock_csc, mock_cid):
        self.worker.check_resource(self.ctx, self.resource.id,
                                   'stale-traversal', {}, True)
        for mocked in [mock_cru, mock_crc, mock_pcr, mock_csc, mock_cid]:
            self.assertFalse(mocked.called)

    def test_is_update_traversal(
            self, mock_cru, mock_crc, mock_pcr, mock_csc, mock_cid):
        self.worker.check_resource(
            self.ctx, self.resource.id, self.stack.current_traversal, {},
            self.is_update)
        mock_cru.assert_called_once_with(self.resource,
                                         self.resource.stack.t.id,
                                         {})
        self.assertFalse(mock_crc.called)

        expected_calls = []
        for req, fwd in self.stack.convergence_dependencies.leaves():
            expected_calls.append(
                (mock.call.worker.propagate_check_resource.
                    assert_called_once_with(
                        self.ctx, mock.ANY, mock.ANY,
                        self.stack.current_traversal, mock.ANY,
                        self.graph_key, {}, self.is_update)))
        mock_csc.assert_called_once_with(
            self.ctx, mock.ANY, self.stack.current_traversal,
            self.resource.id,
            mock.ANY, True)

    @mock.patch.object(resource.Resource, 'make_replacement')
    def test_is_update_traversal_raise_update_replace(
            self, mock_mr, mock_cru, mock_crc, mock_pcr, mock_csc, mock_cid):
        mock_cru.side_effect = resource.UpdateReplace
        self.worker.check_resource(
            self.ctx, self.resource.id, self.stack.current_traversal, {},
            self.is_update)
        mock_cru.assert_called_once_with(self.resource,
                                         self.resource.stack.t.id,
                                         {})
        self.assertTrue(mock_mr.called)
        self.assertFalse(mock_crc.called)
        self.assertFalse(mock_pcr.called)
        self.assertFalse(mock_csc.called)

    @mock.patch.object(resource.Resource, 'make_replacement')
    def test_is_update_traversal_raise_update_inprogress(
            self, mock_mr, mock_cru, mock_crc, mock_pcr, mock_csc, mock_cid):
        mock_cru.side_effect = resource.UpdateInProgress
        self.worker.check_resource(
            self.ctx, self.resource.id, self.stack.current_traversal, {},
            self.is_update)
        mock_cru.assert_called_once_with(self.resource,
                                         self.resource.stack.t.id,
                                         {})
        self.assertFalse(mock_mr.called)
        self.assertFalse(mock_crc.called)
        self.assertFalse(mock_pcr.called)
        self.assertFalse(mock_csc.called)


@mock.patch.object(worker, 'construct_input_data')
@mock.patch.object(worker, 'check_stack_complete')
@mock.patch.object(worker, 'propagate_check_resource')
@mock.patch.object(worker, 'check_resource_cleanup')
@mock.patch.object(worker, 'check_resource_update')
class CheckWorkflowCleanupTest(common.HeatTestCase):
    @mock.patch.object(worker_client.WorkerClient, 'check_resource',
                       lambda *_: None)
    def setUp(self):
        super(CheckWorkflowCleanupTest, self).setUp()
        thread_group_mgr = mock.Mock()
        self.worker = worker.WorkerService('host-1',
                                           'topic-1',
                                           'engine_id',
                                           thread_group_mgr)
        self.worker._rpc_client = worker_client.WorkerClient()
        self.ctx = utils.dummy_context()
        tstack = tools.get_stack(
            'check_workflow_create_stack', self.ctx,
            template=tools.string_template_five, convergence=True)
        tstack.converge_stack(tstack.t, action=tstack.CREATE)
        self.stack = stack.Stack.load(self.ctx, stack_id=tstack.id)
        self.stack.converge_stack(self.stack.t, action=self.stack.DELETE)
        self.resource = self.stack['A']
        self.is_update = False
        self.graph_key = (self.resource.id, self.is_update)

    def test_is_cleanup_traversal(
            self, mock_cru, mock_crc, mock_pcr, mock_csc, mock_cid):
        self.worker.check_resource(
            self.ctx, self.resource.id, self.stack.current_traversal, {},
            self.is_update)
        self.assertFalse(mock_cru.called)
        mock_crc.assert_called_once_with(
            self.resource, self.resource.stack.t.id,
            {})

    def test_is_cleanup_traversal_raise_update_inprogress(
            self, mock_cru, mock_crc, mock_pcr, mock_csc, mock_cid):
        mock_crc.side_effect = resource.UpdateInProgress
        self.worker.check_resource(
            self.ctx, self.resource.id, self.stack.current_traversal, {},
            self.is_update)
        mock_crc.assert_called_once_with(self.resource,
                                         self.resource.stack.t.id,
                                         {})
        self.assertFalse(mock_cru.called)
        self.assertFalse(mock_pcr.called)
        self.assertFalse(mock_csc.called)


class MiscMethodsTest(common.HeatTestCase):
    def setUp(self):
        super(MiscMethodsTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.stack = tools.get_stack(
            'check_workflow_create_stack', self.ctx,
            template=tools.string_template_five, convergence=True)
        self.stack.converge_stack(self.stack.t)
        self.resource = self.stack['A']

    def test_construct_input_data(self):
        expected_input_data = {'attrs': {'value': None},
                               'id': mock.ANY,
                               'physical_resource_id': None,
                               'name': 'A'}
        actual_input_data = worker.construct_input_data(self.resource)
        self.assertEqual(expected_input_data, actual_input_data)

    @mock.patch.object(sync_point, 'sync')
    def test_check_stack_complete_root(self, mock_sync):
        worker.check_stack_complete(
            self.ctx, self.stack, self.stack.current_traversal,
            self.stack['E'].id, self.stack.convergence_dependencies,
            True)
        mock_sync.assert_called_once_with(
            self.ctx, self.stack.id, self.stack.current_traversal, True,
            mock.ANY, mock.ANY, {(self.stack['E'].id, True): None})

    @mock.patch.object(sync_point, 'sync')
    def test_check_stack_complete_child(self, mock_sync):
        worker.check_stack_complete(
            self.ctx, self.stack, self.stack.current_traversal,
            self.resource.id, self.stack.convergence_dependencies,
            True)
        self.assertFalse(mock_sync.called)

    @mock.patch.object(sync_point, 'sync')
    def test_propagate_check_resource(self, mock_sync):
        worker.propagate_check_resource(
            self.ctx, mock.ANY, mock.ANY,
            self.stack.current_traversal, mock.ANY,
            mock.ANY, {}, True)
        self.assertTrue(mock_sync.called)

    @mock.patch.object(resource.Resource, 'create_convergence')
    def test_check_resource_update_create(self, mock_create):
        worker.check_resource_update(self.resource, self.resource.stack.t.id,
                                     {})
        self.assertTrue(mock_create.called)

    @mock.patch.object(resource.Resource, 'update_convergence')
    def test_check_resource_update_update(self, mock_update):
        self.resource.resource_id = 'physical-res-id'
        worker.check_resource_update(self.resource, self.resource.stack.t.id,
                                     {})
        self.assertTrue(mock_update.called)

    @mock.patch.object(resource.Resource, 'delete_convergence')
    def test_check_resource_cleanup_delete(self, mock_delete):
        self.resource.current_template_id = 'new-template-id'
        worker.check_resource_cleanup(self.resource, self.resource.stack.t.id,
                                      {})
        self.assertTrue(mock_delete.called)

    @mock.patch.object(resource.Resource, 'delete_convergence')
    def test_check_resource_cleanup_nodelete(self, mock_delete):
        worker.check_resource_cleanup(self.resource, self.resource.stack.t.id,
                                      {})
        self.assertFalse(mock_delete.called)
