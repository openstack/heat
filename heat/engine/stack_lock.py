
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

from oslo.config import cfg

cfg.CONF.import_opt('engine_id', 'heat.common.config')

from heat.common import exception
from heat.db import api as db_api

from heat.openstack.common import log as logging
from heat.openstack.common import uuidutils

logger = logging.getLogger(__name__)


class StackLock(object):
    def __init__(self, context, stack):
        self.context = context
        self.stack = stack
        if cfg.CONF.engine_id == "generate_uuid":
            self.engine_id = uuidutils.generate_uuid()
        else:
            self.engine_id = cfg.CONF.engine_id

    @staticmethod
    def _lock_staleness(lock):
        """Returns number of seconds since stack was created or updated."""
        if lock.updated_at:
            changed_time = lock.updated_at
        else:
            changed_time = lock.created_at
        current_time = db_api.current_timestamp()
        current_epoch = float(current_time.strftime('%s'))
        changed_epoch = float(changed_time.strftime('%s'))
        return current_epoch - changed_epoch

    @property
    def timeout(self):
        """Returns the stack timeout in seconds."""
        try:
            return self.stack.timeout * 60
        except AttributeError:
            return self.stack.timeout_secs()

    def acquire(self):
        """Acquire a lock on the stack."""
        existing_lock = db_api.stack_lock_get(self.context, self.stack.id)
        if existing_lock:
            if self._lock_staleness(existing_lock) > self.timeout:
                logger.info("Lock expired.  Engine %s is stealing the lock"
                            % existing_lock.engine_id)
                db_api.stack_lock_steal(self.context, self.stack.id,
                                        self.engine_id)
            else:
                logger.debug("Stack lock is owned by engine %s"
                             % existing_lock.engine_id)
                raise exception.ActionInProgress(stack_name=self.stack.name,
                                                 action=self.stack.action)
        else:
            db_api.stack_lock_create(self.context, self.stack.id,
                                     self.engine_id)
            logger.debug("Acquired lock for engine: %s, stack: %s, action: %s"
                         % (self.engine_id, self.stack.id, self.stack.action))

    def release(self):
        """Release a stack lock."""
        logger.debug("Releasing lock for engine: %s, stack: %s, action: %s"
                     % (self.engine_id, self.stack.id, self.stack.action))
        db_api.stack_lock_release(self.context, self.stack.id)

    def _gt_callback_release(self, gt, *args, **kwargs):
        """Callback function that will be passed to GreenThread.link()."""
        # If gt.wait() isn't called here and a lock exists, then the
        # pending _gt_callback_release() from the previous acquire()
        # will be executed immediately upon the next call to
        # acquire().  This leads to a pre-mature release of the lock.
        gt.wait()
        self.release()
