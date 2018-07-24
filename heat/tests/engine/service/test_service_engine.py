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

import mock
from oslo_config import cfg
from oslo_utils import timeutils

from heat.common import context
from heat.common import service_utils
from heat.engine import service
from heat.engine import worker
from heat.objects import service as service_objects
from heat.rpc import worker_api
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import utils


class ServiceEngineTest(common.HeatTestCase):

    def setUp(self):
        super(ServiceEngineTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.engine_id = 'engine-fake-uuid'

    def test_make_sure_rpc_version(self):
        self.assertEqual(
            '1.36',
            service.EngineService.RPC_API_VERSION,
            ('RPC version is changed, please update this test to new version '
             'and make sure additional test cases are added for RPC APIs '
             'added in new version'))

    @mock.patch.object(service_objects.Service, 'get_all')
    @mock.patch.object(service_utils, 'format_service')
    def test_service_get_all(self, mock_format_service, mock_get_all):
        mock_get_all.return_value = [mock.Mock()]
        mock_format_service.return_value = mock.Mock()
        self.assertEqual(1, len(self.eng.list_services(self.ctx)))
        self.assertTrue(mock_get_all.called)
        mock_format_service.assert_called_once_with(mock.ANY)

    @mock.patch.object(service_objects.Service, 'update_by_id')
    @mock.patch.object(service_objects.Service, 'create')
    @mock.patch.object(context, 'get_admin_context')
    def test_service_manage_report_start(self,
                                         mock_admin_context,
                                         mock_service_create,
                                         mock_service_update):
        self.eng.service_id = None
        mock_admin_context.return_value = self.ctx
        srv = dict(id='mock_id')
        mock_service_create.return_value = srv
        self.eng.service_manage_report()
        mock_admin_context.assert_called_once_with()
        mock_service_create.assert_called_once_with(
            self.ctx,
            dict(host=self.eng.host,
                 hostname=self.eng.hostname,
                 binary=self.eng.binary,
                 engine_id=self.eng.engine_id,
                 topic=self.eng.topic,
                 report_interval=cfg.CONF.periodic_interval))
        self.assertEqual(srv['id'], self.eng.service_id)
        mock_service_update.assert_called_once_with(
            self.ctx,
            self.eng.service_id,
            dict(deleted_at=None))

    @mock.patch.object(service_objects.Service, 'get_all_by_args')
    @mock.patch.object(service_objects.Service, 'delete')
    @mock.patch.object(context, 'get_admin_context')
    def test_service_manage_report_cleanup(self,
                                           mock_admin_context,
                                           mock_service_delete,
                                           mock_get_all):
        mock_admin_context.return_value = self.ctx
        ages_a_go = timeutils.utcnow() - datetime.timedelta(
            seconds=4000)
        mock_get_all.return_value = [{'id': 'foo',
                                      'deleted_at': None,
                                      'updated_at': ages_a_go}]
        self.eng.service_manage_cleanup()
        mock_admin_context.assert_called_once_with()
        mock_get_all.assert_called_once_with(self.ctx,
                                             self.eng.host,
                                             self.eng.binary,
                                             self.eng.hostname)
        mock_service_delete.assert_called_once_with(
            self.ctx, 'foo')

    @mock.patch.object(service_objects.Service, 'update_by_id')
    @mock.patch.object(context, 'get_admin_context')
    def test_service_manage_report_update(self, mock_admin_context,
                                          mock_service_update):
        self.eng.service_id = 'mock_id'
        mock_admin_context.return_value = self.ctx
        self.eng.service_manage_report()
        mock_admin_context.assert_called_once_with()
        mock_service_update.assert_called_once_with(
            self.ctx,
            'mock_id',
            dict(deleted_at=None))

    @mock.patch.object(service_objects.Service, 'update_by_id')
    @mock.patch.object(context, 'get_admin_context')
    def test_service_manage_report_update_fail(self, mock_admin_context,
                                               mock_service_update):
        self.eng.service_id = 'mock_id'
        mock_admin_context.return_value = self.ctx
        mock_service_update.side_effect = Exception()
        self.eng.service_manage_report()
        msg = 'Service %s update failed' % self.eng.service_id
        self.assertIn(msg, self.LOG.output)

    def test_stop_rpc_server(self):
        with mock.patch.object(self.eng,
                               '_rpc_server') as mock_rpc_server:
            self.eng._stop_rpc_server()
            mock_rpc_server.stop.assert_called_once_with()
            mock_rpc_server.wait.assert_called_once_with()

    def _test_engine_service_start(
            self,
            thread_group_class,
            worker_service_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method):
        self.patchobject(self.eng, 'service_manage_cleanup')
        self.patchobject(self.eng, 'reset_stack_status')
        self.eng.start()

        # engine id
        sample_uuid_method.assert_called_once_with()
        sampe_uuid = sample_uuid_method.return_value
        self.assertEqual(sampe_uuid,
                         self.eng.engine_id,
                         'Failed to generated engine_id')

        # Thread group manager
        thread_group_manager_class.assert_called_once_with()
        thread_group_manager = thread_group_manager_class.return_value
        self.assertEqual(thread_group_manager,
                         self.eng.thread_group_mgr,
                         'Failed to create Thread Group Manager')

        # Engine Listener
        engine_listener_class.assert_called_once_with(
            self.eng.host,
            self.eng.engine_id,
            self.eng.thread_group_mgr
        )
        engine_lister = engine_listener_class.return_value
        engine_lister.start.assert_called_once_with()

        # Worker Service
        if cfg.CONF.convergence_engine:
            worker_service_class.assert_called_once_with(
                host=self.eng.host,
                topic=worker_api.TOPIC,
                engine_id=self.eng.engine_id,
                thread_group_mgr=self.eng.thread_group_mgr
            )
            worker_service = worker_service_class.return_value
            worker_service.start.assert_called_once_with()

        # RPC Target
        target_class.assert_called_once_with(
            version=service.EngineService.RPC_API_VERSION,
            server=self.eng.host,
            topic=self.eng.topic)

        # RPC server
        target = target_class.return_value
        rpc_server_method.assert_called_once_with(target,
                                                  self.eng)
        rpc_server = rpc_server_method.return_value
        self.assertEqual(rpc_server,
                         self.eng._rpc_server,
                         "Failed to create RPC server")

        rpc_server.start.assert_called_once_with()

        # RPC client
        rpc_client = rpc_client_class.return_value
        rpc_client_class.assert_called_once_with(
            version=service.EngineService.RPC_API_VERSION)
        self.assertEqual(rpc_client,
                         self.eng._client,
                         "Failed to create RPC client")

        # Manage Thread group
        thread_group_class.assert_called_once_with()
        manage_thread_group = thread_group_class.return_value
        manage_thread_group.add_timer.assert_called_once_with(
            cfg.CONF.periodic_interval,
            self.eng.service_manage_report
        )

    @mock.patch('heat.common.messaging.get_rpc_server',
                return_value=mock.Mock())
    @mock.patch('oslo_messaging.Target',
                return_value=mock.Mock())
    @mock.patch('heat.common.messaging.get_rpc_client',
                return_value=mock.Mock())
    @mock.patch('heat.common.service_utils.generate_engine_id',
                return_value='sample-uuid')
    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch('heat.engine.service.EngineListener',
                return_value=mock.Mock())
    @mock.patch('heat.engine.worker.WorkerService',
                return_value=mock.Mock())
    @mock.patch('oslo_service.threadgroup.ThreadGroup',
                return_value=mock.Mock())
    @mock.patch.object(service.EngineService, '_configure_db_conn_pool_size')
    def test_engine_service_start_in_non_convergence_mode(
            self,
            configure_db_conn_pool_size,
            thread_group_class,
            worker_service_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method):
        cfg.CONF.set_override('convergence_engine', False)
        self._test_engine_service_start(
            thread_group_class,
            worker_service_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method
        )

    @mock.patch('heat.common.messaging.get_rpc_server',
                return_value=mock.Mock())
    @mock.patch('oslo_messaging.Target',
                return_value=mock.Mock())
    @mock.patch('heat.common.messaging.get_rpc_client',
                return_value=mock.Mock())
    @mock.patch('heat.common.service_utils.generate_engine_id',
                return_value=mock.Mock())
    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch('heat.engine.service.EngineListener',
                return_value=mock.Mock())
    @mock.patch('heat.engine.worker.WorkerService',
                return_value=mock.Mock())
    @mock.patch('oslo_service.threadgroup.ThreadGroup',
                return_value=mock.Mock())
    @mock.patch.object(service.EngineService, '_configure_db_conn_pool_size')
    def test_engine_service_start_in_convergence_mode(
            self,
            configure_db_conn_pool_size,
            thread_group_class,
            worker_service_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method):
        cfg.CONF.set_override('convergence_engine', True)
        self._test_engine_service_start(
            thread_group_class,
            worker_service_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method
        )

    def _test_engine_service_stop(
            self,
            service_delete_method,
            admin_context_method):
        cfg.CONF.set_default('periodic_interval', 60)
        self.patchobject(self.eng, 'service_manage_cleanup')
        self.patchobject(self.eng, 'reset_stack_status')
        self.patchobject(self.eng, 'service_manage_report')

        self.eng.start()
        # Add dummy thread group to test thread_group_mgr.stop() is executed?
        dtg1 = tools.DummyThreadGroup()
        dtg2 = tools.DummyThreadGroup()
        self.eng.thread_group_mgr.groups['sample-uuid1'] = dtg1
        self.eng.thread_group_mgr.groups['sample-uuid2'] = dtg2
        self.eng.service_id = 'sample-service-uuid'

        self.patchobject(self.eng.manage_thread_grp, 'stop',
                         new=mock.Mock(wraps=self.eng.manage_thread_grp.stop))
        self.patchobject(self.eng, '_stop_rpc_server',
                         new=mock.Mock(wraps=self.eng._stop_rpc_server))
        orig_stop = self.eng.thread_group_mgr.stop

        with mock.patch.object(self.eng.thread_group_mgr, 'stop') as stop:
            stop.side_effect = orig_stop

            self.eng.stop()

            # RPC server
            self.eng._stop_rpc_server.assert_called_once_with()

            if cfg.CONF.convergence_engine:
                # WorkerService
                self.eng.worker_service.stop.assert_called_once_with()

            # Wait for all active threads to be finished
            calls = [mock.call('sample-uuid1', True),
                     mock.call('sample-uuid2', True)]
            self.eng.thread_group_mgr.stop.assert_has_calls(calls, True)

            # Manage Thread group
            self.eng.manage_thread_grp.stop.assert_called_with()

            # Service delete
            admin_context_method.assert_called_once_with()
            ctxt = admin_context_method.return_value
            service_delete_method.assert_called_once_with(
                ctxt,
                self.eng.service_id
            )

    @mock.patch.object(worker.WorkerService,
                       'stop')
    @mock.patch('heat.common.context.get_admin_context',
                return_value=mock.Mock())
    @mock.patch('heat.objects.service.Service.delete',
                return_value=mock.Mock())
    def test_engine_service_stop_in_convergence_mode(
            self,
            service_delete_method,
            admin_context_method,
            worker_service_stop):
        cfg.CONF.set_default('convergence_engine', True)
        self._test_engine_service_stop(
            service_delete_method,
            admin_context_method
        )

    @mock.patch('heat.common.context.get_admin_context',
                return_value=mock.Mock())
    @mock.patch('heat.objects.service.Service.delete',
                return_value=mock.Mock())
    def test_engine_service_stop_in_non_convergence_mode(
            self,
            service_delete_method,
            admin_context_method):
        cfg.CONF.set_default('convergence_engine', False)
        self._test_engine_service_stop(
            service_delete_method,
            admin_context_method
        )

    @mock.patch('oslo_log.log.setup')
    def test_engine_service_reset(self, setup_logging_mock):
        self.eng.reset()
        setup_logging_mock.assert_called_once_with(cfg.CONF, 'heat')

    @mock.patch('heat.common.messaging.get_rpc_client',
                return_value=mock.Mock())
    @mock.patch('heat.common.service_utils.generate_engine_id',
                return_value=mock.Mock())
    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch('heat.engine.service.EngineListener',
                return_value=mock.Mock())
    @mock.patch('heat.engine.worker.WorkerService',
                return_value=mock.Mock())
    @mock.patch('oslo_service.threadgroup.ThreadGroup',
                return_value=mock.Mock())
    def test_engine_service_configures_connection_pool(
            self,
            thread_group_class,
            worker_service_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class):
        self.addCleanup(self.eng._stop_rpc_server)
        self.eng.start()
        self.assertEqual(cfg.CONF.executor_thread_pool_size,
                         cfg.CONF.database.max_overflow)
