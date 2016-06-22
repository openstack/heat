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

import eventlet
import mock

from oslo_context import context

from heat.engine import service
from heat.tests import common


class ThreadGroupManagerTest(common.HeatTestCase):

    def setUp(self):
        super(ThreadGroupManagerTest, self).setUp()
        self.f = 'function'
        self.fargs = ('spam', 'ham', 'eggs')
        self.fkwargs = {'foo': 'bar'}
        self.cnxt = 'ctxt'
        self.engine_id = 'engine_id'
        self.stack = mock.Mock()
        self.lock_mock = mock.Mock()
        self.stlock_mock = self.patch('heat.engine.service.stack_lock')
        self.stlock_mock.StackLock.return_value = self.lock_mock
        self.tg_mock = mock.Mock()
        self.thg_mock = self.patch('heat.engine.service.threadgroup')
        self.thg_mock.ThreadGroup.return_value = self.tg_mock
        self.cfg_mock = self.patch('heat.engine.service.cfg')

    def test_tgm_start_with_lock(self):
        thm = service.ThreadGroupManager()
        with self.patchobject(thm, 'start_with_acquired_lock'):
            mock_thread_lock = mock.Mock()
            mock_thread_lock.__enter__ = mock.Mock(return_value=None)
            mock_thread_lock.__exit__ = mock.Mock(return_value=None)
            self.lock_mock.thread_lock.return_value = mock_thread_lock
            thm.start_with_lock(self.cnxt, self.stack, self.engine_id, self.f,
                                *self.fargs, **self.fkwargs)
            self.stlock_mock.StackLock.assert_called_with(self.cnxt,
                                                          self.stack.id,
                                                          self.engine_id)

            thm.start_with_acquired_lock.assert_called_once_with(
                self.stack, self.lock_mock,
                self.f, *self.fargs, **self.fkwargs)

    def test_tgm_start(self):
        stack_id = 'test'

        thm = service.ThreadGroupManager()
        ret = thm.start(stack_id, self.f, *self.fargs, **self.fkwargs)

        self.assertEqual(self.tg_mock, thm.groups['test'])
        self.tg_mock.add_thread.assert_called_with(
            thm._start_with_trace, context.get_current(), None,
            self.f, *self.fargs, **self.fkwargs)
        self.assertEqual(ret, self.tg_mock.add_thread())

    def test_tgm_add_timer(self):
        stack_id = 'test'

        thm = service.ThreadGroupManager()
        thm.add_timer(stack_id, self.f, *self.fargs, **self.fkwargs)

        self.assertEqual(self.tg_mock, thm.groups[stack_id])
        self.tg_mock.add_timer.assert_called_with(
            self.cfg_mock.CONF.periodic_interval,
            self.f, *self.fargs, **self.fkwargs)

    def test_tgm_add_msg_queue(self):
        stack_id = 'add_msg_queues_test'
        e1, e2 = mock.Mock(), mock.Mock()
        thm = service.ThreadGroupManager()
        thm.add_msg_queue(stack_id, e1)
        thm.add_msg_queue(stack_id, e2)
        self.assertEqual([e1, e2], thm.msg_queues[stack_id])

    def test_tgm_remove_msg_queue(self):
        stack_id = 'add_msg_queues_test'
        e1, e2 = mock.Mock(), mock.Mock()
        thm = service.ThreadGroupManager()
        thm.add_msg_queue(stack_id, e1)
        thm.add_msg_queue(stack_id, e2)
        thm.remove_msg_queue(None, stack_id, e2)
        self.assertEqual([e1], thm.msg_queues[stack_id])
        thm.remove_msg_queue(None, stack_id, e1)
        self.assertNotIn(stack_id, thm.msg_queues)

    def test_tgm_send(self):
        stack_id = 'send_test'
        e1, e2 = mock.MagicMock(), mock.Mock()
        thm = service.ThreadGroupManager()
        thm.add_msg_queue(stack_id, e1)
        thm.add_msg_queue(stack_id, e2)
        thm.send(stack_id, 'test_message')


class ThreadGroupManagerStopTest(common.HeatTestCase):

    def test_tgm_stop(self):
        stack_id = 'test'
        done = []

        def function():
            while True:
                eventlet.sleep()

        def linked(gt, thread):
            for i in range(10):
                eventlet.sleep()
            done.append(thread)

        thm = service.ThreadGroupManager()
        thm.add_msg_queue(stack_id, mock.Mock())
        thread = thm.start(stack_id, function)
        thread.link(linked, thread)

        thm.stop(stack_id)

        self.assertIn(thread, done)
        self.assertNotIn(stack_id, thm.groups)
        self.assertNotIn(stack_id, thm.msg_queues)
