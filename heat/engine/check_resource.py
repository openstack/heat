# Copyright (c) 2016 Hewlett-Packard Development Company, L.P.
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

from oslo_log import log as logging
from oslo_utils import excutils

from heat.common import exception
from heat.engine import dependencies
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import snapshots
from heat.engine import stack as parser
from heat.engine import sync_point
from heat.objects import resource as resource_objects
from heat.objects import snapshot as snapshot_objects
from heat.rpc import api as rpc_api
from heat.rpc import listener_client

LOG = logging.getLogger(__name__)


class CancelOperation(BaseException):
    """Exception to cancel an in-progress operation on a resource.

    This exception is raised when operations on a resource are cancelled.
    """
    def __init__(self):
        return super(CancelOperation, self).__init__('user triggered cancel')


class CheckResource(object):

    def __init__(self,
                 engine_id,
                 rpc_client,
                 thread_group_mgr,
                 msg_queue,
                 input_data):
        self.engine_id = engine_id
        self._rpc_client = rpc_client
        self.thread_group_mgr = thread_group_mgr
        self.msg_queue = msg_queue
        self.input_data = input_data

    def _stale_resource_needs_retry(self, cnxt, rsrc, prev_template_id):
        """Determine whether a resource needs retrying after failure to lock.

        Return True if we need to retry the check operation because of a
        failure to acquire the lock. This can be either because the engine
        holding the lock is no longer working, or because no other engine had
        locked the resource and the data was just out of date.

        In the former case, the lock will be stolen and the resource status
        changed to FAILED.
        """
        fields = {'current_template_id', 'engine_id'}
        rs_obj = resource_objects.Resource.get_obj(cnxt,
                                                   rsrc.id,
                                                   refresh=True,
                                                   fields=fields)
        if rs_obj.engine_id not in (None, self.engine_id):
            if not listener_client.EngineListenerClient(
                    rs_obj.engine_id).is_alive(cnxt):
                # steal the lock.
                rs_obj.update_and_save({'engine_id': None})

                # set the resource state as failed
                status_reason = ('Worker went down '
                                 'during resource %s' % rsrc.action)
                rsrc.state_set(rsrc.action,
                               rsrc.FAILED,
                               str(status_reason))
                return True
        elif (rs_obj.engine_id is None and
              rs_obj.current_template_id == prev_template_id):
            LOG.debug('Resource id=%d stale; retrying check', rsrc.id)
            return True
        LOG.debug('Resource id=%d modified by another traversal', rsrc.id)
        return False

    def _handle_resource_failure(self, cnxt, is_update, rsrc_id,
                                 stack, failure_reason, rsrc_name=None,
                                 current_traversal=None):
        # Use stack's current traversal if not provided
        if current_traversal is None:
            current_traversal = stack.current_traversal
        if stack.action == stack.CHECK:
            # For CHECK action, continue traversal and let failures propagate
            # through sync mechanism. Return failure info for propagation.
            # Use resource name for better error messages if available
            failure_key = rsrc_name if rsrc_name else str(rsrc_id)
            # Return (check_done=True, is_skip=True, failure_info)
            return True, True, {failure_key: failure_reason}
        failure_handled = stack.mark_failed(failure_reason)
        if not failure_handled:
            # Another concurrent update has taken over. But there is a
            # possibility for that update to be waiting for this rsrc to
            # complete, hence retrigger current rsrc for latest traversal.
            self._retrigger_new_traversal(cnxt, current_traversal,
                                          is_update,
                                          stack.id, rsrc_id)
        return False, False, None

    def _retrigger_new_traversal(self, cnxt, current_traversal, is_update,
                                 stack_id, rsrc_id):
        latest_stack = parser.Stack.load(cnxt, stack_id=stack_id,
                                         force_reload=True)
        if current_traversal != latest_stack.current_traversal:
            self.retrigger_check_resource(cnxt, rsrc_id, latest_stack)

    def _handle_stack_timeout(self, cnxt, stack):
        failure_reason = 'Timed out'
        stack.mark_failed(failure_reason)

    def _handle_resource_replacement(self, cnxt,
                                     current_traversal, new_tmpl_id, requires,
                                     rsrc, stack, adopt_stack_data):
        """Create a replacement resource and trigger a check on it."""
        try:
            new_res_id = rsrc.make_replacement(new_tmpl_id, requires)
        except exception.UpdateInProgress:
            LOG.info("No replacement created - "
                     "resource already locked by new traversal")
            return
        if new_res_id is None:
            LOG.info("No replacement created - "
                     "new traversal already in progress")
            self._retrigger_new_traversal(cnxt, current_traversal, True,
                                          stack.id, rsrc.id)
            return
        LOG.info("Replacing resource with new id %s", new_res_id)
        rpc_data = sync_point.serialize_input_data(self.input_data)
        self._rpc_client.check_resource(cnxt,
                                        new_res_id,
                                        current_traversal,
                                        rpc_data, True,
                                        adopt_stack_data)

    def _do_check_resource(self, cnxt, current_traversal, tmpl, resource_data,
                           is_update, rsrc, stack, adopt_stack_data):
        prev_template_id = rsrc.current_template_id
        try:
            if is_update:
                requires = set(d.primary_key for d in resource_data.values()
                               if d is not None)
                try:
                    check_resource_update(rsrc, tmpl.id, requires,
                                          self.engine_id,
                                          stack, self.msg_queue)
                except resource.UpdateReplace:
                    self._handle_resource_replacement(cnxt, current_traversal,
                                                      tmpl.id, requires,
                                                      rsrc, stack,
                                                      adopt_stack_data)
                    return False, False, None

            else:
                check_resource_cleanup(rsrc, tmpl.id, self.engine_id, stack,
                                       self.msg_queue)

            return True, False, None
        except exception.UpdateInProgress:
            LOG.debug('Waiting for existing update to unlock resource %s',
                      rsrc.id)
            if self._stale_resource_needs_retry(cnxt, rsrc, prev_template_id):
                rpc_data = sync_point.serialize_input_data(self.input_data)
                self._rpc_client.check_resource(cnxt,
                                                rsrc.id,
                                                current_traversal,
                                                rpc_data, is_update,
                                                adopt_stack_data)
            else:
                rsrc.handle_preempt()
        except exception.ResourceFailure as ex:
            action = ex.action or rsrc.action
            reason = 'Resource %s failed: %s' % (action,
                                                 str(ex))
            return self._handle_resource_failure(
                cnxt, is_update, rsrc.id, stack, reason,
                rsrc_name=rsrc.name, current_traversal=current_traversal)
        except scheduler.Timeout:
            return self._handle_resource_failure(
                cnxt, is_update, rsrc.id, stack, 'Timed out',
                rsrc_name=rsrc.name, current_traversal=current_traversal)
        except CancelOperation:
            # Stack is already marked FAILED, so we just need to retrigger
            # in case a new traversal has started and is waiting on us.
            self._retrigger_new_traversal(cnxt, current_traversal, is_update,
                                          stack.id, rsrc.id)

        return False, False, None

    def retrigger_check_resource(self, cnxt, resource_id, stack):
        current_traversal = stack.current_traversal
        graph = stack.convergence_dependencies.graph()

        # When re-trigger received for latest traversal, first check if update
        # key is available in graph. If yes, the latest traversal is waiting
        # for update, otherwise it is waiting for delete. This is the case
        # regardless of which action (update or cleanup) from the previous
        # traversal was blocking it.
        update_key = parser.ConvergenceNode(resource_id, True)
        key = parser.ConvergenceNode(resource_id, update_key in graph)

        LOG.info('Re-trigger resource: %s', key)
        predecessors = set(graph[key])

        try:
            propagate_check_resource(cnxt, self._rpc_client, resource_id,
                                     current_traversal, predecessors, key,
                                     None, key.is_update, None,
                                     converge=stack.converge)
        except exception.EntityNotFound as e:
            if e.entity != "Sync Point":
                raise

    def _initiate_propagate_resource(self, cnxt, resource_id,
                                     current_traversal, is_update, rsrc,
                                     stack, is_skip=False, rsrc_failure=None):
        deps = stack.convergence_dependencies
        graph = deps.graph()
        graph_key = parser.ConvergenceNode(resource_id, is_update)

        if graph_key not in graph and rsrc.replaces is not None:
            # If we are a replacement, impersonate the replaced resource for
            # the purposes of calculating whether subsequent resources are
            # ready, since everybody has to work from the same version of the
            # graph. Our real resource ID is sent in the input_data, so the
            # dependencies will get updated to point to this resource in time
            # for the next traversal.
            graph_key = parser.ConvergenceNode(rsrc.replaces, is_update)

        def _get_input_data(req_node, input_forward_data=None):
            if req_node.is_update:
                if input_forward_data is None:
                    return rsrc.node_data().as_dict()
                else:
                    # do not re-resolve attrs
                    return input_forward_data
            else:
                # Don't send data if initiating clean-up for self i.e.
                # initiating delete of a replaced resource
                if req_node.rsrc_id != graph_key.rsrc_id:
                    # send replaced resource as needed_by if it exists
                    return (rsrc.replaced_by
                            if rsrc.replaced_by is not None
                            else resource_id)
            return None

        try:
            input_forward_data = None
            for req_node in sorted(deps.required_by(graph_key),
                                   key=lambda n: n.is_update):
                input_data = _get_input_data(req_node, input_forward_data)
                if req_node.is_update:
                    input_forward_data = input_data
                propagate_check_resource(
                    cnxt, self._rpc_client, req_node.rsrc_id,
                    current_traversal, set(graph[req_node]),
                    graph_key, input_data, req_node.is_update,
                    stack.adopt_stack_data, is_skip=is_skip,
                    rsrc_failure=rsrc_failure, converge=stack.converge)
            if is_update:
                if input_forward_data is None:
                    # we haven't resolved attribute data for the resource,
                    # so clear any old attributes so they may be re-resolved
                    rsrc.clear_stored_attributes()
                else:
                    rsrc.store_attributes()
            check_stack_complete(cnxt, stack, current_traversal,
                                 graph_key.rsrc_id, deps, graph_key.is_update,
                                 rsrc_failure, graph_key.node_type)
        except exception.EntityNotFound as e:
            if e.entity == "Sync Point":
                # Reload the stack to determine the current traversal, and
                # check the SyncPoint for the current node to determine if
                # it is ready. If it is, then retrigger the current node
                # with the appropriate data for the latest traversal.
                stack = parser.Stack.load(cnxt, stack_id=rsrc.stack.id,
                                          force_reload=True)
                if current_traversal == stack.current_traversal:
                    LOG.debug('[%s] Traversal sync point missing.',
                              current_traversal)
                    return

                self.retrigger_check_resource(cnxt, resource_id, stack)
            else:
                raise

    def check_delete_snapshot(self, cnxt, rsrc, snapshot):

        try:
            done = do_snapshot_delete(
                rsrc=rsrc, snapshot=snapshot, msg_queue=self.msg_queue,
                engine_id=self.engine_id)
            # TODO(ricolin) Allow running resources in batch_size.
            # Current delete snapshot runs all resources without
            # dependencies (every resources is root) because snapshot does
            # not depend on each other. Therefore, there are no next set.
            if done:
                deps = dependencies.Dependencies(
                    [(parser.ConvergenceNode(rsrc_name, True),
                        None) for rsrc_name in snapshot.resources])
                check_snapshot_complete(cnxt, snapshot, rsrc.name, deps, True)
        except BaseException as exc:
            with excutils.save_and_reraise_exception():
                msg = str(exc)
                LOG.exception("Unexpected exception in resource check delete "
                              "snapshot.")
                snapshot.mark_failed(rsrc.name, msg)

    def check(self, cnxt, resource_id, current_traversal,
              resource_data, is_update, adopt_stack_data,
              rsrc, stack, skip_propagate=False, accumulated_failures=None):
        """Process a node in the dependency graph.

        The node may be associated with either an update or a cleanup of its
        associated resource.
        """
        if stack.has_timed_out():
            self._handle_stack_timeout(cnxt, stack)
            return

        tmpl = stack.t
        stack.adopt_stack_data = adopt_stack_data
        stack.thread_group_mgr = self.thread_group_mgr

        try:
            if skip_propagate:
                check_done, is_skip, rsrc_failure = (True, True, None)
            else:
                check_done, is_skip, rsrc_failure = self._do_check_resource(
                    cnxt, current_traversal, tmpl, resource_data,
                    is_update, rsrc, stack, adopt_stack_data
                )

            if check_done:
                # Merge own failure with accumulated failures from predecessors
                merged_failures = dict(accumulated_failures or {})
                if rsrc_failure:
                    merged_failures.update(rsrc_failure)
                # initiate check on next set of resources from graph
                self._initiate_propagate_resource(
                    cnxt, resource_id, current_traversal, is_update,
                    rsrc, stack, is_skip=is_skip,
                    rsrc_failure=merged_failures or None)
        except BaseException as exc:
            with excutils.save_and_reraise_exception():
                msg = str(exc)
                LOG.exception("Unexpected exception in resource check.")
                self._handle_resource_failure(
                    cnxt, is_update, rsrc.id, stack, msg,
                    rsrc_name=rsrc.name,
                    current_traversal=current_traversal)


def load_resource(cnxt, resource_id, resource_data,
                  current_traversal, is_update):
    try:
        return resource.Resource.load(cnxt, resource_id, current_traversal,
                                      is_update, resource_data)
    except (exception.ResourceNotFound, exception.NotFound):
        # can be ignored
        return None, None, None


def load_resource_from_snapshot(cnxt, rsrc_name, snapshot_id,
                                thread_group_mgr, is_stack_delete,
                                current_traversal, start_time):
    try:
        snapshot_obj = snapshot_objects.Snapshot.get_snapshot(
            cnxt, snapshot_id, load_rsrc_snapshot=True)
        # Using stack_id from snapshot to load stack
        stack = parser.Stack.load(cnxt, stack_id=snapshot_obj.stack_id,
                                  force_reload=True)

        new_stack, tmpl = stack.restore_data(snapshot_obj)
        rsrc = new_stack.resources.get(rsrc_name)
        snapshot = snapshots.Snapshot(
            context=cnxt,
            snapshot_id=snapshot_id,
            stack_id=stack.id,
            action=snapshots.Snapshot.DELETE_SNAPSHOT,
            resources=snapshot_obj.data['resources'],
            thread_group_mgr=thread_group_mgr,
            is_stack_delete=is_stack_delete,
            current_traversal=current_traversal,
            start_time=start_time)

        # provide resource_data that contains resource snapshot information.
        rsrc._data = snapshot.resources.get(rsrc.name).get('resource_data')
        rsrc.converge = True

        return rsrc, stack, snapshot
    except exception.NotFound:
        # can be ignored
        return None, None, None


def check_snapshot_complete(cnxt, snapshot, sender_id, deps, is_update):
    """Mark the snapshot complete if the update is complete."""

    roots = set(deps.roots())

    if (sender_id, is_update) not in roots:
        return

    def check_complete(snapshot_id, data, rsrc_failures):
        if rsrc_failures:
            msg = (
                "Snapshot %(snapshot_id)s %(action)s failed: "
                "%(rsrc_failures)s"
            ) % {
                'snapshot_id': snapshot_id,
                'action': snapshot.action,
                'rsrc_failures': rsrc_failures
            }
            snapshot.mark_failed(snapshot_id, msg)
        else:
            snapshot.mark_complete(predecessors=roots)

    sender_key = parser.ConvergenceNode(sender_id, is_update)
    try:
        sync_point.sync(cnxt, snapshot.id, snapshot.current_traversal, True,
                        check_complete, roots, {sender_key: None})
    except exception.EntityNotFound:
        LOG.debug("Ignore EntityNotFound: Snapshot sync_point entity %s "
                  "already deleted. This might because other resource "
                  "snapshot actions already failed.",
                  (snapshot.id, snapshot.current_traversal, True))


def check_stack_complete(cnxt, stack, current_traversal, sender_id, deps,
                         is_update, rsrc_failure=None,
                         node_type=parser.NODE_TYPE_RESOURCE):
    """Mark the stack complete if the update is complete.

    Complete is currently in the sense that all desired resources are in
    service, not that superfluous ones have been cleaned up.
    """
    roots = set(deps.roots())
    sender_key = parser.ConvergenceNode(sender_id, is_update, node_type)

    if sender_key not in roots:
        return

    def check_complete(stack_id, data, rsrc_failures, skip_propagate):
        if stack.action == stack.CHECK:
            # mark failed if resource_failures provided.
            if rsrc_failures:
                # Format failures into readable message
                failure_msgs = [
                    '{}: {}'.format(name, reason)
                    for name, reason in rsrc_failures.items()]
                reason = 'Resource CHECK failed: ' + '; '.join(failure_msgs)
                stack.mark_failed(reason)
                return
        stack.mark_complete()

    sync_point.sync(cnxt, stack.id, current_traversal, True,
                    check_complete, roots, {sender_key: None},
                    new_resource_failures=rsrc_failure)


def propagate_check_resource(cnxt, rpc_client, next_res_id,
                             current_traversal, predecessors, sender_key,
                             sender_data, is_update, adopt_stack_data,
                             is_skip=False, rsrc_failure=None, converge=False,
                             node_type=parser.NODE_TYPE_RESOURCE):
    """Trigger processing of node if all of its dependencies are satisfied."""
    def do_check(entity_id, data, rsrc_failures, skip_propagate):
        # Pass accumulated failures through RPC so they propagate to dependents
        rpc_client.check_resource(cnxt, entity_id, current_traversal,
                                  data, is_update, adopt_stack_data,
                                  converge=converge,
                                  skip_propagate=skip_propagate,
                                  accumulated_failures=rsrc_failures or None,
                                  node_type=node_type)

    sync_point.sync(cnxt, next_res_id, current_traversal,
                    is_update, do_check, predecessors,
                    {sender_key: sender_data},
                    new_resource_failures=rsrc_failure,
                    is_skip=is_skip)


def _check_for_message(msg_queue):
    if msg_queue is None:
        return
    try:
        message = msg_queue.get_nowait()
    except queue.Empty:
        return

    if message == rpc_api.THREAD_CANCEL:
        raise CancelOperation

    LOG.error('Unknown message "%s" received', message)


def check_resource_update(rsrc, template_id, requires, engine_id,
                          stack, msg_queue):
    """Create or update the Resource if appropriate."""
    if stack.action == stack.SUSPEND:
        return
    check_message = functools.partial(_check_for_message, msg_queue)
    if stack.action in [stack.CHECK, stack.RESUME, stack.SNAPSHOT]:
        do_convergence = getattr(rsrc, stack.action.lower() + "_convergence")
        do_convergence(engine_id, stack.time_remaining(), check_message)
    elif rsrc.action == resource.Resource.INIT:
        rsrc.create_convergence(template_id, requires, engine_id,
                                stack.time_remaining(), check_message)
    else:
        rsrc.update_convergence(template_id, requires, engine_id,
                                stack.time_remaining(), stack,
                                check_message)


def check_resource_cleanup(rsrc, template_id, engine_id, stack, msg_queue):
    """Delete the Resource if appropriate."""
    if stack.action in [stack.CHECK, stack.RESUME, stack.SNAPSHOT]:
        return
    check_message = functools.partial(_check_for_message, msg_queue)
    if stack.action == stack.SUSPEND:
        rsrc.suspend_convergence(engine_id, stack.time_remaining(),
                                 check_message)
    else:
        rsrc.delete_convergence(template_id, engine_id,
                                stack.time_remaining(), check_message)


def do_snapshot_delete(rsrc, snapshot, msg_queue, engine_id):
    try:
        check_message = functools.partial(
            _check_for_message, msg_queue)
        do_convergence = getattr(
            rsrc, snapshot.action.lower() + "_convergence")
        do_convergence(
            engine_id, snapshot.time_remaining(), check_message)
    except exception.ResourceFailure as ex:
        action = ex.action or rsrc.action
        reason = 'Resource %s failed: %s' % (action,
                                             str(ex))
        snapshot.mark_failed(rsrc.name, reason)
        return False
    except scheduler.Timeout:
        snapshot.mark_failed(rsrc.name, u'Timed out')
        return False
    return True
