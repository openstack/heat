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
import uuid

from oslo_log import log as logging
from oslo_utils import excutils

from heat.common import exception
from heat.common.i18n import _LI
from heat.common.i18n import _LW
from heat.objects import stack as stack_object
from heat.objects import stack_lock as stack_lock_object
from heat.rpc import listener_client

LOG = logging.getLogger(__name__)


class StackLock(object):
    def __init__(self, context, stack_id, engine_id):
        self.context = context
        self.stack_id = stack_id
        self.engine_id = engine_id
        self.listener = None

    @staticmethod
    def engine_alive(context, engine_id):
        return listener_client.EngineListenerClient(
            engine_id).is_alive(context)

    @staticmethod
    def generate_engine_id():
        return str(uuid.uuid4())

    def get_engine_id(self):
        return stack_lock_object.StackLock.get_engine_id(self.stack_id)

    def try_acquire(self):
        """Try to acquire a stack lock.

        Don't raise an ActionInProgress exception or try to steal lock.
        """
        return stack_lock_object.StackLock.create(self.stack_id,
                                                  self.engine_id)

    def acquire(self, retry=True):
        """Acquire a lock on the stack.

        :param retry: When True, retry if lock was released while stealing.
        :type retry: boolean
        """
        lock_engine_id = stack_lock_object.StackLock.create(self.stack_id,
                                                            self.engine_id)
        if lock_engine_id is None:
            LOG.debug("Engine %(engine)s acquired lock on stack "
                      "%(stack)s" % {'engine': self.engine_id,
                                     'stack': self.stack_id})
            return

        stack = stack_object.Stack.get_by_id(self.context, self.stack_id,
                                             show_deleted=True)
        if (lock_engine_id == self.engine_id or
                self.engine_alive(self.context, lock_engine_id)):
            LOG.debug("Lock on stack %(stack)s is owned by engine "
                      "%(engine)s" % {'stack': self.stack_id,
                                      'engine': lock_engine_id})
            raise exception.ActionInProgress(stack_name=stack.name,
                                             action=stack.action)
        else:
            LOG.info(_LI("Stale lock detected on stack %(stack)s.  Engine "
                         "%(engine)s will attempt to steal the lock"),
                     {'stack': self.stack_id, 'engine': self.engine_id})

            result = stack_lock_object.StackLock.steal(self.stack_id,
                                                       lock_engine_id,
                                                       self.engine_id)

            if result is None:
                LOG.info(_LI("Engine %(engine)s successfully stole the lock "
                             "on stack %(stack)s"),
                         {'engine': self.engine_id,
                          'stack': self.stack_id})
                return
            elif result is True:
                if retry:
                    LOG.info(_LI("The lock on stack %(stack)s was released "
                                 "while engine %(engine)s was stealing it. "
                                 "Trying again"), {'stack': self.stack_id,
                                                   'engine': self.engine_id})
                    return self.acquire(retry=False)
            else:
                new_lock_engine_id = result
                LOG.info(_LI("Failed to steal lock on stack %(stack)s. "
                             "Engine %(engine)s stole the lock first"),
                         {'stack': self.stack_id,
                          'engine': new_lock_engine_id})

            raise exception.ActionInProgress(
                stack_name=stack.name, action=stack.action)

    def release(self):
        """Release a stack lock."""

        # Only the engine that owns the lock will be releasing it.
        result = stack_lock_object.StackLock.release(self.stack_id,
                                                     self.engine_id)
        if result is True:
            LOG.warn(_LW("Lock was already released on stack %s!"),
                     self.stack_id)
        else:
            LOG.debug("Engine %(engine)s released lock on stack "
                      "%(stack)s" % {'engine': self.engine_id,
                                     'stack': self.stack_id})

    @contextlib.contextmanager
    def thread_lock(self):
        """Acquire a lock and release it only if there is an exception.

        The release method still needs to be scheduled to be run at the
        end of the thread using the Thread.link method.
        """
        try:
            self.acquire()
            yield
        except exception.ActionInProgress:
            raise
        except:  # noqa
            with excutils.save_and_reraise_exception():
                self.release()

    @contextlib.contextmanager
    def try_thread_lock(self):
        """Similar to thread_lock, but acquire the lock using try_acquire.

        Only release it upon any exception after a successful acquisition.
        """
        result = None
        try:
            result = self.try_acquire()
            yield result
        except:  # noqa
            if result is None:  # Lock was successfully acquired
                with excutils.save_and_reraise_exception():
                    self.release()
            raise
