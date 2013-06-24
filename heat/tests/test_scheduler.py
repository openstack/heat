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

import contextlib
import eventlet

from heat.engine import dependencies
from heat.engine import scheduler


class DummyTask(object):
    def __init__(self, num_steps=3):
        self.num_steps = num_steps

    def __call__(self, *args, **kwargs):
        for i in range(1, self.num_steps + 1):
            self.do_step(i, *args, **kwargs)
            yield

    def do_step(self, step_num, *args, **kwargs):
        print(self, step_num)


class PollingTaskGroupTest(mox.MoxTestBase):

    def test_group(self):
        tasks = [DummyTask() for i in range(3)]
        for t in tasks:
            self.mox.StubOutWithMock(t, 'do_step')

        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        for t in tasks:
            t.do_step(1).AndReturn(None)
        for t in tasks:
            scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
            t.do_step(2).AndReturn(None)
            scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
            t.do_step(3).AndReturn(None)

        self.mox.ReplayAll()

        tg = scheduler.PollingTaskGroup(tasks)
        scheduler.TaskRunner(tg)()

    def test_kwargs(self):
        input_kwargs = {'i': [0, 1, 2],
                        'i2': [0, 1, 4]}

        output_kwargs = scheduler.PollingTaskGroup._kwargs(input_kwargs)

        expected_kwargs = [{'i': 0, 'i2': 0},
                           {'i': 1, 'i2': 1},
                           {'i': 2, 'i2': 4}]

        self.assertEqual(list(output_kwargs), expected_kwargs)

    def test_kwargs_short(self):
        input_kwargs = {'i': [0, 1, 2],
                        'i2': [0]}

        output_kwargs = scheduler.PollingTaskGroup._kwargs(input_kwargs)

        expected_kwargs = [{'i': 0, 'i2': 0}]

        self.assertEqual(list(output_kwargs), expected_kwargs)

    def test_no_kwargs(self):
        output_kwargs = scheduler.PollingTaskGroup._kwargs({})
        self.assertEqual(list(output_kwargs), [])

    def test_args(self):
        input_args = ([0, 1, 2],
                      [0, 1, 4])

        output_args = scheduler.PollingTaskGroup._args(input_args)

        expected_args = [(0, 0), (1, 1), (2, 4)]

        self.assertEqual(list(output_args), expected_args)

    def test_args_short(self):
        input_args = ([0, 1, 2],
                      [0])

        output_args = scheduler.PollingTaskGroup._args(input_args)

        expected_args = [(0, 0)]

        self.assertEqual(list(output_args), expected_args)

    def test_no_args(self):
        output_args = scheduler.PollingTaskGroup._args([])
        self.assertEqual(list(output_args), [])

    @contextlib.contextmanager
    def _args_test(self, *arg_lists, **kwarg_lists):
        dummy = DummyTask(1)

        tg = scheduler.PollingTaskGroup.from_task_with_args(dummy,
                                                            *arg_lists,
                                                            **kwarg_lists)

        self.mox.StubOutWithMock(dummy, 'do_step')
        yield dummy

        self.mox.ReplayAll()
        scheduler.TaskRunner(tg)(wait_time=None)
        self.mox.VerifyAll()

    def test_with_all_args(self):
        with self._args_test([0, 1, 2], [0, 1, 8],
                             i=[0, 1, 2], i2=[0, 1, 4]) as dummy:
            for i in range(3):
                dummy.do_step(1, i, i * i * i, i=i, i2=i * i)

    def test_with_short_args(self):
        with self._args_test([0, 1, 2], [0, 1],
                             i=[0, 1, 2], i2=[0, 1, 4]) as dummy:
            for i in range(2):
                dummy.do_step(1, i, i * i, i=i, i2=i * i)

    def test_with_short_kwargs(self):
        with self._args_test([0, 1, 2], [0, 1, 8],
                             i=[0, 1], i2=[0, 1, 4]) as dummy:
            for i in range(2):
                dummy.do_step(1, i, i * i, i=i, i2=i * i)

    def test_with_empty_args(self):
        with self._args_test([],
                             i=[0, 1, 2], i2=[0, 1, 4]) as dummy:
            pass

    def test_with_empty_kwargs(self):
        with self._args_test([0, 1, 2], [0, 1, 8],
                             i=[]) as dummy:
            pass

    def test_with_no_args(self):
        with self._args_test(i=[0, 1, 2], i2=[0, 1, 4]) as dummy:
            for i in range(3):
                dummy.do_step(1, i=i, i2=i * i)

    def test_with_no_kwargs(self):
        with self._args_test([0, 1, 2], [0, 1, 4]) as dummy:
            for i in range(3):
                dummy.do_step(1, i, i * i)


class DependencyTaskGroupTest(mox.MoxTestBase):

    @contextlib.contextmanager
    def _dep_test(self, *edges):
        dummy = DummyTask(getattr(self, 'steps', 3))

        deps = dependencies.Dependencies(edges)

        tg = scheduler.DependencyTaskGroup(deps, dummy)

        self.mox.StubOutWithMock(dummy, 'do_step')

        yield dummy

        self.mox.ReplayAll()
        scheduler.TaskRunner(tg)(wait_time=None)
        self.mox.VerifyAll()

    def test_no_steps(self):
        self.steps = 0
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        with self._dep_test(('second', 'first')) as dummy:
            scheduler.TaskRunner._sleep(None).AndReturn(None)

    def test_single_node(self):
        with self._dep_test(('only', None)) as dummy:
            dummy.do_step(1, 'only').AndReturn(None)
            dummy.do_step(2, 'only').AndReturn(None)
            dummy.do_step(3, 'only').AndReturn(None)

    def test_disjoint(self):
        with self._dep_test(('1', None), ('2', None)) as dummy:
            dummy.do_step(1, '1').InAnyOrder('1')
            dummy.do_step(1, '2').InAnyOrder('1')
            dummy.do_step(2, '1').InAnyOrder('2')
            dummy.do_step(2, '2').InAnyOrder('2')
            dummy.do_step(3, '1').InAnyOrder('3')
            dummy.do_step(3, '2').InAnyOrder('3')

    def test_single_fwd(self):
        with self._dep_test(('second', 'first')) as dummy:
            dummy.do_step(1, 'first').AndReturn(None)
            dummy.do_step(2, 'first').AndReturn(None)
            dummy.do_step(3, 'first').AndReturn(None)
            dummy.do_step(1, 'second').AndReturn(None)
            dummy.do_step(2, 'second').AndReturn(None)
            dummy.do_step(3, 'second').AndReturn(None)

    def test_chain_fwd(self):
        with self._dep_test(('third', 'second'),
                            ('second', 'first')) as dummy:
            dummy.do_step(1, 'first').AndReturn(None)
            dummy.do_step(2, 'first').AndReturn(None)
            dummy.do_step(3, 'first').AndReturn(None)
            dummy.do_step(1, 'second').AndReturn(None)
            dummy.do_step(2, 'second').AndReturn(None)
            dummy.do_step(3, 'second').AndReturn(None)
            dummy.do_step(1, 'third').AndReturn(None)
            dummy.do_step(2, 'third').AndReturn(None)
            dummy.do_step(3, 'third').AndReturn(None)

    def test_diamond_fwd(self):
        with self._dep_test(('last', 'mid1'), ('last', 'mid2'),
                            ('mid1', 'first'), ('mid2', 'first')) as dummy:
            dummy.do_step(1, 'first').AndReturn(None)
            dummy.do_step(2, 'first').AndReturn(None)
            dummy.do_step(3, 'first').AndReturn(None)
            dummy.do_step(1, 'mid1').InAnyOrder('1')
            dummy.do_step(1, 'mid2').InAnyOrder('1')
            dummy.do_step(2, 'mid1').InAnyOrder('2')
            dummy.do_step(2, 'mid2').InAnyOrder('2')
            dummy.do_step(3, 'mid1').InAnyOrder('3')
            dummy.do_step(3, 'mid2').InAnyOrder('3')
            dummy.do_step(1, 'last').AndReturn(None)
            dummy.do_step(2, 'last').AndReturn(None)
            dummy.do_step(3, 'last').AndReturn(None)

    def test_complex_fwd(self):
        with self._dep_test(('last', 'mid1'), ('last', 'mid2'),
                            ('mid1', 'mid3'), ('mid1', 'first'),
                            ('mid3', 'first'), ('mid2', 'first')) as dummy:
            dummy.do_step(1, 'first').AndReturn(None)
            dummy.do_step(2, 'first').AndReturn(None)
            dummy.do_step(3, 'first').AndReturn(None)
            dummy.do_step(1, 'mid2').InAnyOrder('1')
            dummy.do_step(1, 'mid3').InAnyOrder('1')
            dummy.do_step(2, 'mid2').InAnyOrder('2')
            dummy.do_step(2, 'mid3').InAnyOrder('2')
            dummy.do_step(3, 'mid2').InAnyOrder('3')
            dummy.do_step(3, 'mid3').InAnyOrder('3')
            dummy.do_step(1, 'mid1').AndReturn(None)
            dummy.do_step(2, 'mid1').AndReturn(None)
            dummy.do_step(3, 'mid1').AndReturn(None)
            dummy.do_step(1, 'last').AndReturn(None)
            dummy.do_step(2, 'last').AndReturn(None)
            dummy.do_step(3, 'last').AndReturn(None)

    def test_many_edges_fwd(self):
        with self._dep_test(('last', 'e1'), ('last', 'mid1'), ('last', 'mid2'),
                            ('mid1', 'e2'), ('mid1', 'mid3'),
                            ('mid2', 'mid3'),
                            ('mid3', 'e3')) as dummy:
            dummy.do_step(1, 'e1').InAnyOrder('1edges')
            dummy.do_step(1, 'e2').InAnyOrder('1edges')
            dummy.do_step(1, 'e3').InAnyOrder('1edges')
            dummy.do_step(2, 'e1').InAnyOrder('2edges')
            dummy.do_step(2, 'e2').InAnyOrder('2edges')
            dummy.do_step(2, 'e3').InAnyOrder('2edges')
            dummy.do_step(3, 'e1').InAnyOrder('3edges')
            dummy.do_step(3, 'e2').InAnyOrder('3edges')
            dummy.do_step(3, 'e3').InAnyOrder('3edges')
            dummy.do_step(1, 'mid3').AndReturn(None)
            dummy.do_step(2, 'mid3').AndReturn(None)
            dummy.do_step(3, 'mid3').AndReturn(None)
            dummy.do_step(1, 'mid2').InAnyOrder('1mid')
            dummy.do_step(1, 'mid1').InAnyOrder('1mid')
            dummy.do_step(2, 'mid2').InAnyOrder('2mid')
            dummy.do_step(2, 'mid1').InAnyOrder('2mid')
            dummy.do_step(3, 'mid2').InAnyOrder('3mid')
            dummy.do_step(3, 'mid1').InAnyOrder('3mid')
            dummy.do_step(1, 'last').AndReturn(None)
            dummy.do_step(2, 'last').AndReturn(None)
            dummy.do_step(3, 'last').AndReturn(None)

    def test_dbldiamond_fwd(self):
        with self._dep_test(('last', 'a1'), ('last', 'a2'),
                            ('a1', 'b1'), ('a2', 'b1'), ('a2', 'b2'),
                            ('b1', 'first'), ('b2', 'first')) as dummy:
            dummy.do_step(1, 'first').AndReturn(None)
            dummy.do_step(2, 'first').AndReturn(None)
            dummy.do_step(3, 'first').AndReturn(None)
            dummy.do_step(1, 'b1').InAnyOrder('1b')
            dummy.do_step(1, 'b2').InAnyOrder('1b')
            dummy.do_step(2, 'b1').InAnyOrder('2b')
            dummy.do_step(2, 'b2').InAnyOrder('2b')
            dummy.do_step(3, 'b1').InAnyOrder('3b')
            dummy.do_step(3, 'b2').InAnyOrder('3b')
            dummy.do_step(1, 'a1').InAnyOrder('1a')
            dummy.do_step(1, 'a2').InAnyOrder('1a')
            dummy.do_step(2, 'a1').InAnyOrder('2a')
            dummy.do_step(2, 'a2').InAnyOrder('2a')
            dummy.do_step(3, 'a1').InAnyOrder('3a')
            dummy.do_step(3, 'a2').InAnyOrder('3a')
            dummy.do_step(1, 'last').AndReturn(None)
            dummy.do_step(2, 'last').AndReturn(None)
            dummy.do_step(3, 'last').AndReturn(None)

    def test_circular_deps(self):
        d = dependencies.Dependencies([('first', 'second'),
                                       ('second', 'third'),
                                       ('third', 'first')])
        self.assertRaises(dependencies.CircularDependencyException,
                          scheduler.DependencyTaskGroup, d)


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

    def test_timeout(self):
        st = scheduler.wallclock()

        def task():
            while True:
                yield

        self.mox.StubOutWithMock(scheduler, 'wallclock')
        scheduler.wallclock().AndReturn(st)
        scheduler.wallclock().AndReturn(st + 0.5)
        scheduler.wallclock().AndReturn(st + 1.5)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task)

        runner.start(timeout=1)
        self.assertTrue(runner)
        self.assertRaises(scheduler.Timeout, runner.step)

        self.mox.VerifyAll()

    def test_timeout_return(self):
        st = scheduler.wallclock()

        def task():
            while True:
                try:
                    yield
                except scheduler.Timeout:
                    return

        self.mox.StubOutWithMock(scheduler, 'wallclock')
        scheduler.wallclock().AndReturn(st)
        scheduler.wallclock().AndReturn(st + 0.5)
        scheduler.wallclock().AndReturn(st + 1.5)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task)

        runner.start(timeout=1)
        self.assertTrue(runner)
        self.assertTrue(runner.step())
        self.assertFalse(runner)

        self.mox.VerifyAll()

    def test_timeout_swallowed(self):
        st = scheduler.wallclock()

        def task():
            while True:
                try:
                    yield
                except scheduler.Timeout:
                    yield
                    self.fail('Task still running')

        self.mox.StubOutWithMock(scheduler, 'wallclock')
        scheduler.wallclock().AndReturn(st)
        scheduler.wallclock().AndReturn(st + 0.5)
        scheduler.wallclock().AndReturn(st + 1.5)

        self.mox.ReplayAll()

        runner = scheduler.TaskRunner(task)

        runner.start(timeout=1)
        self.assertTrue(runner)
        self.assertTrue(runner.step())
        self.assertFalse(runner)
        self.assertTrue(runner.step())

        self.mox.VerifyAll()


class DescriptionTest(mox.MoxTestBase):
    def test_func(self):
        def f():
            pass

        self.assertEqual(scheduler.task_description(f), 'f')

    def test_lambda(self):
        l = lambda: None

        self.assertEqual(scheduler.task_description(l), '<lambda>')

    def test_method(self):
        class C(object):
            def __str__(self):
                return 'C "o"'

            def __repr__(self):
                return 'o'

            def m(self):
                pass

        self.assertEqual(scheduler.task_description(C().m), 'm from C "o"')

    def test_object(self):
        class C(object):
            def __str__(self):
                return 'C "o"'

            def __repr__(self):
                return 'o'

            def __call__(self):
                pass

        self.assertEqual(scheduler.task_description(C()), 'o')


class WrapperTaskTest(mox.MoxTestBase):

    def test_wrap(self):
        child_tasks = [DummyTask() for i in range(3)]

        @scheduler.wrappertask
        def task():
            for child_task in child_tasks:
                yield child_task()

            yield

        for child_task in child_tasks:
            self.mox.StubOutWithMock(child_task, 'do_step')
        self.mox.StubOutWithMock(scheduler.TaskRunner, '_sleep')

        for child_task in child_tasks:
            child_task.do_step(1).AndReturn(None)
            scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
            child_task.do_step(2).AndReturn(None)
            scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)
            child_task.do_step(3).AndReturn(None)
            scheduler.TaskRunner._sleep(mox.IsA(int)).AndReturn(None)

        self.mox.ReplayAll()

        scheduler.TaskRunner(task)()

    def test_child_exception(self):
        class MyException(Exception):
            pass

        def child_task():
            yield

            raise MyException()

        @scheduler.wrappertask
        def parent_task():
            try:
                yield child_task()
            except MyException:
                raise
            else:
                self.fail('No exception raised in parent_task')

        task = parent_task()
        task.next()
        self.assertRaises(MyException, task.next)

    def test_child_exception_exit(self):
        class MyException(Exception):
            pass

        def child_task():
            yield

            raise MyException()

        @scheduler.wrappertask
        def parent_task():
            try:
                yield child_task()
            except MyException:
                return
            else:
                self.fail('No exception raised in parent_task')

        task = parent_task()
        task.next()
        self.assertRaises(StopIteration, task.next)

    def test_child_exception_swallow(self):
        class MyException(Exception):
            pass

        def child_task():
            yield

            raise MyException()

        @scheduler.wrappertask
        def parent_task():
            try:
                yield child_task()
            except MyException:
                yield
            else:
                self.fail('No exception raised in parent_task')

            yield

        task = parent_task()
        task.next()
        task.next()

    def test_child_exception_swallow_next(self):
        class MyException(Exception):
            pass

        def child_task():
            yield

            raise MyException()

        dummy = DummyTask()

        @scheduler.wrappertask
        def parent_task():
            try:
                yield child_task()
            except MyException:
                pass
            else:
                self.fail('No exception raised in parent_task')

            yield dummy()

        task = parent_task()
        task.next()

        self.mox.StubOutWithMock(dummy, 'do_step')
        for i in range(1, dummy.num_steps + 1):
            dummy.do_step(i).AndReturn(None)
        self.mox.ReplayAll()

        for i in range(1, dummy.num_steps + 1):
            task.next()
        self.assertRaises(StopIteration, task.next)

    def test_thrown_exception_swallow_next(self):
        class MyException(Exception):
            pass

        dummy = DummyTask()

        @scheduler.wrappertask
        def child_task():
            try:
                yield
            except MyException:
                yield dummy()
            else:
                self.fail('No exception raised in child_task')

        @scheduler.wrappertask
        def parent_task():
            yield child_task()

        task = parent_task()

        self.mox.StubOutWithMock(dummy, 'do_step')
        for i in range(1, dummy.num_steps + 1):
            dummy.do_step(i).AndReturn(None)
        self.mox.ReplayAll()

        next(task)
        task.throw(MyException)

        for i in range(2, dummy.num_steps + 1):
            task.next()
        self.assertRaises(StopIteration, task.next)

    def test_thrown_exception_raise(self):
        class MyException(Exception):
            pass

        dummy = DummyTask()

        @scheduler.wrappertask
        def child_task():
            try:
                yield
            except MyException:
                raise
            else:
                self.fail('No exception raised in child_task')

        @scheduler.wrappertask
        def parent_task():
            try:
                yield child_task()
            except MyException:
                yield dummy()

        task = parent_task()

        self.mox.StubOutWithMock(dummy, 'do_step')
        for i in range(1, dummy.num_steps + 1):
            dummy.do_step(i).AndReturn(None)
        self.mox.ReplayAll()

        next(task)
        task.throw(MyException)

        for i in range(2, dummy.num_steps + 1):
            task.next()
        self.assertRaises(StopIteration, task.next)

    def test_thrown_exception_exit(self):
        class MyException(Exception):
            pass

        dummy = DummyTask()

        @scheduler.wrappertask
        def child_task():
            try:
                yield
            except MyException:
                return
            else:
                self.fail('No exception raised in child_task')

        @scheduler.wrappertask
        def parent_task():
            yield child_task()
            yield dummy()

        task = parent_task()

        self.mox.StubOutWithMock(dummy, 'do_step')
        for i in range(1, dummy.num_steps + 1):
            dummy.do_step(i).AndReturn(None)
        self.mox.ReplayAll()

        next(task)
        task.throw(MyException)

        for i in range(2, dummy.num_steps + 1):
            task.next()
        self.assertRaises(StopIteration, task.next)

    def test_parent_exception(self):
        class MyException(Exception):
            pass

        def child_task():
            yield

        @scheduler.wrappertask
        def parent_task():
            yield child_task()
            raise MyException()

        task = parent_task()
        task.next()
        self.assertRaises(MyException, task.next)

    def test_parent_throw(self):
        class MyException(Exception):
            pass

        @scheduler.wrappertask
        def parent_task():
            try:
                yield DummyTask()()
            except MyException:
                raise
            else:
                self.fail('No exception raised in parent_task')

        task = parent_task()
        task.next()
        self.assertRaises(MyException, task.throw, MyException())

    def test_parent_throw_exit(self):
        class MyException(Exception):
            pass

        @scheduler.wrappertask
        def parent_task():
            try:
                yield DummyTask()()
            except MyException:
                return
            else:
                self.fail('No exception raised in parent_task')

        task = parent_task()
        task.next()
        self.assertRaises(StopIteration, task.throw, MyException())

    def test_parent_cancel(self):
        @scheduler.wrappertask
        def parent_task():
            try:
                yield
            except GeneratorExit:
                raise
            else:
                self.fail('parent_task not closed')

        task = parent_task()
        task.next()
        task.close()

    def test_parent_cancel_exit(self):
        @scheduler.wrappertask
        def parent_task():
            try:
                yield
            except GeneratorExit:
                return
            else:
                self.fail('parent_task not closed')

        task = parent_task()
        task.next()
        task.close()

    def test_cancel(self):
        def child_task():
            try:
                yield
            except GeneratorExit:
                raise
            else:
                self.fail('child_task not closed')

        @scheduler.wrappertask
        def parent_task():
            try:
                yield child_task()
            except GeneratorExit:
                raise
            else:
                self.fail('parent_task not closed')

        task = parent_task()
        task.next()
        task.close()

    def test_cancel_exit(self):
        def child_task():
            try:
                yield
            except GeneratorExit:
                return
            else:
                self.fail('child_task not closed')

        @scheduler.wrappertask
        def parent_task():
            try:
                yield child_task()
            except GeneratorExit:
                raise
            else:
                self.fail('parent_task not closed')

        task = parent_task()
        task.next()
        task.close()

    def test_cancel_parent_exit(self):
        def child_task():
            try:
                yield
            except GeneratorExit:
                return
            else:
                self.fail('child_task not closed')

        @scheduler.wrappertask
        def parent_task():
            try:
                yield child_task()
            except GeneratorExit:
                return
            else:
                self.fail('parent_task not closed')

        task = parent_task()
        task.next()
        task.close()
