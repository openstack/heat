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

from heat.engine import parser
from heat.engine.resources.software_config import structured_config as sc
from heat.engine import template
from heat.tests.common import HeatTestCase
from heat.tests import utils


class StructuredConfigTestJSON(HeatTestCase):

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
        heat = mock.MagicMock()
        self.config.heat = heat
        self.software_configs = heat.return_value.software_configs

    def test_resource_mapping(self):
        mapping = sc.resource_mapping()
        self.assertEqual(3, len(mapping))
        self.assertEqual(sc.StructuredConfig,
                         mapping['OS::Heat::StructuredConfig'])
        self.assertEqual(sc.StructuredDeployment,
                         mapping['OS::Heat::StructuredDeployment'])
        self.assertEqual(sc.StructuredDeployments,
                         mapping['OS::Heat::StructuredDeployments'])
        self.assertIsInstance(self.config, sc.StructuredConfig)

    def test_handle_create(self):
        stc = mock.MagicMock()
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        stc.id = config_id
        self.software_configs.create.return_value = stc
        self.config.handle_create()
        self.assertEqual(config_id, self.config.resource_id)
        kwargs = self.software_configs.create.call_args[1]
        self.assertEqual(self.stored_config, kwargs['config'])


class StructuredDeploymentDerivedTest(HeatTestCase):

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
            'input_values': {'bar': 'baz'},
        }
        self.template['Resources']['deploy_mysql']['Properties'] = props
        self.stack = parser.Stack(
            self.ctx, 'software_deploly_test_stack',
            template.Template(self.template))
        self.deployment = self.stack['deploy_mysql']
        heat = mock.MagicMock()
        self.deployments = heat.return_value.software_deployments

    def test_build_derived_config(self):
        source = {
            'config': {"foo": {"get_input": "bar"}}
        }
        inputs = [{'name': 'bar', 'value': 'baz'}]
        result = self.deployment._build_derived_config(
            'CREATE', source, inputs, {})
        self.assertEqual({"foo": "baz"}, result)


class StructuredDeploymentParseTest(HeatTestCase):

    scenarios = [
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
                 config={'foo': {'get_input': 'bar', 'other': 'thing'}},
                 result={'foo': {'get_input': 'bar', 'other': 'thing'}}),
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

    def test_parse(self):
        parse = sc.StructuredDeployment.parse
        self.assertEqual(
            self.result,
            parse(self.inputs, self.input_key, self.config))


class StructuredDeploymentsTest(HeatTestCase):

    template = {
        'heat_template_version': '2013-05-23',
        'resources': {
            'deploy_mysql': {
                'type': 'OS::Heat::StructuredDeployments',
                'properties': {
                    'config': 'config_uuid',
                    'servers': {'server1': 'uuid1', 'server2': 'uuid2'},
                }
            }
        }
    }

    def setUp(self):
        HeatTestCase.setUp(self)
        heat = mock.MagicMock()
        self.deployments = heat.return_value.software_deployments

    def test_build_resource_definition(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sc.StructuredDeployments('test', snip, stack)
        expect = {
            'type': 'OS::Heat::StructuredDeployment',
            'properties': {
                'actions': ['CREATE', 'UPDATE'],
                'config': 'config_uuid',
                'input_key': 'get_input',
                'input_values': None,
                'name': None,
                'signal_transport': 'CFN_SIGNAL'
            }
        }
        self.assertEqual(
            expect, resg._build_resource_definition())
        self.assertEqual(
            expect, resg._build_resource_definition(include_all=True))

    def test_resource_names(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sc.StructuredDeployments('test', snip, stack)
        self.assertEqual(
            set(('server1', 'server2')),
            set(resg._resource_names())
        )

        self.assertEqual(
            set(('s1', 's2', 's3')),
            set(resg._resource_names({
                'servers': {'s1': 'u1', 's2': 'u2', 's3': 'u3'}}))
        )

    def test_assemble_nested(self):
        """
        Tests that the nested stack that implements the group is created
        appropriately based on properties.
        """
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sc.StructuredDeployments('test', snip, stack)
        templ = {
            "heat_template_version": "2013-05-23",
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
                        'signal_transport': 'CFN_SIGNAL'
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
                        'signal_transport': 'CFN_SIGNAL'
                    }
                }
            }
        }

        self.assertEqual(templ, resg._assemble_nested(['server1', 'server2']))
