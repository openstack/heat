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

import copy
import hashlib
import json

import fixtures
import six
from stevedore import extension

from heat.common import exception
from heat.common import template_format
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.cfn import parameters as cfn_p
from heat.engine.cfn import template as cfn_t
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine import function
from heat.engine.hot import template as hot_t
from heat.engine import node_data
from heat.engine import rsrc_defn
from heat.engine import stack
from heat.engine import stk_defn
from heat.engine import template
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils

mapping_template = template_format.parse('''{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Mappings" : {
    "ValidMapping" : {
      "TestKey" : { "TestValue" : "wibble" }
    },
    "InvalidMapping" : {
      "ValueList" : [ "foo", "bar" ],
      "ValueString" : "baz"
    },
    "MapList": [ "foo", { "bar" : "baz" } ],
    "MapString": "foobar"
  }
}''')

empty_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
}''')

aws_empty_template = template_format.parse('''{
  "AWSTemplateFormatVersion" : "2010-09-09",
}''')

parameter_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
  "Parameters" : {
    "foo" : { "Type" : "String" },
    "blarg" : { "Type" : "String", "Default": "quux" }
  }
}''')


resource_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
  "Resources" : {
    "foo" : { "Type" : "GenericResourceType" },
    "blarg" : { "Type" : "GenericResourceType" }
  }
}''')


def join(raw):
    tmpl = template.Template(mapping_template)
    return function.resolve(tmpl.parse(None, raw))


class DummyClass(object):
    metadata = None

    def metadata_get(self):
        return self.metadata

    def metadata_set(self, metadata):
        self.metadata = metadata


class TemplatePluginFixture(fixtures.Fixture):
    def __init__(self, templates=None):
        templates = templates or {}
        super(TemplatePluginFixture, self).__init__()
        self.templates = [extension.Extension(k, None, v, None)
                          for (k, v) in templates.items()]

    def _get_template_extension_manager(self):
        return extension.ExtensionManager.make_test_instance(self.templates)

    def setUp(self):
        super(TemplatePluginFixture, self).setUp()

        def clear_template_classes():
            template._template_classes = None

        clear_template_classes()
        self.useFixture(fixtures.MockPatchObject(
            template,
            '_get_template_extension_manager',
            new=self._get_template_extension_manager))
        self.addCleanup(clear_template_classes)


class TestTemplatePluginManager(common.HeatTestCase):
    def test_template_NEW_good(self):
        class NewTemplate(template.Template):
            SECTIONS = (VERSION, MAPPINGS, CONDITIONS, PARAMETERS) = (
                'NEWTemplateFormatVersion',
                '__undefined__',
                'conditions',
                'parameters')
            RESOURCES = 'thingies'

            def param_schemata(self, param_defaults=None):
                pass

            def get_section_name(self, section):
                pass

            def parameters(self, stack_identifier, user_params,
                           param_defaults=None):
                pass

            def resource_definitions(self, stack):
                pass

            def add_resource(self, definition, name=None):
                pass

            def outputs(self, stack):
                pass

            def __getitem__(self, section):
                return {}

        class NewTemplatePrint(function.Function):
            def result(self):
                return 'always this'

        self.useFixture(TemplatePluginFixture(
            {'NEWTemplateFormatVersion.2345-01-01': NewTemplate}))

        t = {'NEWTemplateFormatVersion': '2345-01-01'}
        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)


class TestTemplateVersion(common.HeatTestCase):

    versions = (('heat_template_version', '2013-05-23'),
                ('HeatTemplateFormatVersion', '2012-12-12'),
                ('AWSTemplateFormatVersion', '2010-09-09'))

    def test_hot_version(self):
        tmpl = {
            'heat_template_version': '2013-05-23',
            'foo': 'bar',
            'parameters': {}
        }
        self.assertEqual(('heat_template_version', '2013-05-23'),
                         template.get_version(tmpl, self.versions))

    def test_cfn_version(self):
        tmpl = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'foo': 'bar',
            'Parameters': {}
        }
        self.assertEqual(('AWSTemplateFormatVersion', '2010-09-09'),
                         template.get_version(tmpl, self.versions))

    def test_heat_cfn_version(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'foo': 'bar',
            'Parameters': {}
        }
        self.assertEqual(('HeatTemplateFormatVersion', '2012-12-12'),
                         template.get_version(tmpl, self.versions))

    def test_missing_version(self):
        tmpl = {
            'foo': 'bar',
            'Parameters': {}
        }
        ex = self.assertRaises(exception.InvalidTemplateVersion,
                               template.get_version, tmpl, self.versions)
        self.assertEqual('The template version is invalid: Template version '
                         'was not provided', six.text_type(ex))

    def test_ambiguous_version(self):
        tmpl = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'HeatTemplateFormatVersion': '2012-12-12',
            'foo': 'bar',
            'Parameters': {}
        }
        self.assertRaises(exception.InvalidTemplateVersion,
                          template.get_version, tmpl, self.versions)


class ParserTest(common.HeatTestCase):

    def test_list(self):
        raw = ['foo', 'bar', 'baz']
        parsed = join(raw)
        for i in six.moves.xrange(len(raw)):
            self.assertEqual(raw[i], parsed[i])
        self.assertIsNot(raw, parsed)

    def test_dict(self):
        raw = {'foo': 'bar', 'blarg': 'wibble'}
        parsed = join(raw)
        for k in raw:
            self.assertEqual(raw[k], parsed[k])
        self.assertIsNot(raw, parsed)

    def test_dict_list(self):
        raw = {'foo': ['bar', 'baz'], 'blarg': 'wibble'}
        parsed = join(raw)
        self.assertEqual(raw['blarg'], parsed['blarg'])
        for i in six.moves.xrange(len(raw['foo'])):
            self.assertEqual(raw['foo'][i], parsed['foo'][i])
        self.assertIsNot(raw, parsed)
        self.assertIsNot(raw['foo'], parsed['foo'])

    def test_list_dict(self):
        raw = [{'foo': 'bar', 'blarg': 'wibble'}, 'baz', 'quux']
        parsed = join(raw)
        for i in six.moves.xrange(1, len(raw)):
            self.assertEqual(raw[i], parsed[i])
        for k in raw[0]:
            self.assertEqual(raw[0][k], parsed[0][k])
        self.assertIsNot(raw, parsed)
        self.assertIsNot(raw[0], parsed[0])

    def test_join(self):
        raw = {'Fn::Join': [' ', ['foo', 'bar', 'baz']]}
        self.assertEqual('foo bar baz', join(raw))

    def test_join_none(self):
        raw = {'Fn::Join': [' ', ['foo', None, 'baz']]}
        self.assertEqual('foo  baz', join(raw))

    def test_join_list(self):
        raw = [{'Fn::Join': [' ', ['foo', 'bar', 'baz']]}, 'blarg', 'wibble']
        parsed = join(raw)
        self.assertEqual('foo bar baz', parsed[0])
        for i in six.moves.xrange(1, len(raw)):
            self.assertEqual(raw[i], parsed[i])
        self.assertIsNot(raw, parsed)

    def test_join_dict_val(self):
        raw = {'quux': {'Fn::Join': [' ', ['foo', 'bar', 'baz']]},
               'blarg': 'wibble'}
        parsed = join(raw)
        self.assertEqual('foo bar baz', parsed['quux'])
        self.assertEqual(raw['blarg'], parsed['blarg'])
        self.assertIsNot(raw, parsed)


class TestTemplateConditionParser(common.HeatTestCase):

    def setUp(self):
        super(TestTemplateConditionParser, self).setUp()
        self.ctx = utils.dummy_context()
        t = {
            'heat_template_version': '2016-10-14',
            'parameters': {
                'env_type': {
                    'type': 'string',
                    'default': 'test'
                }
            },
            'conditions': {
                'prod_env': {
                    'equals': [{'get_param': 'env_type'}, 'prod']}},
            'resources': {
                'r1': {
                    'type': 'GenericResourceType',
                    'condition': 'prod_env'
                }
            },
            'outputs': {
                'foo': {
                    'condition': 'prod_env',
                    'value': 'show me'
                }
            }
        }

        self.tmpl = template.Template(t)

    def test_conditions_with_non_supported_functions(self):
        t = {
            'heat_template_version': '2016-10-14',
            'parameters': {
                'env_type': {
                    'type': 'string',
                    'default': 'test'
                }
            },
            'conditions': {
                'prod_env': {
                    'equals': [{'get_param': 'env_type'},
                               {'get_attr': [None, 'att']}]}}}
        # test with get_attr in equals
        tmpl = template.Template(t)
        stk = stack.Stack(self.ctx, 'test_condition_with_get_attr_func', tmpl)
        ex = self.assertRaises(exception.StackValidationFailed,
                               tmpl.conditions, stk)
        self.assertIn('"get_attr" is invalid', six.text_type(ex))
        self.assertIn('conditions.prod_env.equals[1].get_attr',
                      six.text_type(ex))

        # test with get_resource in top level of a condition
        tmpl.t['conditions']['prod_env'] = {'get_resource': 'R1'}
        stk = stack.Stack(self.ctx, 'test_condition_with_get_attr_func', tmpl)
        ex = self.assertRaises(exception.StackValidationFailed,
                               tmpl.conditions, stk)
        self.assertIn('"get_resource" is invalid', six.text_type(ex))

        # test with get_attr in top level of a condition
        tmpl.t['conditions']['prod_env'] = {'get_attr': [None, 'att']}
        stk = stack.Stack(self.ctx, 'test_condition_with_get_attr_func', tmpl)
        ex = self.assertRaises(exception.StackValidationFailed,
                               tmpl.conditions, stk)
        self.assertIn('"get_attr" is invalid', six.text_type(ex))

    def test_condition_resolved_not_boolean(self):
        t = {
            'heat_template_version': '2016-10-14',
            'parameters': {
                'env_type': {
                    'type': 'string',
                    'default': 'test'
                }
            },
            'conditions': {
                'prod_env': {'get_param': 'env_type'}}}

        # test with get_attr in equals
        tmpl = template.Template(t)
        stk = stack.Stack(self.ctx, 'test_condition_not_boolean', tmpl)

        conditions = tmpl.conditions(stk)
        ex = self.assertRaises(exception.StackValidationFailed,
                               conditions.is_enabled, 'prod_env')
        self.assertIn('The definition of condition "prod_env" is invalid',
                      six.text_type(ex))

    def test_condition_reference_condition(self):
        t = {
            'heat_template_version': '2016-10-14',
            'parameters': {
                'env_type': {
                    'type': 'string',
                    'default': 'test'
                }
            },
            'conditions': {
                'prod_env': {'equals': [{'get_param': 'env_type'}, 'prod']},
                'test_env': {'not': 'prod_env'},
                'prod_or_test_env': {'or': ['prod_env', 'test_env']},
                'prod_and_test_env': {'and': ['prod_env', 'test_env']},
            }}

        # test with get_attr in equals
        tmpl = template.Template(t)
        stk = stack.Stack(self.ctx, 'test_condition_reference', tmpl)
        conditions = tmpl.conditions(stk)

        self.assertFalse(conditions.is_enabled('prod_env'))
        self.assertTrue(conditions.is_enabled('test_env'))
        self.assertTrue(conditions.is_enabled('prod_or_test_env'))
        self.assertFalse(conditions.is_enabled('prod_and_test_env'))

    def test_get_res_condition_invalid(self):
        tmpl = copy.deepcopy(self.tmpl)
        # test condition name is invalid
        stk = stack.Stack(self.ctx, 'test_res_invalid_condition', tmpl)

        conds = tmpl.conditions(stk)
        ex = self.assertRaises(ValueError, conds.is_enabled, 'invalid_cd')
        self.assertIn('Invalid condition "invalid_cd"', six.text_type(ex))
        # test condition name is not string
        ex = self.assertRaises(ValueError, conds.is_enabled, 111)
        self.assertIn('Invalid condition "111"', six.text_type(ex))

    def test_res_condition_using_boolean(self):
        tmpl = copy.deepcopy(self.tmpl)
        # test condition name is boolean
        stk = stack.Stack(self.ctx, 'test_res_cd_boolean', tmpl)

        conds = tmpl.conditions(stk)
        self.assertTrue(conds.is_enabled(True))
        self.assertFalse(conds.is_enabled(False))

    def test_parse_output_condition_invalid(self):
        stk = stack.Stack(self.ctx,
                          'test_output_invalid_condition',
                          self.tmpl)

        # test condition name is invalid
        self.tmpl.t['outputs']['foo']['condition'] = 'invalid_cd'
        ex = self.assertRaises(exception.StackValidationFailed,
                               lambda: stk.outputs)
        self.assertIn('Invalid condition "invalid_cd"', six.text_type(ex))
        self.assertIn('outputs.foo.condition', six.text_type(ex))
        # test condition name is not string
        self.tmpl.t['outputs']['foo']['condition'] = 222
        ex = self.assertRaises(exception.StackValidationFailed,
                               lambda: stk.outputs)
        self.assertIn('Invalid condition "222"', six.text_type(ex))
        self.assertIn('outputs.foo.condition', six.text_type(ex))

    def test_conditions_circular_ref(self):
        t = {
            'heat_template_version': '2016-10-14',
            'parameters': {
                'env_type': {
                    'type': 'string',
                    'default': 'test'
                }
            },
            'conditions': {
                'first_cond': {'not': 'second_cond'},
                'second_cond': {'not': 'third_cond'},
                'third_cond': {'not': 'first_cond'},
            }
        }
        tmpl = template.Template(t)
        stk = stack.Stack(self.ctx, 'test_condition_circular_ref', tmpl)
        conds = tmpl.conditions(stk)
        ex = self.assertRaises(exception.StackValidationFailed,
                               conds.is_enabled, 'first_cond')
        self.assertIn('Circular definition for condition "first_cond"',
                      six.text_type(ex))

    def test_parse_output_condition_boolean(self):
        t = copy.deepcopy(self.tmpl.t)
        t['outputs']['foo']['condition'] = True
        stk = stack.Stack(self.ctx,
                          'test_output_cd_boolean',
                          template.Template(t))

        self.assertEqual('show me', stk.outputs['foo'].get_value())

        t = copy.deepcopy(self.tmpl.t)
        t['outputs']['foo']['condition'] = False
        stk = stack.Stack(self.ctx,
                          'test_output_cd_boolean',
                          template.Template(t))
        self.assertIsNone(stk.outputs['foo'].get_value())

    def test_parse_output_condition_function(self):
        t = copy.deepcopy(self.tmpl.t)
        t['outputs']['foo']['condition'] = {'not': 'prod_env'}
        stk = stack.Stack(self.ctx,
                          'test_output_cd_function',
                          template.Template(t))

        self.assertEqual('show me', stk.outputs['foo'].get_value())


class TestTemplateValidate(common.HeatTestCase):

    def test_template_validate_cfn_check_t_digest(self):
        t = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'Description': 'foo',
            'Parameters': {},
            'Mappings': {},
            'Resources': {
                'server': {
                    'Type': 'OS::Nova::Server'
                }
            },
            'Outputs': {},
        }

        tmpl = template.Template(t)
        self.assertIsNone(tmpl.t_digest)
        tmpl.validate()
        self.assertEqual(
            hashlib.sha256(six.text_type(t).encode('utf-8')).hexdigest(),
            tmpl.t_digest, 'invalid template digest')

    def test_template_validate_cfn_good(self):
        t = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'Description': 'foo',
            'Parameters': {},
            'Mappings': {},
            'Resources': {
                'server': {
                    'Type': 'OS::Nova::Server'
                }
            },
            'Outputs': {},
        }

        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)

        # test with alternate version key
        t = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Description': 'foo',
            'Parameters': {},
            'Mappings': {},
            'Resources': {
                'server': {
                    'Type': 'OS::Nova::Server'
                }
            },
            'Outputs': {},
        }

        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)

    def test_template_validate_cfn_bad_section(self):
        t = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'Description': 'foo',
            'Parameteers': {},
            'Mappings': {},
            'Resources': {
                'server': {
                    'Type': 'OS::Nova::Server'
                }
            },
            'Outputs': {},
        }

        tmpl = template.Template(t)
        err = self.assertRaises(exception.InvalidTemplateSection,
                                tmpl.validate)
        self.assertIn('Parameteers', six.text_type(err))

    def test_template_validate_cfn_empty(self):
        t = template_format.parse('''
            AWSTemplateFormatVersion: 2010-09-09
            Parameters:
            Resources:
            Outputs:
            ''')
        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)

    def test_get_resources_good(self):
        """Test get resources successful."""

        t = template_format.parse('''
            AWSTemplateFormatVersion: 2010-09-09
            Resources:
              resource1:
                Type: AWS::EC2::Instance
                Properties:
                  property1: value1
                Metadata:
                  foo: bar
                DependsOn: dummy
                DeletionPolicy: dummy
                UpdatePolicy:
                  foo: bar
        ''')

        expected = {'resource1': {'Type': 'AWS::EC2::Instance',
                                  'Properties': {'property1': 'value1'},
                                  'Metadata': {'foo': 'bar'},
                                  'DependsOn': 'dummy',
                                  'DeletionPolicy': 'dummy',
                                  'UpdatePolicy': {'foo': 'bar'}}}

        tmpl = template.Template(t)
        self.assertEqual(expected, tmpl[tmpl.RESOURCES])

    def test_get_resources_bad_no_data(self):
        """Test get resources without any mapping."""

        t = template_format.parse('''
            AWSTemplateFormatVersion: 2010-09-09
            Resources:
              resource1:
        ''')

        tmpl = template.Template(t)
        error = self.assertRaises(exception.StackValidationFailed,
                                  tmpl.validate)
        self.assertEqual('Each Resource must contain a Type key.',
                         six.text_type(error))

    def test_get_resources_no_type(self):
        """Test get resources with invalid key."""

        t = template_format.parse('''
            AWSTemplateFormatVersion: 2010-09-09
            Resources:
              resource1:
                Properties:
                  property1: value1
                Metadata:
                  foo: bar
                DependsOn: dummy
                DeletionPolicy: dummy
                UpdatePolicy:
                  foo: bar
        ''')

        tmpl = template.Template(t)
        error = self.assertRaises(exception.StackValidationFailed,
                                  tmpl.validate)
        self.assertEqual('Each Resource must contain a Type key.',
                         six.text_type(error))

    def test_template_validate_hot_check_t_digest(self):
        t = {
            'heat_template_version': '2015-04-30',
            'description': 'foo',
            'parameters': {},
            'resources': {
                'server': {
                    'type': 'OS::Nova::Server'
                }
            },
            'outputs': {},
        }

        tmpl = template.Template(t)
        self.assertIsNone(tmpl.t_digest)
        tmpl.validate()
        self.assertEqual(hashlib.sha256(
            six.text_type(t).encode('utf-8')).hexdigest(),
            tmpl.t_digest, 'invalid template digest')

    def test_template_validate_hot_good(self):
        t = {
            'heat_template_version': '2013-05-23',
            'description': 'foo',
            'parameters': {},
            'resources': {
                'server': {
                    'type': 'OS::Nova::Server'
                }
            },
            'outputs': {},
        }

        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)

    def test_template_validate_hot_bad_section(self):
        t = {
            'heat_template_version': '2013-05-23',
            'description': 'foo',
            'parameteers': {},
            'resources': {
                'server': {
                    'type': 'OS::Nova::Server'
                }
            },
            'outputs': {},
        }

        tmpl = template.Template(t)
        err = self.assertRaises(exception.InvalidTemplateSection,
                                tmpl.validate)
        self.assertIn('parameteers', six.text_type(err))


class TemplateTest(common.HeatTestCase):

    def setUp(self):
        super(TemplateTest, self).setUp()
        self.ctx = utils.dummy_context()

    @staticmethod
    def resolve(snippet, template, stack=None):
        return function.resolve(template.parse(stack and stack.defn, snippet))

    @staticmethod
    def resolve_condition(snippet, template, stack=None):
        return function.resolve(template.parse_condition(stack and stack.defn,
                                                         snippet))

    def test_defaults(self):
        empty = template.Template(empty_template)
        self.assertNotIn('AWSTemplateFormatVersion', empty)
        self.assertEqual('No description', empty['Description'])
        self.assertEqual({}, empty['Mappings'])
        self.assertEqual({}, empty['Resources'])
        self.assertEqual({}, empty['Outputs'])

    def test_aws_version(self):
        tmpl = template.Template(mapping_template)
        self.assertEqual(('AWSTemplateFormatVersion', '2010-09-09'),
                         tmpl.version)

    def test_heat_version(self):
        tmpl = template.Template(resource_template)
        self.assertEqual(('HeatTemplateFormatVersion', '2012-12-12'),
                         tmpl.version)

    def test_invalid_hot_version(self):
        invalid_hot_version_tmp = template_format.parse(
            '''{
            "heat_template_version" : "2012-12-12",
            }''')
        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    template.Template, invalid_hot_version_tmp)
        valid_versions = ['2013-05-23', '2014-10-16',
                          '2015-04-30', '2015-10-15', '2016-04-08',
                          '2016-10-14', '2017-02-24', '2017-09-01',
                          '2018-03-02', '2018-08-31',
                          'newton', 'ocata', 'pike',
                          'queens', 'rocky']
        ex_error_msg = ('The template version is invalid: '
                        '"heat_template_version: 2012-12-12". '
                        '"heat_template_version" should be one of: %s'
                        % ', '.join(valid_versions))
        self.assertEqual(ex_error_msg, six.text_type(init_ex))

    def test_invalid_version_not_in_hot_versions(self):
        invalid_hot_version_tmp = template_format.parse(
            '''{
            "heat_template_version" : "2012-12-12",
            }''')
        versions = {
            ('heat_template_version', '2013-05-23'): hot_t.HOTemplate20130523,
            ('heat_template_version', '2013-06-23'): hot_t.HOTemplate20130523
        }

        temp_copy = copy.deepcopy(template._template_classes)
        template._template_classes = versions
        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    template.Template, invalid_hot_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"heat_template_version: 2012-12-12". '
                        '"heat_template_version" should be '
                        'one of: 2013-05-23, 2013-06-23')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))
        template._template_classes = temp_copy

    def test_invalid_aws_version(self):
        invalid_aws_version_tmp = template_format.parse(
            '''{
            "AWSTemplateFormatVersion" : "2012-12-12",
            }''')
        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    template.Template, invalid_aws_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"AWSTemplateFormatVersion: 2012-12-12". '
                        '"AWSTemplateFormatVersion" should be: 2010-09-09')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))

    def test_invalid_version_not_in_aws_versions(self):
        invalid_aws_version_tmp = template_format.parse(
            '''{
            "AWSTemplateFormatVersion" : "2012-12-12",
            }''')
        versions = {
            ('AWSTemplateFormatVersion', '2010-09-09'): cfn_t.CfnTemplate,
            ('AWSTemplateFormatVersion', '2011-06-23'): cfn_t.CfnTemplate
        }
        temp_copy = copy.deepcopy(template._template_classes)
        template._template_classes = versions

        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    template.Template, invalid_aws_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"AWSTemplateFormatVersion: 2012-12-12". '
                        '"AWSTemplateFormatVersion" should be '
                        'one of: 2010-09-09, 2011-06-23')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))
        template._template_classes = temp_copy

    def test_invalid_heat_version(self):
        invalid_heat_version_tmp = template_format.parse(
            '''{
            "HeatTemplateFormatVersion" : "2010-09-09",
            }''')
        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    template.Template,
                                    invalid_heat_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"HeatTemplateFormatVersion: 2010-09-09". '
                        '"HeatTemplateFormatVersion" should be: 2012-12-12')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))

    def test_invalid_version_not_in_heat_versions(self):
        invalid_heat_version_tmp = template_format.parse(
            '''{
            "HeatTemplateFormatVersion" : "2010-09-09",
            }''')
        versions = {
            ('HeatTemplateFormatVersion', '2012-12-12'): cfn_t.CfnTemplate,
            ('HeatTemplateFormatVersion', '2014-12-12'): cfn_t.CfnTemplate
        }
        temp_copy = copy.deepcopy(template._template_classes)
        template._template_classes = versions

        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    template.Template,
                                    invalid_heat_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"HeatTemplateFormatVersion: 2010-09-09". '
                        '"HeatTemplateFormatVersion" should be '
                        'one of: 2012-12-12, 2014-12-12')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))

        template._template_classes = temp_copy

    def test_invalid_template(self):
        scanner_error = '''
            1
            Mappings:
              ValidMapping:
                TestKey: TestValue
            '''
        parser_error = '''
            Mappings:
              ValidMapping:
                TestKey: {TestKey1: "Value1" TestKey2: "Value2"}
            '''

        self.assertRaises(ValueError, template_format.parse, scanner_error)
        self.assertRaises(ValueError, template_format.parse, parser_error)

    def test_invalid_section(self):
        tmpl = template.Template({'HeatTemplateFormatVersion': '2012-12-12',
                                  'Foo': ['Bar']})
        self.assertNotIn('Foo', tmpl)

    def test_find_in_map(self):
        tmpl = template.Template(mapping_template)
        stk = stack.Stack(self.ctx, 'test', tmpl)
        find = {'Fn::FindInMap': ["ValidMapping", "TestKey", "TestValue"]}
        self.assertEqual("wibble", self.resolve(find, tmpl, stk))

    def test_find_in_invalid_map(self):
        tmpl = template.Template(mapping_template)
        stk = stack.Stack(self.ctx, 'test', tmpl)
        finds = ({'Fn::FindInMap': ["InvalidMapping", "ValueList", "foo"]},
                 {'Fn::FindInMap': ["InvalidMapping", "ValueString", "baz"]},
                 {'Fn::FindInMap': ["MapList", "foo", "bar"]},
                 {'Fn::FindInMap': ["MapString", "foo", "bar"]})

        for find in finds:
            self.assertRaises((KeyError, TypeError), self.resolve,
                              find, tmpl, stk)

    def test_bad_find_in_map(self):
        tmpl = template.Template(mapping_template)
        stk = stack.Stack(self.ctx, 'test', tmpl)
        finds = ({'Fn::FindInMap': "String"},
                 {'Fn::FindInMap': {"Dict": "String"}},
                 {'Fn::FindInMap': ["ShortList", "foo"]},
                 {'Fn::FindInMap': ["ReallyShortList"]})

        for find in finds:
            self.assertRaises(exception.StackValidationFailed,
                              self.resolve, find, tmpl, stk)

    def test_param_refs(self):
        env = environment.Environment({'foo': 'bar', 'blarg': 'wibble'})
        tmpl = template.Template(parameter_template, env=env)
        stk = stack.Stack(self.ctx, 'test', tmpl)
        p_snippet = {"Ref": "foo"}
        self.assertEqual("bar", self.resolve(p_snippet, tmpl, stk))

    def test_param_ref_missing(self):
        env = environment.Environment({'foo': 'bar'})
        tmpl = template.Template(parameter_template, env=env)
        stk = stack.Stack(self.ctx, 'test', tmpl)
        tmpl.env = environment.Environment({})
        stk.defn.parameters = cfn_p.CfnParameters(stk.identifier(), tmpl)
        snippet = {"Ref": "foo"}
        self.assertRaises(exception.UserParameterMissing,
                          self.resolve,
                          snippet, tmpl, stk)

    def test_resource_refs(self):
        tmpl = template.Template(resource_template)
        stk = stack.Stack(self.ctx, 'test', tmpl)
        stk.validate()

        data = node_data.NodeData.from_dict({'reference_id': 'bar'})
        stk_defn.update_resource_data(stk.defn, 'foo', data)
        r_snippet = {"Ref": "foo"}
        self.assertEqual("bar", self.resolve(r_snippet, tmpl, stk))

    def test_resource_refs_param(self):
        tmpl = template.Template(resource_template)
        stk = stack.Stack(self.ctx, 'test', tmpl)

        p_snippet = {"Ref": "baz"}
        parsed = tmpl.parse(stk.defn, p_snippet)
        self.assertIsInstance(parsed, cfn_funcs.ParamRef)

    def test_select_from_list(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Select": ["1", ["foo", "bar"]]}
        self.assertEqual("bar", self.resolve(data, tmpl))

    def test_select_from_list_integer_index(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Select": [1, ["foo", "bar"]]}
        self.assertEqual("bar", self.resolve(data, tmpl))

    def test_select_from_list_out_of_bound(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Select": ["0", ["foo", "bar"]]}
        self.assertEqual("foo", self.resolve(data, tmpl))
        data = {"Fn::Select": ["1", ["foo", "bar"]]}
        self.assertEqual("bar", self.resolve(data, tmpl))
        data = {"Fn::Select": ["2", ["foo", "bar"]]}
        self.assertEqual("", self.resolve(data, tmpl))

    def test_select_from_dict(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Select": ["red", {"red": "robin", "re": "foo"}]}
        self.assertEqual("robin", self.resolve(data, tmpl))

    def test_select_int_from_dict(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Select": ["2", {"1": "bar", "2": "foo"}]}
        self.assertEqual("foo", self.resolve(data, tmpl))

    def test_select_from_none(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Select": ["red", None]}
        self.assertEqual("", self.resolve(data, tmpl))

    def test_select_from_dict_not_existing(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Select": ["green", {"red": "robin", "re": "foo"}]}
        self.assertEqual("", self.resolve(data, tmpl))

    def test_select_from_serialized_json_map(self):
        tmpl = template.Template(empty_template)
        js = json.dumps({"red": "robin", "re": "foo"})
        data = {"Fn::Select": ["re", js]}
        self.assertEqual("foo", self.resolve(data, tmpl))

    def test_select_from_serialized_json_list(self):
        tmpl = template.Template(empty_template)
        js = json.dumps(["foo", "fee", "fum"])
        data = {"Fn::Select": ["0", js]}
        self.assertEqual("foo", self.resolve(data, tmpl))

    def test_select_empty_string(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Select": ["0", '']}
        self.assertEqual("", self.resolve(data, tmpl))
        data = {"Fn::Select": ["1", '']}
        self.assertEqual("", self.resolve(data, tmpl))
        data = {"Fn::Select": ["one", '']}
        self.assertEqual("", self.resolve(data, tmpl))

    def test_equals(self):
        tpl = template_format.parse('''
        AWSTemplateFormatVersion: 2010-09-09
        Parameters:
          env_type:
            Type: String
            Default: 'test'
        ''')
        snippet = {'Fn::Equals': [{'Ref': 'env_type'}, 'prod']}
        # when param 'env_type' is 'test', equals function resolve to false
        tmpl = template.Template(tpl)
        stk = stack.Stack(utils.dummy_context(),
                          'test_equals_false', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertFalse(resolved)
        # when param 'env_type' is 'prod', equals function resolve to true
        tmpl = template.Template(tpl,
                                 env=environment.Environment(
                                     {'env_type': 'prod'}))
        stk = stack.Stack(utils.dummy_context(),
                          'test_equals_true', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertTrue(resolved)

    def test_equals_invalid_args(self):
        tmpl = template.Template(aws_empty_template)

        snippet = {'Fn::Equals': ['test', 'prod', 'invalid']}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)

        error_msg = ('.Fn::Equals: Arguments to "Fn::Equals" must be '
                     'of the form: [value_1, value_2]')
        self.assertIn(error_msg, six.text_type(exc))
        # test invalid type
        snippet = {'Fn::Equals': {"equal": False}}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)
        self.assertIn(error_msg, six.text_type(exc))

    def test_not(self):
        tpl = template_format.parse('''
        AWSTemplateFormatVersion: 2010-09-09
        Parameters:
          env_type:
            Type: String
            Default: 'test'
        ''')
        snippet = {'Fn::Not': [{'Fn::Equals': [{'Ref': 'env_type'}, 'prod']}]}
        # when param 'env_type' is 'test', not function resolve to true
        tmpl = template.Template(tpl)
        stk = stack.Stack(utils.dummy_context(),
                          'test_not_true', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertTrue(resolved)
        # when param 'env_type' is 'prod', not function resolve to false
        tmpl = template.Template(tpl,
                                 env=environment.Environment(
                                     {'env_type': 'prod'}))
        stk = stack.Stack(utils.dummy_context(),
                          'test_not_false', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertFalse(resolved)

    def test_not_invalid_args(self):
        tmpl = template.Template(aws_empty_template)

        stk = stack.Stack(utils.dummy_context(),
                          'test_not_invalid', tmpl)
        snippet = {'Fn::Not': ['invalid_arg']}
        exc = self.assertRaises(ValueError,
                                self.resolve_condition, snippet, tmpl, stk)

        error_msg = 'Invalid condition "invalid_arg"'
        self.assertIn(error_msg, six.text_type(exc))
        # test invalid type
        snippet = {'Fn::Not': 'invalid'}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)
        error_msg = 'Arguments to "Fn::Not" must be '
        self.assertIn(error_msg, six.text_type(exc))

        snippet = {'Fn::Not': ['cd1', 'cd2']}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)
        error_msg = 'Arguments to "Fn::Not" must be '
        self.assertIn(error_msg, six.text_type(exc))

    def test_and(self):
        tpl = template_format.parse('''
        AWSTemplateFormatVersion: 2010-09-09
        Parameters:
          env_type:
            Type: String
            Default: 'test'
          zone:
            Type: String
            Default: 'shanghai'
        ''')
        snippet = {
            'Fn::And': [
                {'Fn::Equals': [{'Ref': 'env_type'}, 'prod']},
                {'Fn::Not': [{'Fn::Equals': [{'Ref': 'zone'}, "beijing"]}]}]}
        # when param 'env_type' is 'test', and function resolve to false
        tmpl = template.Template(tpl)
        stk = stack.Stack(utils.dummy_context(),
                          'test_and_false', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertFalse(resolved)
        # when param 'env_type' is 'prod', and param 'zone' is 'shanghai',
        # the 'and' function resolve to true
        tmpl = template.Template(tpl,
                                 env=environment.Environment(
                                     {'env_type': 'prod'}))
        stk = stack.Stack(utils.dummy_context(),
                          'test_and_true', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertTrue(resolved)
        # when param 'env_type' is 'prod', and param 'zone' is 'shanghai',
        # the 'and' function resolve to true
        tmpl = template.Template(tpl,
                                 env=environment.Environment(
                                     {'env_type': 'prod',
                                      'zone': 'beijing'}))
        stk = stack.Stack(utils.dummy_context(),
                          'test_and_false', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertFalse(resolved)

    def test_and_invalid_args(self):
        tmpl = template.Template(aws_empty_template)

        error_msg = ('The minimum number of condition arguments to "Fn::And" '
                     'is 2.')
        snippet = {'Fn::And': ['invalid_arg']}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)
        self.assertIn(error_msg, six.text_type(exc))

        error_msg = 'Arguments to "Fn::And" must be'
        # test invalid type
        snippet = {'Fn::And': 'invalid'}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)
        self.assertIn(error_msg, six.text_type(exc))

        stk = stack.Stack(utils.dummy_context(), 'test_and_invalid', tmpl)
        snippet = {'Fn::And': ['cd1', True]}
        exc = self.assertRaises(ValueError,
                                self.resolve_condition, snippet, tmpl, stk)
        error_msg = 'Invalid condition "cd1"'
        self.assertIn(error_msg, six.text_type(exc))

    def test_or(self):
        tpl = template_format.parse('''
        AWSTemplateFormatVersion: 2010-09-09
        Parameters:
          zone:
            Type: String
            Default: 'guangzhou'
        ''')
        snippet = {
            'Fn::Or': [
                {'Fn::Equals': [{'Ref': 'zone'}, 'shanghai']},
                {'Fn::Equals': [{'Ref': 'zone'}, 'beijing']}]}
        # when param 'zone' is neither equal to 'shanghai' nor 'beijing',
        # the 'or' function resolve to false
        tmpl = template.Template(tpl)
        stk = stack.Stack(utils.dummy_context(),
                          'test_or_false', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertFalse(resolved)
        # when param 'zone' equals to 'shanghai' or 'beijing',
        # the 'or' function resolve to true
        tmpl = template.Template(tpl,
                                 env=environment.Environment(
                                     {'zone': 'beijing'}))
        stk = stack.Stack(utils.dummy_context(),
                          'test_or_true', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertTrue(resolved)

        tmpl = template.Template(tpl,
                                 env=environment.Environment(
                                     {'zone': 'shanghai'}))
        stk = stack.Stack(utils.dummy_context(),
                          'test_or_true', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stk)
        self.assertTrue(resolved)

    def test_or_invalid_args(self):
        tmpl = template.Template(aws_empty_template)

        error_msg = ('The minimum number of condition arguments to "Fn::Or" '
                     'is 2.')
        snippet = {'Fn::Or': ['invalid_arg']}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)
        self.assertIn(error_msg, six.text_type(exc))

        error_msg = 'Arguments to "Fn::Or" must be'
        # test invalid type
        snippet = {'Fn::Or': 'invalid'}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)
        self.assertIn(error_msg, six.text_type(exc))

        stk = stack.Stack(utils.dummy_context(), 'test_or_invalid', tmpl)
        snippet = {'Fn::Or': ['invalid_cd', True]}
        exc = self.assertRaises(ValueError,
                                self.resolve_condition, snippet, tmpl, stk)
        error_msg = 'Invalid condition "invalid_cd"'
        self.assertIn(error_msg, six.text_type(exc))

    def test_join(self):
        tmpl = template.Template(empty_template)
        join = {"Fn::Join": [" ", ["foo", "bar"]]}
        self.assertEqual("foo bar", self.resolve(join, tmpl))

    def test_split_ok(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Split": [";", "foo; bar; achoo"]}
        self.assertEqual(['foo', ' bar', ' achoo'], self.resolve(data, tmpl))

    def test_split_no_delim_in_str(self):
        tmpl = template.Template(empty_template)
        data = {"Fn::Split": [";", "foo, bar, achoo"]}
        self.assertEqual(['foo, bar, achoo'], self.resolve(data, tmpl))

    def test_base64(self):
        tmpl = template.Template(empty_template)
        snippet = {"Fn::Base64": "foobar"}
        # For now, the Base64 function just returns the original text, and
        # does not convert to base64 (see issue #133)
        self.assertEqual("foobar", self.resolve(snippet, tmpl))

    def test_get_azs(self):
        tmpl = template.Template(empty_template)
        snippet = {"Fn::GetAZs": ""}
        self.assertEqual(["nova"], self.resolve(snippet, tmpl))

    def test_get_azs_with_stack(self):
        tmpl = template.Template(empty_template)
        snippet = {"Fn::GetAZs": ""}
        stk = stack.Stack(self.ctx, 'test_stack',
                          template.Template(empty_template))
        fc = fakes_nova.FakeClient()
        self.patchobject(nova.NovaClientPlugin, 'client', return_value=fc)
        self.assertEqual(["nova1"], self.resolve(snippet, tmpl, stk))

    def test_replace_string_values(self):
        tmpl = template.Template(empty_template)
        snippet = {"Fn::Replace": [
            {'$var1': 'foo', '%var2%': 'bar'},
            '$var1 is %var2%'
        ]}
        self.assertEqual('foo is bar', self.resolve(snippet, tmpl))

    def test_replace_number_values(self):
        tmpl = template.Template(empty_template)
        snippet = {"Fn::Replace": [
            {'$var1': 1, '%var2%': 2},
            '$var1 is not %var2%'
        ]}
        self.assertEqual('1 is not 2', self.resolve(snippet, tmpl))

        snippet = {"Fn::Replace": [
            {'$var1': 1.3, '%var2%': 2.5},
            '$var1 is not %var2%'
        ]}
        self.assertEqual('1.3 is not 2.5', self.resolve(snippet, tmpl))

    def test_replace_none_values(self):
        tmpl = template.Template(empty_template)
        snippet = {"Fn::Replace": [
            {'$var1': None, '${var2}': None},
            '"$var1" is "${var2}"'
        ]}
        self.assertEqual('"" is ""', self.resolve(snippet, tmpl))

    def test_replace_missing_key(self):
        tmpl = template.Template(empty_template)
        snippet = {"Fn::Replace": [
            {'$var1': 'foo', 'var2': 'bar'},
            '"$var1" is "${var3}"'
        ]}
        self.assertEqual('"foo" is "${var3}"', self.resolve(snippet, tmpl))

    def test_replace_param_values(self):
        env = environment.Environment({'foo': 'wibble'})
        tmpl = template.Template(parameter_template, env=env)
        stk = stack.Stack(self.ctx, 'test_stack', tmpl)
        snippet = {"Fn::Replace": [
            {'$var1': {'Ref': 'foo'}, '%var2%': {'Ref': 'blarg'}},
            '$var1 is %var2%'
        ]}
        self.assertEqual('wibble is quux', self.resolve(snippet, tmpl, stk))

    def test_member_list2map_good(self):
        tmpl = template.Template(empty_template)
        snippet = {"Fn::MemberListToMap": [
            'Name', 'Value', ['.member.0.Name=metric',
                              '.member.0.Value=cpu',
                              '.member.1.Name=size',
                              '.member.1.Value=56']]}
        self.assertEqual({'metric': 'cpu', 'size': '56'},
                         self.resolve(snippet, tmpl))

    def test_member_list2map_good2(self):
        tmpl = template.Template(empty_template)
        snippet = {"Fn::MemberListToMap": [
            'Key', 'Value', ['.member.2.Key=metric',
                             '.member.2.Value=cpu',
                             '.member.5.Key=size',
                             '.member.5.Value=56']]}
        self.assertEqual({'metric': 'cpu', 'size': '56'},
                         self.resolve(snippet, tmpl))

    def test_resource_facade(self):
        metadata_snippet = {'Fn::ResourceFacade': 'Metadata'}
        deletion_policy_snippet = {'Fn::ResourceFacade': 'DeletionPolicy'}
        update_policy_snippet = {'Fn::ResourceFacade': 'UpdatePolicy'}

        parent_resource = DummyClass()
        parent_resource.metadata_set({"foo": "bar"})

        parent_resource.t = rsrc_defn.ResourceDefinition(
            'parent', 'SomeType',
            deletion_policy=rsrc_defn.ResourceDefinition.RETAIN,
            update_policy={"blarg": "wibble"})
        tmpl = copy.deepcopy(empty_template)
        tmpl['Resources'] = {'parent': {'Type': 'SomeType',
                                        'DeletionPolicy': 'Retain',
                                        'UpdatePolicy': {"blarg": "wibble"}}}
        parent_resource.stack = stack.Stack(self.ctx, 'toplevel_stack',
                                            template.Template(tmpl))
        parent_resource.stack._resources = {'parent': parent_resource}

        stk = stack.Stack(self.ctx, 'test_stack',
                          template.Template(empty_template),
                          parent_resource='parent', owner_id=45)
        stk.set_parent_stack(parent_resource.stack)
        self.assertEqual({"foo": "bar"},
                         self.resolve(metadata_snippet, stk.t, stk))
        self.assertEqual('Retain',
                         self.resolve(deletion_policy_snippet, stk.t, stk))
        self.assertEqual({"blarg": "wibble"},
                         self.resolve(update_policy_snippet, stk.t, stk))

    def test_resource_facade_function(self):
        deletion_policy_snippet = {'Fn::ResourceFacade': 'DeletionPolicy'}

        parent_resource = DummyClass()
        parent_resource.metadata_set({"foo": "bar"})
        del_policy = cfn_funcs.Join(None,
                                    'Fn::Join', ['eta', ['R', 'in']])
        parent_resource.t = rsrc_defn.ResourceDefinition(
            'parent', 'SomeType',
            deletion_policy=del_policy)
        tmpl = copy.deepcopy(empty_template)
        tmpl['Resources'] = {'parent': {'Type': 'SomeType',
                                        'DeletionPolicy': del_policy}}
        parent_resource.stack = stack.Stack(self.ctx, 'toplevel_stack',
                                            template.Template(tmpl))
        parent_resource.stack._resources = {'parent': parent_resource}

        stk = stack.Stack(self.ctx, 'test_stack',
                          template.Template(empty_template),
                          parent_resource='parent')
        stk.set_parent_stack(parent_resource.stack)
        self.assertEqual('Retain',
                         self.resolve(deletion_policy_snippet, stk.t, stk))

    def test_resource_facade_invalid_arg(self):
        snippet = {'Fn::ResourceFacade': 'wibble'}
        stk = stack.Stack(self.ctx, 'test_stack',
                          template.Template(empty_template))
        error = self.assertRaises(exception.StackValidationFailed,
                                  self.resolve, snippet, stk.t, stk)
        self.assertIn(next(iter(snippet)), six.text_type(error))

    def test_resource_facade_missing_deletion_policy(self):
        snippet = {'Fn::ResourceFacade': 'DeletionPolicy'}

        parent_resource = DummyClass()
        parent_resource.metadata_set({"foo": "bar"})
        parent_resource.t = rsrc_defn.ResourceDefinition('parent', 'SomeType')
        tmpl = copy.deepcopy(empty_template)
        tmpl['Resources'] = {'parent': {'Type': 'SomeType'}}

        parent_resource.stack = stack.Stack(self.ctx, 'toplevel_stack',
                                            template.Template(tmpl))
        parent_resource.stack._resources = {'parent': parent_resource}
        stk = stack.Stack(self.ctx, 'test_stack',
                          template.Template(empty_template),
                          parent_resource='parent', owner_id=78)
        stk.set_parent_stack(parent_resource.stack)
        self.assertEqual('Delete', self.resolve(snippet, stk.t, stk))

    def test_prevent_parameters_access(self):
        expected_description = "This can be accessed"
        tmpl = template.Template({
            'AWSTemplateFormatVersion': '2010-09-09',
            'Description': expected_description,
            'Parameters': {
                'foo': {'Type': 'String', 'Required': True}
            }
        })
        self.assertEqual(expected_description, tmpl['Description'])
        keyError = self.assertRaises(KeyError, tmpl.__getitem__, 'Parameters')
        self.assertIn("can not be accessed directly", six.text_type(keyError))

    def test_parameters_section_not_iterable(self):
        expected_description = "This can be accessed"
        tmpl = template.Template({
            'AWSTemplateFormatVersion': '2010-09-09',
            'Description': expected_description,
            'Parameters': {
                'foo': {'Type': 'String', 'Required': True}
            }
        })
        self.assertEqual(expected_description, tmpl['Description'])
        self.assertNotIn('Parameters', tmpl.keys())

    def test_add_resource(self):
        cfn_tpl = template_format.parse('''
        AWSTemplateFormatVersion: 2010-09-09
        Resources:
          resource1:
            Type: AWS::EC2::Instance
            Properties:
              property1: value1
            Metadata:
              foo: bar
            DependsOn: dummy
            DeletionPolicy: Retain
            UpdatePolicy:
              foo: bar
          resource2:
            Type: AWS::EC2::Instance
          resource3:
            Type: AWS::EC2::Instance
            DependsOn:
              - resource1
              - dummy
              - resource2
        ''')
        source = template.Template(cfn_tpl)
        empty = template.Template(copy.deepcopy(empty_template))
        stk = stack.Stack(self.ctx, 'test_stack', source)

        for rname, defn in sorted(source.resource_definitions(stk).items()):
            empty.add_resource(defn)

        expected = copy.deepcopy(cfn_tpl['Resources'])
        del expected['resource1']['DependsOn']
        expected['resource3']['DependsOn'] = ['resource1', 'resource2']
        self.assertEqual(expected, empty.t['Resources'])

    def test_add_output(self):
        cfn_tpl = template_format.parse('''
        AWSTemplateFormatVersion: 2010-09-09
        Outputs:
          output1:
            Description: An output
            Value: foo
        ''')
        source = template.Template(cfn_tpl)
        empty = template.Template(copy.deepcopy(empty_template))
        stk = stack.Stack(self.ctx, 'test_stack', source)

        for defn in six.itervalues(source.outputs(stk)):
            empty.add_output(defn)

        self.assertEqual(cfn_tpl['Outputs'], empty.t['Outputs'])

    def test_create_empty_template_default_version(self):
        empty_template = template.Template.create_empty_template()
        self.assertEqual(hot_t.HOTemplate20150430, empty_template.__class__)
        self.assertEqual({}, empty_template['parameter_groups'])
        self.assertEqual({}, empty_template['resources'])
        self.assertEqual({}, empty_template['outputs'])

    def test_create_empty_template_returns_correct_version(self):
        t = template_format.parse('''
            AWSTemplateFormatVersion: 2010-09-09
            Parameters:
            Resources:
            Outputs:
            ''')
        aws_tmpl = template.Template(t)
        empty_template = template.Template.create_empty_template(
            version=aws_tmpl.version)
        self.assertEqual(aws_tmpl.__class__, empty_template.__class__)
        self.assertEqual({}, empty_template['Mappings'])
        self.assertEqual({}, empty_template['Resources'])
        self.assertEqual({}, empty_template['Outputs'])

        t = template_format.parse('''
            HeatTemplateFormatVersion: 2012-12-12
            Parameters:
            Resources:
            Outputs:
            ''')
        heat_tmpl = template.Template(t)
        empty_template = template.Template.create_empty_template(
            version=heat_tmpl.version)
        self.assertEqual(heat_tmpl.__class__, empty_template.__class__)
        self.assertEqual({}, empty_template['Mappings'])
        self.assertEqual({}, empty_template['Resources'])
        self.assertEqual({}, empty_template['Outputs'])

        t = template_format.parse('''
            heat_template_version: 2015-04-30
            parameter_groups:
            resources:
            outputs:
            ''')
        hot_tmpl = template.Template(t)
        empty_template = template.Template.create_empty_template(
            version=hot_tmpl.version)
        self.assertEqual(hot_tmpl.__class__, empty_template.__class__)
        self.assertEqual({}, empty_template['parameter_groups'])
        self.assertEqual({}, empty_template['resources'])
        self.assertEqual({}, empty_template['outputs'])

    def test_create_empty_template_from_another_template(self):
        res_param_template = template_format.parse('''{
          "HeatTemplateFormatVersion" : "2012-12-12",
          "Parameters" : {
            "foo" : { "Type" : "String" },
            "blarg" : { "Type" : "String", "Default": "quux" }
          },
          "Resources" : {
            "foo" : { "Type" : "GenericResourceType" },
            "blarg" : { "Type" : "GenericResourceType" }
          }
        }''')

        env = environment.Environment({'foo': 'bar'})
        hot_tmpl = template.Template(res_param_template, env)
        empty_template = template.Template.create_empty_template(
            from_template=hot_tmpl)
        self.assertEqual({}, empty_template['Resources'])
        self.assertEqual(hot_tmpl.env, empty_template.env)


class TemplateFnErrorTest(common.HeatTestCase):
    scenarios = [
        ('select_from_list_not_int',
         dict(expect=TypeError,
              snippet={"Fn::Select": ["one", ["foo", "bar"]]})),
        ('select_from_dict_not_str',
         dict(expect=TypeError,
              snippet={"Fn::Select": [1, {"red": "robin", "re": "foo"}]})),
        ('select_from_serialized_json_wrong',
         dict(expect=ValueError,
              snippet={"Fn::Select": ["not", "no json"]})),
        ('select_wrong_num_args_1',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Select": []})),
        ('select_wrong_num_args_2',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Select": ["4"]})),
        ('select_wrong_num_args_3',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Select": ["foo", {"foo": "bar"}, ""]})),
        ('select_wrong_num_args_4',
         dict(expect=TypeError,
              snippet={'Fn::Select': [['f'], {'f': 'food'}]})),
        ('split_no_delim',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Split": ["foo, bar, achoo"]})),
        ('split_no_list',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Split": "foo, bar, achoo"})),
        ('base64_list',
         dict(expect=TypeError,
              snippet={"Fn::Base64": ["foobar"]})),
        ('base64_dict',
         dict(expect=TypeError,
              snippet={"Fn::Base64": {"foo": "bar"}})),
        ('replace_list_value',
         dict(expect=TypeError,
              snippet={"Fn::Replace": [
                  {'$var1': 'foo', '%var2%': ['bar']},
                  '$var1 is %var2%']})),
        ('replace_list_mapping',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Replace": [
                  ['var1', 'foo', 'var2', 'bar'],
                  '$var1 is ${var2}']})),
        ('replace_dict',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Replace": {}})),
        ('replace_missing_template',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Replace": [['var1', 'foo', 'var2', 'bar']]})),
        ('replace_none_template',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Replace": [['var2', 'bar'], None]})),
        ('replace_list_string',
         dict(expect=TypeError,
              snippet={"Fn::Replace": [
                  {'var1': 'foo', 'var2': 'bar'},
                  ['$var1 is ${var2}']]})),
        ('join_string',
         dict(expect=TypeError,
              snippet={"Fn::Join": [" ", "foo"]})),
        ('join_dict',
         dict(expect=TypeError,
              snippet={"Fn::Join": [" ", {"foo": "bar"}]})),
        ('join_wrong_num_args_1',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Join": []})),
        ('join_wrong_num_args_2',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Join": [" "]})),
        ('join_wrong_num_args_3',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Join": [" ", {"foo": "bar"}, ""]})),
        ('join_string_nodelim',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Join": "o"})),
        ('join_string_nodelim_1',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Join": "oh"})),
        ('join_string_nodelim_2',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Join": "ohh"})),
        ('join_dict_nodelim1',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Join": {"foo": "bar"}})),
        ('join_dict_nodelim2',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Join": {"foo": "bar", "blarg": "wibble"}})),
        ('join_dict_nodelim3',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::Join": {"foo": "bar", "blarg": "wibble",
                                    "baz": "quux"}})),
        ('member_list2map_no_key_or_val',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::MemberListToMap": [
                  'Key', ['.member.2.Key=metric',
                          '.member.2.Value=cpu',
                          '.member.5.Key=size',
                          '.member.5.Value=56']]})),
        ('member_list2map_no_list',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::MemberListToMap": [
                  'Key', '.member.2.Key=metric']})),
        ('member_list2map_not_string',
         dict(expect=exception.StackValidationFailed,
              snippet={"Fn::MemberListToMap": [
                  'Name', ['Value'], ['.member.0.Name=metric',
                                      '.member.0.Value=cpu',
                                      '.member.1.Name=size',
                                      '.member.1.Value=56']]})),
    ]

    def test_bad_input(self):
        tmpl = template.Template(empty_template)

        def resolve(s):
            return TemplateTest.resolve(s, tmpl)

        error = self.assertRaises(self.expect,
                                  resolve,
                                  self.snippet)
        self.assertIn(next(iter(self.snippet)), six.text_type(error))


class ResolveDataTest(common.HeatTestCase):

    def setUp(self):
        super(ResolveDataTest, self).setUp()
        self.username = 'parser_stack_test_user'

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(self.ctx, 'resolve_test_stack',
                                 template.Template(empty_template))

    def resolve(self, snippet):
        return function.resolve(self.stack.t.parse(self.stack.defn, snippet))

    def test_join_split(self):
        # join
        snippet = {'Fn::Join': [';', ['one', 'two', 'three']]}
        self.assertEqual('one;two;three', self.resolve(snippet))

        # join then split
        snippet = {'Fn::Split': [';', snippet]}
        self.assertEqual(['one', 'two', 'three'], self.resolve(snippet))

    def test_split_join_split_join(self):
        # each snippet in this test encapsulates
        # the snippet from the previous step, leading
        # to increasingly nested function calls

        # split
        snippet = {'Fn::Split': [',', 'one,two,three']}
        self.assertEqual(['one', 'two', 'three'], self.resolve(snippet))

        # split then join
        snippet = {'Fn::Join': [';', snippet]}
        self.assertEqual('one;two;three', self.resolve(snippet))

        # split then join then split
        snippet = {'Fn::Split': [';', snippet]}
        self.assertEqual(['one', 'two', 'three'], self.resolve(snippet))

        # split then join then split then join
        snippet = {'Fn::Join': ['-', snippet]}
        self.assertEqual('one-two-three', self.resolve(snippet))

    def test_join_recursive(self):
        raw = {'Fn::Join': ['\n', [{'Fn::Join':
                                   [' ', ['foo', 'bar']]}, 'baz']]}
        self.assertEqual('foo bar\nbaz', self.resolve(raw))

    def test_join_not_string(self):
        snippet = {'Fn::Join': ['\n', [{'Fn::Join':
                                        [' ', ['foo', 45]]}, 'baz']]}
        error = self.assertRaises(TypeError,
                                  self.resolve, snippet)
        self.assertIn('45', six.text_type(error))

    def test_base64_replace(self):
        raw = {'Fn::Base64': {'Fn::Replace': [
            {'foo': 'bar'}, 'Meet at the foo']}}
        self.assertEqual('Meet at the bar', self.resolve(raw))

    def test_replace_base64(self):
        raw = {'Fn::Replace': [{'foo': 'bar'}, {
            'Fn::Base64': 'Meet at the foo'}]}
        self.assertEqual('Meet at the bar', self.resolve(raw))

    def test_nested_selects(self):
        data = {
            'a': ['one', 'two', 'three'],
            'b': ['een', 'twee', {'d': 'D', 'e': 'E'}]
        }
        raw = {'Fn::Select': ['a', data]}
        self.assertEqual(data['a'], self.resolve(raw))

        raw = {'Fn::Select': ['b', data]}
        self.assertEqual(data['b'], self.resolve(raw))

        raw = {
            'Fn::Select': ['1', {
                'Fn::Select': ['b', data]
            }]
        }
        self.assertEqual('twee', self.resolve(raw))

        raw = {
            'Fn::Select': ['e', {
                'Fn::Select': ['2', {
                    'Fn::Select': ['b', data]
                }]
            }]
        }
        self.assertEqual('E', self.resolve(raw))

    def test_member_list_select(self):
        snippet = {'Fn::Select': ['metric', {"Fn::MemberListToMap": [
            'Name', 'Value', ['.member.0.Name=metric',
                              '.member.0.Value=cpu',
                              '.member.1.Name=size',
                              '.member.1.Value=56']]}]}
        self.assertEqual('cpu', self.resolve(snippet))
