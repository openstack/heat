# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import mox

import eventlet

from heat.engine import scheduler


class DummyTask(object):
    def __init__(self, num_steps=3):
        self.num_steps = num_steps

    def __call__(self, *args, **kwargs):
        for i in range(1, self.num_steps + 1):
            self.do_step(i)
            yield

    def do_step(self, step_num):
        print self, step_num


class TaskTest(mox.MoxTestBase):

    def test_run(self):
        task = DummyTask()
        self.mox.StubOutWithMock(task, 'do_step')
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        task.do_step(1).AndReturn(None)
        scheduler.TaskRunner._sleep(1).AndReturn(None)
        task.do_step(2).AndReturn(None)
        scheduler.TaskRunner._sleep(1).AndReturn(None)
        task.do_step(3).AndReturn(None)

        self.mox.ReplayAll()

        scheduler.TaskRunner(task)()

    def test_run_wait_time(self):
        task = DummyTask()
        self.mox.StubOutWithMock(task, 'do_step')
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        task.do_step(1).AndReturn(None)
        scheduler.TaskRunner._sleep(42).AndReturn(None)
        task.do_step(2).AndReturn(None)
        scheduler.TaskRunner._sleep(42).AndReturn(None)
        task.do_step(3).AndReturn(None)

        self.mox.ReplayAll()

        scheduler.TaskRunner(task)(wait_time=42)

    def test_start_run(self):
        task = DummyTask()
        self.mox.StubOutWithMock(task, 'do_step')
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        task.do_step(1).AndReturn(None)
        scheduler.TaskRunner._sleep(1).AndReturn(None)
        task.do_step(2).AndReturn(None)
        scheduler.TaskRunner._sleep(1).AndReturn(None)
        task.do_step(3).AndReturn(None)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task)
        runner.start()
        runner.run_to_completion()

    def test_start_run_wait_time(self):
        task = DummyTask()
        self.mox.StubOutWithMock(task, 'do_step')
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        task.do_step(1).AndReturn(None)
        scheduler.TaskRunner._sleep(24).AndReturn(None)
        task.do_step(2).AndReturn(None)
        scheduler.TaskRunner._sleep(24).AndReturn(None)
        task.do_step(3).AndReturn(None)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task)
        runner.start()
        runner.run_to_completion(wait_time=24)

    def test_sleep(self):
        sleep_time = 42
        self.mox.StubOutWithMock(eventlet, 'sleep')
        eventlet.sleep(sleep_time).MultipleTimes().AndReturn(None)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(DummyTask())
        runner(wait_time=sleep_time)

    def test_sleep_zero(self):
        self.mox.StubOutWithMock(eventlet, 'sleep')
        eventlet.sleep(0).MultipleTimes().AndReturn(None)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(DummyTask())
        runner(wait_time=0)

    def test_sleep_none(self):
        self.mox.StubOutWithMock(eventlet, 'sleep')
        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(DummyTask())
        runner(wait_time=None)

    def test_args(self):
        args = ['foo', 'bar']
        kwargs = {'baz': 'quux', 'blarg': 'wibble'}

        self.mox.StubOutWithMock(DummyTask, '__call__')
        task = DummyTask()

        task(*args, **kwargs)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task, *args, **kwargs)
        runner(wait_time=None)

    def test_non_callable(self):
        self.assertRaises(AssertionError, scheduler.TaskRunner, object())

    def test_stepping(self):
        task = DummyTask()
        self.mox.StubOutWithMock(task, 'do_step')
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        task.do_step(1).AndReturn(None)
        task.do_step(2).AndReturn(None)
        task.do_step(3).AndReturn(None)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task)
        runner.start()

        self.assertFalse(runner.step())
        self.assertTrue(runner)
        self.assertFalse(runner.step())
        self.assertTrue(runner.step())
        self.assertFalse(runner)

    def test_start_no_steps(self):
        task = DummyTask(0)
        self.mox.StubOutWithMock(task, 'do_step')
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task)
        runner.start()

        self.assertTrue(runner.done())
        self.assertTrue(runner.step())

    def test_start_only(self):
        task = DummyTask()
        self.mox.StubOutWithMock(task, 'do_step')
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        task.do_step(1).AndReturn(None)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task)

        self.assertFalse(runner.started())
        runner.start()
        self.assertTrue(runner.started())

    def test_double_start(self):
        runner = scheduler.TaskRunner(DummyTask())

        runner.start()
        self.assertRaises(AssertionError, runner.start)

    def test_call_double_start(self):
        runner = scheduler.TaskRunner(DummyTask())

        runner(wait_time=None)
        self.assertRaises(AssertionError, runner.start)

    def test_start_function(self):
        def task():
            pass

        runner = scheduler.TaskRunner(task)

        runner.start()
        self.assertTrue(runner.started())
        self.assertTrue(runner.done())
        self.assertTrue(runner.step())

    def test_repeated_done(self):
        task = DummyTask(0)
        self.mox.StubOutWithMock(task, 'do_step')
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task)

        runner.start()
        self.assertTrue(runner.step())
        self.assertTrue(runner.step())
