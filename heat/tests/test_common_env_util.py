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

import json

from heat.common import environment_util as env_util
from heat.common import exception
from heat.engine import parameters
from heat.tests import common
from heat.tests import utils


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


class TestMergeEnvironments(common.HeatTestCase):
    def setUp(self):
        super(TestMergeEnvironments, self).setUp()
        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        # Setup
        self.params = {'parameters': {},
                       'resource_registry': {},
                       'parameter_defaults': {}}

        self.env_1 = {'parameters': {
            'str_value1': "string1",
            'str_value2': "string2",
            'del_lst_value1': '1,2',
            'del_lst_value2': '3,4',
            'lst_value1': [1, 2],
            'json_value1': {"1": ["str1", "str2"]},
            'json_value2': {"2": ["test1", "test2"]}},
            'resource_registry': {
                'test::R1': "OS::Heat::RandomString",
                'test::R2': "BROKEN"},
            'parameter_defaults': {
                'lst_value2': [3, 4]}}
        self.env_2 = {'parameters': {
            'str_value1': "string3",
            'str_value2': "string4",
            'del_lst_value1': '5,6',
            'del_lst_value2': '7,8',
            'lst_value1': [5, 6],
            'json_value1': {"3": ["str3", "str4"]},
            'json_value2': {"4": ["test3", "test4"]}},
            'resource_registry': {
                'test::R2': "OS::Heat::None"},
            'parameter_defaults': {
                'lst_value2': [7, 8]}}

        self.env_3 = {'parameters': {
            'lst_value1': [9, 10],
            'json_value1': {"5": ["str5"]}}}

        self.env_4 = {'parameter_defaults': {
            'lst_value2': [9, 10]}}

        self.param_schemata = {
            'str_value1': parameters.Schema(parameters.Schema.STRING),
            'str_value2': parameters.Schema(parameters.Schema.STRING),
            'del_lst_value1': parameters.Schema(parameters.Schema.LIST),
            'del_lst_value2': parameters.Schema(parameters.Schema.LIST),
            'lst_value1': parameters.Schema(parameters.Schema.LIST,
                                            default=[7]),
            'lst_value2': parameters.Schema(parameters.Schema.LIST),
            'json_value1': parameters.Schema(parameters.Schema.MAP),
            'json_value2': parameters.Schema(parameters.Schema.MAP)}

    def test_merge_envs_with_param_default_merge_strategy(self):
        files = {'env_1': json.dumps(self.env_1),
                 'env_2': json.dumps(self.env_2)}
        environment_files = ['env_1', 'env_2']

        # Test
        env_util.merge_environments(environment_files, files, self.params,
                                    self.param_schemata)

        # Verify
        expected = {'parameters': {
                    'json_value1': {u'3': [u'str3', u'str4']},
                    'json_value2': {u'4': [u'test3', u'test4']},
                    'del_lst_value1': '5,6',
                    'del_lst_value2': '7,8',
                    'lst_value1': [5, 6],
                    'str_value1': u'string3',
                    'str_value2': u'string4'},
                    'resource_registry': {
                        'test::R1': "OS::Heat::RandomString",
                        'test::R2': "OS::Heat::None"},
                    'parameter_defaults': {
                        'lst_value2': [7, 8]}}
        self.assertEqual(expected, self.params)

    def test_merge_envs_with_specified_default(self):
        merge_strategies = {'default': 'deep_merge'}
        self.env_2['parameter_merge_strategies'] = merge_strategies
        files = {'env_1': json.dumps(self.env_1),
                 'env_2': json.dumps(self.env_2)}
        environment_files = ['env_1', 'env_2']

        # Test
        env_util.merge_environments(environment_files, files, self.params,
                                    self.param_schemata)

        # Verify
        expected = {'parameters': {
                    'json_value1': {u'3': [u'str3', u'str4'],
                                    u'1': [u'str1', u'str2']},  # added
                    'json_value2': {u'4': [u'test3', u'test4'],
                                    u'2': [u'test1', u'test2']},
                    'del_lst_value1': '1,2,5,6',
                    'del_lst_value2': '3,4,7,8',
                    'lst_value1': [1, 2, 5, 6],  # added
                    'str_value1': u'string1string3',
                    'str_value2': u'string2string4'},
                    'resource_registry': {
                        'test::R1': "OS::Heat::RandomString",
                        'test::R2': "OS::Heat::None"},
                    'parameter_defaults': {
                        'lst_value2': [3, 4, 7, 8]}}
        self.assertEqual(expected, self.params)

    def test_merge_envs_with_param_specific_merge_strategy(self):
        merge_strategies = {
            'default': 'overwrite',
            'lst_value1': 'merge',
            'lst_value2': 'merge',
            'json_value1': 'deep_merge'}

        self.env_2['parameter_merge_strategies'] = merge_strategies

        files = {'env_1': json.dumps(self.env_1),
                 'env_2': json.dumps(self.env_2)}
        environment_files = ['env_1', 'env_2']

        # Test
        env_util.merge_environments(environment_files, files, self.params,
                                    self.param_schemata)

        # Verify
        expected = {'parameters': {
                    'json_value1': {u'3': [u'str3', u'str4'],
                                    u'1': [u'str1', u'str2']},  # added
                    'json_value2': {u'4': [u'test3', u'test4']},
                    'del_lst_value1': '5,6',
                    'del_lst_value2': '7,8',
                    'lst_value1': [1, 2, 5, 6],  # added
                    'str_value1': u'string3',
                    'str_value2': u'string4'},
                    'resource_registry': {
                        'test::R1': 'OS::Heat::RandomString',
                        'test::R2': 'OS::Heat::None'},
                    'parameter_defaults': {
                        'lst_value2': [3, 4, 7, 8]}}
        self.assertEqual(expected, self.params)

    def test_merge_envs_with_param_conflicting_merge_strategy(self):
        merge_strategies = {
            'default': "overwrite",
            'lst_value1': "merge",
            'json_value1': "deep_merge"}

        self.env_2['parameter_merge_strategies'] = merge_strategies

        files = {'env_1': json.dumps(self.env_1),
                 'env_2': json.dumps(self.env_2),
                 'env_3': json.dumps(self.env_3)}

        environment_files = ['env_1', 'env_2', 'env_3']

        # Test
        self.assertRaises(exception.ConflictingMergeStrategyForParam,
                          env_util.merge_environments,
                          environment_files, files,
                          self.params, self.param_schemata)

    def test_merge_envs_with_param_defaults_conflicting_merge_strategy(self):
        merge_strategies = {
            'default': "overwrite",
            'lst_value2': "merge"}

        self.env_2['parameter_merge_strategies'] = merge_strategies

        files = {'env_1': json.dumps(self.env_1),
                 'env_2': json.dumps(self.env_2),
                 'env_4': json.dumps(self.env_4)}

        environment_files = ['env_1', 'env_2', 'env_4']

        # Test
        self.assertRaises(exception.ConflictingMergeStrategyForParam,
                          env_util.merge_environments,
                          environment_files, files,
                          self.params, self.param_schemata)

    def test_merge_environments_no_env_files(self):
        files = {'env_1': json.dumps(self.env_1)}

        # Test - Should ignore env_1 in files
        env_util.merge_environments(None, files, self.params,
                                    self.param_schemata)

        # Verify
        expected = {'parameters': {},
                    'resource_registry': {},
                    'parameter_defaults': {}}

        self.assertEqual(expected, self.params)

    def test_merge_envs_with_zeros(self):
        env1 = {'parameter_defaults': {'value1': 1}}
        env2 = {'parameter_defaults': {'value1': 0}}
        files = {'env_1': json.dumps(env1),
                 'env_2': json.dumps(env2)}
        environment_files = ['env_1', 'env_2']

        param_schemata = {
            'value1': parameters.Schema(parameters.Schema.NUMBER)}
        env_util.merge_environments(environment_files, files, self.params,
                                    param_schemata)

        self.assertEqual({'value1': 0}, self.params['parameter_defaults'])

    def test_merge_envs_with_zeros_in_maps(self):
        env1 = {'parameter_defaults': {'value1': {'foo': 1}}}
        env2 = {'parameter_defaults': {'value1': {'foo': 0}},
                'parameter_merge_strategies': {'value1': 'deep_merge'}}
        files = {'env_1': json.dumps(env1),
                 'env_2': json.dumps(env2)}
        environment_files = ['env_1', 'env_2']

        param_schemata = {
            'value1': parameters.Schema(parameters.Schema.MAP)}
        env_util.merge_environments(environment_files, files, self.params,
                                    param_schemata)

        self.assertEqual({'value1': {'foo': 0}},
                         self.params['parameter_defaults'])
