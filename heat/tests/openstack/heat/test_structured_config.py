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

from heat.common import exception
from heat.engine.resources.openstack.heat import structured_config as sc
from heat.engine import rsrc_defn
from heat.engine import software_config_io as swc_io
from heat.engine import stack as parser
from heat.engine import template
from heat.rpc import api as rpc_api
from heat.tests import common
from heat.tests import utils


SCENARIOS = [
    (
        'no_functions',
        dict(input_key='get_input',
             inputs={},
             config={'foo': 'bar'},
             result={'foo': 'bar'}),
    ),
    (
        'none_inputs',
        dict(input_key='get_input',
             inputs=None,
             config={'foo': 'bar'},
             result={'foo': 'bar'}),
    ),
    (
        'none_config',
        dict(input_key='get_input',
             inputs=None,
             config=None,
             result=None),
    ),
    (
        'empty_config',
        dict(input_key='get_input',
             inputs=None,
             config='',
             result=''),
    ),
    (
        'simple',
        dict(input_key='get_input',
             inputs={'bar': 'baa'},
             config={'foo': {'get_input': 'bar'}},
             result={'foo': 'baa'}),
    ),
    (
        'multi_key',
        dict(input_key='get_input',
             inputs={'bar': 'baa'},
             config={'foo': [{'get_input': 'bar'}, 'other']},
             result={'foo': ['baa', 'other']}),
    ),
    (
        'list_arg',
        dict(input_key='get_input',
             inputs={'bar': 'baa'},
             config={'foo': {'get_input': ['bar', 'baz']}},
             result={'foo': {'get_input': ['bar', 'baz']}}),
    ),
    (
        'missing_input',
        dict(input_key='get_input',
             inputs={'bar': 'baa'},
             config={'foo': {'get_input': 'barr'}},
             result={'foo': None}),
    ),
    (
        'deep',
        dict(input_key='get_input',
             inputs={'bar': 'baa'},
             config={'foo': {'foo': {'get_input': 'bar'}}},
             result={'foo': {'foo': 'baa'}}),
    ),
    (
        'shallow',
        dict(input_key='get_input',
             inputs={'bar': 'baa'},
             config={'get_input': 'bar'},
             result='baa'),
    ),
    (
        'list',
        dict(input_key='get_input',
             inputs={'bar': 'baa', 'bar2': 'baz', 'bar3': 'bink'},
             config={'foo': [
                 {'get_input': 'bar'},
                 {'get_input': 'bar2'},
                 {'get_input': 'bar3'}]},
             result={'foo': ['baa', 'baz', 'bink']}),
    )
]


class StructuredConfigTestJSON(common.HeatTestCase):

    template = {
        'HeatTemplateFormatVersion': '2012-12-12',
        'Resources': {
            'config_mysql': {
                'Type': 'OS::Heat::StructuredConfig',
                'Properties': {'config': {'foo': 'bar'}}
            }
        }
    }

    stored_config = {'foo': 'bar'}

    def setUp(self):
        super(StructuredConfigTestJSON, self).setUp()
        self.ctx = utils.dummy_context()
        self.properties = {
            'config': {'foo': 'bar'}
        }
        self.stack = parser.Stack(
            self.ctx, 'software_config_test_stack',
            template.Template(self.template))
        self.config = self.stack['config_mysql']
        self.rpc_client = mock.MagicMock()
        self.config._rpc_client = self.rpc_client

    def test_handle_create(self):
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        value = {'id': config_id}
        self.rpc_client.create_software_config.return_value = value
        self.config.handle_create()
        self.assertEqual(config_id, self.config.resource_id)
        kwargs = self.rpc_client.create_software_config.call_args[1]
        self.assertEqual(self.stored_config, kwargs['config'])


class StructuredDeploymentDerivedTest(common.HeatTestCase):

    template = {
        'HeatTemplateFormatVersion': '2012-12-12',
        'Resources': {
            'deploy_mysql': {
                'Type': 'OS::Heat::StructuredDeployment'
            }
        }
    }

    def setUp(self):
        super(StructuredDeploymentDerivedTest, self).setUp()
        self.ctx = utils.dummy_context()
        props = {
            'server': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
            'input_values': {'bar': 'baz'},
        }
        self.template['Resources']['deploy_mysql']['Properties'] = props
        self.stack = parser.Stack(
            self.ctx, 'software_deploly_test_stack',
            template.Template(self.template))
        self.deployment = self.stack['deploy_mysql']

    def test_build_derived_config(self):
        source = {
            'config': {"foo": {"get_input": "bar"}}
        }
        inputs = [swc_io.InputConfig(name='bar', value='baz')]
        result = self.deployment._build_derived_config(
            'CREATE', source, inputs, {})
        self.assertEqual({"foo": "baz"}, result)

    def test_build_derived_config_params_with_empty_config(self):
        source = {}
        source[rpc_api.SOFTWARE_CONFIG_INPUTS] = []
        source[rpc_api.SOFTWARE_CONFIG_OUTPUTS] = []
        result = self.deployment._build_derived_config_params(
            'CREATE', source)
        self.assertEqual('Heat::Ungrouped', result['group'])
        self.assertEqual({}, result['config'])
        self.assertEqual(self.deployment.physical_resource_name(),
                         result['name'])
        self.assertIn({'name': 'bar', 'type': 'String', 'value': 'baz'},
                      result['inputs'])
        self.assertIsNone(result['options'])
        self.assertEqual([], result['outputs'])


class StructuredDeploymentWithStrictInputTest(common.HeatTestCase):

    template = {
        'HeatTemplateFormatVersion': '2012-12-12',
        'Resources': {
            'deploy_mysql': {
                'Type': 'OS::Heat::StructuredDeployment',
                'Properties': {}
            }
        }
    }

    def setUp(self):
        super(StructuredDeploymentWithStrictInputTest, self).setUp()
        self.source = {'config':
                       {'foo': [{"get_input": "bar"},
                                {"get_input": "barz"}]}}
        self.inputs = [swc_io.InputConfig(name='bar', value='baz'),
                       swc_io.InputConfig(name='barz', value='baz2')]

    def _stack_with_template(self, template_def):
        self.ctx = utils.dummy_context()
        self.stack = parser.Stack(
            self.ctx, 'software_deploly_test_stack',
            template.Template(template_def))
        self.deployment = self.stack['deploy_mysql']

    def test_build_derived_config_failure(self):
        props = {'input_values_validate': 'STRICT'}
        self.template['Resources']['deploy_mysql']['Properties'] = props
        self._stack_with_template(self.template)

        self.assertRaises(exception.UserParameterMissing,
                          self.deployment._build_derived_config,
                          'CREATE', self.source, self.inputs[:1], {})

    def test_build_derived_config_success(self):
        props = {'input_values_validate': 'STRICT'}
        self.template['Resources']['deploy_mysql']['Properties'] = props
        self._stack_with_template(self.template)

        expected = {'foo': ['baz', 'baz2']}
        result = self.deployment._build_derived_config(
            'CREATE', self.source, self.inputs, {})
        self.assertEqual(expected, result)


class StructuredDeploymentParseTest(common.HeatTestCase):
    scenarios = SCENARIOS

    def test_parse(self):
        parse = sc.StructuredDeployment.parse
        self.assertEqual(
            self.result,
            parse(self.inputs, self.input_key, self.config))


class StructuredDeploymentGroupTest(common.HeatTestCase):

    template = {
        'heat_template_version': '2013-05-23',
        'resources': {
            'deploy_mysql': {
                'type': 'OS::Heat::StructuredDeploymentGroup',
                'properties': {
                    'config': 'config_uuid',
                    'servers': {'server1': 'uuid1', 'server2': 'uuid2'},
                }
            }
        }
    }

    def test_build_resource_definition(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sc.StructuredDeploymentGroup('test', snip, stack)
        expect = rsrc_defn.ResourceDefinition(
            None,
            'OS::Heat::StructuredDeployment',
            {'actions': ['CREATE', 'UPDATE'],
             'config': 'config_uuid',
             'input_values': None,
             'name': None,
             'server': 'uuid1',
             'input_key': 'get_input',
             'signal_transport': 'CFN_SIGNAL',
             'input_values_validate': 'LAX'})

        rdef = resg.get_resource_def()
        self.assertEqual(
            expect, resg.build_resource_definition('server1', rdef))
        rdef = resg.get_resource_def(include_all=True)
        self.assertEqual(
            expect, resg.build_resource_definition('server1', rdef))

    def test_resource_names(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sc.StructuredDeploymentGroup('test', snip, stack)
        self.assertEqual(
            set(('server1', 'server2')),
            set(resg._resource_names())
        )

        resg.properties = {'servers': {'s1': 'u1', 's2': 'u2', 's3': 'u3'}}
        self.assertEqual(
            set(('s1', 's2', 's3')),
            set(resg._resource_names()))

    def test_assemble_nested(self):
        """Tests nested stack implements group creation based on properties.

        Tests that the nested stack that implements the group is created
        appropriately based on properties.
        """
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sc.StructuredDeploymentGroup('test', snip, stack)
        templ = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "server1": {
                    'type': 'OS::Heat::StructuredDeployment',
                    'properties': {
                        'server': 'uuid1',
                        'actions': ['CREATE', 'UPDATE'],
                        'config': 'config_uuid',
                        'input_key': 'get_input',
                        'input_values': None,
                        'name': None,
                        'signal_transport': 'CFN_SIGNAL',
                        'input_values_validate': 'LAX'
                    }
                },
                "server2": {
                    'type': 'OS::Heat::StructuredDeployment',
                    'properties': {
                        'server': 'uuid2',
                        'actions': ['CREATE', 'UPDATE'],
                        'config': 'config_uuid',
                        'input_key': 'get_input',
                        'input_values': None,
                        'name': None,
                        'signal_transport': 'CFN_SIGNAL',
                        'input_values_validate': 'LAX'
                    }
                }
            }
        }

        self.assertEqual(templ, resg._assemble_nested(['server1',
                                                       'server2']).t)


class StructuredDeploymentWithStrictInputParseTest(common.HeatTestCase):
    scenarios = SCENARIOS

    def test_parse(self):
        self.parse = sc.StructuredDeployment.parse
        if 'missing_input' not in self.shortDescription():
            self.assertEqual(
                self.result,
                self.parse(
                    self.inputs,
                    self.input_key,
                    self.config,
                    check_input_val='STRICT')
            )
        else:
            self.assertRaises(exception.UserParameterMissing,
                              self.parse,
                              self.inputs,
                              self.input_key,
                              self.config,
                              check_input_val='STRICT')


class StructuredDeploymentParseMethodsTest(common.HeatTestCase):
    def test_get_key_args(self):
        snippet = {'get_input': 'bar'}
        input_key = 'get_input'
        expected = 'bar'
        result = sc.StructuredDeployment.get_input_key_arg(snippet, input_key)
        self.assertEqual(expected, result)

    def test_get_key_args_long_snippet(self):
        snippet = {'get_input': 'bar', 'second': 'foo'}
        input_key = 'get_input'
        result = sc.StructuredDeployment.get_input_key_arg(snippet, input_key)
        self.assertFalse(result)

    def test_get_key_args_unknown_input_key(self):
        snippet = {'get_input': 'bar'}
        input_key = 'input'
        result = sc.StructuredDeployment.get_input_key_arg(snippet, input_key)
        self.assertFalse(result)

    def test_get_key_args_wrong_args(self):
        snippet = {'get_input': None}
        input_key = 'get_input'
        result = sc.StructuredDeployment.get_input_key_arg(snippet, input_key)
        self.assertFalse(result)

    def test_get_input_key_value(self):
        inputs = {'bar': 'baz', 'foo': 'foo2'}
        res = sc.StructuredDeployment.get_input_key_value('bar', inputs, False)
        expected = 'baz'
        self.assertEqual(expected, res)

    def test_get_input_key_value_raise_exception(self):
        inputs = {'bar': 'baz', 'foo': 'foo2'}
        self.assertRaises(exception.UserParameterMissing,
                          sc.StructuredDeployment.get_input_key_value,
                          'barz',
                          inputs,
                          'STRICT')

    def test_get_input_key_value_get_none(self):
        inputs = {'bar': 'baz', 'foo': 'foo2'}
        res = sc.StructuredDeployment.get_input_key_value('brz', inputs, False)
        self.assertIsNone(res)
