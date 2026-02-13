# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import functools
import queue
import time

from oslo_log import log as logging
import oslo_messaging
from oslo_utils import excutils
from oslo_utils import timeutils as oslo_timeutils
from oslo_utils import uuidutils
from osprofiler import profiler

from heat.common import context
from heat.common import exception
from heat.common import messaging as rpc_messaging
from heat.common import timeutils as heat_timeutils
from heat.db import api as db_api
from heat.engine import check_resource
from heat.engine import node_data
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import sync_point
from heat.objects import stack as stack_objects
from heat.rpc import api as rpc_api
from heat.rpc import worker_client as rpc_client

LOG = logging.getLogger(__name__)

CANCEL_RETRIES = 3


def log_exceptions(func):
    @functools.wraps(func)
    def exception_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Unhandled exception in %s', func.__name__)

    return exception_wrapper


@profiler.trace_cls("rpc")
class WorkerService(object):
    """Service that has 'worker' actor in convergence.

    This service is dedicated to handle internal messages to the 'worker'
    (a.k.a. 'converger') actor in convergence. Messages on this bus will
    use the 'cast' rather than 'call' method to anycast the message to
    an engine that will handle it asynchronously. It won't wait for
    or expect replies from these messages.
    """

    RPC_API_VERSION = '1.9'

    def __init__(self,
                 host,
                 topic,
                 engine_id,
                 thread_group_mgr):
        self.host = host
        self.topic = topic
        self.engine_id = engine_id
        self.thread_group_mgr = thread_group_mgr

        self._rpc_client = rpc_client.WorkerClient()
        self._rpc_server = None
        self.target = None

    def start(self):
        target = oslo_messaging.Target(
            version=self.RPC_API_VERSION,
            server=self.engine_id,
            topic=self.topic)
        self.target = target
        LOG.info("Starting %(topic)s (%(version)s) in engine %(engine)s.",
                 {'topic': self.topic,
                  'version': self.RPC_API_VERSION,
                  'engine': self.engine_id})

        self._rpc_server = rpc_messaging.get_rpc_server(target, self)
        self._rpc_server.start()

    def stop(self):
        if self._rpc_server is None:
            return
        # Stop rpc connection at first for preventing new requests
        LOG.info("Stopping %(topic)s in engine %(engine)s.",
                 {'topic': self.topic, 'engine': self.engine_id})
        try:
            self._rpc_server.stop()
            self._rpc_server.wait()
        except Exception as e:
            LOG.error("%(topic)s is failed to stop, %(exc)s",
                      {'topic': self.topic, 'exc': e})

    def stop_traversal(self, stack):
        """Update current traversal to stop workers from propagating.

        Marks the stack as FAILED due to cancellation, but, allows all
        in_progress resources to complete normally; no worker is stopped
        abruptly.

        Any in-progress traversals are also stopped on all nested stacks that
        are descendants of the one passed.
        """
        _stop_traversal(stack)

        db_child_stacks = stack_objects.Stack.get_all_by_root_owner_id(
            stack.context, stack.id)

        for db_child in db_child_stacks:
            if db_child.status == parser.Stack.IN_PROGRESS:
                child = parser.Stack.load(stack.context,
                                          stack_id=db_child.id,
                                          stack=db_child,
                                          load_template=False)
                _stop_traversal(child)

    def stop_all_workers(self, stack):
        """Cancel all existing worker threads for the stack.

        Threads will stop running at their next yield point, whether or not the
        resource operations are complete.
        """
        cancelled = _cancel_workers(stack, self.thread_group_mgr,
                                    self.engine_id, self._rpc_client)
        if not cancelled:
            LOG.error("Failed to stop all workers of stack %s, "
                      "stack cancel not complete", stack.name)
            return False

        LOG.info('[%(name)s(%(id)s)] Stopped all active workers for stack '
                 '%(action)s',
                 {'name': stack.name, 'id': stack.id, 'action': stack.action})

        return True

    def _retrigger_replaced(self, is_update, rsrc, stack, check_resource):
        graph = stack.convergence_dependencies.graph()
        key = parser.ConvergenceNode(rsrc.id, is_update)
        if key not in graph and rsrc.replaces is not None:
            # This resource replaces old one and is not needed in
            # current traversal. You need to mark the resource as
            # DELETED so that it gets cleaned up in purge_db.
            values = {'action': rsrc.DELETE}
            db_api.resource_update_and_save(stack.context, rsrc.id, values)
            # The old resource might be in the graph (a rollback case);
            # just re-trigger it.
            check_resource.retrigger_check_resource(stack.context,
                                                    rsrc.replaces, stack)

    @context.request_context
    @log_exceptions
    def check_resource_delete_snapshot(self, cnxt, snapshot_id, resource_name,
                                       start_time=None, is_stack_delete=False,
                                       current_traversal=None):
        if start_time is not None:
            start_time = oslo_timeutils.datetime.datetime.strptime(
                start_time, heat_timeutils.str_duration_format)
        rsrc, stack, snapshot = check_resource.load_resource_from_snapshot(
            cnxt, rsrc_name=resource_name, snapshot_id=snapshot_id,
            thread_group_mgr=self.thread_group_mgr,
            is_stack_delete=is_stack_delete,
            current_traversal=current_traversal,
            start_time=start_time)

        if rsrc is None:
            return

        rsrc.stack = stack

        msg_queue = queue.Queue()
        try:
            self.thread_group_mgr.add_msg_queue(snapshot.id, msg_queue)
            cr = check_resource.CheckResource(self.engine_id,
                                              self._rpc_client,
                                              self.thread_group_mgr,
                                              msg_queue, {})
            cr.check_delete_snapshot(cnxt, rsrc, snapshot)
        finally:
            self.thread_group_mgr.remove_msg_queue(None,
                                                   snapshot.id, msg_queue)

    @context.request_context
    @log_exceptions
    def check_resource(self, cnxt, resource_id, current_traversal, data,
                       is_update, adopt_stack_data, converge=False,
                       skip_propagate=False, accumulated_failures=None,
                       node_type='resource', abandon=False):
        """Process a node in the dependency graph.

        The node may be associated with either an update or a cleanup of its
        associated resource, or a snapshot deletion.
        """
        # Handle snapshot nodes differently
        if node_type == 'snapshot':
            return self._handle_snapshot_node(
                cnxt, resource_id, current_traversal, data, is_update)

        in_data = sync_point.deserialize_input_data(data)
        resource_data = node_data.load_resources_data(in_data if is_update
                                                      else {})
        rsrc, stk_defn, stack = check_resource.load_resource(cnxt, resource_id,
                                                             resource_data,
                                                             current_traversal,
                                                             is_update)

        if rsrc is None:
            return

        rsrc.converge = converge
        if abandon:
            rsrc.abandon_in_progress = True

        msg_queue = queue.Queue()
        try:
            self.thread_group_mgr.add_msg_queue(stack.id, msg_queue)
            cr = check_resource.CheckResource(self.engine_id,
                                              self._rpc_client,
                                              self.thread_group_mgr,
                                              msg_queue, in_data)
            if current_traversal != stack.current_traversal:
                LOG.debug('[%s] Traversal cancelled; re-trigerring.',
                          current_traversal)
                self._retrigger_replaced(is_update, rsrc, stack, cr)
            else:
                cr.check(cnxt, resource_id, current_traversal, resource_data,
                         is_update, adopt_stack_data, rsrc, stack,
                         skip_propagate, accumulated_failures)
        finally:
            self.thread_group_mgr.remove_msg_queue(None,
                                                   stack.id, msg_queue)

    def _handle_snapshot_node(self, cnxt, snapshot_id, current_traversal,
                              data, is_update):
        """Handle snapshot deletion as part of convergence graph.

        This method reuses the Snapshot class for the actual deletion work,
        but handles graph propagation separately for the non-blocking flow.
        """
        from heat.engine import snapshots
        from heat.objects import snapshot as snapshot_object

        LOG.debug("Processing snapshot node %s for deletion", snapshot_id)

        try:
            snapshot_obj = snapshot_object.Snapshot.get_snapshot(
                cnxt, snapshot_id, load_rsrc_snapshot=True)
        except exception.NotFound:
            LOG.debug("Snapshot %s already deleted", snapshot_id)
            # Still need to propagate completion
            self._propagate_snapshot_complete(
                cnxt, snapshot_id, current_traversal, stack_id=None)
            return

        stack = parser.Stack.load(cnxt, stack_id=snapshot_obj.stack_id,
                                  force_reload=True)

        if current_traversal != stack.current_traversal:
            LOG.debug('[%s] Traversal cancelled for snapshot deletion.',
                      current_traversal)
            return

        # Create a Snapshot instance to reuse existing deletion logic
        start_time = stack.updated_time or stack.created_time
        snapshot = snapshots.Snapshot(
            context=cnxt,
            snapshot_id=snapshot_id,
            stack_id=stack.id,
            start_time=start_time,
            thread_group_mgr=self.thread_group_mgr,
            resources=snapshot_obj.data.get('resources'),
            action=snapshots.Snapshot.DELETE_SNAPSHOT,
            is_stack_delete=True,
            current_traversal=current_traversal)

        # Delete resource snapshots using resource's delete_snapshot method
        try:
            self._delete_snapshot_resources(cnxt, snapshot_obj, stack)
            # Use Snapshot class to delete DB objects
            snapshot.delete_snapshot_objs()
            LOG.info("Snapshot %s deleted successfully", snapshot_id)
        except Exception as ex:
            LOG.error("Failed to delete snapshot %s: %s", snapshot_id, ex)
            # Propagate failure through the convergence graph
            self._propagate_snapshot_complete(
                cnxt, snapshot_id, current_traversal,
                stack_id=stack.id, failure=str(ex))
            return

        # Propagate completion through the convergence graph
        self._propagate_snapshot_complete(
            cnxt, snapshot_id, current_traversal, stack_id=stack.id)

    def _delete_snapshot_resources(self, cnxt, snapshot_obj, stack):
        """Delete all resource snapshots for a snapshot."""
        resources_data = snapshot_obj.data.get('resources', {})
        for rsrc_name, rsrc_data in resources_data.items():
            rsrc = stack.resources.get(rsrc_name)
            if rsrc and rsrc_data:
                try:
                    # Call delete_snapshot on the resource
                    runner = scheduler.TaskRunner(rsrc.delete_snapshot,
                                                  rsrc_data)
                    runner(timeout=stack.timeout_secs())
                except Exception as ex:
                    LOG.warning("Failed to delete snapshot for resource "
                                "%s: %s", rsrc_name, ex)

    def _propagate_snapshot_complete(self, cnxt, snapshot_id,
                                     current_traversal, stack_id=None,
                                     failure=None):
        """Propagate snapshot completion through the convergence graph."""
        if stack_id is None:
            # Snapshot was already deleted, can't determine stack
            # For now, just return - the sync_point will time out
            LOG.debug("Cannot propagate for already-deleted snapshot")
            return

        stack = parser.Stack.load(cnxt, stack_id=stack_id, force_reload=True)

        if current_traversal != stack.current_traversal:
            return

        deps = stack.convergence_dependencies
        graph = deps.graph()
        graph_key = parser.ConvergenceNode(snapshot_id, False,
                                           parser.NODE_TYPE_SNAPSHOT)

        if failure:
            # Mark stack as failed
            stack.mark_failed('Snapshot deletion failed: %s' % failure)
            return

        # Propagate to dependent nodes (resources waiting on this snapshot)
        if graph_key in graph:
            for req_node in deps.required_by(graph_key):
                # Snapshot nodes don't have input data to pass
                check_resource.propagate_check_resource(
                    cnxt, self._rpc_client, req_node.rsrc_id,
                    current_traversal, set(graph[req_node]),
                    graph_key, None, req_node.is_update,
                    stack.adopt_stack_data, converge=stack.converge,
                    node_type=req_node.node_type)

        # Check if the whole stack operation is complete
        check_resource.check_stack_complete(
            cnxt, stack, current_traversal, snapshot_id, deps, False,
            node_type=parser.NODE_TYPE_SNAPSHOT)

    @context.request_context
    @log_exceptions
    def cancel_check_resource(self, cnxt, stack_id):
        """Cancel check_resource for given stack.

        All the workers running for the given stack will be
        cancelled.
        """
        _cancel_check_resource(stack_id, self.engine_id, self.thread_group_mgr)


def _stop_traversal(stack):
    old_trvsl = stack.current_traversal
    updated = _update_current_traversal(stack)
    if not updated:
        LOG.warning("Failed to update stack %(name)s with new "
                    "traversal, aborting stack cancel", stack.name)
        return

    reason = 'Stack %(action)s cancelled' % {'action': stack.action}
    updated = stack.state_set(stack.action, stack.FAILED, reason)
    if not updated:
        LOG.warning("Failed to update stack %(name)s status "
                    "to %(action)s_%(state)s",
                    {'name': stack.name, 'action': stack.action,
                     'state': stack.FAILED})
        return

    sync_point.delete_all(stack.context, stack.id, old_trvsl)


def _update_current_traversal(stack):
    previous_traversal = stack.current_traversal
    stack.current_traversal = uuidutils.generate_uuid()
    values = {'current_traversal': stack.current_traversal}
    return stack_objects.Stack.select_and_update(
        stack.context, stack.id, values,
        exp_trvsl=previous_traversal)


def _cancel_check_resource(stack_id, engine_id, tgm):
    LOG.debug('Cancelling workers for stack [%s] in engine [%s]',
              stack_id, engine_id)
    tgm.send(stack_id, rpc_api.THREAD_CANCEL)


def _wait_for_cancellation(stack, wait=5):
    # give enough time to wait till cancel is completed
    retries = CANCEL_RETRIES
    while retries > 0:
        retries -= 1
        time.sleep(wait)
        engines = db_api.engine_get_all_locked_by_stack(
            stack.context, stack.id)
        if not engines:
            return True

    return False


def _cancel_workers(stack, tgm, local_engine_id, rpc_client):
    engines = db_api.engine_get_all_locked_by_stack(stack.context, stack.id)

    if not engines:
        return True

    # cancel workers running locally
    if local_engine_id in engines:
        _cancel_check_resource(stack.id, local_engine_id, tgm)
        engines.remove(local_engine_id)

    # cancel workers on remote engines
    for engine_id in engines:
        rpc_client.cancel_check_resource(stack.context, stack.id, engine_id)

    return _wait_for_cancellation(stack)
