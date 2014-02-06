
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


import logging
import os
import sys
import time

import fixtures
import mox
from oslo.config import cfg
import testscenarios
import testtools

from heat.engine import environment
from heat.engine import resources
from heat.engine import scheduler
from heat.openstack.common.fixture import mockpatch


class HeatTestCase(testscenarios.WithScenarios, testtools.TestCase):

    TIME_STEP = 0.1

    def setUp(self):
        super(HeatTestCase, self).setUp()
        self.m = mox.Mox()
        self.addCleanup(self.m.UnsetStubs)
        self.logger = self.useFixture(fixtures.FakeLogger(level=logging.DEBUG))
        scheduler.ENABLE_SLEEP = False
        self.useFixture(fixtures.MonkeyPatch(
            'heat.common.exception._FATAL_EXCEPTION_FORMAT_ERRORS',
            True))

        def enable_sleep():
            scheduler.ENABLE_SLEEP = True

        self.addCleanup(enable_sleep)

        mod_dir = os.path.dirname(sys.modules[__name__].__file__)
        project_dir = os.path.abspath(os.path.join(mod_dir, '../../'))
        env_dir = os.path.join(project_dir, 'etc', 'heat',
                               'environment.d')

        cfg.CONF.set_default('environment_dir', env_dir)
        cfg.CONF.set_override('allowed_rpc_exception_modules',
                              ['heat.common.exception', 'exceptions'])
        self.addCleanup(cfg.CONF.reset)

        tri = resources.global_env().get_resource_info(
            'AWS::RDS::DBInstance',
            registry_type=environment.TemplateResourceInfo)
        if tri is not None:
            cur_path = tri.template_name
            templ_path = os.path.join(project_dir, 'etc', 'heat', 'templates')
            if templ_path not in cur_path:
                tri.template_name = cur_path.replace('/etc/heat/templates',
                                                     templ_path)

    def stub_wallclock(self):
        """
        Overrides scheduler wallclock to speed up tests expecting timeouts.
        """
        self._wallclock = time.time()

        def fake_wallclock():
            self._wallclock += self.TIME_STEP
            return self._wallclock

        self.m.StubOutWithMock(scheduler, 'wallclock')
        scheduler.wallclock = fake_wallclock

    def patchobject(self, obj, attr):
        mockfixture = self.useFixture(mockpatch.PatchObject(obj, attr))
        return mockfixture.mock
