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

import eventlet.queue

from oslo_log import log as logging
import oslo_messaging
from oslo_service import service
from osprofiler import profiler

from heat.common import context
from heat.common.i18n import _LE
from heat.common.i18n import _LI
from heat.common.i18n import _LW
from heat.common import messaging as rpc_messaging
from heat.engine import check_resource
from heat.engine import sync_point
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

    RPC_API_VERSION = '1.3'

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
            server=self.engine_id,
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
        if self._rpc_server is None:
            return
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

    def stop_traversal(self, stack):
        """Update current traversal to stop workers from propagating.

        Marks the stack as FAILED due to cancellation, but, allows all
        in_progress resources to complete normally; no worker is stopped
        abruptly.
        """
        reason = 'User cancelled stack %s ' % stack.action
        # state_set will update the current traversal to '' for FAILED state
        old_trvsl = stack.current_traversal
        updated = stack.state_set(stack.action, stack.FAILED, reason)
        if not updated:
            LOG.warning(_LW("Failed to stop traversal %(trvsl)s of stack "
                            "%(name)s while cancelling the operation."),
                        {'name': stack.name, 'trvsl': old_trvsl})

    @context.request_context
    def check_resource(self, cnxt, resource_id, current_traversal, data,
                       is_update, adopt_stack_data):
        """Process a node in the dependency graph.

        The node may be associated with either an update or a cleanup of its
        associated resource.
        """
        resource_data = dict(sync_point.deserialize_input_data(data))
        rsrc, rsrc_owning_stack, stack = check_resource.load_resource(
            cnxt, resource_id, resource_data, is_update)

        if rsrc is None:
            return

        if current_traversal != stack.current_traversal:
            LOG.debug('[%s] Traversal cancelled; stopping.', current_traversal)
            return

        msg_queue = eventlet.queue.LightQueue()
        try:
            self.thread_group_mgr.add_msg_queue(stack.id, msg_queue)
            cr = check_resource.CheckResource(self.engine_id, self._rpc_client,
                                              self.thread_group_mgr, msg_queue)

            cr.check(cnxt, resource_id, current_traversal, resource_data,
                     is_update, adopt_stack_data, rsrc, stack)
        finally:
            self.thread_group_mgr.remove_msg_queue(None,
                                                   stack.id, msg_queue)

    @context.request_context
    def cancel_check_resource(self, cnxt, stack_id):
        """Cancel check_resource for given stack.

        All the workers running for the given stack will be
        cancelled.
        """
        # TODO(ananta): Implement cancel check-resource
        LOG.debug('Cancelling workers for stack [%s]', stack_id)
