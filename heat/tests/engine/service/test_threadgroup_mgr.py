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

import time

import threading
from unittest import mock

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
        self.stack_id = 'test'
        self.stack = mock.Mock()
        self.lock_mock = mock.Mock()
        self.stlock_mock = self.patch('heat.engine.service.stack_lock')
        self.stlock_mock.StackLock.return_value = self.lock_mock
        self.tg_mock = mock.Mock()
        self.patch('heat.engine.service.ThreadGroup',
                   return_value=self.tg_mock)
        self.cfg_mock = self.patch('heat.engine.service.cfg')
        self.thm = service.ThreadGroupManager()

    def tearDown(self):
        self.thm.stop_timers(self.stack_id)
        super(ThreadGroupManagerTest, self).tearDown()

    def test_tgm_start_with_lock(self):
        with self.patchobject(self.thm, 'start_with_acquired_lock'):
            mock_thread_lock = mock.Mock()
            mock_thread_lock.__enter__ = mock.Mock(return_value=None)
            mock_thread_lock.__exit__ = mock.Mock(return_value=None)
            self.lock_mock.thread_lock.return_value = mock_thread_lock
            self.thm.start_with_lock(self.cnxt, self.stack,
                                     self.engine_id, self.f,
                                     *self.fargs, **self.fkwargs)
            self.stlock_mock.StackLock.assert_called_with(self.cnxt,
                                                          self.stack.id,
                                                          self.engine_id)

            self.thm.start_with_acquired_lock.assert_called_once_with(
                self.stack, self.lock_mock,
                self.f, *self.fargs, **self.fkwargs)

    def test_tgm_start(self):
        ret = self.thm.start(self.stack_id, self.f,
                             *self.fargs, **self.fkwargs)

        self.assertEqual(self.tg_mock, self.thm.groups['test'])
        self.tg_mock.add_thread.assert_called_with(
            self.thm._start_with_trace, context.get_current(), None,
            self.f, *self.fargs, **self.fkwargs)
        self.assertEqual(ret, self.tg_mock.add_thread())

    def test_tgm_add_timer(self):
        self.thm.add_timer(self.stack_id, self.f,
                           *self.fargs, **self.fkwargs)

        self.assertEqual(self.tg_mock,
                         self.thm.groups[self.stack_id])
        self.tg_mock.add_timer.assert_called_with(
            self.cfg_mock.CONF.periodic_interval,
            self.f, None, *self.fargs, **self.fkwargs)

    def test_tgm_add_msg_queue(self):
        e1, e2 = mock.Mock(), mock.Mock()
        self.thm.add_msg_queue(self.stack_id, e1)
        self.thm.add_msg_queue(self.stack_id, e2)
        self.assertEqual([e1, e2],
                         self.thm.msg_queues[self.stack_id])

    def test_tgm_remove_msg_queue(self):
        e1, e2 = mock.Mock(), mock.Mock()
        self.thm.add_msg_queue(self.stack_id, e1)
        self.thm.add_msg_queue(self.stack_id, e2)
        self.thm.remove_msg_queue(None, self.stack_id, e2)
        self.assertEqual([e1], self.thm.msg_queues[self.stack_id])
        self.thm.remove_msg_queue(None, self.stack_id, e1)
        self.assertNotIn(self.stack_id, self.thm.msg_queues)

    def test_tgm_send(self):
        e1, e2 = mock.MagicMock(), mock.Mock()
        self.thm.add_msg_queue(self.stack_id, e1)
        self.thm.add_msg_queue(self.stack_id, e2)
        self.thm.send(self.stack_id, 'test_message')


class ThreadGroupManagerStopTest(common.HeatTestCase):
    def test_tgm_stop(self):
        stack_id = 'test'
        done = []
        stop_flag = threading.Event()

        def function():
            while not stop_flag.is_set():  # Make the loop breakable
                time.sleep(0.1)  # Shorter sleep for faster test

        def linked(gt, thread):
            for i in range(10):
                time.sleep(0)
            done.append(thread)

        thm = service.ThreadGroupManager()
        thm.add_msg_queue(stack_id, mock.Mock())
        thread = thm.start(stack_id, function)
        thread.link(linked, thread)

        stop_flag.set()  # Ensure thread stops
        # Wait with timeout instead of fixed sleep
        for _ in range(50):  # 5 second timeout (50 * 0.1)
            if thread in done:
                break
            time.sleep(0.1)

        self.assertIn(thread, done)
        thm.stop(stack_id)
        self.assertNotIn(stack_id, thm.groups)
        self.assertNotIn(stack_id, thm.msg_queues)
