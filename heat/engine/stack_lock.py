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

from oslo.config import cfg
from oslo import messaging
from oslo.utils import excutils

from heat.common import exception
from heat.common.i18n import _
from heat.common import messaging as rpc_messaging
from heat.db import api as db_api
from heat.openstack.common import log as logging

cfg.CONF.import_opt('engine_life_check_timeout', 'heat.common.config')

LOG = logging.getLogger(__name__)


class StackLock(object):
    def __init__(self, context, stack, engine_id):
        self.context = context
        self.stack = stack
        self.engine_id = engine_id
        self.listener = None

    @staticmethod
    def engine_alive(context, engine_id):
        client = rpc_messaging.get_rpc_client(version='1.0', topic=engine_id)
        client_context = client.prepare(
            timeout=cfg.CONF.engine_life_check_timeout)
        try:
            return client_context.call(context, 'listening')
        except messaging.MessagingTimeout:
            return False

    @staticmethod
    def generate_engine_id():
        return str(uuid.uuid4())

    def try_acquire(self):
        """
        Try to acquire a stack lock, but don't raise an ActionInProgress
        exception or try to steal lock.
        """
        return db_api.stack_lock_create(self.stack.id, self.engine_id)

    def acquire(self, retry=True):
        """
        Acquire a lock on the stack.

        :param retry: When True, retry if lock was released while stealing.
        :type retry: boolean
        """
        lock_engine_id = db_api.stack_lock_create(self.stack.id,
                                                  self.engine_id)
        if lock_engine_id is None:
            LOG.debug("Engine %(engine)s acquired lock on stack "
                      "%(stack)s" % {'engine': self.engine_id,
                                     'stack': self.stack.id})
            return

        if lock_engine_id == self.engine_id or \
           self.engine_alive(self.context, lock_engine_id):
            LOG.debug("Lock on stack %(stack)s is owned by engine "
                      "%(engine)s" % {'stack': self.stack.id,
                                      'engine': lock_engine_id})
            raise exception.ActionInProgress(stack_name=self.stack.name,
                                             action=self.stack.action)
        else:
            LOG.info(_("Stale lock detected on stack %(stack)s.  Engine "
                       "%(engine)s will attempt to steal the lock")
                     % {'stack': self.stack.id, 'engine': self.engine_id})

            result = db_api.stack_lock_steal(self.stack.id, lock_engine_id,
                                             self.engine_id)

            if result is None:
                LOG.info(_("Engine %(engine)s successfully stole the lock "
                           "on stack %(stack)s")
                         % {'engine': self.engine_id,
                            'stack': self.stack.id})
                return
            elif result is True:
                if retry:
                    LOG.info(_("The lock on stack %(stack)s was released "
                               "while engine %(engine)s was stealing it. "
                               "Trying again") % {'stack': self.stack.id,
                                                  'engine': self.engine_id})
                    return self.acquire(retry=False)
            else:
                new_lock_engine_id = result
                LOG.info(_("Failed to steal lock on stack %(stack)s. "
                           "Engine %(engine)s stole the lock first")
                         % {'stack': self.stack.id,
                            'engine': new_lock_engine_id})

            raise exception.ActionInProgress(
                stack_name=self.stack.name, action=self.stack.action)

    def release(self, stack_id):
        """Release a stack lock."""
        # Only the engine that owns the lock will be releasing it.
        result = db_api.stack_lock_release(stack_id, self.engine_id)
        if result is True:
            LOG.warning(_("Lock was already released on stack %s!") % stack_id)
        else:
            LOG.debug("Engine %(engine)s released lock on stack "
                      "%(stack)s" % {'engine': self.engine_id,
                                     'stack': stack_id})

    @contextlib.contextmanager
    def thread_lock(self, stack_id):
        """
        Acquire a lock and release it only if there is an exception.  The
        release method still needs to be scheduled to be run at the
        end of the thread using the Thread.link method.
        """
        try:
            self.acquire()
            yield
        except:  # noqa
            with excutils.save_and_reraise_exception():
                self.release(stack_id)

    @contextlib.contextmanager
    def try_thread_lock(self, stack_id):
        """
        Similar to thread_lock, but acquire the lock using try_acquire
        and only release it upon any exception after a successful
        acquisition.
        """
        result = None
        try:
            result = self.try_acquire()
            yield result
        except:  # noqa
            if result is None:  # Lock was successfully acquired
                with excutils.save_and_reraise_exception():
                    self.release(stack_id)
            raise
