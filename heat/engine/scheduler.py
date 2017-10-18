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

import sys
import types

import eventlet
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
import six

from heat.common.i18n import _
from heat.common.i18n import repr_wrapper
from heat.common import timeutils

LOG = logging.getLogger(__name__)


# Whether TaskRunner._sleep actually does an eventlet sleep when called.
ENABLE_SLEEP = True


def task_description(task):
    """Return a human-readable string description of a task.

    The description is used to identify the task when logging its status.
    """
    name = task.__name__ if hasattr(task, '__name__') else None
    if name is not None and isinstance(task, (types.MethodType,
                                              types.FunctionType)):
        if getattr(task, '__self__', None) is not None:
            return '%s from %s' % (six.text_type(name), task.__self__)
        else:
            return six.text_type(name)
    return encodeutils.safe_decode(repr(task))


class Timeout(BaseException):
    """Raised when task has exceeded its allotted (wallclock) running time.

    This allows the task to perform any necessary cleanup, as well as use a
    different exception to notify the controlling task if appropriate. If the
    task suppresses the exception altogether, it will be cancelled but the
    controlling task will not be notified of the timeout.
    """

    def __init__(self, task_runner, timeout):
        """Initialise with the TaskRunner and a timeout period in seconds."""
        message = _('%s Timed out') % six.text_type(task_runner)
        super(Timeout, self).__init__(message)

        self._duration = timeutils.Duration(timeout)

    def expired(self):
        return self._duration.expired()

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

    def earlier_than(self, other):
        if other is None:
            return True

        assert isinstance(other, Timeout), "Invalid type for Timeout compare"
        return self._duration.endtime() < other._duration.endtime()


class TimedCancel(Timeout):
    def trigger(self, generator):
        """Trigger the timeout on a given generator."""
        generator.close()
        return False


@six.python_2_unicode_compatible
class ExceptionGroup(Exception):
    """Container for multiple exceptions.

    This exception is used by DependencyTaskGroup when the flag
    aggregate_exceptions is set to True and it's re-raised again when all tasks
    are finished.  This way it can be caught later on so that the individual
    exceptions can be acted upon.
    """

    def __init__(self, exceptions=None):
        if exceptions is None:
            exceptions = list()

        self.exceptions = list(exceptions)

    def __str__(self):
        return str([str(ex) for ex in self.exceptions])


@six.python_2_unicode_compatible
class TaskRunner(object):
    """Wrapper for a resumable task (co-routine)."""

    def __init__(self, task, *args, **kwargs):
        """Initialise with a task function and arguments.

        The arguments are passed to task when it is started.

        The task function may be a co-routine that yields control flow between
        steps.

        If the task co-routine wishes to be advanced only on every nth step of
        the TaskRunner, it may yield an integer which is the period of the
        task. e.g. "yield 2" will result in the task being advanced on every
        second step.
        """
        assert callable(task), "Task is not callable"

        self._task = task
        self._args = args
        self._kwargs = kwargs
        self._runner = None
        self._done = False
        self._timeout = None
        self._poll_period = 1
        self.name = task_description(task)

    def __str__(self):
        """Return a human-readable string representation of the task."""
        text = 'Task %s' % self.name
        return six.text_type(text)

    def _sleep(self, wait_time):
        """Sleep for the specified number of seconds."""
        if ENABLE_SLEEP and wait_time is not None:
            LOG.debug('%s sleeping', six.text_type(self))
            eventlet.sleep(wait_time)

    def __call__(self, wait_time=1, timeout=None, progress_callback=None):
        """Start and run the task to completion.

        The task will first sleep for zero seconds, then sleep for `wait_time`
        seconds between steps. To avoid sleeping, pass `None` for `wait_time`.
        """
        assert self._runner is None, "Task already started"

        started = False
        for step in self.as_task(timeout=timeout,
                                 progress_callback=progress_callback):
            self._sleep(wait_time if (started or wait_time is None) else 0)
            started = True

    def start(self, timeout=None):
        """Initialise the task and run its first step.

        If a timeout is specified, any attempt to step the task after that
        number of seconds has elapsed will result in a Timeout being
        raised inside the task.
        """
        assert self._runner is None, "Task already started"
        assert not self._done, "Task already cancelled"

        LOG.debug('%s starting', six.text_type(self))

        if timeout is not None:
            self._timeout = Timeout(self, timeout)

        result = self._task(*self._args, **self._kwargs)
        if isinstance(result, types.GeneratorType):
            self._runner = result
            self.step()
        else:
            self._runner = False
            self._done = True
            LOG.debug('%s done (not resumable)', six.text_type(self))

    def step(self):
        """Run another step of the task.

        Return True if the task is complete; False otherwise.
        """
        if not self.done():
            assert self._runner is not None, "Task not started"

            if self._poll_period > 1:
                self._poll_period -= 1
                return False

            if self._timeout is not None and self._timeout.expired():
                LOG.info('%s timed out', self)
                self._done = True

                self._timeout.trigger(self._runner)
            else:
                LOG.debug('%s running', six.text_type(self))

                try:
                    poll_period = next(self._runner)
                except StopIteration:
                    self._done = True
                    LOG.debug('%s complete', six.text_type(self))
                else:
                    if isinstance(poll_period, six.integer_types):
                        self._poll_period = max(poll_period, 1)
                    else:
                        self._poll_period = 1

        return self._done

    def run_to_completion(self, wait_time=1, progress_callback=None):
        """Run the task to completion.

        The task will sleep for `wait_time` seconds between steps. To avoid
        sleeping, pass `None` for `wait_time`.
        """
        assert self._runner is not None, "Task not started"

        for step in self.as_task(progress_callback=progress_callback):
            self._sleep(wait_time)

    def as_task(self, timeout=None, progress_callback=None):
        """Return a task that drives the TaskRunner."""
        resuming = self.started()
        if not resuming:
            self.start(timeout=timeout)
        else:
            if timeout is not None:
                new_timeout = Timeout(self, timeout)
                if new_timeout.earlier_than(self._timeout):
                    self._timeout = new_timeout

        done = self.step() if resuming else self.done()
        while not done:
            try:
                yield

                if progress_callback is not None:
                    progress_callback()
            except GeneratorExit:
                self.cancel()
                raise
            except:  # noqa
                self._done = True
                try:
                    self._runner.throw(*sys.exc_info())
                except StopIteration:
                    return
                else:
                    self._done = False
            else:
                done = self.step()

    def cancel(self, grace_period=None):
        """Cancel the task and mark it as done."""
        if self.done():
            return

        if not self.started() or grace_period is None:
            LOG.debug('%s cancelled', six.text_type(self))
            self._done = True
            if self.started():
                self._runner.close()
        else:
            timeout = TimedCancel(self, grace_period)
            if timeout.earlier_than(self._timeout):
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

    def __bool__(self):
        """Return True if there are steps remaining."""
        return self.__nonzero__()


def wrappertask(task):
    """Decorator for a task that needs to drive a subtask.

    This is essentially a replacement for the Python 3-only "yield from"
    keyword (PEP 380), using the "yield" keyword that is supported in
    Python 2. For example::

        @wrappertask
        def parent_task(self):
            self.setup()

            yield self.child_task()

            self.cleanup()
    """

    @six.wraps(task)
    def wrapper(*args, **kwargs):
        parent = task(*args, **kwargs)

        try:
            subtask = next(parent)
        except StopIteration:
            return

        while True:
            try:
                if isinstance(subtask, types.GeneratorType):
                    subtask_running = True
                    try:
                        step = next(subtask)
                    except StopIteration:
                        subtask_running = False

                    while subtask_running:
                        try:
                            yield step
                        except GeneratorExit:
                            subtask.close()
                            raise
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
                    yield subtask
            except GeneratorExit:
                parent.close()
                raise
            except:  # noqa
                try:
                    subtask = parent.throw(*sys.exc_info())
                except StopIteration:
                    return
            else:
                try:
                    subtask = next(parent)
                except StopIteration:
                    return

    return wrapper


@repr_wrapper
class DependencyTaskGroup(object):
    """Task which manages group of subtasks that have ordering dependencies."""

    def __init__(self, dependencies, task=lambda o: o(),
                 reverse=False, name=None, error_wait_time=None,
                 aggregate_exceptions=False):
        """Initialise with the task dependencies.

        A task to run on each dependency may optionally be specified.  If no
        task is supplied, it is assumed that the tasks are stored directly in
        the dependency tree. If a task is supplied, the object stored in the
        dependency tree is passed as an argument.

        If an error_wait_time is specified, tasks that are already running at
        the time of an error will continue to run for up to the specified time
        before being cancelled. Once all remaining tasks are complete or have
        been cancelled, the original exception is raised. If error_wait_time is
        a callable function it will be called for each task, passing the
        dependency key as an argument, to determine the error_wait_time for
        that particular task.

        If aggregate_exceptions is True, then execution of parallel operations
        will not be cancelled in the event of an error (operations downstream
        of the error will be cancelled). Once all chains are complete, any
        errors will be rolled up into an ExceptionGroup exception.
        """
        self._keys = list(dependencies)
        self._runners = dict((o, TaskRunner(task, o)) for o in self._keys)
        self._graph = dependencies.graph(reverse=reverse)
        self.error_wait_time = error_wait_time
        self.aggregate_exceptions = aggregate_exceptions

        if name is None:
            name = '(%s) %s' % (getattr(task, '__name__',
                                        task_description(task)),
                                six.text_type(dependencies))
        self.name = name

    def __repr__(self):
        """Return a string representation of the task."""
        text = '%s(%s)' % (type(self).__name__, self.name)
        return text

    def __call__(self):
        """Return a co-routine which runs the task group."""
        raised_exceptions = []
        thrown_exceptions = []

        try:
            while any(six.itervalues(self._runners)):
                try:
                    for k, r in self._ready():
                        r.start()
                        if not r:
                            del self._graph[k]

                    if self._graph:
                        try:
                            yield
                        except Exception:
                            thrown_exceptions.append(sys.exc_info())
                            raise

                    for k, r in self._running():
                        if r.step():
                            del self._graph[k]
                except Exception:
                    exc_info = None
                    try:
                        exc_info = sys.exc_info()
                        if self.aggregate_exceptions:
                            self._cancel_recursively(k, r)
                        else:
                            self.cancel_all(grace_period=self.error_wait_time)
                        raised_exceptions.append(exc_info)
                    finally:
                        del exc_info
                except:  # noqa
                    with excutils.save_and_reraise_exception():
                        self.cancel_all()

            if raised_exceptions:
                if self.aggregate_exceptions:
                    raise ExceptionGroup(v for t, v, tb in raised_exceptions)
                else:
                    if thrown_exceptions:
                        six.reraise(*thrown_exceptions[-1])
                    else:
                        six.reraise(*raised_exceptions[0])
        finally:
            del raised_exceptions
            del thrown_exceptions

    def cancel_all(self, grace_period=None):
        if callable(grace_period):
            get_grace_period = grace_period
        else:
            def get_grace_period(key):
                return grace_period

        for k, r in six.iteritems(self._runners):
            if not r.started() or r.done():
                gp = None
            else:
                gp = get_grace_period(k)
            try:
                r.cancel(grace_period=gp)
            except Exception as ex:
                LOG.debug('Exception cancelling task: %s', six.text_type(ex))

    def _cancel_recursively(self, key, runner):
        try:
            runner.cancel()
        except Exception as ex:
            LOG.debug('Exception cancelling task: %s', six.text_type(ex))
        node = self._graph[key]
        for dependent_node in node.required_by():
            node_runner = self._runners[dependent_node]
            self._cancel_recursively(dependent_node, node_runner)

        del self._graph[key]

    def _ready(self):
        """Iterate over all subtasks that are ready to start.

        Ready subtasks are subtasks whose dependencies have all been satisfied,
        but which have not yet been started.
        """
        for k in self._keys:
            if not self._graph.get(k, True):
                runner = self._runners[k]
                if runner and not runner.started():
                    yield k, runner

    def _running(self):
        """Iterate over all subtasks that are currently running.

        Running subtasks are subtasks have been started but have not yet
        completed.
        """

        def running(k_r):
            return k_r[0] in self._graph and k_r[1].started()

        return six.moves.filter(running, six.iteritems(self._runners))
