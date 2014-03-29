
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

from heat.common import exception
from heat.db import api as db_api
from heat.engine import stack_lock
from heat.openstack.common.rpc import common as rpc_common
from heat.openstack.common.rpc import proxy
from heat.tests.common import HeatTestCase
from heat.tests import utils


class StackLockTest(HeatTestCase):
    def setUp(self):
        super(StackLockTest, self).setUp()
        utils.setup_dummy_db()
        self.context = utils.dummy_context()
        self.stack = self.m.CreateMockAnything()
        self.stack.id = "aae01f2d-52ae-47ac-8a0d-3fde3d220fea"
        self.stack.name = "test_stack"
        self.stack.action = "CREATE"
        self.engine_id = stack_lock.StackLock.generate_engine_id()

    def test_successful_acquire_new_lock(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(self.stack.id, self.engine_id).\
            AndReturn(None)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        slock.acquire()
        self.m.VerifyAll()

    def test_failed_acquire_existing_lock_current_engine(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(self.stack.id, self.engine_id).\
            AndReturn(self.engine_id)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        self.assertRaises(exception.ActionInProgress, slock.acquire)
        self.m.VerifyAll()

    def test_successful_acquire_existing_lock_engine_dead(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(self.stack.id, self.engine_id).\
            AndReturn("fake-engine-id")

        topic = self.stack.id
        self.m.StubOutWithMock(proxy.RpcProxy, "call")
        rpc = proxy.RpcProxy(topic, "1.0")
        rpc.call(self.context, rpc.make_msg("listening"), timeout=2,
                 topic="fake-engine-id").AndRaise(rpc_common.Timeout)

        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(self.stack.id, "fake-engine-id",
                                self.engine_id).AndReturn(None)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        slock.acquire()
        self.m.VerifyAll()

    def test_failed_acquire_existing_lock_engine_alive(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(self.stack.id, self.engine_id).\
            AndReturn("fake-engine-id")

        topic = self.stack.id
        self.m.StubOutWithMock(proxy.RpcProxy, "call")
        rpc = proxy.RpcProxy(topic, "1.0")
        rpc.call(self.context, rpc.make_msg("listening"), timeout=2,
                 topic="fake-engine-id").AndReturn(True)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        self.assertRaises(exception.ActionInProgress, slock.acquire)
        self.m.VerifyAll()

    def test_failed_acquire_existing_lock_engine_dead(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(self.stack.id, self.engine_id).\
            AndReturn("fake-engine-id")

        topic = self.stack.id
        self.m.StubOutWithMock(proxy.RpcProxy, "call")
        rpc = proxy.RpcProxy(topic, "1.0")
        rpc.call(self.context, rpc.make_msg("listening"), timeout=2,
                 topic="fake-engine-id").AndRaise(rpc_common.Timeout)

        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(self.stack.id, "fake-engine-id",
                                self.engine_id).\
            AndReturn("fake-engine-id2")

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        self.assertRaises(exception.ActionInProgress, slock.acquire)
        self.m.VerifyAll()

    def test_successful_acquire_with_retry(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(self.stack.id, self.engine_id).\
            AndReturn("fake-engine-id")

        topic = self.stack.id
        self.m.StubOutWithMock(proxy.RpcProxy, "call")
        rpc = proxy.RpcProxy(topic, "1.0")
        rpc.call(self.context, rpc.make_msg("listening"), timeout=2,
                 topic="fake-engine-id").AndRaise(rpc_common.Timeout)

        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(self.stack.id, "fake-engine-id",
                                self.engine_id).\
            AndReturn(True)

        db_api.stack_lock_create(self.stack.id, self.engine_id).\
            AndReturn("fake-engine-id")

        topic = self.stack.id
        rpc = proxy.RpcProxy(topic, "1.0")
        rpc.call(self.context, rpc.make_msg("listening"), timeout=2,
                 topic="fake-engine-id").AndRaise(rpc_common.Timeout)

        db_api.stack_lock_steal(self.stack.id, "fake-engine-id",
                                self.engine_id).\
            AndReturn(None)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        slock.acquire()
        self.m.VerifyAll()

    def test_failed_acquire_one_retry_only(self):
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(self.stack.id, self.engine_id).\
            AndReturn("fake-engine-id")

        topic = self.stack.id
        self.m.StubOutWithMock(proxy.RpcProxy, "call")
        rpc = proxy.RpcProxy(topic, "1.0")
        rpc.call(self.context, rpc.make_msg("listening"), timeout=2,
                 topic="fake-engine-id").AndRaise(rpc_common.Timeout)

        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(self.stack.id, "fake-engine-id",
                                self.engine_id).\
            AndReturn(True)

        db_api.stack_lock_create(self.stack.id, self.engine_id).\
            AndReturn("fake-engine-id")

        topic = self.stack.id
        rpc = proxy.RpcProxy(topic, "1.0")
        rpc.call(self.context, rpc.make_msg("listening"), timeout=2,
                 topic="fake-engine-id").AndRaise(rpc_common.Timeout)

        db_api.stack_lock_steal(self.stack.id, "fake-engine-id",
                                self.engine_id).\
            AndReturn(True)

        self.m.ReplayAll()

        slock = stack_lock.StackLock(self.context, self.stack, self.engine_id)
        self.assertRaises(exception.ActionInProgress, slock.acquire)
        self.m.VerifyAll()
