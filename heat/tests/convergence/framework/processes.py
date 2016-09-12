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

from heat.tests.convergence.framework import engine_wrapper
from heat.tests.convergence.framework import event_loop as event_loop_module
from heat.tests.convergence.framework import worker_wrapper


engine = None
worker = None
event_loop = None


class Processes(object):

    def __init__(self):
        global engine
        global worker
        global event_loop

        worker = worker_wrapper.Worker()
        engine = engine_wrapper.Engine(worker)

        event_loop = event_loop_module.EventLoop(engine, worker)

        self.engine = engine
        self.worker = worker
        self.event_loop = event_loop

    def clear(self):
        self.engine.clear()
        self.worker.clear()

Processes()
