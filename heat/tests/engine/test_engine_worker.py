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

from heat.engine import check_resource
from heat.engine import worker
from heat.tests import common
from heat.tests import utils


class WorkerServiceTest(common.HeatTestCase):
    def setUp(self):
        super(WorkerServiceTest, self).setUp()

    def test_make_sure_rpc_version(self):
        self.assertEqual(
            '1.3',
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
