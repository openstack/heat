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

from oslo_log import log as logging
import oslo_messaging
from oslo_service import service
from osprofiler import profiler
import six

from heat.common import context
from heat.common import exception
from heat.common.i18n import _LE
from heat.common.i18n import _LI
from heat.common import messaging as rpc_messaging
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import sync_point
from heat.objects import resource as resource_objects
from heat.rpc import listener_client
from heat.rpc import worker_client as rpc_client

LOG = logging.getLogger(__name__)


@profiler.trace_cls("rpc")
class WorkerService(service.Service):
    """Service that has 'worker' actor in convergence.

    This service is dedicated to handle internal messages to the 'worker'
    (a.k.a. 'converger') actor in convergence. Messages on this bus will
    use the 'cast' rather than 'call' method to anycast the message to
    an engine that will handle it asynchronously. It won't wait for
    or expect replies from these messages.
    """

    RPC_API_VERSION = '1.2'

    def __init__(self,
                 host,
                 topic,
                 engine_id,
                 thread_group_mgr):
        super(WorkerService, self).__init__()
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
            server=self.host,
            topic=self.topic)
        self.target = target
        LOG.info(_LI("Starting %(topic)s (%(version)s) in engine %(engine)s."),
                 {'topic': self.topic,
                  'version': self.RPC_API_VERSION,
                  'engine': self.engine_id})

        self._rpc_server = rpc_messaging.get_rpc_server(target, self)
        self._rpc_server.start()

        super(WorkerService, self).start()

    def stop(self):
        # Stop rpc connection at first for preventing new requests
        LOG.info(_LI("Stopping %(topic)s in engine %(engine)s."),
                 {'topic': self.topic, 'engine': self.engine_id})
        try:
            self._rpc_server.stop()
            self._rpc_server.wait()
        except Exception as e:
            LOG.error(_LE("%(topic)s is failed to stop, %(exc)s"),
                      {'topic': self.topic, 'exc': e})

        super(WorkerService, self).stop()

    def _try_steal_engine_lock(self, cnxt, resource_id):
        rs_obj = resource_objects.Resource.get_obj(cnxt,
                                                   resource_id)
        if (rs_obj.engine_id != self.engine_id and
                rs_obj.engine_id is not None):
            if not listener_client.EngineListenerClient(
                    rs_obj.engine_id).is_alive(cnxt):
                # steal the lock.
                rs_obj.update_and_save({'engine_id': None})
                return True
        return False

    def _trigger_rollback(self, stack):
        LOG.info(_LI("Triggering rollback of %(stack_name)s %(action)s "),
                 {'action': stack.action, 'stack_name': stack.name})
        stack.rollback()

    def _handle_failure(self, cnxt, stack, failure_reason):
        updated = stack.state_set(stack.action, stack.FAILED, failure_reason)
        if not updated:
            return False

        if (not stack.disable_rollback and
                stack.action in (stack.CREATE, stack.ADOPT, stack.UPDATE)):
            self._trigger_rollback(stack)
        else:
            stack.purge_db()
        return True

    def _handle_resource_failure(self, cnxt, is_update, rsrc_id,
                                 stack, failure_reason):
        failure_handled = self._handle_failure(cnxt, stack, failure_reason)
        if not failure_handled:
            # Another concurrent update has taken over. But there is a
            # possibility for that update to be waiting for this rsrc to
            # complete, hence retrigger current rsrc for latest traversal.
            traversal = stack.current_traversal
            latest_stack = parser.Stack.load(cnxt, stack_id=stack.id)
            if traversal != latest_stack.current_traversal:
                self._retrigger_check_resource(cnxt, is_update, rsrc_id,
                                               latest_stack)

    def _handle_stack_timeout(self, cnxt, stack):
        failure_reason = u'Timed out'
        self._handle_failure(cnxt, stack, failure_reason)

    def _load_resource(self, cnxt, resource_id, resource_data, is_update):
        if is_update:
            cache_data = {in_data.get(
                'name'): in_data for in_data in resource_data.values()
                if in_data is not None}
        else:
            # no data to resolve in cleanup phase
            cache_data = {}

        try:
            return resource.Resource.load(cnxt, resource_id,
                                          is_update, cache_data)
        except (exception.ResourceNotFound, exception.NotFound):
            pass  # can be ignored

        return None, None, None

    def _do_check_resource(self, cnxt, current_traversal, tmpl, resource_data,
                           is_update, rsrc, stack, adopt_stack_data):
        try:
            if is_update:
                try:
                    check_resource_update(rsrc, tmpl.id, resource_data,
                                          self.engine_id,
                                          stack)
                except exception.UpdateReplace:
                    new_res_id = rsrc.make_replacement(tmpl.id)
                    LOG.info("Replacing resource with new id %s", new_res_id)
                    rpc_data = sync_point.serialize_input_data(resource_data)
                    self._rpc_client.check_resource(cnxt,
                                                    new_res_id,
                                                    current_traversal,
                                                    rpc_data, is_update,
                                                    adopt_stack_data)
                    return False

            else:
                check_resource_cleanup(rsrc, tmpl.id, resource_data,
                                       self.engine_id, stack.time_remaining())

            return True
        except exception.UpdateInProgress:
            if self._try_steal_engine_lock(cnxt, rsrc.id):
                rpc_data = sync_point.serialize_input_data(resource_data)
                self._rpc_client.check_resource(cnxt,
                                                rsrc.id,
                                                current_traversal,
                                                rpc_data, is_update,
                                                adopt_stack_data)
        except exception.ResourceFailure as ex:
            reason = 'Resource %s failed: %s' % (rsrc.action,
                                                 six.text_type(ex))
            self._handle_resource_failure(cnxt, is_update, rsrc.id,
                                          stack, reason)
        except scheduler.Timeout:
            # reload the stack to verify current traversal
            stack = parser.Stack.load(cnxt, stack_id=stack.id)
            if stack.current_traversal != current_traversal:
                return
            self._handle_stack_timeout(cnxt, stack)

        return False

    def _retrigger_check_resource(self, cnxt, is_update, resource_id, stack):
        current_traversal = stack.current_traversal
        graph = stack.convergence_dependencies.graph()
        key = (resource_id, is_update)
        if is_update:
            # When re-triggering for a rsrc, we need to first check if update
            # traversal is present for the rsrc in latest stack traversal,
            # if No, then latest traversal is waiting for delete.
            if (resource_id, is_update) not in graph:
                key = (resource_id, not is_update)
        LOG.info('Re-trigger resource: (%s, %s)' % (key[0], key[1]))
        predecessors = set(graph[key])

        try:
            propagate_check_resource(cnxt, self._rpc_client, resource_id,
                                     current_traversal, predecessors, key,
                                     None, key[1], None)
        except sync_point.SyncPointNotFound:
            pass

    def _initiate_propagate_resource(self, cnxt, resource_id,
                                     current_traversal, is_update, rsrc,
                                     stack):
        deps = stack.convergence_dependencies
        graph = deps.graph()
        graph_key = (resource_id, is_update)

        if graph_key not in graph and rsrc.replaces is not None:
            # If we are a replacement, impersonate the replaced resource for
            # the purposes of calculating whether subsequent resources are
            # ready, since everybody has to work from the same version of the
            # graph. Our real resource ID is sent in the input_data, so the
            # dependencies will get updated to point to this resource in time
            # for the next traversal.
            graph_key = (rsrc.replaces, is_update)

        def _get_input_data(req, fwd):
            if fwd:
                return construct_input_data(rsrc, stack)
            else:
                # Don't send data if initiating clean-up for self i.e.
                # initiating delete of a replaced resource
                if req not in graph_key:
                    # send replaced resource as needed_by if it exists
                    return (rsrc.replaced_by
                            if rsrc.replaced_by is not None
                            else resource_id)
            return None

        try:
            for req, fwd in deps.required_by(graph_key):
                input_data = _get_input_data(req, fwd)
                propagate_check_resource(
                    cnxt, self._rpc_client, req, current_traversal,
                    set(graph[(req, fwd)]), graph_key, input_data, fwd,
                    stack.adopt_stack_data)

            check_stack_complete(cnxt, stack, current_traversal,
                                 resource_id, deps, is_update)
        except sync_point.SyncPointNotFound:
            # Reload the stack to determine the current traversal, and check
            # the SyncPoint for the current node to determine if it is ready.
            # If it is, then retrigger the current node with the appropriate
            # data for the latest traversal.
            stack = parser.Stack.load(cnxt, stack_id=rsrc.stack.id)
            if current_traversal == stack.current_traversal:
                LOG.debug('[%s] Traversal sync point missing.',
                          current_traversal)
                return

            self._retrigger_check_resource(cnxt, is_update, resource_id, stack)

    @context.request_context
    def check_resource(self, cnxt, resource_id, current_traversal, data,
                       is_update, adopt_stack_data):
        """Process a node in the dependency graph.

        The node may be associated with either an update or a cleanup of its
        associated resource.
        """
        resource_data = dict(sync_point.deserialize_input_data(data))
        rsrc, rsrc_owning_stack, stack = self._load_resource(cnxt, resource_id,
                                                             resource_data,
                                                             is_update)

        if rsrc is None:
            return

        if current_traversal != stack.current_traversal:
            LOG.debug('[%s] Traversal cancelled; stopping.', current_traversal)
            return

        if stack.has_timed_out():
            self._handle_stack_timeout(cnxt, stack)
            return

        tmpl = stack.t
        stack.adopt_stack_data = adopt_stack_data

        if is_update:
            if (rsrc.replaced_by is not None and
                    rsrc.current_template_id != tmpl.id):
                return

        check_resource_done = self._do_check_resource(cnxt, current_traversal,
                                                      tmpl, resource_data,
                                                      is_update,
                                                      rsrc, stack,
                                                      adopt_stack_data)

        if check_resource_done:
            # initiate check on next set of resources from graph
            self._initiate_propagate_resource(cnxt, resource_id,
                                              current_traversal, is_update,
                                              rsrc, stack)


def construct_input_data(rsrc, curr_stack):
    attributes = curr_stack.get_dep_attrs(
        six.itervalues(curr_stack.resources),
        curr_stack.outputs,
        rsrc.name)
    resolved_attributes = {}
    for attr in attributes:
        try:
            if isinstance(attr, six.string_types):
                resolved_attributes[attr] = rsrc.FnGetAtt(attr)
            else:
                resolved_attributes[attr] = rsrc.FnGetAtt(*attr)
        except exception.InvalidTemplateAttribute as ita:
            LOG.info(six.text_type(ita))

    input_data = {'id': rsrc.id,
                  'name': rsrc.name,
                  'reference_id': rsrc.FnGetRefId(),
                  'attrs': resolved_attributes,
                  'status': rsrc.status,
                  'action': rsrc.action,
                  'uuid': rsrc.uuid}
    return input_data


def check_stack_complete(cnxt, stack, current_traversal, sender_id, deps,
                         is_update):
    """Mark the stack complete if the update is complete.

    Complete is currently in the sense that all desired resources are in
    service, not that superfluous ones have been cleaned up.
    """
    roots = set(deps.roots())

    if (sender_id, is_update) not in roots:
        return

    def mark_complete(stack_id, data):
        stack.mark_complete()

    sender_key = (sender_id, is_update)
    sync_point.sync(cnxt, stack.id, current_traversal, True,
                    mark_complete, roots, {sender_key: None})


def propagate_check_resource(cnxt, rpc_client, next_res_id,
                             current_traversal, predecessors, sender_key,
                             sender_data, is_update, adopt_stack_data):
    """Trigger processing of node if all of its dependencies are satisfied."""
    def do_check(entity_id, data):
        rpc_client.check_resource(cnxt, entity_id, current_traversal,
                                  data, is_update, adopt_stack_data)

    sync_point.sync(cnxt, next_res_id, current_traversal,
                    is_update, do_check, predecessors,
                    {sender_key: sender_data})


def check_resource_update(rsrc, template_id, resource_data, engine_id,
                          stack):
    """Create or update the Resource if appropriate."""
    if rsrc.action == resource.Resource.INIT:
        rsrc.create_convergence(template_id, resource_data, engine_id,
                                stack.time_remaining())
    else:
        rsrc.update_convergence(template_id, resource_data, engine_id,
                                stack.time_remaining(), stack)


def check_resource_cleanup(rsrc, template_id, resource_data, engine_id,
                           timeout):
    """Delete the Resource if appropriate."""
    rsrc.delete_convergence(template_id, resource_data, engine_id, timeout)
