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

import mock

from oslo import messaging

from heat.common import exception
from heat.db import api as db_api
from heat.engine import stack_lock
from heat.tests.common import HeatTestCase
from heat.tests import utils


class StackLockTest(HeatTestCase):
    def setUp(self):
        super(StackLockTest, self).setUp()
        self.context = utils.dummy_context()
        self.stack = self.m.CreateMockAnything()
        self.stack.id = "aae01f2d-52ae-47ac-8a0d-3fde3d220fea"
        self.stack.name = "test_stack"
        self.stack.action = "CREATE"
        self.engine_id = stack_lock.StackLock.generate_engine_id()

    class TestThreadLockException(Exception):
            pass

    def test_successful_acquire_new_lock(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(
            self.stack.id, self.engine_id).AndReturn(None)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        slock.acquire()
        self.m.VerifyAll()

    def test_failed_acquire_existing_lock_current_engine(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(
            self.stack.id, self.engine_id).AndReturn(self.engine_id)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        self.assertRaises(exception.ActionInProgress, slock.acquire)
        self.m.VerifyAll()

    def test_successful_acquire_existing_lock_engine_dead(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(
            self.stack.id, self.engine_id).AndReturn("fake-engine-id")

        self.m.StubOutWithMock(messaging.rpc.client._CallContext, "call")
        messaging.rpc.client._CallContext.call(
            self.context, "listening").AndRaise(messaging.MessagingTimeout)

        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(self.stack.id, "fake-engine-id",
                                self.engine_id).AndReturn(None)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        slock.acquire()
        self.m.VerifyAll()

    def test_failed_acquire_existing_lock_engine_alive(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(
            self.stack.id, self.engine_id).AndReturn("fake-engine-id")

        self.m.StubOutWithMock(messaging.rpc.client._CallContext, "call")
        messaging.rpc.client._CallContext.call(
            self.context, "listening").AndReturn(True)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        self.assertRaises(exception.ActionInProgress, slock.acquire)
        self.m.VerifyAll()

    def test_failed_acquire_existing_lock_engine_dead(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(
            self.stack.id, self.engine_id).AndReturn("fake-engine-id")

        self.m.StubOutWithMock(messaging.rpc.client._CallContext, "call")
        messaging.rpc.client._CallContext.call(
            self.context, "listening").AndRaise(messaging.MessagingTimeout)

        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(
            self.stack.id, "fake-engine-id",
            self.engine_id).AndReturn("fake-engine-id2")

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        self.assertRaises(exception.ActionInProgress, slock.acquire)
        self.m.VerifyAll()

    def test_successful_acquire_with_retry(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(
            self.stack.id, self.engine_id).AndReturn("fake-engine-id")

        self.m.StubOutWithMock(messaging.rpc.client._CallContext, "call")
        messaging.rpc.client._CallContext.call(
            self.context, "listening").AndRaise(messaging.MessagingTimeout)

        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(
            self.stack.id, "fake-engine-id", self.engine_id).AndReturn(True)

        db_api.stack_lock_create(
            self.stack.id, self.engine_id).AndReturn("fake-engine-id")

        messaging.rpc.client._CallContext.call(
            self.context, "listening").AndRaise(messaging.MessagingTimeout)

        db_api.stack_lock_steal(
            self.stack.id, "fake-engine-id", self.engine_id).AndReturn(None)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        slock.acquire()
        self.m.VerifyAll()

    def test_failed_acquire_one_retry_only(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(
            self.stack.id, self.engine_id).AndReturn("fake-engine-id")

        self.m.StubOutWithMock(messaging.rpc.client._CallContext, "call")
        messaging.rpc.client._CallContext.call(
            self.context, "listening").AndRaise(messaging.MessagingTimeout)

        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(
            self.stack.id, "fake-engine-id", self.engine_id).AndReturn(True)

        db_api.stack_lock_create(
            self.stack.id, self.engine_id).AndReturn("fake-engine-id")

        messaging.rpc.client._CallContext.call(
            self.context, "listening").AndRaise(messaging.MessagingTimeout)

        db_api.stack_lock_steal(
            self.stack.id, "fake-engine-id", self.engine_id).AndReturn(True)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        self.assertRaises(exception.ActionInProgress, slock.acquire)
        self.m.VerifyAll()

    def test_thread_lock_context_mgr_exception(self):
        db_api.stack_lock_create = mock.Mock(return_value=None)
        db_api.stack_lock_release = mock.Mock(return_value=None)
        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)

        def check_thread_lock():
            with slock.thread_lock(self.stack.id):
                self.assertEqual(1, db_api.stack_lock_create.call_count)
                raise self.TestThreadLockException
        self.assertRaises(self.TestThreadLockException, check_thread_lock)
        self.assertEqual(1, db_api.stack_lock_release.call_count)

    def test_thread_lock_context_mgr_no_exception(self):
        db_api.stack_lock_create = mock.Mock(return_value=None)
        db_api.stack_lock_release = mock.Mock(return_value=None)
        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        with slock.thread_lock(self.stack.id):
            self.assertEqual(1, db_api.stack_lock_create.call_count)
        assert not db_api.stack_lock_release.called

    def test_try_thread_lock_context_mgr_exception(self):
        db_api.stack_lock_create = mock.Mock(return_value=None)
        db_api.stack_lock_release = mock.Mock(return_value=None)
        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)

        def check_thread_lock():
            with slock.try_thread_lock(self.stack.id):
                self.assertEqual(1, db_api.stack_lock_create.call_count)
                raise self.TestThreadLockException
        self.assertRaises(self.TestThreadLockException, check_thread_lock)
        self.assertEqual(1, db_api.stack_lock_release.call_count)

    def test_try_thread_lock_context_mgr_no_exception(self):
        db_api.stack_lock_create = mock.Mock(return_value=None)
        db_api.stack_lock_release = mock.Mock(return_value=None)
        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        with slock.try_thread_lock(self.stack.id):
            self.assertEqual(1, db_api.stack_lock_create.call_count)
        assert not db_api.stack_lock_release.called

    def test_try_thread_lock_context_mgr_existing_lock(self):
        db_api.stack_lock_create = mock.Mock(return_value=1234)
        db_api.stack_lock_release = mock.Mock(return_value=None)
        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)

        def check_thread_lock():
            with slock.try_thread_lock(self.stack.id):
                self.assertEqual(1, db_api.stack_lock_create.call_count)
                raise self.TestThreadLockException
        self.assertRaises(self.TestThreadLockException, check_thread_lock)
        assert not db_api.stack_lock_release.called
