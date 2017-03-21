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

import os
from oslo_log import log as logging


LOG = logging.getLogger(__name__)


def list_all():
    scenario_dir = os.path.join(os.path.dirname(__file__), '../scenarios')
    if not os.path.isdir(scenario_dir):
        LOG.error('Scenario directory "%s" not found', scenario_dir)
        return

    for root, dirs, files in os.walk(scenario_dir):
        for filename in files:
            name, ext = os.path.splitext(filename)
            if ext == '.py':
                LOG.debug('Found scenario "%s"', name)
                yield name, os.path.join(root, filename)


class Scenario(object):

    def __init__(self, name, path):
        self.name = name

        with open(path) as f:
            source = f.read()

        self.code = compile(source, path, 'exec')
        LOG.debug('Loaded scenario %s', self.name)

    def __call__(self, _event_loop, **global_env):
        LOG.info('*** Beginning scenario "%s"', self.name)

        exec(self.code, global_env, {})
        _event_loop()
