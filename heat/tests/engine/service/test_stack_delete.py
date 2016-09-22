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

import mock
from oslo_messaging.rpc import dispatcher

from heat.common import exception
from heat.engine import service
from heat.engine import stack as parser
from heat.engine import stack_lock
from heat.objects import stack as stack_object
from heat.objects import stack_lock as stack_lock_object
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import utils


class StackDeleteTest(common.HeatTestCase):

    def setUp(self):
        super(StackDeleteTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.create_periodic_tasks()

    @mock.patch.object(parser.Stack, 'load')
    def test_stack_delete(self, mock_load):
        stack_name = 'service_delete_test_stack'
        stack = tools.get_stack(stack_name, self.ctx)
        sid = stack.store()
        mock_load.return_value = stack

        s = stack_object.Stack.get_by_id(self.ctx, sid)

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()
        mock_load.assert_called_once_with(self.ctx, stack=s)

    def test_stack_delete_nonexist(self):
        stack_name = 'service_delete_nonexist_test_stack'
        stack = tools.get_stack(stack_name, self.ctx)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.delete_stack,
                               self.ctx, stack.identifier())
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])

    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(stack_lock.StackLock, 'try_acquire')
    def test_stack_delete_acquired_lock(self, mock_acquire, mock_load):
        mock_acquire.return_value = self.man.engine_id

        stack_name = 'service_delete_test_stack_acquired_lock'
        stack = tools.get_stack(stack_name, self.ctx)
        sid = stack.store()
        mock_load.return_value = stack
        st = stack_object.Stack.get_by_id(self.ctx, sid)

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()

        mock_acquire.assert_called_once_with()
        mock_load.assert_called_once_with(self.ctx, stack=st)

    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(stack_lock.StackLock, 'try_acquire')
    def test_stack_delete_acquired_lock_stop_timers(self, mock_acquire,
                                                    mock_load):
        mock_acquire.return_value = self.man.engine_id
        stack_name = 'service_delete_test_stack_stop_timers'
        stack = tools.get_stack(stack_name, self.ctx)
        sid = stack.store()
        mock_load.return_value = stack
        st = stack_object.Stack.get_by_id(self.ctx, sid)

        self.man.thread_group_mgr.add_timer(stack.id, 'test')

        self.assertEqual(1, len(self.man.thread_group_mgr.groups[sid].timers))
        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.assertEqual(0, len(self.man.thread_group_mgr.groups[sid].timers))

        self.man.thread_group_mgr.groups[sid].wait()

        mock_acquire.assert_called_once_with()
        mock_load.assert_called_once_with(self.ctx, stack=st)

    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(stack_lock.StackLock, 'try_acquire')
    @mock.patch.object(stack_lock.StackLock, 'acquire')
    def test_stack_delete_current_engine_active_lock(self, mock_acquire,
                                                     mock_try, mock_load):
        self.man.start()
        stack_name = 'service_delete_test_stack_current_active_lock'
        stack = tools.get_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        stack_lock_object.StackLock.create(stack.id, self.man.engine_id)

        # Create a fake ThreadGroup too
        self.man.thread_group_mgr.groups[stack.id] = tools.DummyThreadGroup()
        st = stack_object.Stack.get_by_id(self.ctx, sid)

        mock_load.return_value = stack
        mock_try.return_value = self.man.engine_id
        mock_stop = self.patchobject(self.man.thread_group_mgr, 'stop')

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))

        mock_load.assert_called_with(self.ctx, stack=st)
        self.assertEqual(2, len(mock_load.mock_calls))
        mock_try.assert_called_once_with()
        mock_acquire.assert_called_once_with(True)
        mock_stop.assert_called_once_with(stack.id)

    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(stack_lock.StackLock, 'try_acquire')
    @mock.patch.object(stack_lock.StackLock, 'engine_alive')
    def test_stack_delete_other_engine_active_lock_failed(self, mock_alive,
                                                          mock_try, mock_load):
        OTHER_ENGINE = "other-engine-fake-uuid"
        self.man.start()
        stack_name = 'service_delete_test_stack_other_engine_lock_fail'
        stack = tools.get_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        stack_lock_object.StackLock.create(stack.id, OTHER_ENGINE)

        st = stack_object.Stack.get_by_id(self.ctx, sid)
        mock_load.return_value = stack
        mock_try.return_value = OTHER_ENGINE
        mock_alive.return_value = True

        mock_call = self.patchobject(self.man, '_remote_call',
                                     return_value=False)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.delete_stack,
                               self.ctx, stack.identifier())
        self.assertEqual(exception.StopActionFailed, ex.exc_info[0])

        mock_load.assert_called_once_with(self.ctx, stack=st)
        mock_try.assert_called_once_with()
        mock_alive.assert_called_once_with(self.ctx, OTHER_ENGINE)
        mock_call.assert_called_once_with(self.ctx, OTHER_ENGINE, mock.ANY,
                                          "stop_stack",
                                          stack_identity=mock.ANY)

    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(stack_lock.StackLock, 'try_acquire')
    @mock.patch.object(stack_lock.StackLock, 'engine_alive')
    @mock.patch.object(stack_lock.StackLock, 'acquire')
    def test_stack_delete_other_engine_active_lock_succeeded(
            self, mock_acquire, mock_alive, mock_try, mock_load):

        OTHER_ENGINE = "other-engine-fake-uuid"
        self.man.start()
        stack_name = 'service_delete_test_stack_other_engine_lock'
        stack = tools.get_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        stack_lock_object.StackLock.create(stack.id, OTHER_ENGINE)

        st = stack_object.Stack.get_by_id(self.ctx, sid)
        mock_load.return_value = stack
        mock_try.return_value = OTHER_ENGINE
        mock_alive.return_value = True
        mock_call = self.patchobject(self.man, '_remote_call',
                                     return_value=None)

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()

        self.assertEqual(2, len(mock_load.mock_calls))
        mock_load.assert_called_with(self.ctx, stack=st)
        mock_try.assert_called_once_with()
        mock_alive.assert_called_once_with(self.ctx, OTHER_ENGINE)
        mock_call.assert_called_once_with(self.ctx, OTHER_ENGINE, mock.ANY,
                                          "stop_stack",
                                          stack_identity=mock.ANY)
        mock_acquire.assert_called_once_with(True)

    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(stack_lock.StackLock, 'try_acquire')
    @mock.patch.object(stack_lock.StackLock, 'engine_alive')
    @mock.patch.object(stack_lock.StackLock, 'acquire')
    def test_stack_delete_other_dead_engine_active_lock(
            self, mock_acquire, mock_alive, mock_try, mock_load):
        OTHER_ENGINE = "other-engine-fake-uuid"
        stack_name = 'service_delete_test_stack_other_dead_engine'
        stack = tools.get_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        stack_lock_object.StackLock.create(stack.id, "other-engine-fake-uuid")

        st = stack_object.Stack.get_by_id(self.ctx, sid)
        mock_load.return_value = stack
        mock_try.return_value = OTHER_ENGINE
        mock_alive.return_value = False

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()

        mock_load.assert_called_with(self.ctx, stack=st)
        mock_try.assert_called_once_with()
        mock_acquire.assert_called_once_with(True)
        mock_alive.assert_called_once_with(self.ctx, OTHER_ENGINE)
