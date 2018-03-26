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
import mock
import six

from heat.common import exception
from heat.common import identifier
from heat.common import template_format
from heat.engine.cfn import functions as cfn_functions
from heat.engine.cfn import parameters as cfn_param
from heat.engine import conditions
from heat.engine import environment
from heat.engine import function
from heat.engine.hot import functions as hot_functions
from heat.engine.hot import parameters as hot_param
from heat.engine.hot import template as hot_template
from heat.engine import resource
from heat.engine import resources
from heat.engine import rsrc_defn
from heat.engine import stack as parser
from heat.engine import stk_defn
from heat.engine import template
from heat.tests import common
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils

empty_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
}''')

hot_tpl_empty = template_format.parse('''
heat_template_version: 2013-05-23
''')

hot_juno_tpl_empty = template_format.parse('''
heat_template_version: 2014-10-16
''')

hot_kilo_tpl_empty = template_format.parse('''
heat_template_version: 2015-04-30
''')

hot_liberty_tpl_empty = template_format.parse('''
heat_template_version: 2015-10-15
''')

hot_mitaka_tpl_empty = template_format.parse('''
heat_template_version: 2016-04-08
''')

hot_newton_tpl_empty = template_format.parse('''
heat_template_version: 2016-10-14
''')

hot_ocata_tpl_empty = template_format.parse('''
heat_template_version: 2017-02-24
''')

hot_pike_tpl_empty = template_format.parse('''
heat_template_version: 2017-09-01
''')

hot_tpl_empty_sections = template_format.parse('''
heat_template_version: 2013-05-23
parameters:
resources:
outputs:
''')

hot_tpl_generic_resource = template_format.parse('''
heat_template_version: 2013-05-23
resources:
  resource1:
    type: GenericResourceType
''')

hot_tpl_generic_resource_20141016 = template_format.parse('''
heat_template_version: 2014-10-16
resources:
  resource1:
    type: GenericResourceType
''')

hot_tpl_generic_resource_all_attrs = template_format.parse('''
heat_template_version: 2015-10-15
resources:
  resource1:
    type: GenericResourceType
''')

hot_tpl_complex_attrs_all_attrs = template_format.parse('''
heat_template_version: 2015-10-15
resources:
  resource1:
    type: ResourceWithComplexAttributesType
''')

hot_tpl_complex_attrs = template_format.parse('''
heat_template_version: 2013-05-23
resources:
  resource1:
    type: ResourceWithComplexAttributesType
''')

hot_tpl_complex_attrs_20141016 = template_format.parse('''
heat_template_version: 2014-10-16
resources:
  resource1:
    type: ResourceWithComplexAttributesType
''')

hot_tpl_mapped_props = template_format.parse('''
heat_template_version: 2013-05-23
resources:
  resource1:
    type: ResWithComplexPropsAndAttrs
  resource2:
    type: ResWithComplexPropsAndAttrs
    properties:
      a_list: { get_attr: [ resource1, list] }
      a_string: { get_attr: [ resource1, string ] }
      a_map: { get_attr: [ resource1, map] }
''')

hot_tpl_mapped_props_all_attrs = template_format.parse('''
heat_template_version: 2015-10-15
resources:
  resource1:
    type: ResWithComplexPropsAndAttrs
  resource2:
    type: ResWithComplexPropsAndAttrs
    properties:
      a_list: { get_attr: [ resource1, list] }
      a_string: { get_attr: [ resource1, string ] }
      a_map: { get_attr: [ resource1, map] }
''')


class DummyClass(object):
    metadata = None

    def metadata_get(self):
        return self.metadata

    def metadata_set(self, metadata):
        self.metadata = metadata


class HOTemplateTest(common.HeatTestCase):
    """Test processing of HOT templates."""

    @staticmethod
    def resolve(snippet, template, stack=None):
        return function.resolve(template.parse(stack and stack.defn, snippet))

    @staticmethod
    def resolve_condition(snippet, template, stack=None):
        return function.resolve(template.parse_condition(stack and stack.defn,
                                                         snippet))

    def test_defaults(self):
        """Test default content behavior of HOT template."""

        tmpl = template.Template(hot_tpl_empty)
        # check if we get the right class
        self.assertIsInstance(tmpl, hot_template.HOTemplate20130523)
        # test getting an invalid section
        self.assertNotIn('foobar', tmpl)

        # test defaults for valid sections
        self.assertEqual('No description', tmpl[tmpl.DESCRIPTION])
        self.assertEqual({}, tmpl[tmpl.RESOURCES])
        self.assertEqual({}, tmpl[tmpl.OUTPUTS])

    def test_defaults_for_empty_sections(self):
        """Test default secntion's content behavior of HOT template."""

        tmpl = template.Template(hot_tpl_empty_sections)
        # check if we get the right class
        self.assertIsInstance(tmpl, hot_template.HOTemplate20130523)
        # test getting an invalid section
        self.assertNotIn('foobar', tmpl)

        # test defaults for valid sections
        self.assertEqual('No description', tmpl[tmpl.DESCRIPTION])
        self.assertEqual({}, tmpl[tmpl.RESOURCES])
        self.assertEqual({}, tmpl[tmpl.OUTPUTS])

        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)

        self.assertIsNone(stack.parameters._validate_user_parameters())
        self.assertIsNone(stack.validate())

    def test_translate_resources_good(self):
        """Test translation of resources into internal engine format."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            depends_on: dummy
            deletion_policy: dummy
            update_policy:
              foo: bar
        ''')

        expected = {'resource1': {'Type': 'AWS::EC2::Instance',
                                  'Properties': {'property1': 'value1'},
                                  'Metadata': {'foo': 'bar'},
                                  'DependsOn': 'dummy',
                                  'DeletionPolicy': 'dummy',
                                  'UpdatePolicy': {'foo': 'bar'}}}

        tmpl = template.Template(hot_tpl)
        self.assertEqual(expected, tmpl[tmpl.RESOURCES])

    def test_translate_resources_bad_no_data(self):
        """Test translation of resources without any mapping."""

        hot_tpl = template_format.parse("""
        heat_template_version: 2013-05-23
        resources:
          resource1:
        """)

        tmpl = template.Template(hot_tpl)
        error = self.assertRaises(exception.StackValidationFailed,
                                  tmpl.__getitem__, tmpl.RESOURCES)
        self.assertEqual('Each resource must contain a type key.',
                         six.text_type(error))

    def test_translate_resources_bad_type(self):
        """Test translation of resources including invalid keyword."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            Type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            depends_on: dummy
            deletion_policy: dummy
            update_policy:
              foo: bar
        ''')

        tmpl = template.Template(hot_tpl)
        err = self.assertRaises(exception.StackValidationFailed,
                                tmpl.__getitem__, tmpl.RESOURCES)
        self.assertEqual('"Type" is not a valid keyword '
                         'inside a resource definition',
                         six.text_type(err))

    def test_translate_resources_bad_properties(self):
        """Test translation of resources including invalid keyword."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            Properties:
              property1: value1
            metadata:
              foo: bar
            depends_on: dummy
            deletion_policy: dummy
            update_policy:
              foo: bar
        ''')

        tmpl = template.Template(hot_tpl)
        err = self.assertRaises(exception.StackValidationFailed,
                                tmpl.__getitem__, tmpl.RESOURCES)
        self.assertEqual('"Properties" is not a valid keyword '
                         'inside a resource definition',
                         six.text_type(err))

    def test_translate_resources_resources_without_name(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          type: AWS::EC2::Instance
          properties:
            property1: value1
          metadata:
            foo: bar
          depends_on: dummy
          deletion_policy: dummy
        ''')
        tmpl = template.Template(hot_tpl)
        error = self.assertRaises(exception.StackValidationFailed,
                                  tmpl.__getitem__, tmpl.RESOURCES)
        self.assertEqual('"resources" must contain a map of resource maps. '
                         'Found a [%s] instead' % six.text_type,
                         six.text_type(error))

    def test_translate_resources_bad_metadata(self):
        """Test translation of resources including invalid keyword."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            Metadata:
              foo: bar
            depends_on: dummy
            deletion_policy: dummy
            update_policy:
              foo: bar
        ''')

        tmpl = template.Template(hot_tpl)
        err = self.assertRaises(exception.StackValidationFailed,
                                tmpl.__getitem__, tmpl.RESOURCES)

        self.assertEqual('"Metadata" is not a valid keyword '
                         'inside a resource definition',
                         six.text_type(err))

    def test_translate_resources_bad_depends_on(self):
        """Test translation of resources including invalid keyword."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            DependsOn: dummy
            deletion_policy: dummy
            update_policy:
              foo: bar
        ''')

        tmpl = template.Template(hot_tpl)
        err = self.assertRaises(exception.StackValidationFailed,
                                tmpl.__getitem__, tmpl.RESOURCES)
        self.assertEqual('"DependsOn" is not a valid keyword '
                         'inside a resource definition',
                         six.text_type(err))

    def test_translate_resources_bad_deletion_policy(self):
        """Test translation of resources including invalid keyword."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            depends_on: dummy
            DeletionPolicy: dummy
            update_policy:
              foo: bar
        ''')

        tmpl = template.Template(hot_tpl)
        err = self.assertRaises(exception.StackValidationFailed,
                                tmpl.__getitem__, tmpl.RESOURCES)
        self.assertEqual('"DeletionPolicy" is not a valid keyword '
                         'inside a resource definition',
                         six.text_type(err))

    def test_translate_resources_bad_update_policy(self):
        """Test translation of resources including invalid keyword."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            depends_on: dummy
            deletion_policy: dummy
            UpdatePolicy:
              foo: bar
        ''')

        tmpl = template.Template(hot_tpl)
        err = self.assertRaises(exception.StackValidationFailed,
                                tmpl.__getitem__, tmpl.RESOURCES)
        self.assertEqual('"UpdatePolicy" is not a valid keyword '
                         'inside a resource definition',
                         six.text_type(err))

    def test_get_outputs_good(self):
        """Test get outputs."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        outputs:
          output1:
            description: output1
            value: value1
        ''')

        expected = {'output1': {'description': 'output1', 'value': 'value1'}}

        tmpl = template.Template(hot_tpl)
        self.assertEqual(expected, tmpl[tmpl.OUTPUTS])

    def test_get_outputs_bad_no_data(self):
        """Test get outputs without any mapping."""

        hot_tpl = template_format.parse("""
        heat_template_version: 2013-05-23
        outputs:
          output1:
        """)

        tmpl = template.Template(hot_tpl)
        error = self.assertRaises(exception.StackValidationFailed,
                                  tmpl.__getitem__, tmpl.OUTPUTS)
        self.assertEqual('Each output must contain a value key.',
                         six.text_type(error))

    def test_get_outputs_bad_without_name(self):
        """Test get outputs without name."""

        hot_tpl = template_format.parse("""
        heat_template_version: 2013-05-23
        outputs:
          description: wrong output
          value: value1
        """)

        tmpl = template.Template(hot_tpl)
        error = self.assertRaises(exception.StackValidationFailed,
                                  tmpl.__getitem__, tmpl.OUTPUTS)
        self.assertEqual('"outputs" must contain a map of output maps. '
                         'Found a [%s] instead' % six.text_type,
                         six.text_type(error))

    def test_get_outputs_bad_description(self):
        """Test get outputs with bad description name."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        outputs:
          output1:
            Description: output1
            value: value1
        ''')

        tmpl = template.Template(hot_tpl)
        err = self.assertRaises(exception.StackValidationFailed,
                                tmpl.__getitem__, tmpl.OUTPUTS)
        self.assertIn('Description', six.text_type(err))

    def test_get_outputs_bad_value(self):
        """Test get outputs with bad value name."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        outputs:
          output1:
            description: output1
            Value: value1
        ''')

        tmpl = template.Template(hot_tpl)
        err = self.assertRaises(exception.StackValidationFailed,
                                tmpl.__getitem__, tmpl.OUTPUTS)
        self.assertIn('Value', six.text_type(err))

    def test_resource_group_list_join(self):
        """Test list_join on a ResourceGroup's inner attributes

        This should not fail during validation (i.e. before the ResourceGroup
        can return the list of the runtime values.
        """
        hot_tpl = template_format.parse('''
        heat_template_version: 2014-10-16
        resources:
          rg:
            type: OS::Heat::ResourceGroup
            properties:
              count: 3
              resource_def:
                type: OS::Nova::Server
        ''')
        tmpl = template.Template(hot_tpl)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        snippet = {'list_join': ["\n", {'get_attr': ['rg', 'name']}]}
        self.assertEqual('', self.resolve(snippet, tmpl, stack))
        # test list_join for liberty template
        hot_tpl['heat_template_version'] = '2015-10-15'
        tmpl = template.Template(hot_tpl)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        snippet = {'list_join': ["\n", {'get_attr': ['rg', 'name']}]}
        self.assertEqual('', self.resolve(snippet, tmpl, stack))
        # test list join again and update to multiple lists
        snippet = {'list_join': ["\n",
                                 {'get_attr': ['rg', 'name']},
                                 {'get_attr': ['rg', 'name']}]}
        self.assertEqual('', self.resolve(snippet, tmpl, stack))

    def test_deletion_policy_titlecase(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2016-10-14
        resources:
          del:
            type: OS::Heat::None
            deletion_policy: Delete
          ret:
            type: OS::Heat::None
            deletion_policy: Retain
          snap:
            type: OS::Heat::None
            deletion_policy: Snapshot
        ''')

        rsrc_defns = template.Template(hot_tpl).resource_definitions(None)

        self.assertEqual(rsrc_defn.ResourceDefinition.DELETE,
                         rsrc_defns['del'].deletion_policy())
        self.assertEqual(rsrc_defn.ResourceDefinition.RETAIN,
                         rsrc_defns['ret'].deletion_policy())
        self.assertEqual(rsrc_defn.ResourceDefinition.SNAPSHOT,
                         rsrc_defns['snap'].deletion_policy())

    def test_deletion_policy(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2016-10-14
        resources:
          del:
            type: OS::Heat::None
            deletion_policy: delete
          ret:
            type: OS::Heat::None
            deletion_policy: retain
          snap:
            type: OS::Heat::None
            deletion_policy: snapshot
        ''')

        rsrc_defns = template.Template(hot_tpl).resource_definitions(None)

        self.assertEqual(rsrc_defn.ResourceDefinition.DELETE,
                         rsrc_defns['del'].deletion_policy())
        self.assertEqual(rsrc_defn.ResourceDefinition.RETAIN,
                         rsrc_defns['ret'].deletion_policy())
        self.assertEqual(rsrc_defn.ResourceDefinition.SNAPSHOT,
                         rsrc_defns['snap'].deletion_policy())

    def test_str_replace(self):
        """Test str_replace function."""

        snippet = {'str_replace': {'template': 'Template var1 string var2',
                                   'params': {'var1': 'foo', 'var2': 'bar'}}}
        snippet_resolved = 'Template foo string bar'

        tmpl = template.Template(hot_tpl_empty)

        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_replace_map_param(self):
        """Test old str_replace function with non-string map param."""

        snippet = {'str_replace': {'template': 'jsonvar1',
                                   'params': {'jsonvar1': {'foo': 123}}}}

        tmpl = template.Template(hot_tpl_empty)
        ex = self.assertRaises(TypeError, self.resolve, snippet, tmpl)
        self.assertIn('"str_replace" params must be strings or numbers, '
                      'param jsonvar1 is not valid', six.text_type(ex))

    def test_liberty_str_replace_map_param(self):
        """Test str_replace function with non-string map param."""

        snippet = {'str_replace': {'template': 'jsonvar1',
                                   'params': {'jsonvar1': {'foo': 123}}}}
        snippet_resolved = '{"foo": 123}'

        tmpl = template.Template(hot_liberty_tpl_empty)
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_replace_list_param(self):
        """Test old str_replace function with non-string list param."""

        snippet = {'str_replace': {'template': 'listvar1',
                                   'params': {'listvar1': ['foo', 123]}}}

        tmpl = template.Template(hot_tpl_empty)
        ex = self.assertRaises(TypeError, self.resolve, snippet, tmpl)
        self.assertIn('"str_replace" params must be strings or numbers, '
                      'param listvar1 is not valid', six.text_type(ex))

    def test_liberty_str_replace_list_param(self):
        """Test str_replace function with non-string param."""

        snippet = {'str_replace': {'template': 'listvar1',
                                   'params': {'listvar1': ['foo', 123]}}}
        snippet_resolved = '["foo", 123]'

        tmpl = template.Template(hot_liberty_tpl_empty)
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_replace_number(self):
        """Test str_replace function with numbers."""

        snippet = {'str_replace': {'template': 'Template number string bar',
                                   'params': {'number': 1}}}
        snippet_resolved = 'Template 1 string bar'

        tmpl = template.Template(hot_tpl_empty)

        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_fn_replace(self):
        """Test Fn:Replace function."""

        snippet = {'Fn::Replace': [{'$var1': 'foo', '$var2': 'bar'},
                                   'Template $var1 string $var2']}
        snippet_resolved = 'Template foo string bar'

        tmpl = template.Template(hot_tpl_empty)

        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_replace_order(self):
        """Test str_replace function substitution order."""

        snippet = {'str_replace': {'template': '1234567890',
                                   'params': {'1': 'a',
                                              '12': 'b',
                                              '123': 'c',
                                              '1234': 'd',
                                              '12345': 'e',
                                              '123456': 'f',
                                              '1234567': 'g'}}}

        tmpl = template.Template(hot_tpl_empty)

        self.assertEqual('g890', self.resolve(snippet, tmpl))

    def test_str_replace_single_pass(self):
        """Test that str_replace function does not do double substitution."""

        snippet = {'str_replace': {'template': '1234567890',
                                   'params': {'1': 'a',
                                              '4': 'd',
                                              '8': 'h',
                                              '9': 'i',
                                              '123': '1',
                                              '456': '4',
                                              '890': '8',
                                              '90': '9'}}}

        tmpl = template.Template(hot_tpl_empty)

        self.assertEqual('1478', self.resolve(snippet, tmpl))

    def test_str_replace_sort_order(self):
        """Test str_replace function replacement order."""

        snippet = {'str_replace': {'template': '9876543210',
                                   'params': {'987654': 'a',
                                              '876543': 'b',
                                              '765432': 'c',
                                              '654321': 'd',
                                              '543210': 'e'}}}

        tmpl = template.Template(hot_tpl_empty)

        self.assertEqual('9876e', self.resolve(snippet, tmpl))

    def test_str_replace_syntax(self):
        """Test str_replace function syntax.

        Pass wrong syntax (array instead of dictionary) to function and
        validate that we get a TypeError.
        """

        snippet = {'str_replace': [{'template': 'Template var1 string var2'},
                                   {'params': {'var1': 'foo', 'var2': 'bar'}}]}

        tmpl = template.Template(hot_tpl_empty)

        self.assertRaises(exception.StackValidationFailed,
                          self.resolve, snippet, tmpl)

    def test_str_replace_missing_param(self):
        """Test str_replace function missing param is OK."""

        snippet = {'str_replace':
                   {'template': 'Template var1 string var2',
                    'params': {'var1': 'foo', 'var2': 'bar',
                               'var3': 'zed'}}}
        snippet_resolved = 'Template foo string bar'

        # older template uses Replace, newer templates use ReplaceJson.
        # test both.
        for hot_tpl in (hot_tpl_empty, hot_ocata_tpl_empty):
            tmpl = template.Template(hot_tpl)
            self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_replace_strict_no_missing_param(self):
        """Test str_replace_strict function no missing params, no problem."""

        snippet = {'str_replace_strict':
                   {'template': 'Template var1 var1 s var2 t varvarvar3',
                    'params': {'var1': 'foo', 'var2': 'bar',
                               'var3': 'zed', 'var': 'tricky '}}}
        snippet_resolved = 'Template foo foo s bar t tricky tricky zed'

        tmpl = template.Template(hot_ocata_tpl_empty)
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_replace_strict_missing_param(self):
        """Test str_replace_strict function missing param(s) raises error."""

        snippet = {'str_replace_strict':
                   {'template': 'Template var1 string var2',
                    'params': {'var1': 'foo', 'var2': 'bar',
                               'var3': 'zed'}}}

        tmpl = template.Template(hot_ocata_tpl_empty)
        ex = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
        self.assertEqual('The following params were not found in the '
                         'template: var3', six.text_type(ex))

        snippet = {'str_replace_strict':
                   {'template': 'Template var1 string var2',
                    'params': {'var1': 'foo', 'var2': 'bar',
                               'var0': 'zed'}}}

        ex = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
        self.assertEqual('The following params were not found in the '
                         'template: var0', six.text_type(ex))

        # str_replace_vstrict has same behaviour
        snippet = {'str_replace_vstrict':
                   {'template': 'Template var1 string var2',
                    'params': {'var1': 'foo', 'var2': 'bar',
                               'var0': 'zed', 'var': 'z',
                               'longvarname': 'q'}}}

        tmpl = template.Template(hot_pike_tpl_empty)
        ex = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
        self.assertEqual('The following params were not found in the '
                         'template: longvarname,var0,var', six.text_type(ex))

    def test_str_replace_strict_empty_param_ok(self):
        """Test str_replace_strict function with empty params."""

        snippet = {'str_replace_strict':
                   {'template': 'Template var1 string var2',
                    'params': {'var1': 'foo', 'var2': ''}}}

        tmpl = template.Template(hot_ocata_tpl_empty)
        self.assertEqual('Template foo string ', self.resolve(snippet, tmpl))

    def test_str_replace_vstrict_empty_param_not_ok(self):
        """Test str_replace_vstrict function with empty params.

        Raise ValueError when any of the params are None or empty.
        """

        snippet = {'str_replace_vstrict':
                   {'template': 'Template var1 string var2',
                    'params': {'var1': 'foo', 'var2': ''}}}

        tmpl = template.Template(hot_pike_tpl_empty)
        for val in (None, '', {}, []):
            snippet['str_replace_vstrict']['params']['var2'] = val
            ex = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
            self.assertIn('str_replace_vstrict has an undefined or empty '
                          'value for param var2', six.text_type(ex))

    def test_str_replace_invalid_param_keys(self):
        """Test str_replace function parameter keys.

        Pass wrong parameters to function and verify that we get
        a KeyError.
        """

        snippet = {'str_replace': {'tmpl': 'Template var1 string var2',
                                   'params': {'var1': 'foo', 'var2': 'bar'}}}

        tmpl = template.Template(hot_tpl_empty)

        self.assertRaises(exception.StackValidationFailed,
                          self.resolve, snippet, tmpl)

        snippet = {'str_replace': {'tmpl': 'Template var1 string var2',
                                   'parms': {'var1': 'foo', 'var2': 'bar'}}}

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.resolve, snippet, tmpl)
        self.assertIn('"str_replace" syntax should be str_replace:\\n',
                      six.text_type(ex))

    def test_str_replace_strict_invalid_param_keys(self):
        """Test str_replace function parameter keys.

        Pass wrong parameters to function and verify that we get
        a KeyError.
        """

        snippets = [{'str_replace_strict':
                    {'t': 'Template var1 string var2',
                     'params': {'var1': 'foo', 'var2': 'bar'}}},
                    {'str_replace_strict':
                    {'template': 'Template var1 string var2',
                     'param': {'var1': 'foo', 'var2': 'bar'}}}]

        for snippet in snippets:
            tmpl = template.Template(hot_ocata_tpl_empty)
            ex = self.assertRaises(exception.StackValidationFailed,
                                   self.resolve, snippet, tmpl)
        self.assertIn('"str_replace_strict" syntax should be '
                      'str_replace_strict:\\n', six.text_type(ex))

    def test_str_replace_invalid_param_types(self):
        """Test str_replace function parameter values.

        Pass parameter values of wrong type to function and verify that we get
        a TypeError.
        """

        snippet = {'str_replace': {'template': 12345,
                                   'params': {'var1': 'foo', 'var2': 'bar'}}}

        tmpl = template.Template(hot_tpl_empty)

        self.assertRaises(TypeError, self.resolve, snippet, tmpl)

        snippet = {'str_replace': {'template': 'Template var1 string var2',
                                   'params': ['var1', 'foo', 'var2', 'bar']}}

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.resolve, snippet, tmpl)
        self.assertIn('str_replace: "str_replace" parameters must be a'
                      ' mapping', six.text_type(ex))

    def test_str_replace_invalid_param_type_init(self):
        """Test str_replace function parameter values.

        Pass parameter values of wrong type to function and verify that we get
        a TypeError in the constructor.
        """
        args = [['var1', 'foo', 'var2', 'bar'],
                'Template var1 string var2']
        ex = self.assertRaises(
            TypeError,
            cfn_functions.Replace,
            None, 'Fn::Replace', args)
        self.assertIn('parameters must be a mapping', six.text_type(ex))

    def test_str_replace_ref_get_param(self):
        """Test str_replace referencing parameters."""
        hot_tpl = template_format.parse('''
        heat_template_version: 2015-04-30
        parameters:
          p_template:
            type: string
            default: foo-replaceme
          p_params:
            type: json
            default:
              replaceme: success
        resources:
          rsrc:
            type: ResWithStringPropAndAttr
            properties:
              a_string:
                str_replace:
                  template: {get_param: p_template}
                  params: {get_param: p_params}
        outputs:
          replaced:
            value: {get_attr: [rsrc, string]}
        ''')
        tmpl = template.Template(hot_tpl)
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.stack._update_all_resource_data(False, True)
        self.assertEqual('foo-success',
                         self.stack.outputs['replaced'].get_value())

    def test_get_file(self):
        """Test get_file function."""

        snippet = {'get_file': 'file:///tmp/foo.yaml'}
        snippet_resolved = 'foo contents'

        tmpl = template.Template(hot_tpl_empty, files={
            'file:///tmp/foo.yaml': 'foo contents'
        })
        stack = parser.Stack(utils.dummy_context(), 'param_id_test', tmpl)

        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl, stack))

    def test_get_file_not_string(self):
        """Test get_file function with non-string argument."""

        snippet = {'get_file': ['file:///tmp/foo.yaml']}
        tmpl = template.Template(hot_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'param_id_test', tmpl)
        notStrErr = self.assertRaises(TypeError, self.resolve,
                                      snippet, tmpl, stack)
        self.assertEqual(
            'Argument to "get_file" must be a string',
            six.text_type(notStrErr))

    def test_get_file_missing_files(self):
        """Test get_file function with no matching key in files section."""

        snippet = {'get_file': 'file:///tmp/foo.yaml'}

        tmpl = template.Template(hot_tpl_empty, files={
            'file:///tmp/bar.yaml': 'bar contents'
        })
        stack = parser.Stack(utils.dummy_context(), 'param_id_test', tmpl)

        missingErr = self.assertRaises(ValueError, self.resolve,
                                       snippet, tmpl, stack)
        self.assertEqual(
            ('No content found in the "files" section for '
             'get_file path: file:///tmp/foo.yaml'),
            six.text_type(missingErr))

    def test_get_file_nested_does_not_resolve(self):
        """Test get_file function does not resolve nested calls."""
        snippet = {'get_file': 'file:///tmp/foo.yaml'}
        snippet_resolved = '{get_file: file:///tmp/bar.yaml}'

        tmpl = template.Template(hot_tpl_empty, files={
            'file:///tmp/foo.yaml': snippet_resolved,
            'file:///tmp/bar.yaml': 'bar content',
        })
        stack = parser.Stack(utils.dummy_context(), 'param_id_test', tmpl)

        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl, stack))

    def test_list_join(self):
        snippet = {'list_join': [',', ['bar', 'baz']]}
        snippet_resolved = 'bar,baz'
        tmpl = template.Template(hot_kilo_tpl_empty)
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_join_multiple(self):
        snippet = {'list_join': [',', ['bar', 'baz'], ['bar2', 'baz2']]}
        snippet_resolved = 'bar,baz,bar2,baz2'
        tmpl = template.Template(hot_liberty_tpl_empty)
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_list_join_empty_list(self):
        snippet = {'list_join': [',', []]}
        snippet_resolved = ''
        k_tmpl = template.Template(hot_kilo_tpl_empty)
        self.assertEqual(snippet_resolved, self.resolve(snippet, k_tmpl))
        l_tmpl = template.Template(hot_liberty_tpl_empty)
        self.assertEqual(snippet_resolved, self.resolve(snippet, l_tmpl))

    def test_join_json(self):
        snippet = {'list_join': [',', [{'foo': 'json'}, {'foo2': 'json2'}]]}
        snippet_resolved = '{"foo": "json"},{"foo2": "json2"}'
        l_tmpl = template.Template(hot_liberty_tpl_empty)
        self.assertEqual(snippet_resolved, self.resolve(snippet, l_tmpl))
        # old versions before liberty don't support to join json
        k_tmpl = template.Template(hot_kilo_tpl_empty)
        exc = self.assertRaises(TypeError, self.resolve, snippet, k_tmpl)
        self.assertEqual("Items to join must be strings not {'foo': 'json'}",
                         six.text_type(exc))

    def test_join_object_type_fail(self):
        not_serializable = object
        snippet = {'list_join': [',', [not_serializable]]}
        l_tmpl = template.Template(hot_liberty_tpl_empty)
        exc = self.assertRaises(TypeError, self.resolve, snippet, l_tmpl)
        self.assertIn('Items to join must be string, map or list not',
                      six.text_type(exc))
        k_tmpl = template.Template(hot_kilo_tpl_empty)
        exc = self.assertRaises(TypeError, self.resolve, snippet, k_tmpl)
        self.assertIn("Items to join must be strings", six.text_type(exc))

    def test_join_json_fail(self):
        not_serializable = object
        snippet = {'list_join': [',', [{'foo': not_serializable}]]}
        l_tmpl = template.Template(hot_liberty_tpl_empty)
        exc = self.assertRaises(TypeError, self.resolve, snippet, l_tmpl)
        self.assertIn('Items to join must be string, map or list',
                      six.text_type(exc))
        self.assertIn("failed json serialization",
                      six.text_type(exc))

    def test_join_invalid(self):
        snippet = {'list_join': 'bad'}
        l_tmpl = template.Template(hot_liberty_tpl_empty)
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve, snippet, l_tmpl)
        self.assertIn('list_join: Incorrect arguments to "list_join"',
                      six.text_type(exc))

        k_tmpl = template.Template(hot_kilo_tpl_empty)
        exc1 = self.assertRaises(exception.StackValidationFailed,
                                 self.resolve, snippet, k_tmpl)
        self.assertIn('list_join: Incorrect arguments to "list_join"',
                      six.text_type(exc1))

    def test_join_int_invalid(self):
        snippet = {'list_join': 5}
        l_tmpl = template.Template(hot_liberty_tpl_empty)
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve, snippet, l_tmpl)
        self.assertIn('list_join: Incorrect arguments', six.text_type(exc))

        k_tmpl = template.Template(hot_kilo_tpl_empty)
        exc1 = self.assertRaises(exception.StackValidationFailed,
                                 self.resolve, snippet, k_tmpl)
        self.assertIn('list_join: Incorrect arguments', six.text_type(exc1))

    def test_join_invalid_value(self):
        snippet = {'list_join': [',']}
        l_tmpl = template.Template(hot_liberty_tpl_empty)
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve, snippet, l_tmpl)
        self.assertIn('list_join: Incorrect arguments to "list_join"',
                      six.text_type(exc))

        k_tmpl = template.Template(hot_kilo_tpl_empty)
        exc1 = self.assertRaises(exception.StackValidationFailed,
                                 self.resolve, snippet, k_tmpl)
        self.assertIn('list_join: Incorrect arguments to "list_join"',
                      six.text_type(exc1))

    def test_join_invalid_multiple(self):
        snippet = {'list_join': [',', 'bad', ['foo']]}
        tmpl = template.Template(hot_liberty_tpl_empty)
        exc = self.assertRaises(TypeError, self.resolve, snippet, tmpl)
        self.assertIn('must operate on a list', six.text_type(exc))

    def test_merge(self):
        snippet = {'map_merge': [{'f1': 'b1', 'f2': 'b2'}, {'f1': 'b2'}]}
        tmpl = template.Template(hot_mitaka_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual('b2', resolved['f1'])
        self.assertEqual('b2', resolved['f2'])

    def test_merge_none(self):
        snippet = {'map_merge': [{'f1': 'b1', 'f2': 'b2'}, None]}
        tmpl = template.Template(hot_mitaka_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual('b1', resolved['f1'])
        self.assertEqual('b2', resolved['f2'])

    def test_merge_invalid(self):
        snippet = {'map_merge': [{'f1': 'b1', 'f2': 'b2'}, ['f1', 'b2']]}
        tmpl = template.Template(hot_mitaka_tpl_empty)
        exc = self.assertRaises(TypeError, self.resolve, snippet, tmpl)
        self.assertIn('Incorrect arguments', six.text_type(exc))

    def test_merge_containing_repeat(self):
        snippet = {'map_merge': {'repeat': {'template': {'ROLE': 'ROLE'},
                   'for_each': {'ROLE': ['role1', 'role2']}}}}
        tmpl = template.Template(hot_mitaka_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('role1', resolved['role1'])
        self.assertEqual('role2', resolved['role2'])

    def test_merge_containing_repeat_with_none(self):
        snippet = {'map_merge': {'repeat': {'template': {'ROLE': 'ROLE'},
                   'for_each': {'ROLE': None}}}}
        tmpl = template.Template(hot_mitaka_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual({}, resolved)

    def test_merge_containing_repeat_multi_list_no_nested_loop_with_none(self):
        snippet = {'map_merge': {'repeat': {
            'template': {'ROLE': 'ROLE', 'NAME': 'NAME'},
            'for_each': {'ROLE': None, 'NAME': ['n1', 'n2']},
            'permutations': False}}}
        tmpl = template.Template(hot_mitaka_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual({}, resolved)

    def test_merge_containing_repeat_multi_list_no_nested_loop_all_none(self):
        snippet = {'map_merge': {'repeat': {
            'template': {'ROLE': 'ROLE', 'NAME': 'NAME'},
            'for_each': {'ROLE': None, 'NAME': None},
            'permutations': False}}}
        tmpl = template.Template(hot_mitaka_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual({}, resolved)

    def test_map_replace(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'},
                                   {'keys': {'f1': 'F1'},
                                    'values': {'b2': 'B2'}}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual({'F1': 'b1', 'f2': 'B2'},
                         resolved)

    def test_map_replace_nokeys(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'},
                                   {'values': {'b2': 'B2'}}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual({'f1': 'b1', 'f2': 'B2'},
                         resolved)

    def test_map_replace_novalues(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'},
                                   {'keys': {'f2': 'F2'}}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual({'f1': 'b1', 'F2': 'b2'},
                         resolved)

    def test_map_replace_keys_collide_ok_equal(self):
        # It's OK to replace a key with the same value
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'},
                                   {'keys': {'f2': 'f2'}}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual({'f1': 'b1', 'f2': 'b2'},
                         resolved)

    def test_map_replace_none_values(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'},
                                   {'values': None}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual({'f1': 'b1', 'f2': 'b2'},
                         resolved)

    def test_map_replace_none_keys(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'},
                                   {'keys': None}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual({'f1': 'b1', 'f2': 'b2'},
                         resolved)

    def test_map_replace_unhashable_value(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': []},
                                   {'values': {}}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual({'f1': 'b1', 'f2': []},
                         resolved)

    def test_map_replace_keys_collide(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'},
                                   {'keys': {'f2': 'f1'}}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        msg = "key replacement f1 collides with a key in the input map"
        self.assertRaisesRegex(ValueError, msg, self.resolve, snippet, tmpl)

    def test_map_replace_replaced_keys_collide(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'},
                                   {'keys': {'f1': 'f3', 'f2': 'f3'}}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        msg = "key replacement f3 collides with a key in the output map"
        self.assertRaisesRegex(ValueError, msg, self.resolve, snippet, tmpl)

    def test_map_replace_invalid_str_arg1(self):
        snippet = {'map_replace': 'ab'}
        tmpl = template.Template(hot_newton_tpl_empty)
        msg = "Incorrect arguments to \"map_replace\" should be:"
        self.assertRaisesRegex(TypeError, msg, self.resolve, snippet, tmpl)

    def test_map_replace_invalid_str_arg2(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'}, "ab"]}
        tmpl = template.Template(hot_newton_tpl_empty)
        msg = ("Incorrect arguments: to \"map_replace\", "
               "arguments must be a list of maps")
        self.assertRaisesRegex(TypeError, msg, self.resolve, snippet, tmpl)

    def test_map_replace_invalid_empty(self):
        snippet = {'map_replace': []}
        tmpl = template.Template(hot_newton_tpl_empty)
        msg = "Incorrect arguments to \"map_replace\" should be:"
        self.assertRaisesRegex(TypeError, msg, self.resolve, snippet, tmpl)

    def test_map_replace_invalid_missing1(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        msg = "Incorrect arguments to \"map_replace\" should be:"
        self.assertRaisesRegex(TypeError, msg, self.resolve, snippet, tmpl)

    def test_map_replace_invalid_missing2(self):
        snippet = {'map_replace': [{'keys': {'f1': 'f3', 'f2': 'f3'}}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        msg = "Incorrect arguments to \"map_replace\" should be:"
        self.assertRaisesRegex(TypeError, msg, self.resolve, snippet, tmpl)

    def test_map_replace_invalid_wrongkey(self):
        snippet = {'map_replace': [{'f1': 'b1', 'f2': 'b2'},
                                   {'notkeys': {'f2': 'F2'}}]}
        tmpl = template.Template(hot_newton_tpl_empty)
        msg = "Incorrect arguments to \"map_replace\" should be:"
        self.assertRaisesRegex(ValueError, msg, self.resolve, snippet, tmpl)

    def test_yaql(self):
        snippet = {'yaql': {'expression': '$.data.var1.sum()',
                            'data': {'var1': [1, 2, 3, 4]}}}
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        resolved = self.resolve(snippet, tmpl, stack=stack)

        self.assertEqual(10, resolved)

    def test_yaql_list_input(self):
        snippet = {'yaql': {'expression': '$.data.sum()',
                            'data': [1, 2, 3, 4]}}
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        resolved = self.resolve(snippet, tmpl, stack=stack)

        self.assertEqual(10, resolved)

    def test_yaql_string_input(self):
        snippet = {'yaql': {'expression': '$.data',
                            'data': 'whynotastring'}}
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        resolved = self.resolve(snippet, tmpl, stack=stack)

        self.assertEqual('whynotastring', resolved)

    def test_yaql_int_input(self):
        snippet = {'yaql': {'expression': '$.data + 2',
                            'data': 2}}
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        resolved = self.resolve(snippet, tmpl, stack=stack)

        self.assertEqual(4, resolved)

    def test_yaql_bogus_keys(self):
        snippet = {'yaql': {'expression': '1 + 3',
                            'data': {'var1': [1, 2, 3, 4]},
                            'bogus': ""}}
        tmpl = template.Template(hot_newton_tpl_empty)
        self.assertRaises(exception.StackValidationFailed,
                          self.resolve, snippet, tmpl)

    def test_yaql_invalid_syntax(self):
        snippet = {'yaql': {'wrong': 'wrong_expr',
                            'wrong_data': 'mustbeamap'}}
        tmpl = template.Template(hot_newton_tpl_empty)
        self.assertRaises(exception.StackValidationFailed,
                          self.resolve, snippet, tmpl)

    def test_yaql_non_map_args(self):
        snippet = {'yaql': 'invalid'}
        tmpl = template.Template(hot_newton_tpl_empty)
        msg = 'yaql: Arguments to "yaql" must be a map.'
        self.assertRaisesRegex(exception.StackValidationFailed,
                               msg, self.resolve, snippet, tmpl)

    def test_yaql_invalid_expression(self):
        snippet = {'yaql': {'expression': 'invalid(',
                   'data': {'var1': [1, 2, 3, 4]}}}
        tmpl = template.Template(hot_newton_tpl_empty)
        yaql = tmpl.parse(None, snippet)
        regxp = ('yaql: Bad expression Parse error: unexpected end '
                 'of statement.')
        self.assertRaisesRegex(exception.StackValidationFailed, regxp,
                               function.validate, yaql)

    def test_yaql_data_as_function(self):
        snippet = {'yaql': {'expression': '$.data.var1.len()',
                            'data': {'var1': {'list_join': ['', ['1', '2']]}}}}
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        resolved = self.resolve(snippet, tmpl, stack=stack)

        self.assertEqual(2, resolved)

    def test_yaql_merge(self):
        snippet = {'yaql': {'expression': '$.data.d.reduce($1.mergeWith($2))',
                            'data': {'d': [{'a': [1]}, {'a': [2]},
                                           {'a': [3]}]}}}
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        resolved = self.resolve(snippet, tmpl, stack=stack)

        self.assertEqual({'a': [1, 2, 3]}, resolved)

    def test_yaql_as_condition(self):
        hot_tpl = template_format.parse('''
        heat_template_version: pike
        parameters:
          ServiceNames:
            type: comma_delimited_list
            default: ['neutron', 'heat']
        ''')
        snippet = {
            'yaql': {
                'expression': '$.data.service_names.contains("neutron")',
                'data': {'service_names': {'get_param': 'ServiceNames'}}}}
        # when param 'ServiceNames' contains 'neutron',
        # equals function resolve to true
        tmpl = template.Template(hot_tpl)
        stack = parser.Stack(utils.dummy_context(),
                             'test_condition_yaql_true', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stack)
        self.assertTrue(resolved)
        # when param 'ServiceNames' doesn't contain 'neutron',
        # equals function resolve to false
        tmpl = template.Template(
            hot_tpl,
            env=environment.Environment(
                {'ServiceNames': ['nova_network', 'heat']}))
        stack = parser.Stack(utils.dummy_context(),
                             'test_condition_yaql_false', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stack)
        self.assertFalse(resolved)

    def test_equals(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2016-10-14
        parameters:
          env_type:
            type: string
            default: 'test'
        ''')
        snippet = {'equals': [{'get_param': 'env_type'}, 'prod']}
        # when param 'env_type' is 'test', equals function resolve to false
        tmpl = template.Template(hot_tpl)
        stack = parser.Stack(utils.dummy_context(),
                             'test_equals_false', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stack)
        self.assertFalse(resolved)
        # when param 'env_type' is 'prod', equals function resolve to true
        tmpl = template.Template(hot_tpl,
                                 env=environment.Environment(
                                     {'env_type': 'prod'}))
        stack = parser.Stack(utils.dummy_context(),
                             'test_equals_true', tmpl)
        resolved = self.resolve_condition(snippet, tmpl, stack)
        self.assertTrue(resolved)

    def test_equals_invalid_args(self):
        tmpl = template.Template(hot_newton_tpl_empty)

        snippet = {'equals': ['test', 'prod', 'invalid']}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)

        error_msg = ('equals: Arguments to "equals" must be '
                     'of the form: [value_1, value_2]')
        self.assertIn(error_msg, six.text_type(exc))

        snippet = {'equals': "invalid condition"}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)
        self.assertIn(error_msg, six.text_type(exc))

    def test_equals_with_non_supported_function(self):

        tmpl = template.Template(hot_newton_tpl_empty)

        snippet = {'equals': [{'get_attr': [None, 'att1']},
                              {'get_attr': [None, 'att2']}]}
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve_condition, snippet, tmpl)
        self.assertIn('"get_attr" is invalid', six.text_type(exc))

    def test_if(self):
        snippet = {'if': ['create_prod', 'value_if_true', 'value_if_false']}
        # when condition evaluates to true, if function
        # resolve to value_if_true
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(),
                             'test_if_function', tmpl)
        with mock.patch.object(tmpl, 'conditions') as conds:
            conds.return_value = conditions.Conditions({'create_prod': True})
            resolved = self.resolve(snippet, tmpl, stack)
            self.assertEqual('value_if_true', resolved)
        # when condition evaluates to false, if function
        # resolve to value_if_false
        with mock.patch.object(tmpl, 'conditions') as conds:
            conds.return_value = conditions.Conditions({'create_prod': False})
            resolved = self.resolve(snippet, tmpl, stack)
            self.assertEqual('value_if_false', resolved)

    def test_if_using_boolean_condition(self):
        snippet = {'if': [True, 'value_if_true', 'value_if_false']}
        # when condition is true, if function resolve to value_if_true
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(),
                             'test_if_using_boolean_condition', tmpl)
        resolved = self.resolve(snippet, tmpl, stack)
        self.assertEqual('value_if_true', resolved)
        # when condition is false, if function resolve to value_if_false
        snippet = {'if': [False, 'value_if_true', 'value_if_false']}
        resolved = self.resolve(snippet, tmpl, stack)
        self.assertEqual('value_if_false', resolved)

    def test_if_null_return(self):
        snippet = {'if': [True, None, 'value_if_false']}
        # when condition is true, if function resolve to value_if_true
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(),
                             'test_if_null_return', tmpl)
        resolved = self.resolve(snippet, tmpl, stack)
        self.assertIsNone(resolved)

    def test_if_using_condition_function(self):
        tmpl_with_conditions = template_format.parse('''
heat_template_version: 2016-10-14
conditions:
  create_prod: False
''')
        snippet = {'if': [{'not': 'create_prod'},
                          'value_if_true', 'value_if_false']}

        tmpl = template.Template(tmpl_with_conditions)
        stack = parser.Stack(utils.dummy_context(),
                             'test_if_using_condition_function', tmpl)

        resolved = self.resolve(snippet, tmpl, stack)
        self.assertEqual('value_if_true', resolved)

    def test_if_referenced_by_resource(self):
        tmpl_with_conditions = template_format.parse('''
heat_template_version: pike
conditions:
  create_prod: False
resources:
  AResource:
    type: ResourceWithPropsType
    properties:
      Foo:
        if:
          - create_prod
          - "one"
          - "two"
''')
        tmpl = template.Template(tmpl_with_conditions)
        self.stack = parser.Stack(utils.dummy_context(),
                                  'test_if_referenced_by_resource', tmpl)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('two', self.stack['AResource'].properties['Foo'])

    def test_if_referenced_by_resource_null(self):
        tmpl_with_conditions = template_format.parse('''
heat_template_version: pike
conditions:
  create_prod: True
resources:
  AResource:
    type: ResourceWithPropsType
    properties:
      Foo:
        if:
          - create_prod
          - null
          - "two"
''')
        tmpl = template.Template(tmpl_with_conditions)
        self.stack = parser.Stack(utils.dummy_context(),
                                  'test_if_referenced_by_resource_null', tmpl)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('', self.stack['AResource'].properties['Foo'])

    def test_if_invalid_args(self):
        snippet = {'if': ['create_prod', 'one_value']}
        tmpl = template.Template(hot_newton_tpl_empty)
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve, snippet, tmpl)
        self.assertIn('Arguments to "if" must be of the form: '
                      '[condition_name, value_if_true, value_if_false]',
                      six.text_type(exc))

    def test_if_condition_name_non_existing(self):
        snippet = {'if': ['cd_not_existing', 'value_true', 'value_false']}
        tmpl = template.Template(hot_newton_tpl_empty)
        stack = parser.Stack(utils.dummy_context(),
                             'test_if_function', tmpl)
        with mock.patch.object(tmpl, 'conditions') as conds:
            conds.return_value = conditions.Conditions({'create_prod': True})
            exc = self.assertRaises(exception.StackValidationFailed,
                                    self.resolve, snippet, tmpl, stack)
        self.assertIn('Invalid condition "cd_not_existing"',
                      six.text_type(exc))
        self.assertIn('if:', six.text_type(exc))

    def _test_repeat(self, templ=hot_kilo_tpl_empty):
        """Test repeat function."""
        snippet = {'repeat': {'template': 'this is %var%',
                              'for_each': {'%var%': ['a', 'b', 'c']}}}
        snippet_resolved = ['this is a', 'this is b', 'this is c']

        tmpl = template.Template(templ)

        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_repeat(self):
        self._test_repeat()

    def test_repeat_with_pike_version(self):
        self._test_repeat(templ=hot_pike_tpl_empty)

    def test_repeat_get_param(self):
        """Test repeat function with get_param function as an argument."""
        hot_tpl = template_format.parse('''
        heat_template_version: 2015-04-30
        parameters:
          param:
            type: comma_delimited_list
            default: 'a,b,c'
        ''')
        snippet = {'repeat': {'template': 'this is var%',
                   'for_each': {'var%': {'get_param': 'param'}}}}
        snippet_resolved = ['this is a', 'this is b', 'this is c']

        tmpl = template.Template(hot_tpl)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)

        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl, stack))

    def _test_repeat_dict_with_no_replacement(self,
                                              templ=hot_newton_tpl_empty):
        snippet = {'repeat': {'template': {'SERVICE_enabled': True},
                              'for_each': {'SERVICE': ['x', 'y', 'z']}}}
        snippet_resolved = [{'x_enabled': True},
                            {'y_enabled': True},
                            {'z_enabled': True}]
        tmpl = template.Template(templ)
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_repeat_dict_with_no_replacement(self):
        self._test_repeat_dict_with_no_replacement()

    def test_repeat_dict_with_no_replacement_pike_version(self):
        self._test_repeat_dict_with_no_replacement(templ=hot_pike_tpl_empty)

    def _test_repeat_dict_template(self, templ=hot_kilo_tpl_empty):
        """Test repeat function with a dictionary as a template."""
        snippet = {'repeat': {'template': {'key-%var%': 'this is %var%'},
                              'for_each': {'%var%': ['a', 'b', 'c']}}}
        snippet_resolved = [{'key-a': 'this is a'},
                            {'key-b': 'this is b'},
                            {'key-c': 'this is c'}]

        tmpl = template.Template(templ)

        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_repeat_dict_template(self):
        self._test_repeat_dict_template()

    def test_repeat_dict_template_pike_version(self):
        self._test_repeat_dict_template(templ=hot_pike_tpl_empty)

    def _test_repeat_list_template(self, templ=hot_kilo_tpl_empty):
        """Test repeat function with a list as a template."""
        snippet = {'repeat': {'template': ['this is %var%', 'static'],
                              'for_each': {'%var%': ['a', 'b', 'c']}}}
        snippet_resolved = [['this is a', 'static'],
                            ['this is b', 'static'],
                            ['this is c', 'static']]

        tmpl = template.Template(templ)

        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_repeat_list_template(self):
        self._test_repeat_list_template()

    def test_repeat_list_template_pike_version(self):
        self._test_repeat_list_template(templ=hot_pike_tpl_empty)

    def _test_repeat_multi_list(self, templ=hot_kilo_tpl_empty):
        """Test repeat function with multiple input lists."""
        snippet = {'repeat': {'template': 'this is %var1%-%var2%',
                              'for_each': {'%var1%': ['a', 'b', 'c'],
                                           '%var2%': ['1', '2']}}}
        snippet_resolved = ['this is a-1', 'this is b-1', 'this is c-1',
                            'this is a-2', 'this is b-2', 'this is c-2']

        tmpl = template.Template(templ)

        result = self.resolve(snippet, tmpl)
        self.assertEqual(len(result), len(snippet_resolved))
        for item in result:
            self.assertIn(item, snippet_resolved)

    def test_repeat_multi_list(self):
        self._test_repeat_multi_list()

    def test_repeat_multi_list_pike_version(self):
        self._test_repeat_multi_list(templ=hot_pike_tpl_empty)

    def test_repeat_list_and_map(self):
        """Test repeat function with a list and a map."""
        snippet = {'repeat': {'template': 'this is %var1%-%var2%',
                              'for_each': {'%var1%': ['a', 'b', 'c'],
                                           '%var2%': {'x': 'v', 'y': 'v'}}}}
        snippet_resolved = ['this is a-x', 'this is b-x', 'this is c-x',
                            'this is a-y', 'this is b-y', 'this is c-y']

        tmpl = template.Template(hot_newton_tpl_empty)

        result = self.resolve(snippet, tmpl)
        self.assertEqual(len(result), len(snippet_resolved))
        for item in result:
            self.assertIn(item, snippet_resolved)

    def test_repeat_with_no_nested_loop(self):
        snippet = {'repeat': {'template': {'network': '%net%',
                                           'port': '%port%',
                                           'subnet': '%sub%'},
                              'for_each': {'%net%': ['n1', 'n2', 'n3', 'n4'],
                                           '%port%': ['p1', 'p2', 'p3', 'p4'],
                                           '%sub%': ['s1', 's2', 's3', 's4']},
                              'permutations': False}}
        tmpl = template.Template(hot_pike_tpl_empty)
        snippet_resolved = [{'network': 'n1', 'port': 'p1', 'subnet': 's1'},
                            {'network': 'n2', 'port': 'p2', 'subnet': 's2'},
                            {'network': 'n3', 'port': 'p3', 'subnet': 's3'},
                            {'network': 'n4', 'port': 'p4', 'subnet': 's4'}]

        result = self.resolve(snippet, tmpl)
        self.assertEqual(snippet_resolved, result)

    def test_repeat_no_nested_loop_different_len(self):
        snippet = {'repeat': {'template': {'network': '%net%',
                                           'port': '%port%',
                                           'subnet': '%sub%'},
                              'for_each': {'%net%': ['n1', 'n2', 'n3'],
                                           '%port%': ['p1', 'p2'],
                                           '%sub%': ['s1', 's2']},
                              'permutations': False}}
        tmpl = template.Template(hot_pike_tpl_empty)
        self.assertRaises(ValueError, self.resolve, snippet, tmpl)

    def test_repeat_no_nested_loop_with_dict_type(self):
        snippet = {'repeat': {'template': {'network': '%net%',
                                           'port': '%port%',
                                           'subnet': '%sub%'},
                              'for_each': {'%net%': ['n1', 'n2'],
                                           '%port%': {'p1': 'pp', 'p2': 'qq'},
                                           '%sub%': ['s1', 's2']},
                              'permutations': False}}
        tmpl = template.Template(hot_pike_tpl_empty)
        self.assertRaises(TypeError, self.resolve, snippet, tmpl)

    def test_repeat_permutations_non_bool(self):
        snippet = {'repeat': {'template': {'network': '%net%',
                                           'port': '%port%',
                                           'subnet': '%sub%'},
                              'for_each': {'%net%': ['n1', 'n2'],
                                           '%port%': ['p1', 'p2'],
                                           '%sub%': ['s1', 's2']},
                              'permutations': 'non bool'}}
        tmpl = template.Template(hot_pike_tpl_empty)
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve, snippet, tmpl)
        self.assertIn('"permutations" should be boolean type '
                      'for repeat function', six.text_type(exc))

    def test_repeat_bad_args(self):
        """Tests reporting error by repeat function.

        Test that the repeat function reports a proper error when missing or
        invalid arguments.
        """
        tmpl = template.Template(hot_kilo_tpl_empty)

        # missing for_each
        snippet = {'repeat': {'template': 'this is %var%'}}
        self.assertRaises(exception.StackValidationFailed,
                          self.resolve, snippet, tmpl)

        # misspelled for_each
        snippet = {'repeat': {'template': 'this is %var%',
                              'foreach': {'%var%': ['a', 'b', 'c']}}}
        self.assertRaises(exception.StackValidationFailed,
                          self.resolve, snippet, tmpl)

        # misspelled template
        snippet = {'repeat': {'templte': 'this is %var%',
                              'for_each': {'%var%': ['a', 'b', 'c']}}}
        self.assertRaises(exception.StackValidationFailed,
                          self.resolve, snippet, tmpl)

    def test_repeat_bad_arg_type(self):
        tmpl = template.Template(hot_kilo_tpl_empty)

        # for_each is not a map
        snippet = {'repeat': {'template': 'this is %var%',
                              'for_each': '%var%'}}
        repeat = tmpl.parse(None, snippet)
        regxp = ('repeat: The "for_each" argument to "repeat" '
                 'must contain a map')
        self.assertRaisesRegex(exception.StackValidationFailed, regxp,
                               function.validate, repeat)

    def test_digest(self):
        snippet = {'digest': ['md5', 'foobar']}
        snippet_resolved = '3858f62230ac3c915f300c664312c63f'

        tmpl = template.Template(hot_kilo_tpl_empty)
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_digest_invalid_types(self):
        tmpl = template.Template(hot_kilo_tpl_empty)

        invalid_snippets = [
            {'digest': 'invalid'},
            {'digest': {'foo': 'invalid'}},
            {'digest': [123]},
        ]
        for snippet in invalid_snippets:
            exc = self.assertRaises(TypeError, self.resolve, snippet, tmpl)
            self.assertIn('must be a list of strings', six.text_type(exc))

    def test_digest_incorrect_number_arguments(self):
        tmpl = template.Template(hot_kilo_tpl_empty)

        invalid_snippets = [
            {'digest': []},
            {'digest': ['foo']},
            {'digest': ['md5']},
            {'digest': ['md5', 'foo', 'bar']},
        ]
        for snippet in invalid_snippets:
            exc = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
            self.assertIn('usage: ["<algorithm>", "<value>"]',
                          six.text_type(exc))

    def test_digest_invalid_algorithm(self):
        tmpl = template.Template(hot_kilo_tpl_empty)

        snippet = {'digest': ['invalid_algorithm', 'foobar']}
        exc = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
        self.assertIn('Algorithm must be one of', six.text_type(exc))

    def test_str_split(self):
        tmpl = template.Template(hot_liberty_tpl_empty)
        snippet = {'str_split': [',', 'bar,baz']}
        snippet_resolved = ['bar', 'baz']
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_split_index(self):
        tmpl = template.Template(hot_liberty_tpl_empty)
        snippet = {'str_split': [',', 'bar,baz', 1]}
        snippet_resolved = 'baz'
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_split_index_str(self):
        tmpl = template.Template(hot_liberty_tpl_empty)
        snippet = {'str_split': [',', 'bar,baz', '1']}
        snippet_resolved = 'baz'
        self.assertEqual(snippet_resolved, self.resolve(snippet, tmpl))

    def test_str_split_index_bad(self):
        tmpl = template.Template(hot_liberty_tpl_empty)
        snippet = {'str_split': [',', 'bar,baz', 'bad']}
        exc = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
        self.assertIn('Incorrect index to \"str_split\"', six.text_type(exc))

    def test_str_split_index_out_of_range(self):
        tmpl = template.Template(hot_liberty_tpl_empty)
        snippet = {'str_split': [',', 'bar,baz', '2']}
        exc = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
        expected = 'Incorrect index to \"str_split\" should be between 0 and 1'
        self.assertEqual(expected, six.text_type(exc))

    def test_str_split_bad_novalue(self):
        tmpl = template.Template(hot_liberty_tpl_empty)
        snippet = {'str_split': [',']}
        exc = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
        self.assertIn('Incorrect arguments to \"str_split\"',
                      six.text_type(exc))

    def test_str_split_bad_empty(self):
        tmpl = template.Template(hot_liberty_tpl_empty)
        snippet = {'str_split': []}
        exc = self.assertRaises(ValueError, self.resolve, snippet, tmpl)
        self.assertIn('Incorrect arguments to \"str_split\"',
                      six.text_type(exc))

    def test_str_split_none_string_to_split(self):
        tmpl = template.Template(hot_liberty_tpl_empty)
        snippet = {'str_split': ['.', None]}
        self.assertIsNone(self.resolve(snippet, tmpl))

    def test_str_split_none_delim(self):
        tmpl = template.Template(hot_liberty_tpl_empty)
        snippet = {'str_split': [None, 'check']}
        self.assertEqual(['check'], self.resolve(snippet, tmpl))

    def test_prevent_parameters_access(self):
        """Check parameters section inaccessible using the template as a dict.

        Test that the parameters section can't be accessed using the template
        as a dictionary.
        """
        expected_description = "This can be accessed"
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        description: {0}
        parameters:
          foo:
            type: string
        '''.format(expected_description))

        tmpl = template.Template(hot_tpl)
        self.assertEqual(expected_description, tmpl['description'])

        err_str = "can not be accessed directly"

        # Hot template test
        keyError = self.assertRaises(KeyError, tmpl.__getitem__, 'parameters')
        self.assertIn(err_str, six.text_type(keyError))

        # CFN template test
        keyError = self.assertRaises(KeyError, tmpl.__getitem__, 'Parameters')
        self.assertIn(err_str, six.text_type(keyError))

    def test_parameters_section_not_iterable(self):
        """Check parameters section is not returned using the template as iter.

        Test that the parameters section is not returned when the template is
        used as an iterable.
        """
        expected_description = "This can be accessed"
        tmpl = template.Template({'heat_template_version': '2013-05-23',
                                  'description': expected_description,
                                  'parameters':
                                  {'foo': {'Type': 'String',
                                           'Required': True}}})
        self.assertEqual(expected_description, tmpl['description'])
        self.assertNotIn('parameters', tmpl.keys())

    def test_invalid_hot_version(self):
        """Test HOT version check.

        Pass an invalid HOT version to template.Template.__new__() and
        validate that we get a ValueError.
        """

        tmpl_str = "heat_template_version: this-ain't-valid"
        hot_tmpl = template_format.parse(tmpl_str)
        self.assertRaises(exception.InvalidTemplateVersion,
                          template.Template, hot_tmpl)

    def test_valid_hot_version(self):
        """Test HOT version check.

        Pass a valid HOT version to template.Template.__new__() and
        validate that we get back a parsed template.
        """

        tmpl_str = "heat_template_version: 2013-05-23"
        hot_tmpl = template_format.parse(tmpl_str)
        parsed_tmpl = template.Template(hot_tmpl)
        expected = ('heat_template_version', '2013-05-23')
        observed = parsed_tmpl.version
        self.assertEqual(expected, observed)

    def test_resource_facade(self):
        metadata_snippet = {'resource_facade': 'metadata'}
        deletion_policy_snippet = {'resource_facade': 'deletion_policy'}
        update_policy_snippet = {'resource_facade': 'update_policy'}

        parent_resource = DummyClass()
        parent_resource.metadata_set({"foo": "bar"})
        parent_resource.t = rsrc_defn.ResourceDefinition(
            'parent', 'SomeType',
            deletion_policy=rsrc_defn.ResourceDefinition.RETAIN,
            update_policy={"blarg": "wibble"})
        tmpl = copy.deepcopy(hot_tpl_empty)
        tmpl['resources'] = {'parent': parent_resource.t.render_hot()}
        parent_resource.stack = parser.Stack(utils.dummy_context(),
                                             'toplevel_stack',
                                             template.Template(tmpl))
        parent_resource.stack._resources = {'parent': parent_resource}
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             template.Template(hot_tpl_empty),
                             parent_resource='parent')
        stack.set_parent_stack(parent_resource.stack)
        self.assertEqual({"foo": "bar"},
                         self.resolve(metadata_snippet, stack.t, stack))
        self.assertEqual('Retain',
                         self.resolve(deletion_policy_snippet, stack.t, stack))
        self.assertEqual({"blarg": "wibble"},
                         self.resolve(update_policy_snippet, stack.t, stack))

    def test_resource_facade_function(self):
        deletion_policy_snippet = {'resource_facade': 'deletion_policy'}

        parent_resource = DummyClass()
        parent_resource.metadata_set({"foo": "bar"})
        del_policy = hot_functions.Join(None,
                                        'list_join', ['eta', ['R', 'in']])
        parent_resource.t = rsrc_defn.ResourceDefinition(
            'parent', 'SomeType',
            deletion_policy=del_policy)
        tmpl = copy.deepcopy(hot_juno_tpl_empty)
        tmpl['resources'] = {'parent': parent_resource.t.render_hot()}
        parent_resource.stack = parser.Stack(utils.dummy_context(),
                                             'toplevel_stack',
                                             template.Template(tmpl))
        parent_resource.stack._resources = {'parent': parent_resource}

        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             template.Template(hot_tpl_empty),
                             parent_resource='parent')
        stack.set_parent_stack(parent_resource.stack)
        self.assertEqual('Retain',
                         self.resolve(deletion_policy_snippet, stack.t, stack))

    def test_resource_facade_invalid_arg(self):
        snippet = {'resource_facade': 'wibble'}
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             template.Template(hot_tpl_empty))
        error = self.assertRaises(exception.StackValidationFailed,
                                  self.resolve,
                                  snippet,
                                  stack.t, stack)
        self.assertIn(next(iter(snippet)), six.text_type(error))

    def test_resource_facade_missing_deletion_policy(self):
        snippet = {'resource_facade': 'deletion_policy'}

        parent_resource = DummyClass()
        parent_resource.metadata_set({"foo": "bar"})
        parent_resource.t = rsrc_defn.ResourceDefinition('parent', 'SomeType')
        tmpl = copy.deepcopy(hot_tpl_empty)
        tmpl['resources'] = {'parent': parent_resource.t.render_hot()}
        parent_stack = parser.Stack(utils.dummy_context(),
                                    'toplevel_stack',
                                    template.Template(tmpl))
        parent_stack._resources = {'parent': parent_resource}
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             template.Template(hot_tpl_empty),
                             parent_resource='parent')
        stack.set_parent_stack(parent_stack)
        self.assertEqual('Delete', self.resolve(snippet, stack.t, stack))

    def test_removed_function(self):
        snippet = {'Fn::GetAZs': ''}
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             template.Template(hot_juno_tpl_empty))
        regxp = 'Fn::GetAZs: The template version is invalid'
        self.assertRaisesRegex(exception.StackValidationFailed,
                               regxp,
                               function.validate,
                               stack.t.parse(stack.defn, snippet))

    def test_add_resource(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            depends_on:
              - dummy
            deletion_policy: Retain
            update_policy:
              foo: bar
          resource2:
            type: AWS::EC2::Instance
          resource3:
            type: AWS::EC2::Instance
            depends_on:
              - resource1
              - dummy
              - resource2
        ''')
        source = template.Template(hot_tpl)
        empty = template.Template(copy.deepcopy(hot_tpl_empty))
        stack = parser.Stack(utils.dummy_context(), 'test_stack', source)

        for rname, defn in sorted(source.resource_definitions(stack).items()):
            empty.add_resource(defn)

        expected = copy.deepcopy(hot_tpl['resources'])
        expected['resource1']['depends_on'] = []
        expected['resource3']['depends_on'] = ['resource1', 'resource2']
        self.assertEqual(expected, empty.t['resources'])

    def test_add_output(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        outputs:
          output1:
            description: An output
            value: bar
        ''')
        source = template.Template(hot_tpl)
        empty = template.Template(copy.deepcopy(hot_tpl_empty))
        stack = parser.Stack(utils.dummy_context(), 'test_stack', source)

        for defn in six.itervalues(source.outputs(stack)):
            empty.add_output(defn)

        self.assertEqual(hot_tpl['outputs'], empty.t['outputs'])

    def test_filter(self):
        snippet = {'filter': [[None], [1, None, 4, 2, None]]}
        tmpl = template.Template(hot_ocata_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        resolved = self.resolve(snippet, tmpl, stack=stack)

        self.assertEqual([1, 4, 2], resolved)

    def test_filter_wrong_args_type(self):
        snippet = {'filter': 'foo'}
        tmpl = template.Template(hot_ocata_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        self.assertRaises(exception.StackValidationFailed, self.resolve,
                          snippet, tmpl, stack=stack)

    def test_filter_wrong_args_number(self):
        snippet = {'filter': [[None], [1, 2], 'foo']}
        tmpl = template.Template(hot_ocata_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        self.assertRaises(exception.StackValidationFailed, self.resolve,
                          snippet, tmpl, stack=stack)

    def test_filter_dict(self):
        snippet = {'filter': [[None], {'a': 1}]}
        tmpl = template.Template(hot_ocata_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        self.assertRaises(TypeError, self.resolve, snippet, tmpl, stack=stack)

    def test_filter_str(self):
        snippet = {'filter': [['a'], 'abcd']}
        tmpl = template.Template(hot_ocata_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        self.assertRaises(TypeError, self.resolve, snippet, tmpl, stack=stack)

    def test_filter_str_values(self):
        snippet = {'filter': ['abcd', ['a', 'b', 'c', 'd']]}
        tmpl = template.Template(hot_ocata_tpl_empty)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        self.assertRaises(TypeError, self.resolve, snippet, tmpl, stack=stack)

    def test_make_url_basic(self):
        snippet = {
            'make_url': {
                'scheme': 'http',
                'host': 'example.com',
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        func = tmpl.parse(None, snippet)
        function.validate(func)
        resolved = function.resolve(func)

        self.assertEqual('http://example.com/foo/bar',
                         resolved)

    def test_make_url_ipv6(self):
        snippet = {
            'make_url': {
                'scheme': 'http',
                'host': '::1',
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('http://[::1]/foo/bar',
                         resolved)

    def test_make_url_ipv6_ready(self):
        snippet = {
            'make_url': {
                'scheme': 'http',
                'host': '[::1]',
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('http://[::1]/foo/bar',
                         resolved)

    def test_make_url_port_string(self):
        snippet = {
            'make_url': {
                'scheme': 'https',
                'host': 'example.com',
                'port': '80',
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('https://example.com:80/foo/bar',
                         resolved)

    def test_make_url_port_int(self):
        snippet = {
            'make_url': {
                'scheme': 'https',
                'host': 'example.com',
                'port': 80,
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('https://example.com:80/foo/bar',
                         resolved)

    def test_make_url_port_invalid_high(self):
        snippet = {
            'make_url': {
                'scheme': 'https',
                'host': 'example.com',
                'port': 100000,
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        self.assertRaises(ValueError, self.resolve, snippet, tmpl)

    def test_make_url_port_invalid_low(self):
        snippet = {
            'make_url': {
                'scheme': 'https',
                'host': 'example.com',
                'port': '0',
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        self.assertRaises(ValueError, self.resolve, snippet, tmpl)

    def test_make_url_port_invalid_string(self):
        snippet = {
            'make_url': {
                'scheme': 'https',
                'host': 'example.com',
                'port': '1.1',
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        self.assertRaises(ValueError, self.resolve, snippet, tmpl)

    def test_make_url_username(self):
        snippet = {
            'make_url': {
                'scheme': 'http',
                'username': 'wibble',
                'host': 'example.com',
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('http://wibble@example.com/foo/bar',
                         resolved)

    def test_make_url_username_password(self):
        snippet = {
            'make_url': {
                'scheme': 'http',
                'username': 'wibble',
                'password': 'blarg',
                'host': 'example.com',
                'path': '/foo/bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('http://wibble:blarg@example.com/foo/bar',
                         resolved)

    def test_make_url_query(self):
        snippet = {
            'make_url': {
                'scheme': 'http',
                'host': 'example.com',
                'path': '/foo/?bar',
                'query': {
                    'foo#': 'bar & baz',
                    'blarg': '/wib=ble/',
                },
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertIn(resolved,
                      ['http://example.com/foo/%3Fbar'
                       '?foo%23=bar+%26+baz&blarg=/wib%3Dble/',
                       'http://example.com/foo/%3Fbar'
                       '?blarg=/wib%3Dble/&foo%23=bar+%26+baz'])

    def test_make_url_fragment(self):
        snippet = {
            'make_url': {
                'scheme': 'http',
                'host': 'example.com',
                'path': 'foo/bar',
                'fragment': 'baz'
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('http://example.com/foo/bar#baz',
                         resolved)

    def test_make_url_file(self):
        snippet = {
            'make_url': {
                'scheme': 'file',
                'path': 'foo/bar'
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('file:///foo/bar',
                         resolved)

    def test_make_url_file_leading_slash(self):
        snippet = {
            'make_url': {
                'scheme': 'file',
                'path': '/foo/bar'
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)

        self.assertEqual('file:///foo/bar',
                         resolved)

    def test_make_url_bad_args_type(self):
        snippet = {
            'make_url': 'http://example.com/foo/bar'
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        func = tmpl.parse(None, snippet)
        self.assertRaises(exception.StackValidationFailed, function.validate,
                          func)

    def test_make_url_invalid_key(self):
        snippet = {
            'make_url': {
                'scheme': 'http',
                'host': 'example.com',
                'foo': 'bar',
            }
        }
        tmpl = template.Template(hot_pike_tpl_empty)
        func = tmpl.parse(None, snippet)
        self.assertRaises(exception.StackValidationFailed, function.validate,
                          func)

    def test_depends_condition(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2016-10-14
        resources:
          one:
            type: OS::Heat::None
          two:
            type: OS::Heat::None
            condition: False
          three:
            type: OS::Heat::None
            depends_on: two
        ''')

        tmpl = template.Template(hot_tpl)
        stack = parser.Stack(utils.dummy_context(), 'test_stack', tmpl)
        stack.validate()
        self.assertEqual({'one', 'three'}, set(stack.resources))

    def test_list_concat(self):
        snippet = {'list_concat': [['v1', 'v2'], ['v3', 'v4']]}
        snippet_resolved = ['v1', 'v2', 'v3', 'v4']
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual(snippet_resolved, resolved)

    def test_list_concat_none(self):
        snippet = {'list_concat': [['v1', 'v2'], ['v3', 'v4'], None]}
        snippet_resolved = ['v1', 'v2', 'v3', 'v4']
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual(snippet_resolved, resolved)

    def test_list_concat_repeat_dict_item(self):
        snippet = {'list_concat': [[{'v1': 'v2'}], [{'v1': 'v2'}]]}
        snippet_resolved = [{'v1': 'v2'}, {'v1': 'v2'}]
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual(snippet_resolved, resolved)

    def test_list_concat_repeat_item(self):
        snippet = {'list_concat': [['v1', 'v2'], ['v2', 'v3']]}
        snippet_resolved = ['v1', 'v2', 'v2', 'v3']
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual(snippet_resolved, resolved)

    def test_list_concat_unique_dict_item(self):
        snippet = {'list_concat_unique': [[{'v1': 'v2'}], [{'v1': 'v2'}]]}
        snippet_resolved = [{'v1': 'v2'}]
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual(snippet_resolved, resolved)

    def test_list_concat_unique(self):
        snippet = {'list_concat_unique': [['v1', 'v2'], ['v2', 'v3']]}
        snippet_resolved = ['v1', 'v2', 'v3']
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertEqual(snippet_resolved, resolved)

    def _test_list_concat_invalid(self, snippet):
        tmpl = template.Template(hot_pike_tpl_empty)
        msg = 'Incorrect arguments'
        exc = self.assertRaises(TypeError, self.resolve, snippet, tmpl)
        self.assertIn(msg, six.text_type(exc))

    def test_list_concat_with_dict_arg(self):
        snippet = {'list_concat': [{'k1': 'v2'}, ['v3', 'v4']]}
        self._test_list_concat_invalid(snippet)

    def test_list_concat_with_string_arg(self):
        snippet = {'list_concat': 'I am string'}
        self._test_list_concat_invalid(snippet)

    def test_list_concat_with_string_item(self):
        snippet = {'list_concat': ['v1', 'v2']}
        self._test_list_concat_invalid(snippet)

    def test_contains_with_list(self):
        snippet = {'contains': ['v1', ['v1', 'v2']]}
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertTrue(resolved)

    def test_contains_with_string(self):
        snippet = {'contains': ['a', 'abc']}
        tmpl = template.Template(hot_pike_tpl_empty)
        resolved = self.resolve(snippet, tmpl)
        self.assertTrue(resolved)

    def test_contains_with_invalid_args_type(self):
        snippet = {'contains': {'key': 'value'}}
        tmpl = template.Template(hot_pike_tpl_empty)
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve, snippet, tmpl)
        msg = 'Incorrect arguments to '
        self.assertIn(msg, six.text_type(exc))

    def test_contains_with_invalid_args_number(self):
        snippet = {'contains': ['v1', ['v1', 'v2'], 'redundant']}
        tmpl = template.Template(hot_pike_tpl_empty)
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.resolve, snippet, tmpl)
        msg = 'must be of the form: [value1, [value1, value2]]'
        self.assertIn(msg, six.text_type(exc))

    def test_contains_with_invalid_sequence(self):
        snippet = {'contains': ['v1', {'key': 'value'}]}
        tmpl = template.Template(hot_pike_tpl_empty)
        exc = self.assertRaises(TypeError,
                                self.resolve, snippet, tmpl)
        msg = 'should be a sequence'
        self.assertIn(msg, six.text_type(exc))


class HotStackTest(common.HeatTestCase):
    """Test stack function when stack was created from HOT template."""
    def setUp(self):
        super(HotStackTest, self).setUp()

        self.tmpl = template.Template(copy.deepcopy(empty_template))
        self.ctx = utils.dummy_context()

    def resolve(self, snippet):
        return function.resolve(self.stack.t.parse(self.stack.defn, snippet))

    def test_repeat_get_attr(self):
        """Test repeat function with get_attr function as an argument."""
        tmpl = template.Template(hot_tpl_complex_attrs_all_attrs)
        self.stack = parser.Stack(self.ctx, 'test_repeat_get_attr', tmpl)

        snippet = {'repeat': {'template': 'this is %var%',
                   'for_each': {'%var%': {'get_attr': ['resource1', 'list']}}}}
        repeat = self.stack.t.parse(self.stack.defn, snippet)

        self.stack.store()
        with mock.patch.object(rsrc_defn.ResourceDefinition,
                               'dep_attrs') as mock_da:
            mock_da.return_value = ['list']
            self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(['this is foo', 'this is bar'],
                         function.resolve(repeat))

    def test_get_attr_multiple_rsrc_status(self):
        """Test resolution of get_attr occurrences in HOT template."""

        hot_tpl = hot_tpl_generic_resource
        self.stack = parser.Stack(self.ctx, 'test_get_attr',
                                  template.Template(hot_tpl))
        self.stack.store()
        with mock.patch.object(rsrc_defn.ResourceDefinition,
                               'dep_attrs') as mock_da:
            mock_da.return_value = ['foo']
            self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        snippet = {'Value': {'get_attr': ['resource1', 'foo']}}
        rsrc = self.stack['resource1']
        for action, status in (
                (rsrc.CREATE, rsrc.IN_PROGRESS),
                (rsrc.CREATE, rsrc.COMPLETE),
                (rsrc.RESUME, rsrc.IN_PROGRESS),
                (rsrc.RESUME, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.IN_PROGRESS),
                (rsrc.UPDATE, rsrc.COMPLETE)):
            rsrc.state_set(action, status)

            # GenericResourceType has an attribute 'foo' which yields the
            # resource name.
            self.assertEqual({'Value': 'resource1'}, self.resolve(snippet))

    def test_get_attr_invalid(self):
        """Test resolution of get_attr occurrences in HOT template."""

        hot_tpl = hot_tpl_generic_resource
        self.stack = parser.Stack(self.ctx, 'test_get_attr',
                                  template.Template(hot_tpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertRaises(exception.InvalidTemplateAttribute,
                          self.resolve,
                          {'Value': {'get_attr': ['resource1', 'NotThere']}})

    def test_get_attr_invalid_resource(self):
        """Test resolution of get_attr occurrences in HOT template."""

        hot_tpl = hot_tpl_complex_attrs
        self.stack = parser.Stack(self.ctx,
                                  'test_get_attr_invalid_none',
                                  template.Template(hot_tpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        snippet = {'Value': {'get_attr': ['resource2', 'who_cares']}}
        self.assertRaises(exception.InvalidTemplateReference,
                          self.resolve, snippet)

    def test_get_resource(self):
        """Test resolution of get_resource occurrences in HOT template."""

        hot_tpl = hot_tpl_generic_resource
        self.stack = parser.Stack(self.ctx, 'test_get_resource',
                                  template.Template(hot_tpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        snippet = {'value': {'get_resource': 'resource1'}}
        self.assertEqual({'value': 'resource1'}, self.resolve(snippet))

    def test_set_param_id(self):
        tmpl = template.Template(hot_tpl_empty)
        self.stack = parser.Stack(self.ctx, 'param_id_test', tmpl)
        self.assertEqual('None', self.stack.parameters['OS::stack_id'])
        self.stack.store()
        stack_identifier = self.stack.identifier()
        self.assertEqual(self.stack.id, self.stack.parameters['OS::stack_id'])
        self.assertEqual(stack_identifier.stack_id,
                         self.stack.parameters['OS::stack_id'])

    def test_set_wrong_param(self):
        tmpl = template.Template(hot_tpl_empty)
        stack_id = identifier.HeatIdentifier('', "stack_testit", None)
        params = tmpl.parameters(None, {})
        self.assertFalse(params.set_stack_id(None))
        self.assertTrue(params.set_stack_id(stack_id))

    def test_set_param_id_update(self):
        tmpl = template.Template(
            {'heat_template_version': '2013-05-23',
             'resources': {'AResource': {'type': 'ResourceWithPropsType',
                           'metadata': {'Bar': {'get_param': 'OS::stack_id'}},
                           'properties': {'Foo': 'abc'}}}})
        self.stack = parser.Stack(self.ctx, 'update_stack_id_test', tmpl)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        stack_id = self.stack.parameters['OS::stack_id']

        tmpl2 = template.Template(
            {'heat_template_version': '2013-05-23',
             'resources': {'AResource': {'type': 'ResourceWithPropsType',
                           'metadata': {'Bar': {'get_param': 'OS::stack_id'}},
                           'properties': {'Foo': 'xyz'}}}})
        updated_stack = parser.Stack(self.ctx, 'updated_stack', tmpl2)

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('xyz', self.stack['AResource'].properties['Foo'])

        self.assertEqual(stack_id,
                         self.stack['AResource'].metadata_get()['Bar'])

    def test_load_param_id(self):
        tmpl = template.Template(hot_tpl_empty)
        self.stack = parser.Stack(self.ctx, 'param_load_id_test', tmpl)
        self.stack.store()
        stack_identifier = self.stack.identifier()
        self.assertEqual(stack_identifier.stack_id,
                         self.stack.parameters['OS::stack_id'])

        newstack = parser.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertEqual(stack_identifier.stack_id,
                         newstack.parameters['OS::stack_id'])

    def test_update_modify_param_ok_replace(self):
        tmpl = {
            'heat_template_version': '2013-05-23',
            'parameters': {
                'foo': {'type': 'string'}
            },
            'resources': {
                'AResource': {
                    'type': 'ResourceWithPropsType',
                    'properties': {'Foo': {'get_param': 'foo'}}
                }
            }
        }

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(
                                      tmpl, env=environment.Environment(
                                          {'foo': 'abc'})))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(
                                         tmpl, env=environment.Environment(
                                             {'foo': 'xyz'})))

        def check_props_and_raise(*args):
            self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
            raise resource.UpdateReplace()

        mock_update = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'update_template_diff',
                                       side_effect=check_props_and_raise)

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('xyz', self.stack['AResource'].properties['Foo'])
        mock_update.assert_called_once_with(
            rsrc_defn.ResourceDefinition('AResource',
                                         'ResourceWithPropsType',
                                         properties={'Foo': 'xyz'}),
            rsrc_defn.ResourceDefinition('AResource',
                                         'ResourceWithPropsType',
                                         properties={'Foo': 'abc'}))

    def test_update_modify_files_ok_replace(self):
        tmpl = {
            'heat_template_version': '2013-05-23',
            'parameters': {},
            'resources': {
                'AResource': {
                    'type': 'ResourceWithPropsType',
                    'properties': {'Foo': {'get_file': 'foo'}}
                }
            }
        }

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl,
                                                    files={'foo': 'abc'}))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl,
                                                       files={'foo': 'xyz'}))

        def check_props_and_raise(*args):
            self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
            raise resource.UpdateReplace()

        mock_update = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'update_template_diff',
                                       side_effect=check_props_and_raise)

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('xyz', self.stack['AResource'].properties['Foo'])
        mock_update.assert_called_once_with(
            rsrc_defn.ResourceDefinition('AResource',
                                         'ResourceWithPropsType',
                                         properties={'Foo': 'xyz'}),
            rsrc_defn.ResourceDefinition('AResource',
                                         'ResourceWithPropsType',
                                         properties={'Foo': 'abc'}))


class StackAttributesTest(common.HeatTestCase):
    """Test get_attr function when stack was created from HOT template."""

    def setUp(self):
        super(StackAttributesTest, self).setUp()

        self.ctx = utils.dummy_context()

    scenarios = [
        # for hot template 2013-05-23, get_attr: hot_funcs.GetAttThenSelect
        ('get_flat_attr',
         dict(hot_tpl=hot_tpl_generic_resource,
              snippet={'Value': {'get_attr': ['resource1', 'foo']}},
              resource_name='resource1',
              expected={'Value': 'resource1'})),
        ('get_list_attr',
         dict(hot_tpl=hot_tpl_complex_attrs,
              snippet={'Value': {'get_attr': ['resource1', 'list', 0]}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.list[0]})),
        ('get_flat_dict_attr',
         dict(hot_tpl=hot_tpl_complex_attrs,
              snippet={'Value': {'get_attr': ['resource1',
                                              'flat_dict',
                                              'key2']}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.
                  flat_dict['key2']})),
        ('get_nested_attr_list',
         dict(hot_tpl=hot_tpl_complex_attrs,
              snippet={'Value': {'get_attr': ['resource1',
                                              'nested_dict',
                                              'list',
                                              0]}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.
                  nested_dict['list'][0]})),
        ('get_nested_attr_dict',
         dict(hot_tpl=hot_tpl_complex_attrs,
              snippet={'Value': {'get_attr': ['resource1',
                                              'nested_dict',
                                              'dict',
                                              'a']}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.
                  nested_dict['dict']['a']})),
        ('get_attr_none',
         dict(hot_tpl=hot_tpl_complex_attrs,
              snippet={'Value': {'get_attr': ['resource1',
                                              'none',
                                              'who_cares']}},
              resource_name='resource1',
              expected={'Value': None})),
        # for hot template version 2014-10-16 and 2015-04-30,
        # get_attr: hot_funcs.GetAtt
        ('get_flat_attr',
         dict(hot_tpl=hot_tpl_generic_resource_20141016,
              snippet={'Value': {'get_attr': ['resource1', 'foo']}},
              resource_name='resource1',
              expected={'Value': 'resource1'})),
        ('get_list_attr',
         dict(hot_tpl=hot_tpl_complex_attrs_20141016,
              snippet={'Value': {'get_attr': ['resource1', 'list', 0]}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.list[0]})),
        ('get_flat_dict_attr',
         dict(hot_tpl=hot_tpl_complex_attrs_20141016,
              snippet={'Value': {'get_attr': ['resource1',
                                              'flat_dict',
                                              'key2']}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.
                  flat_dict['key2']})),
        ('get_nested_attr_list',
         dict(hot_tpl=hot_tpl_complex_attrs_20141016,
              snippet={'Value': {'get_attr': ['resource1',
                                              'nested_dict',
                                              'list',
                                              0]}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.
                  nested_dict['list'][0]})),
        ('get_nested_attr_dict',
         dict(hot_tpl=hot_tpl_complex_attrs_20141016,
              snippet={'Value': {'get_attr': ['resource1',
                                              'nested_dict',
                                              'dict',
                                              'a']}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.
                  nested_dict['dict']['a']})),
        ('get_attr_none',
         dict(hot_tpl=hot_tpl_complex_attrs_20141016,
              snippet={'Value': {'get_attr': ['resource1',
                                              'none',
                                              'who_cares']}},
              resource_name='resource1',
              expected={'Value': None}))
    ]

    def test_get_attr(self):
        """Test resolution of get_attr occurrences in HOT template."""

        self.stack = parser.Stack(self.ctx, 'test_get_attr',
                                  template.Template(self.hot_tpl))
        self.stack.store()

        parsed = self.stack.t.parse(self.stack.defn, self.snippet)
        dep_attrs = list(function.dep_attrs(parsed, self.resource_name))

        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        rsrc = self.stack[self.resource_name]
        for action, status in (
                (rsrc.CREATE, rsrc.IN_PROGRESS),
                (rsrc.CREATE, rsrc.COMPLETE),
                (rsrc.RESUME, rsrc.IN_PROGRESS),
                (rsrc.RESUME, rsrc.COMPLETE),
                (rsrc.SUSPEND, rsrc.IN_PROGRESS),
                (rsrc.SUSPEND, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.IN_PROGRESS),
                (rsrc.UPDATE, rsrc.COMPLETE),
                (rsrc.SNAPSHOT, rsrc.IN_PROGRESS),
                (rsrc.SNAPSHOT, rsrc.COMPLETE),
                (rsrc.CHECK, rsrc.IN_PROGRESS),
                (rsrc.CHECK, rsrc.COMPLETE),
                (rsrc.ADOPT, rsrc.IN_PROGRESS),
                (rsrc.ADOPT, rsrc.COMPLETE)):
            rsrc.state_set(action, status)

            with mock.patch.object(rsrc_defn.ResourceDefinition,
                                   'dep_attrs') as mock_da:
                mock_da.return_value = dep_attrs
                node_data = rsrc.node_data()
            stk_defn.update_resource_data(self.stack.defn, rsrc.name,
                                          node_data)

            self.assertEqual(self.expected, function.resolve(parsed))


class StackGetAttrValidationTest(common.HeatTestCase):

    def setUp(self):
        super(StackGetAttrValidationTest, self).setUp()
        self.ctx = utils.dummy_context()

    def test_validate_props_from_attrs(self):
        stack = parser.Stack(self.ctx, 'test_props_from_attrs',
                             template.Template(hot_tpl_mapped_props))
        stack.resources['resource1'].list = None
        stack.resources['resource1'].map = None
        stack.resources['resource1'].string = None
        try:
            stack.validate()
        except exception.StackValidationFailed as exc:
            self.fail("Validation should have passed: %s" % six.text_type(exc))
        self.assertEqual([],
                         stack.resources['resource2'].properties['a_list'])
        self.assertEqual({},
                         stack.resources['resource2'].properties['a_map'])
        self.assertEqual('',
                         stack.resources['resource2'].properties['a_string'])

    def test_validate_props_from_attrs_all_attrs(self):
        stack = parser.Stack(self.ctx, 'test_props_from_attrs',
                             template.Template(hot_tpl_mapped_props_all_attrs))
        stack.resources['resource1'].list = None
        stack.resources['resource1'].map = None
        stack.resources['resource1'].string = None
        try:
            stack.validate()
        except exception.StackValidationFailed as exc:
            self.fail("Validation should have passed: %s" % six.text_type(exc))
        self.assertEqual([],
                         stack.resources['resource2'].properties['a_list'])
        self.assertEqual({},
                         stack.resources['resource2'].properties['a_map'])
        self.assertEqual('',
                         stack.resources['resource2'].properties['a_string'])


class StackParametersTest(common.HeatTestCase):
    """Test get_param function when stack was created from HOT template."""

    scenarios = [
        ('Ref_string',
         dict(params={'foo': 'bar', 'blarg': 'wibble'},
              snippet={'properties': {'prop1': {'Ref': 'foo'},
                                      'prop2': {'Ref': 'blarg'}}},
              expected={'properties': {'prop1': 'bar',
                                       'prop2': 'wibble'}})),
        ('get_param_string',
         dict(params={'foo': 'bar', 'blarg': 'wibble'},
              snippet={'properties': {'prop1': {'get_param': 'foo'},
                                      'prop2': {'get_param': 'blarg'}}},
              expected={'properties': {'prop1': 'bar',
                                       'prop2': 'wibble'}})),
        ('get_list_attr',
         dict(params={'list': 'foo,bar'},
              snippet={'properties': {'prop1': {'get_param': ['list', 1]}}},
              expected={'properties': {'prop1': 'bar'}})),
        ('get_list_attr_string_index',
         dict(params={'list': 'foo,bar'},
              snippet={'properties': {'prop1': {'get_param': ['list', '1']}}},
              expected={'properties': {'prop1': 'bar'}})),
        ('get_flat_dict_attr',
         dict(params={'flat_dict':
                      {'key1': 'val1', 'key2': 'val2', 'key3': 'val3'}},
              snippet={'properties': {'prop1': {'get_param':
                                                ['flat_dict', 'key2']}}},
              expected={'properties': {'prop1': 'val2'}})),
        ('get_nested_attr_list',
         dict(params={'nested_dict':
                      {'list': [1, 2, 3],
                       'string': 'abc',
                       'dict': {'a': 1, 'b': 2, 'c': 3}}},
              snippet={'properties': {'prop1': {'get_param':
                                                ['nested_dict',
                                                 'list',
                                                 0]}}},
              expected={'properties': {'prop1': 1}})),
        ('get_nested_attr_dict',
         dict(params={'nested_dict':
                      {'list': [1, 2, 3],
                       'string': 'abc',
                       'dict': {'a': 1, 'b': 2, 'c': 3}}},
              snippet={'properties': {'prop1': {'get_param':
                                                ['nested_dict',
                                                 'dict',
                                                 'a']}}},
              expected={'properties': {'prop1': 1}})),
        ('get_attr_none',
         dict(params={'none': None},
              snippet={'properties': {'prop1': {'get_param':
                                                ['none',
                                                 'who_cares']}}},
              expected={'properties': {'prop1': ''}})),
        ('pseudo_stack_id',
         dict(params={},
              snippet={'properties': {'prop1': {'get_param':
                                                'OS::stack_id'}}},
              expected={'properties':
                        {'prop1': '1ba8c334-2297-4312-8c7c-43763a988ced'}})),
        ('pseudo_stack_name',
         dict(params={},
              snippet={'properties': {'prop1': {'get_param':
                                                'OS::stack_name'}}},
              expected={'properties': {'prop1': 'test'}})),
        ('pseudo_project_id',
         dict(params={},
              snippet={'properties': {'prop1': {'get_param':
                                                'OS::project_id'}}},
              expected={'properties':
                        {'prop1': '9913ef0a-b8be-4b33-b574-9061441bd373'}})),

    ]

    props_template = template_format.parse('''
    heat_template_version: 2013-05-23
    parameters:
        foo:
            type: string
            default: ''
        blarg:
            type: string
            default: ''
        list:
            type: comma_delimited_list
            default: ''
        flat_dict:
            type: json
            default: {}
        nested_dict:
            type: json
            default: {}
        none:
            type: string
            default: 'default'
    ''')

    def test_param_refs(self):
        """Test if parameter references work."""
        env = environment.Environment(self.params)
        tmpl = template.Template(self.props_template, env=env)
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl,
                             stack_id='1ba8c334-2297-4312-8c7c-43763a988ced',
                             tenant_id='9913ef0a-b8be-4b33-b574-9061441bd373')
        self.assertEqual(self.expected,
                         function.resolve(tmpl.parse(stack.defn,
                                                     self.snippet)))


class HOTParamValidatorTest(common.HeatTestCase):
    """Test HOTParamValidator."""

    def test_multiple_constraint_descriptions(self):
        len_desc = 'string length should be between 8 and 16'
        pattern_desc1 = 'Value must consist of characters only'
        pattern_desc2 = 'Value must start with a lowercase character'
        param = {
            'db_name': {
                'description': 'The WordPress database name',
                'type': 'string',
                'default': 'wordpress',
                'constraints': [
                    {'length': {'min': 6, 'max': 16},
                     'description': len_desc},
                    {'allowed_pattern': '[a-zA-Z]+',
                     'description': pattern_desc1},
                    {'allowed_pattern': '[a-z]+[a-zA-Z]*',
                     'description': pattern_desc2}]}}

        name = 'db_name'
        schema = param['db_name']

        def v(value):
            param_schema = hot_param.HOTParamSchema.from_dict(name, schema)
            param_schema.validate()
            param_schema.validate_value(value)
            return True

        value = 'wp'
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertIn(len_desc, six.text_type(err))

        value = 'abcdefghijklmnopq'
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertIn(len_desc, six.text_type(err))

        value = 'abcdefgh1'
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertIn(pattern_desc1, six.text_type(err))

        value = 'Abcdefghi'
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertIn(pattern_desc2, six.text_type(err))

        value = 'abcdefghi'
        self.assertTrue(v(value))

        value = 'abcdefghI'
        self.assertTrue(v(value))

    def test_hot_template_validate_param(self):
        len_desc = 'string length should be between 8 and 16'
        pattern_desc1 = 'Value must consist of characters only'
        pattern_desc2 = 'Value must start with a lowercase character'
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
          db_name:
            description: The WordPress database name
            type: string
            default: wordpress
            constraints:
              - length: { min: 8, max: 16 }
                description: %s
              - allowed_pattern: "[a-zA-Z]+"
                description: %s
              - allowed_pattern: "[a-z]+[a-zA-Z]*"
                description: %s
        ''' % (len_desc, pattern_desc1, pattern_desc2))
        tmpl = template.Template(hot_tpl)

        def run_parameters(value):
            tmpl.parameters(
                identifier.HeatIdentifier('', "stack_testit", None),
                {'db_name': value}).validate(validate_value=True)
            return True

        value = 'wp'
        err = self.assertRaises(exception.StackValidationFailed,
                                run_parameters, value)
        self.assertIn(len_desc, six.text_type(err))

        value = 'abcdefghijklmnopq'
        err = self.assertRaises(exception.StackValidationFailed,
                                run_parameters, value)
        self.assertIn(len_desc, six.text_type(err))

        value = 'abcdefgh1'
        err = self.assertRaises(exception.StackValidationFailed,
                                run_parameters, value)
        self.assertIn(pattern_desc1, six.text_type(err))

        value = 'Abcdefghi'
        err = self.assertRaises(exception.StackValidationFailed,
                                run_parameters, value)
        self.assertIn(pattern_desc2, six.text_type(err))

        value = 'abcdefghi'
        self.assertTrue(run_parameters(value))

        value = 'abcdefghI'
        self.assertTrue(run_parameters(value))

    def test_range_constraint(self):
        range_desc = 'Value must be between 30000 and 50000'
        param = {
            'db_port': {
                'description': 'The database port',
                'type': 'number',
                'default': 31000,
                'constraints': [
                    {'range': {'min': 30000, 'max': 50000},
                     'description': range_desc}]}}

        name = 'db_port'
        schema = param['db_port']

        def v(value):
            param_schema = hot_param.HOTParamSchema.from_dict(name, schema)
            param_schema.validate()
            param_schema.validate_value(value)
            return True

        value = 29999
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertIn(range_desc, six.text_type(err))

        value = 50001
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertIn(range_desc, six.text_type(err))

        value = 30000
        self.assertTrue(v(value))

        value = 40000
        self.assertTrue(v(value))

        value = 50000
        self.assertTrue(v(value))

    def test_custom_constraint(self):
        class ZeroConstraint(object):
            def validate(self, value, context):
                return value == "0"

        env = resources.global_env()
        env.register_constraint("zero", ZeroConstraint)
        self.addCleanup(env.constraints.pop, "zero")

        desc = 'Value must be zero'
        param = {
            'param1': {
                'type': 'string',
                'constraints': [
                    {'custom_constraint': 'zero',
                     'description': desc}]}}

        name = 'param1'
        schema = param['param1']

        def v(value):
            param_schema = hot_param.HOTParamSchema.from_dict(name, schema)
            param_schema.validate()
            param_schema.validate_value(value)
            return True

        value = "1"
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertEqual(desc, six.text_type(err))

        value = "2"
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertEqual(desc, six.text_type(err))

        value = "0"
        self.assertTrue(v(value))

    def test_custom_constraint_default_skip(self):
        schema = {
            'type': 'string',
            'constraints': [{
                'custom_constraint': 'skipping',
                'description': 'Must be skipped on default value'
            }],
            'default': 'foo'
        }
        param_schema = hot_param.HOTParamSchema.from_dict('p', schema)

        param_schema.validate()

    def test_range_constraint_invalid_default(self):
        range_desc = 'Value must be between 30000 and 50000'
        param = {
            'db_port': {
                'description': 'The database port',
                'type': 'number',
                'default': 15,
                'constraints': [
                    {'range': {'min': 30000, 'max': 50000},
                     'description': range_desc}]}}

        schema = hot_param.HOTParamSchema.from_dict('db_port',
                                                    param['db_port'])
        err = self.assertRaises(exception.InvalidSchemaError,
                                schema.validate)
        self.assertIn(range_desc, six.text_type(err))

    def test_validate_schema_wrong_key(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                foo: bar
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual("Invalid key 'foo' for parameter (param1)",
                         six.text_type(error))

    def test_validate_schema_no_type(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                description: Hi!
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual("Missing parameter type for parameter: param1",
                         six.text_type(error))

    def test_validate_schema_unknown_type(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: Unicode
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual(
            "Invalid type (Unicode)", six.text_type(error))

    def test_validate_schema_constraints(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                constraints:
                   - allowed_valus: [foo, bar]
                default: foo
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual(
            "Invalid key 'allowed_valus' for parameter constraints",
            six.text_type(error))

    def test_validate_schema_constraints_not_list(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                constraints: 1
                default: foo
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual(
            "Invalid parameter constraints for parameter param1, "
            "expected a list", six.text_type(error))

    def test_validate_schema_constraints_not_mapping(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                constraints: [foo]
                default: foo
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual(
            "Invalid parameter constraints, expected a mapping",
            six.text_type(error))

    def test_validate_schema_empty_constraints(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                constraints:
                    - description: a constraint
                default: foo
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual("No constraint expressed", six.text_type(error))

    def test_validate_schema_constraints_range_wrong_format(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: number
                constraints:
                   - range: foo
                default: foo
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual(
            "Invalid range constraint, expected a mapping",
            six.text_type(error))

    def test_validate_schema_constraints_range_invalid_key(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: number
                constraints:
                    - range: {min: 1, foo: bar}
                default: 1
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual(
            "Invalid key 'foo' for range constraint", six.text_type(error))

    def test_validate_schema_constraints_length_wrong_format(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                constraints:
                   - length: foo
                default: foo
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual(
            "Invalid length constraint, expected a mapping",
            six.text_type(error))

    def test_validate_schema_constraints_length_invalid_key(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                constraints:
                    - length: {min: 1, foo: bar}
                default: foo
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual(
            "Invalid key 'foo' for length constraint", six.text_type(error))

    def test_validate_schema_constraints_wrong_allowed_pattern(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                constraints:
                    - allowed_pattern: [foo, bar]
                default: foo
        ''')
        error = self.assertRaises(
            exception.InvalidSchemaError, cfn_param.CfnParameters,
            "stack_testit", template.Template(hot_tpl))
        self.assertEqual(
            "AllowedPattern must be a string", six.text_type(error))

    def test_modulo_constraint(self):
        modulo_desc = 'Value must be an odd number'
        modulo_name = 'ControllerCount'
        param = {
            modulo_name: {
                'description': 'Number of controller nodes',
                'type': 'number',
                'default': 1,
                'constraints': [{
                    'modulo': {'step': 2, 'offset': 1},
                    'description': modulo_desc
                }]
            }
        }

        def v(value):
            param_schema = hot_param.HOTParamSchema20170224.from_dict(
                modulo_name, param[modulo_name])
            param_schema.validate()
            param_schema.validate_value(value)
            return True

        value = 2
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertIn(modulo_desc, six.text_type(err))

        value = 100
        err = self.assertRaises(exception.StackValidationFailed, v, value)
        self.assertIn(modulo_desc, six.text_type(err))

        value = 1
        self.assertTrue(v(value))

        value = 3
        self.assertTrue(v(value))

        value = 777
        self.assertTrue(v(value))

    def test_modulo_constraint_invalid_default(self):
        modulo_desc = 'Value must be an odd number'
        modulo_name = 'ControllerCount'
        param = {
            modulo_name: {
                'description': 'Number of controller nodes',
                'type': 'number',
                'default': 2,
                'constraints': [{
                    'modulo': {'step': 2, 'offset': 1},
                    'description': modulo_desc
                }]
            }
        }

        schema = hot_param.HOTParamSchema20170224.from_dict(
            modulo_name, param[modulo_name])
        err = self.assertRaises(exception.InvalidSchemaError, schema.validate)
        self.assertIn(modulo_desc, six.text_type(err))


class TestGetAttAllAttributes(common.HeatTestCase):
    scenarios = [
        ('test_get_attr_all_attributes', dict(
            hot_tpl=hot_tpl_generic_resource_all_attrs,
            snippet={'Value': {'get_attr': ['resource1']}},
            expected={'Value': {'Foo': 'resource1', 'foo': 'resource1'}},
            raises=None
        )),
        ('test_get_attr_all_attributes_str', dict(
            hot_tpl=hot_tpl_generic_resource_all_attrs,
            snippet={'Value': {'get_attr': 'resource1'}},
            expected='.Value.get_attr: Argument to "get_attr" must be a '
                     'list',
            raises=exception.StackValidationFailed
        )),
        ('test_get_attr_all_attributes_invalid_resource_list', dict(
            hot_tpl=hot_tpl_generic_resource_all_attrs,
            snippet={'Value': {'get_attr': ['resource2']}},
            raises=exception.InvalidTemplateReference,
            expected='The specified reference "resource2" '
                     '(in unknown) is incorrect.'
        )),
        ('test_get_attr_all_attributes_invalid_type', dict(
            hot_tpl=hot_tpl_generic_resource_all_attrs,
            snippet={'Value': {'get_attr': {'resource1': 'attr1'}}},
            raises=exception.StackValidationFailed,
            expected='.Value.get_attr: Argument to "get_attr" must be a '
                     'list'
        )),
        ('test_get_attr_all_attributes_invalid_arg_str', dict(
            hot_tpl=hot_tpl_generic_resource_all_attrs,
            snippet={'Value': {'get_attr': ''}},
            raises=exception.StackValidationFailed,
            expected='.Value.get_attr: Arguments to "get_attr" can be of '
                     'the next forms: [resource_name] or '
                     '[resource_name, attribute, (path), ...]'
        )),
        ('test_get_attr_all_attributes_invalid_arg_list', dict(
            hot_tpl=hot_tpl_generic_resource_all_attrs,
            snippet={'Value': {'get_attr': []}},
            raises=exception.StackValidationFailed,
            expected='.Value.get_attr: Arguments to "get_attr" can be of '
                     'the next forms: [resource_name] or '
                     '[resource_name, attribute, (path), ...]'
        )),
        ('test_get_attr_all_attributes_standard', dict(
            hot_tpl=hot_tpl_generic_resource_all_attrs,
            snippet={'Value': {'get_attr': ['resource1', 'foo']}},
            expected={'Value': 'resource1'},
            raises=None
        )),
        ('test_get_attr_all_attrs_complex_attrs', dict(
            hot_tpl=hot_tpl_complex_attrs_all_attrs,
            snippet={'Value': {'get_attr': ['resource1']}},
            expected={'Value': {'flat_dict': {'key1': 'val1',
                                              'key2': 'val2',
                                              'key3': 'val3'},
                                'list': ['foo', 'bar'],
                                'nested_dict': {'dict': {'a': 1,
                                                         'b': 2,
                                                         'c': 3},
                                                'list': [1, 2, 3],
                                                'string': 'abc'},
                                'none': None}},
            raises=None
        )),
        ('test_get_attr_all_attrs_complex_attrs_standard', dict(
            hot_tpl=hot_tpl_complex_attrs_all_attrs,
            snippet={'Value': {'get_attr': ['resource1', 'list', 1]}},
            expected={'Value': 'bar'},
            raises=None
        )),
    ]

    @staticmethod
    def resolve(snippet, template, stack):
        return function.resolve(template.parse(stack.defn, snippet))

    def test_get_attr_all_attributes(self):
        tmpl = template.Template(self.hot_tpl)
        stack = parser.Stack(utils.dummy_context(), 'test_get_attr', tmpl)
        stack.store()

        if self.raises is None:
            dep_attrs = list(function.dep_attrs(tmpl.parse(stack.defn,
                                                           self.snippet),
                                                'resource1'))
        else:
            dep_attrs = []
        stack.create()

        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         stack.state)

        rsrc = stack['resource1']
        for action, status in (
                (rsrc.CREATE, rsrc.IN_PROGRESS),
                (rsrc.CREATE, rsrc.COMPLETE),
                (rsrc.RESUME, rsrc.IN_PROGRESS),
                (rsrc.RESUME, rsrc.COMPLETE),
                (rsrc.SUSPEND, rsrc.IN_PROGRESS),
                (rsrc.SUSPEND, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.IN_PROGRESS),
                (rsrc.UPDATE, rsrc.COMPLETE),
                (rsrc.SNAPSHOT, rsrc.IN_PROGRESS),
                (rsrc.SNAPSHOT, rsrc.COMPLETE),
                (rsrc.CHECK, rsrc.IN_PROGRESS),
                (rsrc.CHECK, rsrc.COMPLETE),
                (rsrc.ADOPT, rsrc.IN_PROGRESS),
                (rsrc.ADOPT, rsrc.COMPLETE)):
            rsrc.state_set(action, status)

            with mock.patch.object(rsrc_defn.ResourceDefinition,
                                   'dep_attrs') as mock_da:
                mock_da.return_value = dep_attrs
                node_data = rsrc.node_data()
            stk_defn.update_resource_data(stack.defn, rsrc.name, node_data)

            if self.raises is not None:
                ex = self.assertRaises(self.raises,
                                       self.resolve, self.snippet, tmpl, stack)
                self.assertEqual(self.expected, six.text_type(ex))
            else:
                self.assertEqual(self.expected,
                                 self.resolve(self.snippet, tmpl, stack))

    def test_stack_validate_outputs_get_all_attribute(self):
        hot_liberty_tpl = template_format.parse('''
heat_template_version: 2015-10-15
resources:
  resource1:
    type: GenericResourceType
outputs:
  all_attr:
    value: {get_attr: [resource1]}
''')

        stack = parser.Stack(utils.dummy_context(), 'test_outputs_get_all',
                             template.Template(hot_liberty_tpl))
        stack.validate()
