# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import uuid

import mock
from oslo_messaging.rpc import dispatcher
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import service
from heat.engine import stack
from heat.objects import snapshot as snapshot_objects
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import utils


class SnapshotServiceTest(common.HeatTestCase):
    # TODO(Qiming): Rework this test to handle OS::Nova::Server which
    # has a real snapshot support.
    def setUp(self):
        super(SnapshotServiceTest, self).setUp()
        self.ctx = utils.dummy_context()

        self.engine = service.EngineService('a-host', 'a-topic')
        self.engine.thread_group_mgr = service.ThreadGroupManager()

    def _create_stack(self, stack_name, files=None):
        t = template_format.parse(tools.wp_template)
        stk = utils.parse_stack(t, stack_name=stack_name, files=files)
        stk.state_set(stk.CREATE, stk.COMPLETE, 'mock completion')

        return stk

    def test_show_snapshot_not_found(self):
        stk = self._create_stack('stack_snapshot_not_found')
        snapshot_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_snapshot,
                               self.ctx, stk.identifier(),
                               snapshot_id)
        expected = 'Snapshot with id %s not found' % snapshot_id
        self.assertEqual(exception.NotFound, ex.exc_info[0])
        self.assertIn(expected, six.text_type(ex.exc_info[1]))

    def test_show_snapshot_not_belong_to_stack(self):
        stk1 = self._create_stack('stack_snaphot_not_belong_to_stack_1')
        stk1._persist_state()
        snapshot1 = self.engine.stack_snapshot(
            self.ctx, stk1.identifier(), 'snap1')
        self.engine.thread_group_mgr.groups[stk1.id].wait()
        snapshot_id = snapshot1['id']

        stk2 = self._create_stack('stack_snaphot_not_belong_to_stack_2')
        stk2._persist_state()
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_snapshot,
                               self.ctx, stk2.identifier(),
                               snapshot_id)
        expected = ('The Snapshot (%(snapshot)s) for Stack (%(stack)s) '
                    'could not be found') % {'snapshot': snapshot_id,
                                             'stack': stk2.name}
        self.assertEqual(exception.SnapshotNotFound, ex.exc_info[0])
        self.assertIn(expected, six.text_type(ex.exc_info[1]))

    @mock.patch.object(stack.Stack, 'load')
    def test_create_snapshot(self, mock_load):
        files = {'a_file': 'the contents'}
        stk = self._create_stack('stack_snapshot_create', files=files)
        mock_load.return_value = stk

        snapshot = self.engine.stack_snapshot(
            self.ctx, stk.identifier(), 'snap1')
        self.assertIsNotNone(snapshot['id'])
        self.assertIsNotNone(snapshot['creation_time'])
        self.assertEqual('snap1', snapshot['name'])
        self.assertEqual("IN_PROGRESS", snapshot['status'])
        self.engine.thread_group_mgr.groups[stk.id].wait()
        snapshot = self.engine.show_snapshot(
            self.ctx, stk.identifier(), snapshot['id'])
        self.assertEqual("COMPLETE", snapshot['status'])
        self.assertEqual("SNAPSHOT", snapshot['data']['action'])
        self.assertEqual("COMPLETE", snapshot['data']['status'])
        self.assertEqual(files, snapshot['data']['files'])
        self.assertEqual(stk.id, snapshot['data']['id'])
        self.assertIsNotNone(stk.updated_time)
        self.assertIsNotNone(snapshot['creation_time'])
        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)

    @mock.patch.object(stack.Stack, 'load')
    def test_create_snapshot_action_in_progress(self, mock_load):
        stack_name = 'stack_snapshot_action_in_progress'
        stk = self._create_stack(stack_name)
        mock_load.return_value = stk

        stk.state_set(stk.UPDATE, stk.IN_PROGRESS, 'test_override')
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.stack_snapshot,
                               self.ctx, stk.identifier(), 'snap_none')
        self.assertEqual(exception.ActionInProgress, ex.exc_info[0])
        msg = ("Stack %(stack)s already has an action (%(action)s) "
               "in progress.") % {'stack': stack_name, 'action': stk.action}
        self.assertEqual(msg, six.text_type(ex.exc_info[1]))

        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)

    @mock.patch.object(stack.Stack, 'load')
    def test_delete_snapshot_not_found(self, mock_load):
        stk = self._create_stack('stack_snapshot_delete_not_found')
        mock_load.return_value = stk

        snapshot_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.delete_snapshot,
                               self.ctx, stk.identifier(), snapshot_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)

    @mock.patch.object(stack.Stack, 'load')
    def test_delete_snapshot_not_belong_to_stack(self, mock_load):
        stk1 = self._create_stack('stack_snapshot_delete_not_belong_1')
        mock_load.return_value = stk1

        snapshot1 = self.engine.stack_snapshot(
            self.ctx, stk1.identifier(), 'snap1')
        self.engine.thread_group_mgr.groups[stk1.id].wait()
        snapshot_id = snapshot1['id']

        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)
        mock_load.reset_mock()

        stk2 = self._create_stack('stack_snapshot_delete_not_belong_2')
        mock_load.return_value = stk2

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.delete_snapshot,
                               self.ctx,
                               stk2.identifier(),
                               snapshot_id)
        expected = ('The Snapshot (%(snapshot)s) for Stack (%(stack)s) '
                    'could not be found') % {'snapshot': snapshot_id,
                                             'stack': stk2.name}
        self.assertEqual(exception.SnapshotNotFound, ex.exc_info[0])
        self.assertIn(expected, six.text_type(ex.exc_info[1]))

        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)
        mock_load.reset_mock()

    @mock.patch.object(stack.Stack, 'load')
    def test_delete_snapshot_in_progress(self, mock_load):
        # can not delete the snapshot in snapshotting
        stk = self._create_stack('test_delete_snapshot_in_progress')
        mock_load.return_value = stk
        snapshot = mock.Mock()
        snapshot.id = str(uuid.uuid4())
        snapshot.status = 'IN_PROGRESS'
        self.patchobject(snapshot_objects.Snapshot,
                         'get_snapshot_by_stack').return_value = snapshot
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.delete_snapshot,
                               self.ctx, stk.identifier(), snapshot.id)
        msg = 'Deleting in-progress snapshot is not supported'
        self.assertIn(msg, six.text_type(ex.exc_info[1]))
        self.assertEqual(exception.NotSupported, ex.exc_info[0])

    @mock.patch.object(stack.Stack, 'load')
    def test_delete_snapshot(self, mock_load):
        stk = self._create_stack('stack_snapshot_delete_normal')
        mock_load.return_value = stk

        snapshot = self.engine.stack_snapshot(
            self.ctx, stk.identifier(), 'snap1')
        self.engine.thread_group_mgr.groups[stk.id].wait()
        snapshot_id = snapshot['id']
        self.engine.delete_snapshot(self.ctx, stk.identifier(), snapshot_id)
        self.engine.thread_group_mgr.groups[stk.id].wait()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_snapshot, self.ctx,
                               stk.identifier(), snapshot_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        self.assertTrue(2, mock_load.call_count)

    @mock.patch.object(stack.Stack, 'load')
    def test_list_snapshots(self, mock_load):
        stk = self._create_stack('stack_snapshot_list')
        mock_load.return_value = stk

        snapshot = self.engine.stack_snapshot(
            self.ctx, stk.identifier(), 'snap1')
        self.assertIsNotNone(snapshot['id'])
        self.assertEqual("IN_PROGRESS", snapshot['status'])
        self.engine.thread_group_mgr.groups[stk.id].wait()

        snapshots = self.engine.stack_list_snapshots(
            self.ctx, stk.identifier())
        expected = {
            "id": snapshot["id"],
            "name": "snap1",
            "status": "COMPLETE",
            "status_reason": "Stack SNAPSHOT completed successfully",
            "data": stk.prepare_abandon(),
            "creation_time": snapshot['creation_time']}

        self.assertEqual([expected], snapshots)
        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)

    @mock.patch.object(stack.Stack, 'load')
    def test_restore_snapshot(self, mock_load):
        stk = self._create_stack('stack_snapshot_restore_normal')
        mock_load.return_value = stk

        snapshot = self.engine.stack_snapshot(
            self.ctx, stk.identifier(), 'snap1')
        self.engine.thread_group_mgr.groups[stk.id].wait()
        snapshot_id = snapshot['id']
        self.engine.stack_restore(self.ctx, stk.identifier(), snapshot_id)
        self.engine.thread_group_mgr.groups[stk.id].wait()
        self.assertEqual((stk.RESTORE, stk.COMPLETE), stk.state)
        self.assertEqual(2, mock_load.call_count)

    @mock.patch.object(stack.Stack, 'load')
    def test_restore_snapshot_other_stack(self, mock_load):
        stk1 = self._create_stack('stack_snapshot_restore_other_stack_1')
        mock_load.return_value = stk1

        snapshot1 = self.engine.stack_snapshot(
            self.ctx, stk1.identifier(), 'snap1')
        self.engine.thread_group_mgr.groups[stk1.id].wait()
        snapshot_id = snapshot1['id']

        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)
        mock_load.reset_mock()

        stk2 = self._create_stack('stack_snapshot_restore_other_stack_1')
        mock_load.return_value = stk2

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.stack_restore,
                               self.ctx, stk2.identifier(),
                               snapshot_id)
        expected = ('The Snapshot (%(snapshot)s) for Stack (%(stack)s) '
                    'could not be found') % {'snapshot': snapshot_id,
                                             'stack': stk2.name}
        self.assertEqual(exception.SnapshotNotFound, ex.exc_info[0])
        self.assertIn(expected, six.text_type(ex.exc_info[1]))

        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)
