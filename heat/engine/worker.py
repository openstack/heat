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
from heat.engine import dependencies
from heat.engine import resource
from heat.engine import stack as parser
from heat.engine import sync_point
from heat.objects import resource as resource_objects
from heat.rpc import listener_client
from heat.rpc import worker_client as rpc_client

LOG = logging.getLogger(__name__)


@profiler.trace_cls("rpc")
class WorkerService(service.Service):
    """
    This service is dedicated to handle internal messages to the 'worker'
    (a.k.a. 'converger') actor in convergence. Messages on this bus will
    use the 'cast' rather than 'call' method to anycast the message to
    an engine that will handle it asynchronously. It won't wait for
    or expect replies from these messages.
    """

    RPC_API_VERSION = '1.1'

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

    def start(self):
        target = oslo_messaging.Target(
            version=self.RPC_API_VERSION,
            server=self.host,
            topic=self.topic)
        LOG.info(_LI("Starting WorkerService ..."))

        self._rpc_server = rpc_messaging.get_rpc_server(target, self)
        self._rpc_server.start()

        super(WorkerService, self).start()

    def stop(self):
        # Stop rpc connection at first for preventing new requests
        LOG.info(_LI("Stopping WorkerService ..."))
        try:
            self._rpc_server.stop()
            self._rpc_server.wait()
        except Exception as e:
            LOG.error(_LE("WorkerService is failed to stop, %s"), e)

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

    def _handle_resource_failure(self, cnxt, stack_id, traversal_id,
                                 failure_reason):
        stack = parser.Stack.load(cnxt, stack_id=stack_id)
        # make sure no new stack operation was triggered
        if stack.current_traversal != traversal_id:
            return

        stack.state_set(stack.action, stack.FAILED, failure_reason)

        if (not stack.disable_rollback and
                stack.action in (stack.CREATE, stack.ADOPT, stack.UPDATE)):
            self._trigger_rollback(stack)
        else:
            stack.purge_db()

    def _load_resource(self, cnxt, resource_id, data, is_update):
        adopt_data = data.get('adopt_stack_data')
        data = dict(sync_point.deserialize_input_data(data))
        cache_data = {in_data.get(
            'name'): in_data for in_data in data.values()
            if in_data is not None}
        cache_data['adopt_stack_data'] = adopt_data
        rsrc, stack = None, None
        try:
            rsrc, stack = resource.Resource.load(cnxt, resource_id, is_update,
                                                 cache_data)
        except (exception.ResourceNotFound, exception.NotFound):
            pass  # can be ignored

        return rsrc, stack

    def _do_check_resource(self, cnxt, current_traversal, tmpl, data,
                           is_update, rsrc, stack_id):
        try:
            if is_update:
                try:
                    check_resource_update(rsrc, tmpl.id, data, self.engine_id)
                except resource.UpdateReplace:
                    new_res_id = rsrc.make_replacement(tmpl.id)
                    LOG.info("Replacing resource with new id %s", new_res_id)
                    data = sync_point.serialize_input_data(data)
                    self._rpc_client.check_resource(cnxt,
                                                    new_res_id,
                                                    current_traversal,
                                                    data, is_update)
                    return False

            else:
                check_resource_cleanup(rsrc, tmpl.id, data, self.engine_id)

            return True
        except resource.UpdateInProgress:
            if self._try_steal_engine_lock(cnxt, rsrc.id):
                self._rpc_client.check_resource(cnxt,
                                                rsrc.id,
                                                current_traversal,
                                                data, is_update)
        except exception.ResourceFailure as ex:
            reason = 'Resource %s failed: %s' % (rsrc.action,
                                                 six.text_type(ex))
            self._handle_resource_failure(
                cnxt, stack_id, current_traversal, reason)

        return False

    def _compute_dependencies(self, stack):
        current_deps = ([tuple(i), (tuple(j) if j is not None else None)]
                        for i, j in stack.current_deps['edges'])
        return dependencies.Dependencies(edges=current_deps)

    def _retrigger_check_resource(self, cnxt, is_update, resource_id, stack):
        current_traversal = stack.current_traversal
        graph = self._compute_dependencies(stack).graph()
        key = sync_point.make_key(resource_id, current_traversal, is_update)
        predecessors = graph[key]

        def do_check(target_key, data):
            self.check_resource(resource_id, current_traversal,
                                data)

        try:
            sync_point.sync(cnxt, resource_id, current_traversal, is_update,
                            do_check, predecessors, {key: None})
        except sync_point.sync_points.NotFound:
            pass

    def _initiate_propagate_resource(self, cnxt, resource_id,
                                     current_traversal, is_update, rsrc,
                                     stack):
        input_data = None
        if is_update:
            input_data = construct_input_data(rsrc)
        deps = self._compute_dependencies(stack)
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

        try:
            for req, fwd in deps.required_by(graph_key):
                propagate_check_resource(
                    cnxt, self._rpc_client, req, current_traversal,
                    set(graph[(req, fwd)]), graph_key,
                    input_data if fwd else None, fwd)

            check_stack_complete(cnxt, stack, current_traversal,
                                 resource_id, deps, is_update)
        except sync_point.SyncPointNotFound:
            # Reload the stack to determine the current traversal, and check
            # the SyncPoint for the current node to determine if it is ready.
            # If it is, then retrigger the current node with the appropriate
            # data for the latest traversal.
            stack = parser.Stack.load(cnxt, stack_id=rsrc.stack.id)
            if current_traversal == rsrc.stack.current_traversal:
                LOG.debug('[%s] Traversal sync point missing.',
                          current_traversal)
                return

            self._retrigger_check_resource(cnxt, is_update, resource_id, stack)

    @context.request_context
    def check_resource(self, cnxt, resource_id, current_traversal, data,
                       is_update):
        '''
        Process a node in the dependency graph.

        The node may be associated with either an update or a cleanup of its
        associated resource.
        '''
        rsrc, stack = self._load_resource(cnxt, resource_id, data, is_update)

        if rsrc is None:
            return

        if current_traversal != stack.current_traversal:
            LOG.debug('[%s] Traversal cancelled; stopping.', current_traversal)
            return

        tmpl = stack.t

        if is_update:
            if (rsrc.replaced_by is not None and
                    rsrc.current_template_id != tmpl.id):
                return

        check_resource_done = self._do_check_resource(cnxt, current_traversal,
                                                      tmpl, data, is_update,
                                                      rsrc, stack.id)

        if check_resource_done:
            # initiate check on next set of resources from graph
            self._initiate_propagate_resource(cnxt, resource_id,
                                              current_traversal, is_update,
                                              rsrc, stack)


def construct_input_data(rsrc):
    attributes = rsrc.stack.get_dep_attrs(
        six.itervalues(rsrc.stack.resources),
        rsrc.stack.outputs,
        rsrc.name)
    resolved_attributes = {attr: rsrc.FnGetAtt(attr) for attr in attributes}
    input_data = {'id': rsrc.id,
                  'name': rsrc.name,
                  'physical_resource_id': rsrc.resource_id,
                  'attrs': resolved_attributes}
    return input_data


def check_stack_complete(cnxt, stack, current_traversal, sender_id, deps,
                         is_update):
    '''
    Mark the stack complete if the update is complete.

    Complete is currently in the sense that all desired resources are in
    service, not that superfluous ones have been cleaned up.
    '''
    roots = set(deps.roots())

    if (sender_id, is_update) not in roots:
        return

    def mark_complete(stack_id, data):
        stack.mark_complete(current_traversal)

    sender_key = (sender_id, is_update)
    sync_point.sync(cnxt, stack.id, current_traversal, True,
                    mark_complete, roots, {sender_key: None})


def propagate_check_resource(cnxt, rpc_client, next_res_id,
                             current_traversal, predecessors, sender_key,
                             sender_data, is_update):
    '''
    Trigger processing of a node if all of its dependencies are satisfied.
    '''
    def do_check(entity_id, data):
        rpc_client.check_resource(cnxt, entity_id, current_traversal,
                                  data, is_update)

    sync_point.sync(cnxt, next_res_id, current_traversal,
                    is_update, do_check, predecessors,
                    {sender_key: sender_data})


def check_resource_update(rsrc, template_id, data, engine_id):
    '''
    Create or update the Resource if appropriate.
    '''
    if (rsrc.resource_id is None
            and not (rsrc.action == resource.Resource.CREATE and
                     rsrc.status in [
                         resource.Resource.COMPLETE,
                         resource.Resource.FAILED
                     ])):
        rsrc.create_convergence(data, engine_id)
    else:
        rsrc.update_convergence(template_id, data, engine_id)


def check_resource_cleanup(rsrc, template_id, data, engine_id):
    '''
    Delete the Resource if appropriate.
    '''

    if rsrc.current_template_id != template_id:
        rsrc.delete_convergence(engine_id)
