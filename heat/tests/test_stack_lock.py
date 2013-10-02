
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
import mox

from heat.common import exception
from heat.db import api as db_api
from heat.engine import stack_lock
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
        self.stack.timeout = 1

    def test_successful_acquire_new_lock(self):
        self.m.StubOutWithMock(db_api, "stack_lock_get")
        db_api.stack_lock_get(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(None)
        self.m.StubOutWithMock(db_api, "stack_lock_create")
        db_api.stack_lock_create(mox.IgnoreArg(), mox.IgnoreArg(),
                                 mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()
        slock = stack_lock.StackLock(self.context, self.stack)
        slock.acquire()
        self.m.VerifyAll()

    def test_successful_acquire_steal_lock_updated(self):
        existing_lock = self.m.CreateMockAnything()
        existing_lock.updated_at = datetime.datetime(2012, 10, 16, 18, 35, 18)
        current_time = datetime.datetime(2012, 10, 16, 18, 36, 29)
        self.m.StubOutWithMock(db_api, "current_timestamp")
        db_api.current_timestamp().AndReturn(current_time)
        self.m.StubOutWithMock(db_api, "stack_lock_get")
        db_api.stack_lock_get(mox.IgnoreArg(), mox.IgnoreArg())\
              .AndReturn(existing_lock)
        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(mox.IgnoreArg(), mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()
        slock = stack_lock.StackLock(self.context, self.stack)
        slock.acquire()
        self.m.VerifyAll()

    def test_successful_acquire_steal_lock_created(self):
        existing_lock = self.m.CreateMockAnything()
        existing_lock.updated_at = None
        existing_lock.created_at = datetime.datetime(2012, 10, 16, 18, 35, 18)
        current_time = datetime.datetime(2012, 10, 16, 18, 36, 29)
        self.m.StubOutWithMock(db_api, "current_timestamp")
        db_api.current_timestamp().AndReturn(current_time)
        self.m.StubOutWithMock(db_api, "stack_lock_get")
        db_api.stack_lock_get(mox.IgnoreArg(), mox.IgnoreArg())\
              .AndReturn(existing_lock)
        self.m.StubOutWithMock(db_api, "stack_lock_steal")
        db_api.stack_lock_steal(mox.IgnoreArg(), mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()
        slock = stack_lock.StackLock(self.context, self.stack)
        slock.acquire()
        self.m.VerifyAll()

    def test_failed_acquire(self):
        existing_lock = self.m.CreateMockAnything()
        existing_lock.updated_at = datetime.datetime(2012, 10, 16, 18, 35, 18)
        current_time = datetime.datetime(2012, 10, 16, 18, 35, 29)
        self.m.StubOutWithMock(db_api, "current_timestamp")
        db_api.current_timestamp().AndReturn(current_time)
        self.m.StubOutWithMock(db_api, "stack_lock_get")
        db_api.stack_lock_get(mox.IgnoreArg(), mox.IgnoreArg())\
              .AndReturn(existing_lock)
        self.m.ReplayAll()
        slock = stack_lock.StackLock(self.context, self.stack)
        self.assertRaises(exception.ActionInProgress, slock.acquire)
        self.m.VerifyAll()
