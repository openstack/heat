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
from heat.common import template_format
from heat.common import exception
from heat.common import identifier
from heat.engine import parser
from heat.engine import hot
from heat.engine import template
from heat.engine import constraints

from heat.tests.common import HeatTestCase
from heat.tests import test_parser
from heat.tests import utils


hot_tpl_empty = template_format.parse('''
heat_template_version: 2013-05-23
''')


class HOTemplateTest(HeatTestCase):
    """Test processing of HOT templates."""

    def test_defaults(self):
        """Test default content behavior of HOT template."""

        tmpl = parser.Template(hot_tpl_empty)
        # check if we get the right class
        self.assertIsInstance(tmpl, hot.HOTemplate)
        # test getting an invalid section
        self.assertNotIn('foobar', tmpl)

        # test defaults for valid sections
        self.assertEqual('2013-05-23', tmpl[hot.VERSION])
        self.assertEqual('No description', tmpl[hot.DESCRIPTION])
        self.assertEqual({}, tmpl[hot.PARAMETERS])
        self.assertEqual({}, tmpl[hot.RESOURCES])
        self.assertEqual({}, tmpl[hot.OUTPUTS])

    def test_translate_resources(self):
        """Test translation of resources into internal engine format."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
        ''')

        expected = {'resource1': {'Type': 'AWS::EC2::Instance',
                                  'Properties': {'property1': 'value1'}}}

        tmpl = parser.Template(hot_tpl)
        self.assertEqual(expected, tmpl[hot.RESOURCES])

    def test_translate_outputs(self):
        """Test translation of outputs into internal engine format."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        outputs:
          output1:
            description: output1
            value: value1
        ''')

        expected = {'output1': {'Description': 'output1', 'Value': 'value1'}}

        tmpl = parser.Template(hot_tpl)
        self.assertEqual(expected, tmpl[hot.OUTPUTS])

    def test_param_refs(self):
        """Test if parameter references work."""
        params = {'foo': 'bar', 'blarg': 'wibble'}
        snippet = {'properties': {'key1': {'get_param': 'foo'},
                                  'key2': {'get_param': 'blarg'}}}
        snippet_resolved = {'properties': {'key1': 'bar',
                                           'key2': 'wibble'}}
        tmpl = parser.Template(hot_tpl_empty)
        self.assertEqual(snippet_resolved,
                         tmpl.resolve_param_refs(snippet, params))
        snippet = {'properties': {'key1': {'Ref': 'foo'},
                                  'key2': {'Ref': 'blarg'}}}
        snippet_resolved = {'properties': {'key1': 'bar',
                                           'key2': 'wibble'}}
        tmpl = parser.Template(hot_tpl_empty)
        self.assertEqual(snippet_resolved,
                         tmpl.resolve_param_refs(snippet, params))

    def test_str_replace(self):
        """Test str_replace function."""

        snippet = {'str_replace': {'template': 'Template var1 string var2',
                                   'params': {'var1': 'foo', 'var2': 'bar'}}}
        snippet_resolved = 'Template foo string bar'

        tmpl = parser.Template(hot_tpl_empty)

        self.assertEqual(snippet_resolved,
                         tmpl.resolve_replace(snippet))

    def test_str_replace_number(self):
        """Test str_replace function with numbers."""

        snippet = {'str_replace': {'template': 'Template number string bar',
                                   'params': {'number': 1}}}
        snippet_resolved = 'Template 1 string bar'

        tmpl = parser.Template(hot_tpl_empty)

        self.assertEqual(snippet_resolved,
                         tmpl.resolve_replace(snippet))

    def test_str_fn_replace(self):
        """Test Fn:Replace function."""

        snippet = {'Fn::Replace': [{'$var1': 'foo', '$var2': 'bar'},
                                   'Template $var1 string $var2']}
        snippet_resolved = 'Template foo string bar'

        tmpl = parser.Template(hot_tpl_empty)

        self.assertEqual(snippet_resolved, tmpl.resolve_replace(snippet))

    def test_str_replace_syntax(self):
        """
        Test str_replace function syntax.

        Pass wrong syntax (array instead of dictionary) to function and
        validate that we get a TypeError.
        """

        snippet = {'str_replace': [{'template': 'Template var1 string var2'},
                                   {'params': {'var1': 'foo', 'var2': 'bar'}}]}

        tmpl = parser.Template(hot_tpl_empty)

        self.assertRaises(TypeError, tmpl.resolve_replace, snippet)

    def test_str_replace_invalid_param_keys(self):
        """
        Test str_replace function parameter keys.

        Pass wrong parameters to function and verify that we get
        a KeyError.
        """

        snippet = {'str_replace': {'tmpl': 'Template var1 string var2',
                                   'params': {'var1': 'foo', 'var2': 'bar'}}}

        tmpl = parser.Template(hot_tpl_empty)

        self.assertRaises(KeyError, tmpl.resolve_replace, snippet)

        snippet = {'str_replace': {'tmpl': 'Template var1 string var2',
                                   'parms': {'var1': 'foo', 'var2': 'bar'}}}

        self.assertRaises(KeyError, tmpl.resolve_replace, snippet)

    def test_str_replace_invalid_param_types(self):
        """
        Test str_replace function parameter values.

        Pass parameter values of wrong type to function and verify that we get
        a TypeError.
        """

        snippet = {'str_replace': {'template': 12345,
                                   'params': {'var1': 'foo', 'var2': 'bar'}}}

        tmpl = parser.Template(hot_tpl_empty)

        self.assertRaises(TypeError, tmpl.resolve_replace, snippet)

        snippet = {'str_replace': {'template': 'Template var1 string var2',
                                   'params': ['var1', 'foo', 'var2', 'bar']}}

        self.assertRaises(TypeError, tmpl.resolve_replace, snippet)


class StackTest(test_parser.StackTest):
    """Test stack function when stack was created from HOT template."""

    @utils.stack_delete_after
    def test_get_attr(self):
        """Test resolution of get_attr occurrences in HOT template."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: GenericResourceType
        ''')

        self.stack = parser.Stack(self.ctx, 'test_get_attr',
                                  template.Template(hot_tpl))
        self.stack.store()
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

            resolved = hot.HOTemplate.resolve_attributes(snippet, self.stack)
            # GenericResourceType has an attribute 'foo' which yields the
            # resource name.
            self.assertEqual({'Value': 'resource1'}, resolved)
            # test invalid reference
        self.assertRaises(exception.InvalidTemplateAttribute,
                          hot.HOTemplate.resolve_attributes,
                          {'Value': {'get_attr': ['resource1', 'NotThere']}},
                          self.stack)

        snippet = {'Value': {'Fn::GetAtt': ['resource1', 'foo']}}
        resolved = hot.HOTemplate.resolve_attributes(snippet, self.stack)
        self.assertEqual({'Value': 'resource1'}, resolved)

    @utils.stack_delete_after
    def test_get_resource(self):
        """Test resolution of get_resource occurrences in HOT template."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: GenericResourceType
        ''')

        self.stack = parser.Stack(self.ctx, 'test_get_resource',
                                  template.Template(hot_tpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        snippet = {'value': {'get_resource': 'resource1'}}
        resolved = hot.HOTemplate.resolve_resource_refs(snippet, self.stack)
        self.assertEqual({'value': 'resource1'}, resolved)


class HOTParamValidatorTest(HeatTestCase):
    """Test HOTParamValidator"""

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
            hot.HOTParamSchema.from_dict(schema).validate(name, value)
            return True

        value = 'wp'
        err = self.assertRaises(ValueError, v, value)
        self.assertIn(len_desc, str(err))

        value = 'abcdefghijklmnopq'
        err = self.assertRaises(ValueError, v, value)
        self.assertIn(len_desc, str(err))

        value = 'abcdefgh1'
        err = self.assertRaises(ValueError, v, value)
        self.assertIn(pattern_desc1, str(err))

        value = 'Abcdefghi'
        err = self.assertRaises(ValueError, v, value)
        self.assertIn(pattern_desc2, str(err))

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
        tmpl = parser.Template(hot_tpl)

        def run_parameters(value):
            tmpl.parameters(
                identifier.HeatIdentifier('', "stack_testit", None),
                {'db_name': value})
            return True

        value = 'wp'
        err = self.assertRaises(ValueError, run_parameters, value)
        self.assertIn(len_desc, str(err))

        value = 'abcdefghijklmnopq'
        err = self.assertRaises(ValueError, run_parameters, value)
        self.assertIn(len_desc, str(err))

        value = 'abcdefgh1'
        err = self.assertRaises(ValueError, run_parameters, value)
        self.assertIn(pattern_desc1, str(err))

        value = 'Abcdefghi'
        err = self.assertRaises(ValueError, run_parameters, value)
        self.assertIn(pattern_desc2, str(err))

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
            hot.HOTParamSchema.from_dict(schema).validate(name, value)
            return True

        value = 29999
        err = self.assertRaises(ValueError, v, value)
        self.assertIn(range_desc, str(err))

        value = 50001
        err = self.assertRaises(ValueError, v, value)
        self.assertIn(range_desc, str(err))

        value = 30000
        self.assertTrue(v(value))

        value = 40000
        self.assertTrue(v(value))

        value = 50000
        self.assertTrue(v(value))

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

        schema = param['db_port']

        err = self.assertRaises(constraints.InvalidSchemaError,
                                hot.HOTParamSchema.from_dict, schema)
        self.assertIn(range_desc, str(err))
