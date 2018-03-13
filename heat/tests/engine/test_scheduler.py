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

import contextlib
import itertools

import eventlet
import mock
import six

from heat.common.i18n import repr_wrapper
from heat.common import timeutils
from heat.engine import dependencies
from heat.engine import scheduler
from heat.tests import common


class DummyTask(object):
    def __init__(self, num_steps=3, delays=None):
        self.num_steps = num_steps
        if delays is not None:
            self.delays = iter(delays)
        else:
            self.delays = itertools.repeat(None)

    def __call__(self, *args, **kwargs):
        for i in range(1, self.num_steps + 1):
            self.do_step(i, *args, **kwargs)
            yield next(self.delays)

    def do_step(self, step_num, *args, **kwargs):
        pass


class ExceptionGroupTest(common.HeatTestCase):

    def test_contains_exceptions(self):
        exception_group = scheduler.ExceptionGroup()
        self.assertIsInstance(exception_group.exceptions, list)

    def test_can_be_initialized_with_a_list_of_exceptions(self):
        ex1 = Exception("ex 1")
        ex2 = Exception("ex 2")

        exception_group = scheduler.ExceptionGroup([ex1, ex2])
        self.assertIn(ex1, exception_group.exceptions)
        self.assertIn(ex2, exception_group.exceptions)

    def test_can_add_exceptions_after_init(self):
        ex = Exception()
        exception_group = scheduler.ExceptionGroup()

        exception_group.exceptions.append(ex)
        self.assertIn(ex, exception_group.exceptions)

    def test_str_representation_aggregates_all_exceptions(self):
        ex1 = Exception("ex 1")
        ex2 = Exception("ex 2")

        exception_group = scheduler.ExceptionGroup([ex1, ex2])
        self.assertEqual("['ex 1', 'ex 2']", six.text_type(exception_group))


class StepTracker(object):
    def __init__(self):
        self.expected_groups = []
        self.side_effects = {}

    def expect_call_group(self, step_num, targets):
        self.expected_groups.append(set((step_num, t) for t in targets))

    def expect_call(self, step_num, target):
        self.expect_call_group(step_num, (target,))

    def raise_on(self, step_num, target, exc):
        self.side_effects[(step_num, target)] = exc

    def sleep_on(self, step_num, target, sleep_time):
        self.side_effects[(step_num, target)] = float(sleep_time)

    def side_effect(self, step_num, target):
        se = self.side_effects.get((step_num, target), None)
        if isinstance(se, BaseException):
            raise se
        if isinstance(se, float):
            eventlet.sleep(se)

    def verify_calls(self, mock_step):
        actual_calls = mock_step.mock_calls
        CallList = type(actual_calls)
        idx = 0

        try:
            for group in self.expected_groups:
                group_len = len(group)
                group_actual = CallList(actual_calls[idx:idx + group_len])
                idx += group_len
                mock_step.mock_calls = group_actual
                mock_step.assert_has_calls(
                    [mock.call(s, t) for s, t in group],
                    any_order=True)
        finally:
            mock_step.actual_calls = actual_calls

        if len(actual_calls) > idx:
            raise AssertionError("Unexpected calls: %s" %
                                 CallList(actual_calls[idx:]))


class DependencyTaskGroupTest(common.HeatTestCase):
    def setUp(self):
        super(DependencyTaskGroupTest, self).setUp()
        self.aggregate_exceptions = False
        self.error_wait_time = None
        self.reverse_order = False

    @contextlib.contextmanager
    def _dep_test(self, *edges):
        dummy = DummyTask(getattr(self, 'steps', 3))

        deps = dependencies.Dependencies(edges)

        tg = scheduler.DependencyTaskGroup(
            deps, dummy, reverse=self.reverse_order,
            error_wait_time=self.error_wait_time,
            aggregate_exceptions=self.aggregate_exceptions)

        tracker = StepTracker()

        yield tracker

        dummy.do_step = mock.Mock(side_effect=tracker.side_effect)
        scheduler.TaskRunner(tg)(wait_time=None)

        tracker.verify_calls(dummy.do_step)

    def test_test(self):
        def failing_test():
            with self._dep_test(('only', None)) as track:
                track.expect_call(1, 'only')
                track.expect_call(3, 'only')

        self.assertRaises(AssertionError, failing_test)

    @mock.patch.object(scheduler.TaskRunner, '_sleep')
    def test_no_steps(self, mock_sleep):
        self.steps = 0
        with self._dep_test(('second', 'first')):
            pass

    def test_single_node(self):
        with self._dep_test(('only', None)) as track:
            track.expect_call(1, 'only')
            track.expect_call(2, 'only')
            track.expect_call(3, 'only')

    def test_disjoint(self):
        with self._dep_test(('1', None), ('2', None)) as track:
            track.expect_call_group(1, ('1', '2'))
            track.expect_call_group(2, ('1', '2'))
            track.expect_call_group(3, ('1', '2'))

    def test_single_fwd(self):
        with self._dep_test(('second', 'first')) as track:
            track.expect_call(1, 'first')
            track.expect_call(2, 'first')
            track.expect_call(3, 'first')
            track.expect_call(1, 'second')
            track.expect_call(2, 'second')
            track.expect_call(3, 'second')

    def test_chain_fwd(self):
        with self._dep_test(('third', 'second'),
                            ('second', 'first')) as track:
            track.expect_call(1, 'first')
            track.expect_call(2, 'first')
            track.expect_call(3, 'first')
            track.expect_call(1, 'second')
            track.expect_call(2, 'second')
            track.expect_call(3, 'second')
            track.expect_call(1, 'third')
            track.expect_call(2, 'third')
            track.expect_call(3, 'third')

    def test_diamond_fwd(self):
        with self._dep_test(('last', 'mid1'), ('last', 'mid2'),
                            ('mid1', 'first'), ('mid2', 'first')) as track:
            track.expect_call(1, 'first')
            track.expect_call(2, 'first')
            track.expect_call(3, 'first')
            track.expect_call_group(1, ('mid1', 'mid2'))
            track.expect_call_group(2, ('mid1', 'mid2'))
            track.expect_call_group(3, ('mid1', 'mid2'))
            track.expect_call(1, 'last')
            track.expect_call(2, 'last')
            track.expect_call(3, 'last')

    def test_complex_fwd(self):
        with self._dep_test(('last', 'mid1'), ('last', 'mid2'),
                            ('mid1', 'mid3'), ('mid1', 'first'),
                            ('mid3', 'first'), ('mid2', 'first')) as track:
            track.expect_call(1, 'first')
            track.expect_call(2, 'first')
            track.expect_call(3, 'first')
            track.expect_call_group(1, ('mid2', 'mid3'))
            track.expect_call_group(2, ('mid2', 'mid3'))
            track.expect_call_group(3, ('mid2', 'mid3'))
            track.expect_call(1, 'mid1')
            track.expect_call(2, 'mid1')
            track.expect_call(3, 'mid1')
            track.expect_call(1, 'last')
            track.expect_call(2, 'last')
            track.expect_call(3, 'last')

    def test_many_edges_fwd(self):
        with self._dep_test(('last', 'e1'), ('last', 'mid1'), ('last', 'mid2'),
                            ('mid1', 'e2'), ('mid1', 'mid3'),
                            ('mid2', 'mid3'),
                            ('mid3', 'e3')) as track:
            track.expect_call_group(1, ('e1', 'e2', 'e3'))
            track.expect_call_group(2, ('e1', 'e2', 'e3'))
            track.expect_call_group(3, ('e1', 'e2', 'e3'))
            track.expect_call(1, 'mid3')
            track.expect_call(2, 'mid3')
            track.expect_call(3, 'mid3')
            track.expect_call_group(1, ('mid2', 'mid1'))
            track.expect_call_group(2, ('mid2', 'mid1'))
            track.expect_call_group(3, ('mid2', 'mid1'))
            track.expect_call(1, 'last')
            track.expect_call(2, 'last')
            track.expect_call(3, 'last')

    def test_dbldiamond_fwd(self):
        with self._dep_test(('last', 'a1'), ('last', 'a2'),
                            ('a1', 'b1'), ('a2', 'b1'), ('a2', 'b2'),
                            ('b1', 'first'), ('b2', 'first')) as track:
            track.expect_call(1, 'first')
            track.expect_call(2, 'first')
            track.expect_call(3, 'first')
            track.expect_call_group(1, ('b1', 'b2'))
            track.expect_call_group(2, ('b1', 'b2'))
            track.expect_call_group(3, ('b1', 'b2'))
            track.expect_call_group(1, ('a1', 'a2'))
            track.expect_call_group(2, ('a1', 'a2'))
            track.expect_call_group(3, ('a1', 'a2'))
            track.expect_call(1, 'last')
            track.expect_call(2, 'last')
            track.expect_call(3, 'last')

    def test_circular_deps(self):
        d = dependencies.Dependencies([('first', 'second'),
                                       ('second', 'third'),
                                       ('third', 'first')])
        self.assertRaises(dependencies.CircularDependencyException,
                          scheduler.DependencyTaskGroup, d)

    def test_aggregate_exceptions_raises_all_at_the_end(self):
        def run_tasks_with_exceptions(e1=None, e2=None):
            self.aggregate_exceptions = True
            tasks = (('A', None), ('B', None), ('C', None))
            with self._dep_test(*tasks) as track:
                track.expect_call_group(1, ('A', 'B', 'C'))
                track.raise_on(1, 'C', e1)

                track.expect_call_group(2, ('A', 'B'))
                track.raise_on(2, 'B', e2)

                track.expect_call(3, 'A')

        e1 = Exception('e1')
        e2 = Exception('e2')

        exc = self.assertRaises(scheduler.ExceptionGroup,
                                run_tasks_with_exceptions, e1, e2)
        self.assertEqual(set([e1, e2]), set(exc.exceptions))

    def test_aggregate_exceptions_cancels_dependent_tasks_recursively(self):
        def run_tasks_with_exceptions(e1=None, e2=None):
            self.aggregate_exceptions = True
            tasks = (('A', None), ('B', 'A'), ('C', 'B'))
            with self._dep_test(*tasks) as track:
                track.expect_call(1, 'A')
                track.raise_on(1, 'A', e1)

        e1 = Exception('e1')

        exc = self.assertRaises(scheduler.ExceptionGroup,
                                run_tasks_with_exceptions, e1)
        self.assertEqual([e1], exc.exceptions)

    def test_aggregate_exceptions_cancels_tasks_in_reverse_order(self):
        def run_tasks_with_exceptions(e1=None, e2=None):
            self.reverse_order = True
            self.aggregate_exceptions = True
            tasks = (('A', None), ('B', 'A'), ('C', 'B'))
            with self._dep_test(*tasks) as track:
                track.expect_call(1, 'C')
                track.raise_on(1, 'C', e1)

        e1 = Exception('e1')

        exc = self.assertRaises(scheduler.ExceptionGroup,
                                run_tasks_with_exceptions, e1)
        self.assertEqual([e1], exc.exceptions)

    def test_exceptions_on_cancel(self):
        class TestException(Exception):
            pass

        class ExceptionOnExit(Exception):
            pass

        cancelled = []

        def task_func(arg):
            for i in range(4):
                if i > 1:
                    raise TestException

                try:
                    yield
                except GeneratorExit:
                    cancelled.append(arg)
                    raise ExceptionOnExit

        tasks = (('A', None), ('B', None), ('C', None))
        deps = dependencies.Dependencies(tasks)

        tg = scheduler.DependencyTaskGroup(deps, task_func)
        task = tg()

        next(task)
        next(task)
        self.assertRaises(TestException, next, task)
        self.assertEqual(len(tasks) - 1, len(cancelled))

    def test_exception_grace_period(self):
        e1 = Exception('e1')

        def run_tasks_with_exceptions():
            self.error_wait_time = 5
            tasks = (('A', None), ('B', None), ('C', 'A'))
            with self._dep_test(*tasks) as track:
                track.expect_call_group(1, ('A', 'B'))
                track.expect_call_group(2, ('A', 'B'))
                track.raise_on(2, 'B', e1)
                track.expect_call(3, 'B')

        exc = self.assertRaises(type(e1), run_tasks_with_exceptions)
        self.assertEqual(e1, exc)

    def test_exception_grace_period_expired(self):
        e1 = Exception('e1')

        def run_tasks_with_exceptions():
            self.steps = 5
            self.error_wait_time = 0.05

            def sleep():
                eventlet.sleep(self.error_wait_time)

            tasks = (('A', None), ('B', None), ('C', 'A'))
            with self._dep_test(*tasks) as track:
                track.expect_call_group(1, ('A', 'B'))
                track.expect_call_group(2, ('A', 'B'))
                track.raise_on(2, 'B', e1)
                track.expect_call(3, 'B')
                track.expect_call(4, 'B')
                track.sleep_on(4, 'B', self.error_wait_time)

        exc = self.assertRaises(type(e1), run_tasks_with_exceptions)
        self.assertEqual(e1, exc)

    def test_exception_grace_period_per_task(self):
        e1 = Exception('e1')

        def get_wait_time(key):
            if key == 'B':
                return 5
            else:
                return None

        def run_tasks_with_exceptions():
            self.error_wait_time = get_wait_time
            tasks = (('A', None), ('B', None), ('C', 'A'))
            with self._dep_test(*tasks) as track:
                track.expect_call_group(1, ('A', 'B'))
                track.expect_call_group(2, ('A', 'B'))
                track.raise_on(2, 'A', e1)
                track.expect_call(3, 'B')

        exc = self.assertRaises(type(e1), run_tasks_with_exceptions)
        self.assertEqual(e1, exc)

    def test_thrown_exception_order(self):
        e1 = Exception('e1')
        e2 = Exception('e2')

        tasks = (('A', None), ('B', None), ('C', 'A'))
        deps = dependencies.Dependencies(tasks)

        tg = scheduler.DependencyTaskGroup(
            deps, DummyTask(), reverse=self.reverse_order,
            error_wait_time=1,
            aggregate_exceptions=self.aggregate_exceptions)
        task = tg()

        next(task)
        task.throw(e1)
        next(task)
        tg.error_wait_time = None
        exc = self.assertRaises(type(e2), task.throw, e2)
        self.assertIs(e2, exc)


class TaskTest(common.HeatTestCase):

    def setUp(self):
        super(TaskTest, self).setUp()
        scheduler.ENABLE_SLEEP = True
        self.mock_sleep = self.patchobject(scheduler.TaskRunner, '_sleep',
                                           return_value=None)

    def test_run(self):
        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        scheduler.TaskRunner(task)()

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.assertEqual(3, self.mock_sleep.call_count)

    def test_run_as_task(self):
        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        tr = scheduler.TaskRunner(task)
        rt = tr.as_task()
        for step in rt:
            pass
        self.assertTrue(tr.done())

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_not_called()

    def test_run_as_task_started(self):
        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        tr = scheduler.TaskRunner(task)
        tr.start()
        for step in tr.as_task():
            pass
        self.assertTrue(tr.done())

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_not_called()

    def test_run_as_task_cancel(self):
        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        tr = scheduler.TaskRunner(task)
        rt = tr.as_task()
        next(rt)
        rt.close()

        self.assertTrue(tr.done())

        task.do_step.assert_called_once_with(1)
        self.mock_sleep.assert_not_called()

    def test_run_as_task_exception(self):
        class TestException(Exception):
            pass

        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        tr = scheduler.TaskRunner(task)
        rt = tr.as_task()
        next(rt)
        self.assertRaises(TestException, rt.throw, TestException)

        self.assertTrue(tr.done())

        task.do_step.assert_called_once_with(1)
        self.mock_sleep.assert_not_called()

    def test_run_as_task_swallow_exception(self):
        class TestException(Exception):
            pass

        def task():
            try:
                yield
            except TestException:
                yield

        tr = scheduler.TaskRunner(task)
        rt = tr.as_task()
        next(rt)
        rt.throw(TestException)

        self.assertFalse(tr.done())
        self.assertRaises(StopIteration, next, rt)
        self.assertTrue(tr.done())

    def test_run_delays(self):
        task = DummyTask(delays=itertools.repeat(2))
        task.do_step = mock.Mock(return_value=None)

        scheduler.TaskRunner(task)()

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_has_calls([mock.call(0),
                                          mock.call(1),
                                          mock.call(1),
                                          mock.call(1),
                                          mock.call(1),
                                          mock.call(1)])
        self.assertEqual(6, self.mock_sleep.call_count)

    def test_run_delays_dynamic(self):
        task = DummyTask(delays=[2, 4, 1])
        task.do_step = mock.Mock(return_value=None)

        scheduler.TaskRunner(task)()

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_has_calls([mock.call(0),
                                          mock.call(1),
                                          mock.call(1),
                                          mock.call(1),
                                          mock.call(1),
                                          mock.call(1),
                                          mock.call(1)])
        self.assertEqual(7, self.mock_sleep.call_count)

    def test_run_wait_time(self):
        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        scheduler.TaskRunner(task)(wait_time=42)

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_has_calls([mock.call(0),
                                          mock.call(42),
                                          mock.call(42)])
        self.assertEqual(3, self.mock_sleep.call_count)

    def test_start_run(self):
        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)
        runner.start()
        runner.run_to_completion()

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_has_calls([mock.call(1), mock.call(1)])
        self.assertEqual(2, self.mock_sleep.call_count)

    def test_start_run_wait_time(self):
        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)
        runner.start()
        runner.run_to_completion(wait_time=24)

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_has_calls([mock.call(24), mock.call(24)])
        self.assertEqual(2, self.mock_sleep.call_count)

    def test_run_progress(self):
        progress_count = []

        def progress():
            progress_count.append(None)

        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        scheduler.TaskRunner(task)(progress_callback=progress)
        self.assertEqual(task.num_steps, len(progress_count))

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_has_calls([mock.call(0),
                                          mock.call(1),
                                          mock.call(1)])
        self.assertEqual(3, self.mock_sleep.call_count)

    def test_start_run_progress(self):
        progress_count = []

        def progress():
            progress_count.append(None)

        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)
        runner.start()
        runner.run_to_completion(progress_callback=progress)
        self.assertEqual(task.num_steps - 1, len(progress_count))

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_has_calls([mock.call(1), mock.call(1)])
        self.assertEqual(2, self.mock_sleep.call_count)

    def test_run_as_task_progress(self):
        progress_count = []

        def progress():
            progress_count.append(None)

        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        tr = scheduler.TaskRunner(task)
        rt = tr.as_task(progress_callback=progress)
        for step in rt:
            pass
        self.assertEqual(task.num_steps, len(progress_count))

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_not_called()

    def test_run_progress_exception(self):
        class TestException(Exception):
            pass

        progress_count = []

        def progress():
            if progress_count:
                raise TestException
            progress_count.append(None)

        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        self.assertRaises(TestException, scheduler.TaskRunner(task),
                          progress_callback=progress)
        self.assertEqual(1, len(progress_count))

        task.do_step.assert_has_calls([mock.call(1), mock.call(2)])
        self.assertEqual(2, task.do_step.call_count)
        self.mock_sleep.assert_has_calls([mock.call(0), mock.call(1)])
        self.assertEqual(2, self.mock_sleep.call_count)

    def test_start_run_progress_exception(self):
        class TestException(Exception):
            pass

        progress_count = []

        def progress():
            if progress_count:
                raise TestException
            progress_count.append(None)

        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)
        runner.start()
        self.assertRaises(TestException, runner.run_to_completion,
                          progress_callback=progress)
        self.assertEqual(1, len(progress_count))

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_has_calls([mock.call(1), mock.call(1)])
        self.assertEqual(2, self.mock_sleep.call_count)

    def test_run_as_task_progress_exception(self):
        class TestException(Exception):
            pass

        progress_count = []

        def progress():
            if progress_count:
                raise TestException
            progress_count.append(None)

        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        tr = scheduler.TaskRunner(task)
        rt = tr.as_task(progress_callback=progress)
        next(rt)
        next(rt)
        self.assertRaises(TestException, next, rt)
        self.assertEqual(1, len(progress_count))

        task.do_step.assert_has_calls([mock.call(1), mock.call(2)])
        self.assertEqual(2, task.do_step.call_count)
        self.mock_sleep.assert_not_called()

    def test_run_progress_exception_swallow(self):
        class TestException(Exception):
            pass

        progress_count = []

        def progress():
            try:
                if not progress_count:
                    raise TestException
            finally:
                progress_count.append(None)

        def task():
            try:
                yield
            except TestException:
                yield

        scheduler.TaskRunner(task)(progress_callback=progress)
        self.assertEqual(2, len(progress_count))

        self.mock_sleep.assert_has_calls([mock.call(0), mock.call(1)])
        self.assertEqual(2, self.mock_sleep.call_count)

    def test_start_run_progress_exception_swallow(self):
        class TestException(Exception):
            pass

        progress_count = []

        def progress():
            try:
                if not progress_count:
                    raise TestException
            finally:
                progress_count.append(None)

        def task():
            yield
            try:
                yield
            except TestException:
                yield

        runner = scheduler.TaskRunner(task)
        runner.start()
        runner.run_to_completion(progress_callback=progress)
        self.assertEqual(2, len(progress_count))

        self.mock_sleep.assert_has_calls([mock.call(1), mock.call(1)])
        self.assertEqual(2, self.mock_sleep.call_count)

    def test_run_as_task_progress_exception_swallow(self):
        class TestException(Exception):
            pass

        progress_count = []

        def progress():
            try:
                if not progress_count:
                    raise TestException
            finally:
                progress_count.append(None)

        def task():
            try:
                yield
            except TestException:
                yield

        tr = scheduler.TaskRunner(task)
        rt = tr.as_task(progress_callback=progress)
        next(rt)
        next(rt)
        self.assertRaises(StopIteration, next, rt)
        self.assertEqual(2, len(progress_count))

    def test_args(self):
        args = ['foo', 'bar']
        kwargs = {'baz': 'quux', 'blarg': 'wibble'}

        task = mock.Mock()

        runner = scheduler.TaskRunner(task, *args, **kwargs)
        runner(wait_time=None)

        task.assert_called_with(*args, **kwargs)

    def test_non_callable(self):
        self.assertRaises(AssertionError, scheduler.TaskRunner, object())

    def test_stepping(self):
        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)
        runner.start()

        self.assertFalse(runner.step())
        self.assertTrue(runner)
        self.assertFalse(runner.step())
        self.assertTrue(runner.step())
        self.assertFalse(runner)

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3)])
        self.assertEqual(3, task.do_step.call_count)
        self.mock_sleep.assert_not_called()

    def test_start_no_steps(self):
        task = DummyTask(0)
        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)
        runner.start()

        self.assertTrue(runner.done())
        self.assertTrue(runner.step())

        task.do_step.assert_not_called()
        self.mock_sleep.assert_not_called()

    def test_start_only(self):
        task = DummyTask()
        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)

        self.assertFalse(runner.started())
        runner.start()
        self.assertTrue(runner.started())

        task.do_step.assert_called_once_with(1)
        self.mock_sleep.assert_not_called()

    def test_double_start(self):
        runner = scheduler.TaskRunner(DummyTask())

        runner.start()
        self.assertRaises(AssertionError, runner.start)

    def test_start_cancelled(self):
        runner = scheduler.TaskRunner(DummyTask())

        runner.cancel()
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
        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)

        runner.start()
        self.assertTrue(runner.step())
        self.assertTrue(runner.step())

        task.do_step.assert_not_called()
        self.mock_sleep.assert_not_called()

    def test_timeout(self):
        st = timeutils.wallclock()

        def task():
            while True:
                yield

        self.patchobject(timeutils, 'wallclock',
                         side_effect=[st, st + 0.5, st + 1.5])

        runner = scheduler.TaskRunner(task)

        runner.start(timeout=1)
        self.assertTrue(runner)
        self.assertRaises(scheduler.Timeout, runner.step)

        self.assertEqual(3, timeutils.wallclock.call_count)

    def test_timeout_return(self):
        st = timeutils.wallclock()

        def task():
            while True:
                try:
                    yield
                except scheduler.Timeout:
                    return

        self.patchobject(timeutils, 'wallclock',
                         side_effect=[st, st + 0.5, st + 1.5])

        runner = scheduler.TaskRunner(task)

        runner.start(timeout=1)
        self.assertTrue(runner)
        self.assertTrue(runner.step())
        self.assertFalse(runner)

        self.assertEqual(3, timeutils.wallclock.call_count)

    def test_timeout_swallowed(self):
        st = timeutils.wallclock()

        def task():
            while True:
                try:
                    yield
                except scheduler.Timeout:
                    yield
                    self.fail('Task still running')

        self.patchobject(timeutils, 'wallclock',
                         side_effect=[st, st + 0.5, st + 1.5])

        runner = scheduler.TaskRunner(task)

        runner.start(timeout=1)
        self.assertTrue(runner)
        self.assertTrue(runner.step())
        self.assertFalse(runner)
        self.assertTrue(runner.step())

        self.assertEqual(3, timeutils.wallclock.call_count)

    def test_as_task_timeout(self):
        st = timeutils.wallclock()

        def task():
            while True:
                yield

        self.patchobject(timeutils, 'wallclock',
                         side_effect=[st, st + 0.5, st + 1.5])

        runner = scheduler.TaskRunner(task)

        rt = runner.as_task(timeout=1)
        next(rt)
        self.assertTrue(runner)
        self.assertRaises(scheduler.Timeout, next, rt)

        self.assertEqual(3, timeutils.wallclock.call_count)

    def test_as_task_timeout_shorter(self):
        st = timeutils.wallclock()

        def task():
            while True:
                yield

        self.patchobject(timeutils, 'wallclock',
                         side_effect=[st, st + 0.5, st + 0.7,
                                      st + 1.6, st + 2.6])

        runner = scheduler.TaskRunner(task)
        runner.start(timeout=10)
        self.assertTrue(runner)

        rt = runner.as_task(timeout=1)
        next(rt)
        self.assertRaises(scheduler.Timeout, next, rt)

        self.assertEqual(5, timeutils.wallclock.call_count)

    def test_as_task_timeout_longer(self):
        st = timeutils.wallclock()

        def task():
            while True:
                yield

        self.patchobject(timeutils, 'wallclock',
                         side_effect=[st, st + 0.5, st + 0.6, st + 1.5])

        runner = scheduler.TaskRunner(task)
        runner.start(timeout=1)
        self.assertTrue(runner)

        rt = runner.as_task(timeout=10)
        self.assertRaises(scheduler.Timeout, next, rt)

        self.assertEqual(4, timeutils.wallclock.call_count)

    def test_cancel_not_started(self):
        task = DummyTask(1)

        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)

        self.assertFalse(runner.started())

        runner.cancel()

        self.assertTrue(runner.done())

        task.do_step.assert_not_called()
        self.mock_sleep.assert_not_called()

    def test_cancel_done(self):
        task = DummyTask(1)

        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)

        self.assertFalse(runner.started())
        runner.start()
        self.assertTrue(runner.started())
        self.assertTrue(runner.step())
        self.assertTrue(runner.done())

        runner.cancel()

        self.assertTrue(runner.done())
        self.assertTrue(runner.step())

        task.do_step.assert_called_once_with(1)
        self.mock_sleep.assert_not_called()

    def test_cancel(self):
        task = DummyTask(3)

        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)

        self.assertFalse(runner.started())
        runner.start()
        self.assertTrue(runner.started())

        self.assertFalse(runner.step())
        runner.cancel()
        self.assertTrue(runner.step())

        task.do_step.assert_has_calls([mock.call(1), mock.call(2)])
        self.assertEqual(2, task.do_step.call_count)
        self.mock_sleep.assert_not_called()

    def test_cancel_grace_period(self):
        st = timeutils.wallclock()
        task = DummyTask(5)

        task.do_step = mock.Mock(return_value=None)
        self.patchobject(timeutils, 'wallclock',
                         side_effect=[st, st + 0.5, st + 1.0, st + 1.5])

        runner = scheduler.TaskRunner(task)

        self.assertFalse(runner.started())
        runner.start()
        self.assertTrue(runner.started())

        self.assertFalse(runner.step())
        runner.cancel(grace_period=1.0)
        self.assertFalse(runner.step())
        self.assertFalse(runner.step())
        self.assertTrue(runner.step())

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3), mock.call(4)])
        self.assertEqual(4, task.do_step.call_count)
        self.mock_sleep.assert_not_called()
        self.assertEqual(4, timeutils.wallclock.call_count)

    def test_cancel_grace_period_before_timeout(self):
        st = timeutils.wallclock()
        task = DummyTask(5)

        task.do_step = mock.Mock(return_value=None)
        self.patchobject(timeutils, 'wallclock',
                         side_effect=[st, st + 0.1, st + 0.2, st + 0.2,
                                      st + 0.5, st + 1.0, st + 1.5])

        runner = scheduler.TaskRunner(task)

        self.assertFalse(runner.started())
        runner.start(timeout=10)
        self.assertTrue(runner.started())

        self.assertFalse(runner.step())
        runner.cancel(grace_period=1.0)
        self.assertFalse(runner.step())
        self.assertFalse(runner.step())
        self.assertTrue(runner.step())

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3), mock.call(4)])
        self.assertEqual(4, task.do_step.call_count)
        self.mock_sleep.assert_not_called()
        self.assertEqual(7, timeutils.wallclock.call_count)

    def test_cancel_grace_period_after_timeout(self):
        st = timeutils.wallclock()
        task = DummyTask(5)

        task.do_step = mock.Mock(return_value=None)
        self.patchobject(timeutils, 'wallclock',
                         side_effect=[st, st + 0.1, st + 0.2, st + 0.2,
                                      st + 0.5, st + 1.0, st + 1.5])

        runner = scheduler.TaskRunner(task)

        self.assertFalse(runner.started())
        runner.start(timeout=1.25)
        self.assertTrue(runner.started())

        self.assertFalse(runner.step())
        runner.cancel(grace_period=3)
        self.assertFalse(runner.step())
        self.assertFalse(runner.step())
        self.assertRaises(scheduler.Timeout, runner.step)

        task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                       mock.call(3), mock.call(4)])
        self.assertEqual(4, task.do_step.call_count)
        self.mock_sleep.assert_not_called()
        self.assertEqual(7, timeutils.wallclock.call_count)

    def test_cancel_grace_period_not_started(self):
        task = DummyTask(1)

        task.do_step = mock.Mock(return_value=None)

        runner = scheduler.TaskRunner(task)

        self.assertFalse(runner.started())

        runner.cancel(grace_period=0.5)

        self.assertTrue(runner.done())

        task.do_step.assert_not_called()
        self.mock_sleep.assert_not_called()


class TaskSleepTest(common.HeatTestCase):

    def setUp(self):
        super(TaskSleepTest, self).setUp()
        scheduler.ENABLE_SLEEP = True
        self.mock_sleep = self.patchobject(eventlet, 'sleep',
                                           return_value=None)

    def test_sleep(self):
        sleep_time = 42

        runner = scheduler.TaskRunner(DummyTask())
        runner(wait_time=sleep_time)

        self.mock_sleep.assert_any_call(0)
        self.mock_sleep.assert_called_with(sleep_time)

    def test_sleep_zero(self):
        runner = scheduler.TaskRunner(DummyTask())
        runner(wait_time=0)

        self.mock_sleep.assert_called_with(0)

    def test_sleep_none(self):
        runner = scheduler.TaskRunner(DummyTask())
        runner(wait_time=None)

        self.mock_sleep.assert_not_called()


class TimeoutTest(common.HeatTestCase):
    def test_compare(self):
        task = scheduler.TaskRunner(DummyTask())

        earlier = scheduler.Timeout(task, 10)
        eventlet.sleep(0.01)
        later = scheduler.Timeout(task, 10)

        self.assertTrue(earlier.earlier_than(later))
        self.assertFalse(later.earlier_than(earlier))


class DescriptionTest(common.HeatTestCase):

    def setUp(self):
        super(DescriptionTest, self).setUp()

    def test_func(self):
        def f():
            pass

        self.assertEqual('f', scheduler.task_description(f))

    def test_lambda(self):
        l = lambda: None

        self.assertEqual('<lambda>', scheduler.task_description(l))

    def test_method(self):
        class C(object):
            def __str__(self):
                return 'C "o"'

            def __repr__(self):
                return 'o'

            def m(self):
                pass

        self.assertEqual('m from C "o"', scheduler.task_description(C().m))

    def test_object(self):
        class C(object):
            def __str__(self):
                return 'C "o"'

            def __repr__(self):
                return 'o'

            def __call__(self):
                pass

        self.assertEqual('o', scheduler.task_description(C()))

    def test_unicode(self):
        @repr_wrapper
        @six.python_2_unicode_compatible
        class C(object):
            def __str__(self):
                return u'C "\u2665"'

            def __repr__(self):
                return u'\u2665'

            def __call__(self):
                pass

            def m(self):
                pass

        self.assertEqual(u'm from C "\u2665"',
                         scheduler.task_description(C().m))
        self.assertEqual(u'\u2665',
                         scheduler.task_description(C()))


class WrapperTaskTest(common.HeatTestCase):

    def setUp(self):
        super(WrapperTaskTest, self).setUp()

    def test_wrap(self):
        child_tasks = [DummyTask() for i in range(3)]

        @scheduler.wrappertask
        def task():
            for child_task in child_tasks:
                yield child_task()

            yield

        for child_task in child_tasks:
            child_task.do_step = mock.Mock(return_value=None)
        self.patchobject(scheduler.TaskRunner, '_sleep', return_value=None)

        scheduler.TaskRunner(task)()

        for child_task in child_tasks:
            child_task.do_step.assert_has_calls([mock.call(1), mock.call(2),
                                                 mock.call(3)])
            self.assertEqual(3, child_task.do_step.call_count)
        scheduler.TaskRunner._sleep.assert_any_call(0)
        scheduler.TaskRunner._sleep.assert_called_with(1)
        self.assertEqual(1 + len(child_tasks) * 3,
                         scheduler.TaskRunner._sleep.call_count)

    def test_parent_yield_value(self):
        @scheduler.wrappertask
        def parent_task():
            yield
            yield 3
            yield iter([1, 2, 4])

        task = parent_task()

        self.assertIsNone(next(task))
        self.assertEqual(3, next(task))
        self.assertEqual([1, 2, 4], list(next(task)))

    def test_child_yield_value(self):
        def child_task():
            yield
            yield 3
            yield iter([1, 2, 4])

        @scheduler.wrappertask
        def parent_task():
            yield child_task()

        task = parent_task()

        self.assertIsNone(next(task))
        self.assertEqual(3, next(task))
        self.assertEqual([1, 2, 4], list(next(task)))

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
        next(task)
        self.assertRaises(MyException, next, task)

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
        next(task)
        self.assertRaises(StopIteration, next, task)

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
        next(task)
        next(task)

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
        next(task)

        dummy.do_step = mock.Mock(return_value=None)
        for i in range(1, dummy.num_steps + 1):
            next(task)
        self.assertRaises(StopIteration, next, task)

        dummy.do_step.assert_has_calls([mock.call(i)
                                        for i in range(1,
                                                       dummy.num_steps + 1)])
        self.assertEqual(dummy.num_steps, dummy.do_step.call_count)

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

        dummy.do_step = mock.Mock(return_value=None)

        next(task)
        task.throw(MyException)

        for i in range(2, dummy.num_steps + 1):
            next(task)
        self.assertRaises(StopIteration, next, task)

        dummy.do_step.assert_has_calls([mock.call(i)
                                        for i in range(1,
                                                       dummy.num_steps + 1)])
        self.assertEqual(dummy.num_steps, dummy.do_step.call_count)

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

        dummy.do_step = mock.Mock(return_value=None)

        next(task)
        task.throw(MyException)

        for i in range(2, dummy.num_steps + 1):
            next(task)
        self.assertRaises(StopIteration, next, task)

        dummy.do_step.assert_has_calls([mock.call(i)
                                        for i in range(1,
                                                       dummy.num_steps + 1)])
        self.assertEqual(dummy.num_steps, dummy.do_step.call_count)

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

        dummy.do_step = mock.Mock(return_value=None)

        next(task)
        task.throw(MyException)

        for i in range(2, dummy.num_steps + 1):
            next(task)
        self.assertRaises(StopIteration, next, task)

        dummy.do_step.assert_has_calls([mock.call(i)
                                        for i in range(1,
                                                       dummy.num_steps + 1)])
        self.assertEqual(dummy.num_steps, dummy.do_step.call_count)

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
        next(task)
        self.assertRaises(MyException, next, task)

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
        next(task)
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
        next(task)
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
        next(task)
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
        next(task)
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
        next(task)
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
        next(task)
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
        next(task)
        task.close()
