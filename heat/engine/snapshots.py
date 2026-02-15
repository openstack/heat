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

import tenacity
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils as oslo_timeutils
from oslo_utils import uuidutils

from heat.common import context as heat_context
from heat.common import exception
from heat.common import timeutils as heat_timeutils
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import sync_point
from heat.objects import resource_snapshot as rsrc_snapshot_objects
from heat.objects import snapshot as snapshot_object
from heat.rpc import worker_client as rpc_worker_client


LOG = logging.getLogger(__name__)


class Snapshot(object):
    """Operate snapshot actions under convergence."""

    ACTIONS = (
        DELETE_SNAPSHOT
    ) = (
        'delete_snapshot'
    )

    def __init__(self, context, snapshot_id, stack_id,
                 start_time, thread_group_mgr, resources=None, action=None,
                 timeout_mins=None, is_stack_delete=False,
                 current_traversal=None):
        self.context = context
        self.id = snapshot_id
        self.stack_id = stack_id
        self.action = self.DELETE_SNAPSHOT if action is None else action
        self.is_stack_delete = is_stack_delete
        self.current_traversal = current_traversal if (
            current_traversal is not None) else uuidutils.generate_uuid()

        self.thread_group_mgr = thread_group_mgr
        self._worker_client = None

        self.start_time = start_time
        self.timeout_mins = timeout_mins
        self.resources = resources

    def delete_snapshot(self):
        snapshot_obj = snapshot_object.Snapshot.get_snapshot(
            self.context, self.id, load_rsrc_snapshot=True)
        if snapshot_obj.status == parser.Stack.IN_PROGRESS:
            msg = _('Deleting in-progress snapshot')
            raise exception.NotSupported(feature=msg)
        if self.resources is None:
            self.resources = snapshot_obj.data['resources']

        # TODO(ricolin) send notification and add event

        LOG.debug("Start deleting snapshot %s.", self.id)
        self.thread_group_mgr.start(self.stack_id, self.do_delete_snapshot)

    def do_delete_snapshot(self):
        if self.resources:
            sync_point.create(self.context, self.id,
                              self.current_traversal, True,
                              self.stack_id)
            LOG.debug("Create sync_point for (snapshot, traversal, "
                      "is_update): %s.",
                      (self.id, self.current_traversal, True))

            start_time = self.start_time.strftime(
                heat_timeutils.str_duration_format)

            for rsrc_name in self.resources:
                self.worker_client.check_resource_delete_snapshot(
                    self.context, self.id, rsrc_name, start_time,
                    is_stack_delete=self.is_stack_delete,
                    current_traversal=self.current_traversal)

            if scheduler.ENABLE_SLEEP:
                time.sleep(1)
        else:
            self.mark_complete()

    def mark_complete(self, predecessors=None, input_data=None):
        if predecessors is None:
            predecessors = []
        self.delete_snapshot_objs()
        # Clear sync_points for snapshot
        sync_point.delete_all(self.context, self.id, self.current_traversal)
        LOG.debug("Clear all sync_points for (snapshot, traversal): %s.",
                  (self.id, self.current_traversal))
        if self.is_stack_delete:
            if input_data is None:
                sender_key = parser.ConvergenceNode(self.id, True)
                input_data = {sender_key: None}
            try:
                update = sync_point.update_sync_point(
                    self.context, self.stack_id, self.current_traversal,
                    True, predecessors=predecessors, new_data=input_data)
                if not update:
                    LOG.debug("Fail to update stack %(stack)s sync_point entry"
                              "after snapshot %(snapshot_id)s competed",
                              {'snapshot_id': self.id, 'stack': self.stack_id})
                    return False
            except exception.EntityNotFound:
                LOG.debug("Ignore EntityNotFound: Stack sync_point entity %s "
                          "already deleted, this is because other snapshot "
                          "delete already failed.",
                          (self.stack_id, self.current_traversal, True))
        LOG.info("Snapshot %(snapshot_id)s for stack %(stack_id)s %(action)s "
                 "complete.",
                 {'snapshot_id': self.id, 'stack_id': self.stack_id,
                  'action': self.action})
        return True

    def mark_failed(self, rsrc_name, failure_reason):
        LOG.info("Snapshot %(snapshot_id)s for Stack %(stack_id)s %(action)s "
                 "failed. Snapshot resource: %(rsrc_name)s %(action)s failed "
                 "with reason: %(reason)s.",
                 {'snapshot_id': self.id, 'stack_id': self.stack_id,
                  'action': self.action, 'rsrc_name': rsrc_name,
                  'reason': failure_reason})
        # Update snapshot status to DELETE_FAILED
        try:
            snapshot_object.Snapshot.update(
                self.context, self.id,
                {'status': 'DELETE_FAILED',
                 'status_reason': failure_reason})
        except Exception:
            LOG.debug("Failed to update snapshot %(snapshot_id)s status.",
                      {'snapshot_id': self.id})
        # Clear sync_points for snapshot
        sync_point.delete_all(self.context, self.id, self.current_traversal)
        LOG.debug("Clear all sync_points for (snapshot, traversal): %s.",
                  (self.id, self.current_traversal))
        if self.is_stack_delete:
            try:
                update = sync_point.update_sync_point(
                    self.context, self.stack_id, self.current_traversal,
                    True, predecessors=[], new_rsrc_failure=failure_reason)
                if not update:
                    LOG.debug("Fail to update stack %(stack)s sync_point "
                              "entry after snapshot %(snapshot_id)s failed.",
                              {'snapshot_id': self.id, 'stack': self.stack_id})
                    return False
            except exception.EntityNotFound:
                LOG.debug("Ignore EntityNotFound: Stack sync_point entity %s "
                          "already deleted, this is because other snapshot "
                          "delete already failed.",
                          (self.stack_id, self.current_traversal, True))
        return True

    def delete_snapshot_objs(self):
        LOG.debug("Start to clear objects for snapshot %(snapshot_id)s.",
                  {'snapshot_id': self.id})
        rsrc_snapshot_objects.ResourceSnapshot.delete_all_by_snapshot(
            self.context, self.id)
        snapshot_object.Snapshot.delete(self.context, self.id)

    @property
    def worker_client(self):
        """Return a client for making engine RPC calls."""
        if not self._worker_client:
            self._worker_client = rpc_worker_client.WorkerClient()
        return self._worker_client

    def timeout_secs(self):
        """Return the action timeout in seconds."""
        if self.timeout_mins is None:
            return cfg.CONF.stack_action_timeout

        return self.timeout_mins * 60

    def time_elapsed(self):
        """Time elapsed in seconds since the Snapshot operation started."""
        return (oslo_timeutils.utcnow() - self.start_time).total_seconds()

    def time_remaining(self):
        """Time left before Snapshot times out."""
        return self.timeout_secs() - self.time_elapsed()

    def has_timed_out(self):
        """Returns True if this Snapshot has timed-out."""
        return self.time_elapsed() > self.timeout_secs()


def delete_snapshots(context, snapshot_ids, stack_id, current_traversal,
                     start_time, thread_group_mgr, run_till_success=True):
    if not snapshot_ids:
        return
    # create sync_point entry for stack. When snapshot delete completed/failed,
    # it will update to sync_point entry for stack.
    sync_point.create(
        context, stack_id, current_traversal, True, stack_id)
    LOG.debug("Create sync_point for (stack, traversal, is_update): %s",
              (stack_id, current_traversal, True))

    # avoid reuse current db session to multiple threads.
    cnxt = context.to_dict()
    # Iterate over a copy to safely remove items
    for snapshot_id in list(snapshot_ids):
        snapshot = Snapshot(
            context=heat_context.RequestContext.from_dict(cnxt),
            snapshot_id=snapshot_id,
            stack_id=stack_id,
            start_time=start_time,
            thread_group_mgr=thread_group_mgr,
            action=Snapshot.DELETE_SNAPSHOT,
            is_stack_delete=True,
            current_traversal=current_traversal)
        try:
            snapshot.delete_snapshot()
        except exception.NotFound:
            LOG.info("Snapshot %(snapshot)s for stack %(stack)s is "
                     "already deleted.",
                     {'snapshot': snapshot_id, 'stack': stack_id})
            # Since it's not found in object, we don't need to update it to
            # stack sync_point entry.
            snapshot_ids.remove(snapshot_id)
    if run_till_success:
        allow_running_time = cfg.CONF.stack_action_timeout - (
            oslo_timeutils.utcnow() - start_time).total_seconds()
        wait_strategy = tenacity.wait_random_exponential(max=60)
        count_num_snapshots = len(snapshot_ids)

        def init_jitter(existing_input_data):
            nconflicts = max(
                0, count_num_snapshots - len(existing_input_data) - 1)
            # 10ms per potential conflict, up to a max of 10s in total
            return min(nconflicts, 1000) * 0.01

        @tenacity.retry(
            retry=tenacity.retry_if_result(lambda r: r is False),
            wait=wait_strategy,
            stop=tenacity.stop_after_delay(allow_running_time)
        )
        def _wait_for_complete():
            s_p = sync_point.get(context, stack_id, current_traversal, True)
            input_data = sync_point.deserialize_input_data(s_p.input_data)
            extra_data = sync_point.deserialize_extra_data(
                s_p.extra_data) if s_p.extra_data is not None else {}
            rsrc_failures = extra_data.get("resource_failures", {})
            if rsrc_failures:
                return str(rsrc_failures)
            snaps = set(parser.ConvergenceNode(s, True) for s in snapshot_ids)
            waiting = snaps - set(input_data)
            wait_strategy.multiplier = init_jitter(input_data)
            if not waiting:
                return
            return False

        failure_reason = _wait_for_complete()
        # Clear sync_points for stack
        sync_point.delete_all(context, stack_id, current_traversal)
        LOG.debug("Clear all sync_points for (stack, traversal): %s.",
                  (stack_id, current_traversal))
        return failure_reason
