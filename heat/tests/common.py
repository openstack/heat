# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import fixtures
import logging
import mox
import os
import sys
import testtools

from oslo.config import cfg

import heat.engine.scheduler as scheduler


class HeatTestCase(testtools.TestCase):

    def setUp(self):
        super(HeatTestCase, self).setUp()
        self.m = mox.Mox()
        self.addCleanup(self.m.UnsetStubs)
        self.useFixture(fixtures.FakeLogger(level=logging.DEBUG))
        scheduler.ENABLE_SLEEP = False

        def enable_sleep():
            scheduler.ENABLE_SLEEP = True

        self.addCleanup(enable_sleep)

        mod_dir = os.path.dirname(sys.modules[__name__].__file__)
        project_dir = os.path.abspath(os.path.join(mod_dir, '../../'))
        env_dir = os.path.join(project_dir, 'etc', 'heat',
                               'environment.d')

        cfg.CONF.set_default('environment_dir', env_dir)
