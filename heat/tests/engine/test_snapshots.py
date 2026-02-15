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

import tenacity
from unittest import mock

from oslo_config import cfg

from heat.common import exception as heat_exception
from heat.common import timeutils as heat_timeutils
from heat.engine import snapshots
from heat.engine import stack
from heat.engine import sync_point
from heat.engine import worker
from heat.objects import resource_snapshot as rsrc_snapshot_objects
from heat.objects import snapshot as snapshot_objects
from heat.rpc import worker_client
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import utils


class fake_sp(object):
    def __init__(self, input_data, extra_data={}):
        self.input_data = input_data
        self.extra_data = extra_data


class SnapshotTestCase(common.HeatTestCase):
    def setUp(self):
        super(SnapshotTestCase, self).setUp(quieten_logging=False)
        self.thread_group_mgr = mock.Mock()
        cfg.CONF.set_default('convergence_engine', True)
        self.worker = worker.WorkerService('host-1',
                                           'topic-1',
                                           'engine_id',
                                           self.thread_group_mgr)
        self.worker._rpc_client = worker_client.WorkerClient()
        self.ctx = utils.dummy_context()
        self.stack = tools.get_stack(
            'test_snapshot', self.ctx,
            template=tools.string_template_five, convergence=True)
        self.stack.converge_stack(self.stack.t)
        self.stack_load_patcher = mock.patch.object(
            stack.Stack, 'load', return_value=self.stack)
        self.stack_load_patcher.start()
        self.addCleanup(self.stack_load_patcher.stop)
        self.resource = self.stack['A']
        data = self.stack.prepare_abandon(no_resources=True)
        snapshot_obj = snapshot_objects.Snapshot.create(
            self.ctx, {
                'tenant': self.ctx.project_id, 'data': data,
                'name': 'snapshot1', 'stack_id': self.stack.id,
                'status': 'COMPLETE'})
        self.resource_snapshot = self.resource.resource_snapshot_set(
            snapshot_id=snapshot_obj.id)

        self.snapshot_obj = snapshot_objects.Snapshot.get_snapshot(
            self.ctx, snapshot_obj.id, load_rsrc_snapshot=True)
        self.start_time_date_time = (
            self.stack.updated_time or self.stack.created_time)
        self.start_time = self.start_time_date_time.strftime(
            heat_timeutils.str_duration_format)

        resources = self.snapshot_obj.data['resources']
        self.snapshot = snapshots.Snapshot(
            self.ctx, self.snapshot_obj.id, self.stack.id,
            self.start_time_date_time, self.thread_group_mgr,
            resources=resources, is_stack_delete=False,
            current_traversal=self.stack.current_traversal)

    def tearDown(self):
        super(SnapshotTestCase, self).tearDown()

    def test_snapshot_delete(self):
        self.snapshot.delete_snapshot()
        self.thread_group_mgr.start.assert_called_once_with(
            self.snapshot.stack_id, self.snapshot.do_delete_snapshot)

    @mock.patch.object(snapshot_objects.Snapshot, 'get_snapshot')
    def test_snapshot_delete_inprogress(self, mock_gs):
        self.snapshot_obj.status = "IN_PROGRESS"
        mock_gs.return_value = self.snapshot_obj
        self.assertFalse(self.thread_group_mgr.called)
        err = self.assertRaises(
            heat_exception.NotSupported, self.snapshot.delete_snapshot)
        self.assertEqual(
            "Deleting in-progress snapshot is not supported.", str(err))

    @mock.patch.object(snapshots.Snapshot, 'mark_complete')
    @mock.patch.object(worker_client.WorkerClient,
                       'check_resource_delete_snapshot')
    @mock.patch.object(sync_point, 'create')
    def test_do_delete_snapshot(self, mock_sc, mock_crds, mock_mc):
        self.snapshot.do_delete_snapshot()
        mock_sc.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.stack.current_traversal,
            True, self.stack.id)
        mock_crds.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.resource.name, self.start_time,
            current_traversal=self.stack.current_traversal,
            is_stack_delete=False)
        self.assertFalse(mock_mc.called)

    @mock.patch.object(snapshots.Snapshot, 'mark_complete')
    def test_do_delete_snapshot_no_resources(self, mock_mc):
        self.snapshot.resources = None
        self.snapshot.do_delete_snapshot()
        self.assertTrue(mock_mc.called)

    @mock.patch.object(sync_point, 'delete_all')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot_objs')
    def test_mark_complete(self, mock_dso, mock_spda):
        result = self.snapshot.mark_complete()
        self.assertTrue(mock_dso.called)
        self.assertTrue(result)
        mock_spda.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.stack.current_traversal)

    @mock.patch.object(sync_point, 'update_sync_point')
    @mock.patch.object(sync_point, 'delete_all')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot_objs')
    def test_mark_complete_is_stack_delete_with_synced(self, mock_dso,
                                                       mock_spda, mock_usp):
        mock_usp.return_value = True
        self.snapshot.is_stack_delete = True
        result = self.snapshot.mark_complete()
        self.assertTrue(mock_dso.called)
        self.assertTrue(result)
        mock_spda.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.stack.current_traversal)
        mock_usp.assert_called_once_with(
            mock.ANY, self.stack.id, self.stack.current_traversal,
            True, predecessors=[], new_data=mock.ANY)

    @mock.patch.object(sync_point, 'update_sync_point')
    @mock.patch.object(sync_point, 'delete_all')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot_objs')
    def test_mark_complete_is_stack_delete_not_synced(self, mock_dso,
                                                      mock_spda, mock_usp):
        mock_usp.return_value = False
        self.snapshot.is_stack_delete = True
        result = self.snapshot.mark_complete()
        self.assertTrue(mock_dso.called)
        self.assertFalse(result)
        mock_spda.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.stack.current_traversal)
        mock_usp.assert_called_once_with(
            mock.ANY, self.stack.id, self.stack.current_traversal,
            True, predecessors=[], new_data=mock.ANY)

    @mock.patch.object(sync_point, 'update_sync_point')
    @mock.patch.object(sync_point, 'delete_all')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot_objs')
    def test_mark_complete_with_entity_not_found(self, mock_dso,
                                                 mock_spda, mock_usp):
        mock_usp.side_effect = heat_exception.EntityNotFound
        self.snapshot.is_stack_delete = True
        result = self.snapshot.mark_complete()
        self.assertTrue(mock_dso.called)
        self.assertTrue(result)
        mock_spda.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.stack.current_traversal)
        mock_usp.assert_called_once_with(
            mock.ANY, self.stack.id, self.stack.current_traversal,
            True, predecessors=[], new_data=mock.ANY)

    @mock.patch.object(snapshot_objects.Snapshot, 'update')
    @mock.patch.object(sync_point, 'update_sync_point')
    @mock.patch.object(sync_point, 'delete_all')
    def test_mark_failed(self, mock_spda, mock_usp, mock_update):
        result = self.snapshot.mark_failed(
            self.resource.name, failure_reason='Something you should care')
        self.assertTrue(result)
        mock_update.assert_called_once_with(
            mock.ANY, self.snapshot.id,
            {'status': 'DELETE_FAILED',
             'status_reason': 'Something you should care'})
        mock_spda.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.stack.current_traversal)
        self.assertFalse(mock_usp.called)

    @mock.patch.object(sync_point, 'update_sync_point')
    @mock.patch.object(sync_point, 'delete_all')
    def test_mark_failed_with_is_stack_delete(self, mock_spda, mock_usp):
        self.snapshot.is_stack_delete = True
        result = self.snapshot.mark_failed(
            self.resource.name, failure_reason='Something you should care')
        self.assertTrue(result)
        mock_spda.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.stack.current_traversal)
        mock_usp.assert_called_once_with(
            mock.ANY, self.stack.id, self.stack.current_traversal, True,
            predecessors=[], new_rsrc_failure="Something you should care")

    @mock.patch.object(sync_point, 'update_sync_point')
    @mock.patch.object(sync_point, 'delete_all')
    def test_mark_failed_with_is_stack_delete_update_failed(
        self, mock_spda, mock_usp
    ):
        self.snapshot.is_stack_delete = True
        mock_usp.return_value = False
        result = self.snapshot.mark_failed(
            self.resource.name, failure_reason='Something you should care')
        self.assertFalse(result)
        mock_spda.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.stack.current_traversal)
        mock_usp.assert_called_once_with(
            mock.ANY, self.stack.id, self.stack.current_traversal, True,
            predecessors=[], new_rsrc_failure="Something you should care")

    @mock.patch.object(sync_point, 'update_sync_point')
    @mock.patch.object(sync_point, 'delete_all')
    def test_mark_failed_with_entity_not_found(
        self, mock_spda, mock_usp
    ):
        self.snapshot.is_stack_delete = True
        mock_usp.side_effect = heat_exception.EntityNotFound
        result = self.snapshot.mark_failed(
            self.resource.name, failure_reason='Something you should care')
        self.assertTrue(result)
        mock_spda.assert_called_once_with(
            mock.ANY, self.snapshot.id, self.stack.current_traversal)
        mock_usp.assert_called_once_with(
            mock.ANY, self.stack.id, self.stack.current_traversal, True,
            predecessors=[], new_rsrc_failure="Something you should care")

    def test_delete_snapshot_objs(self):
        self.snapshot.delete_snapshot_objs()
        self.assertRaises(
            heat_exception.NotFound,
            snapshot_objects.Snapshot.get_snapshot,
            self.ctx, self.snapshot_obj.id)
        r_snapshots = rsrc_snapshot_objects.ResourceSnapshot.get_all(
            self.ctx, self.snapshot_obj.id)
        self.assertEqual([], r_snapshots)

    @mock.patch.object(sync_point, 'create')
    def test_delete_snapshots_no_snapshot_ids(self, mock_spc):
        result = snapshots.delete_snapshots(
            self.ctx, [], self.stack.id, self.stack.current_traversal,
            start_time=self.start_time_date_time,
            thread_group_mgr=self.thread_group_mgr, run_till_success=True)
        self.assertIsNone(result)
        self.assertFalse(mock_spc.called)

    @mock.patch.object(sync_point, 'get')
    @mock.patch.object(sync_point, 'create')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot')
    def test_delete_snapshots_run_till_success(self, mock_ds,
                                               mock_spc, mock_spg):
        cfg.CONF.set_default('stack_action_timeout', 3600)
        # Update stack sync_point for snapshot complete
        sender_key = stack.ConvergenceNode(self.snapshot.id, True)
        input_data = sync_point.serialize_input_data({sender_key: None})

        mock_spg.return_value = fake_sp(
            input_data=input_data)

        result = snapshots.delete_snapshots(
            self.ctx, [self.snapshot.id], self.stack.id,
            self.stack.current_traversal,
            start_time=self.start_time_date_time,
            thread_group_mgr=self.thread_group_mgr, run_till_success=True)
        self.assertIsNone(result)
        mock_ds.assert_called_once_with()

    @mock.patch.object(sync_point, 'get')
    @mock.patch.object(sync_point, 'create')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot')
    def test_delete_snapshots_retry_limit(self, mock_ds,
                                          mock_spc, mock_spg):
        cfg.CONF.set_default('stack_action_timeout', 0)
        # Update stack sync_point for snapshot complete
        input_data = sync_point.serialize_input_data({})

        mock_spg.return_value = fake_sp(
            input_data=input_data)

        self.assertRaises(
            tenacity.RetryError, snapshots.delete_snapshots,
            self.ctx, [self.snapshot.id], self.stack.id,
            self.stack.current_traversal,
            start_time=self.start_time_date_time,
            thread_group_mgr=self.thread_group_mgr, run_till_success=True)
        mock_ds.assert_called_once_with()

    @mock.patch.object(sync_point, 'get')
    @mock.patch.object(sync_point, 'create')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot')
    def test_delete_snapshots_snapshot_id_not_found(
        self, mock_ds, mock_spc, mock_spg
    ):
        cfg.CONF.set_default('stack_action_timeout', 3600)
        # Update stack sync_point for snapshot complete
        sender_key = stack.ConvergenceNode(self.snapshot.id, True)
        input_data = sync_point.serialize_input_data({sender_key: None})

        mock_spg.return_value = fake_sp(
            input_data=input_data)
        mock_ds.side_effect = [None, heat_exception.NotFound]

        result = snapshots.delete_snapshots(
            self.ctx, [self.snapshot.id, 'fake_id'],
            self.stack.id, self.stack.current_traversal,
            start_time=self.start_time_date_time,
            thread_group_mgr=self.thread_group_mgr, run_till_success=True)
        self.assertIsNone(result)
        self.assertEqual(2, mock_ds.call_count)
        log_msg = (
            "Snapshot %(snapshot)s for stack %(stack)s is already deleted."
        ) % {'snapshot': 'fake_id', 'stack': self.stack.id}
        self.assertIn(log_msg, self.LOG.output)

    @mock.patch.object(sync_point, 'get')
    @mock.patch.object(sync_point, 'create')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot')
    def test_delete_snapshots_run_till_success_with_rsrc_fail(
        self, mock_ds, mock_spc, mock_spg
    ):
        cfg.CONF.set_default('stack_action_timeout', 3600)
        # Update stack sync_point for snapshot complete
        sender_key = stack.ConvergenceNode(self.snapshot.id, True)
        input_data = sync_point.serialize_input_data({sender_key: None})
        extra_data = sync_point.serialize_extra_data(
            {'resource_failures': ["Some resource Failed"]})

        mock_spg.return_value = fake_sp(
            input_data=input_data, extra_data=extra_data)

        result = snapshots.delete_snapshots(
            self.ctx, [self.snapshot.id], self.stack.id,
            self.stack.current_traversal,
            start_time=self.start_time_date_time,
            thread_group_mgr=self.thread_group_mgr, run_till_success=True)
        self.assertEqual(str(["Some resource Failed"]), result)
        mock_ds.assert_called_once_with()

    @mock.patch.object(sync_point, 'get')
    @mock.patch.object(sync_point, 'create')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot')
    def test_stack_delete_all_snapshots(
        self, mock_ds, mock_spc, mock_spg
    ):
        cfg.CONF.set_default('stack_action_timeout', 3600)
        # Update stack sync_point for snapshot complete
        sender_key = stack.ConvergenceNode(self.snapshot.id, True)
        input_data = sync_point.serialize_input_data({sender_key: None})

        mock_spg.return_value = fake_sp(
            input_data=input_data)
        self.stack.delete_all_snapshots(run_till_success=True)
        mock_ds.assert_called_once_with()

    @mock.patch.object(sync_point, 'get')
    @mock.patch.object(sync_point, 'create')
    @mock.patch.object(snapshots.Snapshot, 'delete_snapshot')
    def test_stack_delete_all_snapshots_with_rsrc_fail(
        self, mock_ds, mock_spc, mock_spg
    ):
        cfg.CONF.set_default('stack_action_timeout', 3600)
        # Update stack sync_point for snapshot complete
        sender_key = stack.ConvergenceNode(self.snapshot.id, True)
        input_data = sync_point.serialize_input_data({sender_key: None})
        failure_reason = ["Some resource Failed"]
        extra_data = sync_point.serialize_extra_data(
            {'resource_failures': ["Some resource Failed"]})

        mock_spg.return_value = fake_sp(
            input_data=input_data, extra_data=extra_data)
        err = self.assertRaises(
            heat_exception.Error,
            self.stack.delete_all_snapshots,
            run_till_success=True)
        msg = (
            "Stack %(stack_id)s failed "
            "when delete all snapshots: %(failure_reason)s." % {
                "stack_id": self.stack.id,
                "failure_reason": str(failure_reason)
            }
        )
        self.assertEqual(msg, str(err))
        mock_ds.assert_called_once_with()
