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

import mock

from heat.engine import worker
from heat.tests.convergence.framework import message_processor
from heat.tests.convergence.framework import message_queue


class Worker(message_processor.MessageProcessor):

    queue = message_queue.MessageQueue('worker')

    def __init__(self):
        super(Worker, self).__init__('worker')

    @message_processor.asynchronous
    def check_resource(self, ctxt, resource_id,
                       current_traversal, data,
                       is_update, adopt_stack_data, converge=False):
        worker.WorkerService("fake_host", "fake_topic",
                             "fake_engine", mock.Mock()).check_resource(
                                 ctxt, resource_id,
                                 current_traversal,
                                 data, is_update,
                                 adopt_stack_data,
                                 converge)

    def stop_traversal(self, current_stack):
        pass

    def stop_all_workers(self, current_stack):
        pass
