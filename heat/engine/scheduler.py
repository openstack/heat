# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import types

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


def task_description(task):
    """
    Return a human-readable string description of a task suitable for logging
    the status of the task.
    """
    if isinstance(task, types.MethodType):
        name = getattr(task, '__name__')
        obj = getattr(task, '__self__')
        if name is not None and obj is not None:
            return '%s from %s' % (name, obj)
    return repr(task)


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
        self.name = task_description(task)

    def __str__(self):
        """Return a human-readable string representation of the task."""
        return 'Task %s' % self.name

    def _sleep(self, wait_time):
        """Sleep for the specified number of seconds."""
        if wait_time is not None:
            logger.debug('%s sleeping' % str(self))
            eventlet.sleep(wait_time)

    def __call__(self, wait_time=1):
        """
        Start and run the task to completion.

        The task will sleep for `wait_time` seconds between steps. To avoid
        sleeping, pass `None` for `wait_time`.
        """
        self.start()
        self.run_to_completion(wait_time=wait_time)

    def start(self):
        """
        Initialise the task and run its first step.
        """
        assert self._runner is None, "Task already started"

        logger.debug('%s starting' % str(self))

        result = self._task(*self._args, **self._kwargs)
        if isinstance(result, types.GeneratorType):
            self._runner = result
            self.step()
        else:
            self._runner = False
            self._done = True
            logger.debug('%s done (not resumable)' % str(self))

    def step(self):
        """
        Run another step of the task, and return True if the task is complete;
        False otherwise.
        """
        if not self.done():
            assert self._runner is not None, "Task not started"

            logger.debug('%s running' % str(self))

            try:
                next(self._runner)
            except StopIteration:
                self._done = True
                logger.debug('%s complete' % str(self))

        return self._done

    def run_to_completion(self, wait_time=1):
        """
        Run the task to completion.

        The task will sleep for `wait_time` seconds between steps. To avoid
        sleeping, pass `None` for `wait_time`.
        """
        while not self.step():
            self._sleep(wait_time)

    def cancel(self):
        """Cancel the task if it is running."""
        if self.started() and not self.done():
            logger.debug('%s cancelled' % str(self))
            self._runner.close()
            self._done = True

    def started(self):
        """Return True if the task has been started."""
        return self._runner is not None

    def done(self):
        """Return True if the task is complete."""
        return self._done

    def __nonzero__(self):
        """Return True if there are steps remaining."""
        return not self.done()
