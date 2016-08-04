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

from heat.common import environment_util as env_util
from heat.tests import common


class TestEnvironmentUtil(common.HeatTestCase):

    def test_empty_merge_strategies(self):
        merge_strategies = {}
        param_strategy = env_util.get_param_merge_strategy(merge_strategies,
                                                           'param1')
        self.assertEqual(env_util.OVERWRITE, param_strategy)

    def test_default_merge_strategy(self):
        merge_strategies = {'default': 'deep_merge'}
        param_strategy = env_util.get_param_merge_strategy(merge_strategies,
                                                           'param1')
        self.assertEqual(env_util.DEEP_MERGE, param_strategy)

    def test_param_sepcific_merge_strategy(self):
        merge_strategies = {'default': 'merge',
                            'param1': 'deep_merge'}
        param_strategy = env_util.get_param_merge_strategy(merge_strategies,
                                                           'param1')
        self.assertEqual(env_util.DEEP_MERGE, param_strategy)

    def test_wrong_param_strategy(self):
        merge_strategies = {'default': 'merge',
                            'param1': 'unknown'}
        param_strategy = env_util.get_param_merge_strategy(merge_strategies,
                                                           'param1')
        self.assertEqual(env_util.MERGE, param_strategy)

    def test_merge_startegies_none(self):
        merge_strategies = None
        param_strategy = env_util.get_param_merge_strategy(merge_strategies,
                                                           'param1')
        self.assertEqual(env_util.OVERWRITE, param_strategy)
