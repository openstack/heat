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

import functools
import itertools
import sys
from time import time as wallclock
import types

import eventlet
from oslo.utils import excutils
import six

from heat.common.i18n import _
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


# Whether TaskRunner._sleep actually does an eventlet sleep when called.
ENABLE_SLEEP = True


def task_description(task):
    """
    Return a human-readable string description of a task suitable for logging
    the status of the task.
    """
    name = task.__name__ if hasattr(task, '__name__') else None
    if isinstance(task, types.MethodType):
        if name is not None and hasattr(task, '__self__'):
            return '%s from %s' % (name, task.__self__)
    elif isinstance(task, types.FunctionType):
        if name is not None:
            return str(name)
    return repr(task)


class Timeout(BaseException):
    """
    Timeout exception, raised within a task when it has exceeded its allotted
    (wallclock) running time.

    This allows the task to perform any necessary cleanup, as well as use a
    different exception to notify the controlling task if appropriate. If the
    task suppresses the exception altogether, it will be cancelled but the
    controlling task will not be notified of the timeout.
    """

    def __init__(self, task_runner, timeout):
        """
        Initialise with the TaskRunner and a timeout period in seconds.
        """
        message = _('%s Timed out') % str(task_runner)
        super(Timeout, self).__init__(message)

        # Note that we don't attempt to handle leap seconds or large clock
        # jumps here. The latter are assumed to be rare and the former
        # negligible in the context of the timeout. Time zone adjustments,
        # Daylight Savings and the like *are* handled. PEP 418 adds a proper
        # monotonic clock, but only in Python 3.3.
        self._endtime = wallclock() + timeout

    def expired(self):
        return wallclock() > self._endtime

    def trigger(self, generator):
        """Trigger the timeout on a given generator."""
        try:
            generator.throw(self)
        except StopIteration:
            return True
        else:
            # Clean up in case task swallows exception without exiting
            generator.close()
            return False

    def __cmp__(self, other):
        if not isinstance(other, Timeout):
            return NotImplemented
        return cmp(self._endtime, other._endtime)


class TimedCancel(Timeout):
    def trigger(self, generator):
        """Trigger the timeout on a given generator."""
        generator.close()
        return False


class ExceptionGroup(Exception):
    '''
    Container for multiple exceptions.

    This exception is used by DependencyTaskGroup when the flag
    aggregate_exceptions is set to True and it's re-raised again when all tasks
    are finished.  This way it can be caught later on so that the individual
    exceptions can be acted upon.
    '''

    def __init__(self, exceptions=None):
        if exceptions is None:
            exceptions = list()

        self.exceptions = list(exceptions)

    def __str__(self):
        return unicode([unicode(ex).encode('utf-8')
                        for ex in self.exceptions]).encode('utf-8')

    def __unicode__(self):
        return unicode(map(unicode, self.exceptions))


class TaskRunner(object):
    """
    Wrapper for a resumable task (co-routine).
    """

    def __init__(self, task, *args, **kwargs):
        """
        Initialise with a task function, and arguments to be passed to it when
        it is started.

        The task function may be a co-routine that yields control flow between
        steps.
        """
        assert callable(task), "Task is not callable"

        self._task = task
        self._args = args
        self._kwargs = kwargs
        self._runner = None
        self._done = False
        self._timeout = None
        self.name = task_description(task)

    def __str__(self):
        """Return a human-readable string representation of the task."""
        return 'Task %s' % self.name

    def _sleep(self, wait_time):
        """Sleep for the specified number of seconds."""
        if ENABLE_SLEEP and wait_time is not None:
            LOG.debug('%s sleeping' % str(self))
            eventlet.sleep(wait_time)

    def __call__(self, wait_time=1, timeout=None):
        """
        Start and run the task to completion.

        The task will sleep for `wait_time` seconds between steps. To avoid
        sleeping, pass `None` for `wait_time`.
        """
        self.start(timeout=timeout)
        # ensure that wait is applied only if task has not completed.
        if not self.done():
            self._sleep(wait_time)
        self.run_to_completion(wait_time=wait_time)

    def start(self, timeout=None):
        """
        Initialise the task and run its first step.

        If a timeout is specified, any attempt to step the task after that
        number of seconds has elapsed will result in a Timeout being
        raised inside the task.
        """
        assert self._runner is None, "Task already started"
        assert not self._done, "Task already cancelled"

        LOG.debug('%s starting' % str(self))

        if timeout is not None:
            self._timeout = Timeout(self, timeout)

        result = self._task(*self._args, **self._kwargs)
        if isinstance(result, types.GeneratorType):
            self._runner = result
            self.step()
        else:
            self._runner = False
            self._done = True
            LOG.debug('%s done (not resumable)' % str(self))

    def step(self):
        """
        Run another step of the task, and return True if the task is complete;
        False otherwise.
        """
        if not self.done():
            assert self._runner is not None, "Task not started"

            if self._timeout is not None and self._timeout.expired():
                LOG.info(_('%s timed out') % str(self))
                self._done = True

                self._timeout.trigger(self._runner)
            else:
                LOG.debug('%s running' % str(self))

                try:
                    next(self._runner)
                except StopIteration:
                    self._done = True
                    LOG.debug('%s complete' % str(self))

        return self._done

    def run_to_completion(self, wait_time=1):
        """
        Run the task to completion.

        The task will sleep for `wait_time` seconds between steps. To avoid
        sleeping, pass `None` for `wait_time`.
        """
        while not self.step():
            self._sleep(wait_time)

    def cancel(self, grace_period=None):
        """Cancel the task and mark it as done."""
        if self.done():
            return

        if not self.started() or grace_period is None:
            LOG.debug('%s cancelled' % str(self))
            self._done = True
            if self.started():
                self._runner.close()
        else:
            timeout = TimedCancel(self, grace_period)
            if self._timeout is None or timeout < self._timeout:
                self._timeout = timeout

    def started(self):
        """Return True if the task has been started."""
        return self._runner is not None

    def done(self):
        """Return True if the task is complete."""
        return self._done

    def __nonzero__(self):
        """Return True if there are steps remaining."""
        return not self.done()


def wrappertask(task):
    """
    Decorator for a task that needs to drive a subtask.

    This is essentially a replacement for the Python 3-only "yield from"
    keyword (PEP 380), using the "yield" keyword that is supported in
    Python 2. For example::

        @wrappertask
        def parent_task(self):
            self.setup()

            yield self.child_task()

            self.cleanup()
    """

    @functools.wraps(task)
    def wrapper(*args, **kwargs):
        parent = task(*args, **kwargs)

        subtask = next(parent)

        while True:
            try:
                if subtask is not None:
                    subtask_running = True
                    try:
                        step = next(subtask)
                    except StopIteration:
                        subtask_running = False

                    while subtask_running:
                        try:
                            yield step
                        except GeneratorExit as ex:
                            subtask.close()
                            raise ex
                        except:  # noqa
                            try:
                                step = subtask.throw(*sys.exc_info())
                            except StopIteration:
                                subtask_running = False
                        else:
                            try:
                                step = next(subtask)
                            except StopIteration:
                                subtask_running = False
                else:
                    yield
            except GeneratorExit as ex:
                parent.close()
                raise ex
            except:  # noqa
                subtask = parent.throw(*sys.exc_info())
            else:
                subtask = next(parent)

    return wrapper


class DependencyTaskGroup(object):
    """
    A task which manages a group of subtasks that have ordering dependencies.
    """

    def __init__(self, dependencies, task=lambda o: o(),
                 reverse=False, name=None, error_wait_time=None,
                 aggregate_exceptions=False):
        """
        Initialise with the task dependencies and (optionally) a task to run on
        each.

        If no task is supplied, it is assumed that the tasks are stored
        directly in the dependency tree. If a task is supplied, the object
        stored in the dependency tree is passed as an argument.

        If an error_wait_time is specified, tasks that are already running at
        the time of an error will continue to run for up to the specified
        time before being cancelled. Once all remaining tasks are complete or
        have been cancelled, the original exception is raised.

        If aggregate_exceptions is True, then execution of parallel operations
        will not be cancelled in the event of an error (operations downstream
        of the error will be cancelled). Once all chains are complete, any
        errors will be rolled up into an ExceptionGroup exception.
        """
        self._runners = dict((o, TaskRunner(task, o)) for o in dependencies)
        self._graph = dependencies.graph(reverse=reverse)
        self.error_wait_time = error_wait_time
        self.aggregate_exceptions = aggregate_exceptions

        if name is None:
            name = '(%s) %s' % (getattr(task, '__name__',
                                        task_description(task)),
                                str(dependencies))
        self.name = name

    def __repr__(self):
        """Return a string representation of the task."""
        return '%s(%s)' % (type(self).__name__, self.name)

    def __call__(self):
        """Return a co-routine which runs the task group."""
        raised_exceptions = []
        while any(self._runners.itervalues()):
            try:
                for k, r in self._ready():
                    r.start()

                yield

                for k, r in self._running():
                    if r.step():
                        del self._graph[k]
            except Exception:
                exc_info = sys.exc_info()
                if self.aggregate_exceptions:
                    self._cancel_recursively(k, r)
                else:
                    self.cancel_all(grace_period=self.error_wait_time)
                raised_exceptions.append(exc_info)
            except:  # noqa
                with excutils.save_and_reraise_exception():
                    self.cancel_all()

        if raised_exceptions:
            if self.aggregate_exceptions:
                raise ExceptionGroup(v for t, v, tb in raised_exceptions)
            else:
                exc_type, exc_val, traceback = raised_exceptions[0]
                raise exc_type, exc_val, traceback

    def cancel_all(self, grace_period=None):
        for r in self._runners.itervalues():
            r.cancel(grace_period=grace_period)

    def _cancel_recursively(self, key, runner):
        runner.cancel()
        node = self._graph[key]
        for dependent_node in node.required_by():
            node_runner = self._runners[dependent_node]
            self._cancel_recursively(dependent_node, node_runner)

        del self._graph[key]

    def _ready(self):
        """
        Iterate over all subtasks that are ready to start - i.e. all their
        dependencies have been satisfied but they have not yet been started.
        """
        for k, n in six.iteritems(self._graph):
            if not n:
                runner = self._runners[k]
                if runner and not runner.started():
                    yield k, runner

    def _running(self):
        """
        Iterate over all subtasks that are currently running - i.e. they have
        been started but have not yet completed.
        """
        running = lambda (k, r): k in self._graph and r.started()
        return itertools.ifilter(running, six.iteritems(self._runners))


class PollingTaskGroup(object):
    """
    A task which manages a group of subtasks.

    When the task is started, all of its subtasks are also started. The task
    completes when all subtasks are complete.

    Once started, the subtasks are assumed to be only polling for completion
    of an asynchronous operation, so no attempt is made to give them equal
    scheduling slots.
    """

    def __init__(self, tasks, name=None):
        """Initialise with a list of tasks."""
        self._tasks = list(tasks)
        if name is None:
            name = ', '.join(task_description(t) for t in self._tasks)
        self.name = name

    @staticmethod
    def _args(arg_lists):
        """Return a list containing the positional args for each subtask."""
        return zip(*arg_lists)

    @staticmethod
    def _kwargs(kwarg_lists):
        """Return a list containing the keyword args for each subtask."""
        keygroups = (itertools.izip(itertools.repeat(name),
                                    arglist)
                     for name, arglist in six.iteritems(kwarg_lists))
        return [dict(kwargs) for kwargs in itertools.izip(*keygroups)]

    @classmethod
    def from_task_with_args(cls, task, *arg_lists, **kwarg_lists):
        """
        Return a new PollingTaskGroup where each subtask is identical except
        for the arguments passed to it.

        Each argument to use should be passed as a list (or iterable) of values
        such that one is passed in the corresponding position for each subtask.
        The number of subtasks spawned depends on the length of the argument
        lists. For example:

            PollingTaskGroup.from_task_with_args(my_task,
                                                 [1, 2, 3],
                                                 alpha=['a', 'b', 'c'])

        will start three TaskRunners that will run:

            my_task(1, alpha='a')
            my_task(2, alpha='b')
            my_task(3, alpha='c')

        respectively.

        If multiple arguments are supplied, each list should be of the same
        length. In the case of any discrepancy, the length of the shortest
        argument list will be used, and any extra arguments discarded.
        """

        args_list = cls._args(arg_lists)
        kwargs_list = cls._kwargs(kwarg_lists)

        if kwarg_lists and not arg_lists:
            args_list = [[]] * len(kwargs_list)
        elif arg_lists and not kwarg_lists:
            kwargs_list = [{}] * len(args_list)

        task_args = itertools.izip(args_list, kwargs_list)
        tasks = (functools.partial(task, *a, **kwa) for a, kwa in task_args)

        return cls(tasks, name=task_description(task))

    def __repr__(self):
        """Return a string representation of the task group."""
        return '%s(%s)' % (type(self).__name__, self.name)

    def __call__(self):
        """Return a co-routine which runs the task group."""
        runners = [TaskRunner(t) for t in self._tasks]

        try:
            for r in runners:
                r.start()

            while runners:
                yield
                runners = list(itertools.dropwhile(lambda r: r.step(),
                                                   runners))
        except:  # noqa
            with excutils.save_and_reraise_exception():
                for r in runners:
                    r.cancel()
