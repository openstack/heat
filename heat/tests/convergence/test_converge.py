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

from heat.engine import resource
from heat.tests import common
from heat.tests.convergence.framework import fake_resource
from heat.tests.convergence.framework import processes
from heat.tests.convergence.framework import scenario
from heat.tests.convergence.framework import testutils
from oslo_config import cfg


class ScenarioTest(common.HeatTestCase):

    scenarios = [(name, {'name': name, 'path': path})
                 for name, path in scenario.list_all()]

    def setUp(self):
        super(ScenarioTest, self).setUp()
        resource._register_class('OS::Heat::TestResource',
                                 fake_resource.TestResource)
        self.procs = processes.Processes()
        po = self.patch("heat.rpc.worker_client.WorkerClient.check_resource")
        po.side_effect = self.procs.worker.check_resource
        cfg.CONF.set_default('convergence_engine', True)

    def test_scenario(self):
        self.procs.clear()
        runner = scenario.Scenario(self.name, self.path)
        runner(self.procs.event_loop,
               **testutils.scenario_globals(self.procs, self))
