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
from heat.engine import resource
from heat.engine import hot
from heat.engine import template
from heat.engine import constraints

from heat.tests.common import HeatTestCase
from heat.tests import test_parser
from heat.tests import utils
from heat.tests import generic_resource as generic_rsrc


hot_tpl_empty = template_format.parse('''
heat_template_version: 2013-05-23
''')

hot_tpl_generic_resource = template_format.parse('''
heat_template_version: 2013-05-23
resources:
  resource1:
    type: GenericResourceType
''')

hot_tpl_complex_attrs = template_format.parse('''
heat_template_version: 2013-05-23
resources:
  resource1:
    type: ResourceWithComplexAttributesType
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
        self.assertEqual('2013-05-23', tmpl[tmpl.VERSION])
        self.assertEqual('No description', tmpl[tmpl.DESCRIPTION])
        self.assertEqual({}, tmpl[tmpl.RESOURCES])
        self.assertEqual({}, tmpl[tmpl.OUTPUTS])

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
        self.assertEqual(expected, tmpl[tmpl.RESOURCES])

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
        self.assertEqual(expected, tmpl[tmpl.OUTPUTS])

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

    def test_prevent_parameters_access(self):
        """
        Test that the parameters section can't be accesed using the template
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

        tmpl = parser.Template(hot_tpl)
        self.assertEqual(expected_description, tmpl['description'])

        err_str = "can not be accessed directly"

        #Hot template test
        keyError = self.assertRaises(KeyError, tmpl.__getitem__, 'parameters')
        self.assertIn(err_str, str(keyError))

        #CFN template test
        keyError = self.assertRaises(KeyError, tmpl.__getitem__, 'Parameters')
        self.assertIn(err_str, str(keyError))

    def test_parameters_section_not_iterable(self):
        """
        Test that the parameters section is not returned when the template is
        used as an iterable.
        """
        expected_description = "This can be accessed"
        tmpl = parser.Template({'heat_template_version': '2013-05-23',
                                'description': expected_description,
                                'parameters':
                                {'foo': {'Type': 'String', 'Required': True}}})
        self.assertEqual(expected_description, tmpl['description'])
        self.assertNotIn('parameters', tmpl.keys())


class StackTest(test_parser.StackTest):
    """Test stack function when stack was created from HOT template."""

    @utils.stack_delete_after
    def test_get_attr_multiple_rsrc_status(self):
        """Test resolution of get_attr occurrences in HOT template."""

        hot_tpl = hot_tpl_generic_resource
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

    @utils.stack_delete_after
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
                          hot.HOTemplate.resolve_attributes,
                          {'Value': {'get_attr': ['resource1', 'NotThere']}},
                          self.stack)

    @utils.stack_delete_after
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
        resolved = hot.HOTemplate.resolve_attributes(snippet, self.stack)
        self.assertEqual(snippet, resolved)

    @utils.stack_delete_after
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
        resolved = hot.HOTemplate.resolve_resource_refs(snippet, self.stack)
        self.assertEqual({'value': 'resource1'}, resolved)

    @utils.stack_delete_after
    def test_set_param_id(self):
        tmpl = parser.Template(hot_tpl_empty)
        self.stack = parser.Stack(self.ctx, 'param_id_test', tmpl)
        self.assertEqual(self.stack.parameters['OS::stack_id'], 'None')
        self.stack.store()
        stack_identifier = self.stack.identifier()
        self.assertEqual(self.stack.parameters['OS::stack_id'], self.stack.id)
        self.assertEqual(self.stack.parameters['OS::stack_id'],
                         stack_identifier.stack_id)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_set_param_id_update(self):
        tmpl = template.Template(
            {'heat_template_version': '2013-05-23',
             'resources': {'AResource': {'type': 'ResourceWithPropsType',
                           'Metadata': {'Bar': {'get_param': 'OS::stack_id'}},
                           'properties': {'Foo': 'abc'}}}})
        self.stack = parser.Stack(self.ctx, 'update_stack_id_test', tmpl)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        stack_id = self.stack.parameters['OS::stack_id']

        tmpl2 = template.Template(
            {'heat_template_version': '2013-05-23',
             'resources': {'AResource': {'type': 'ResourceWithPropsType',
                           'Metadata': {'Bar': {'get_param': 'OS::stack_id'}},
                           'properties': {'Foo': 'xyz'}}}})
        updated_stack = parser.Stack(self.ctx, 'updated_stack', tmpl2)

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'xyz')

        self.assertEqual(self.stack['AResource'].metadata['Bar'], stack_id)

    @utils.stack_delete_after
    def test_load_param_id(self):
        tmpl = parser.Template(hot_tpl_empty)
        self.stack = parser.Stack(self.ctx, 'param_load_id_test', tmpl)
        self.stack.store()
        stack_identifier = self.stack.identifier()
        self.assertEqual(self.stack.parameters['OS::stack_id'],
                         stack_identifier.stack_id)

        newstack = parser.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertEqual(newstack.parameters['OS::stack_id'],
                         stack_identifier.stack_id)


class StackAttributesTest(HeatTestCase):
    """
    Test stack get_attr function when stack was created from HOT template.
    """
    def setUp(self):
        super(StackAttributesTest, self).setUp()

        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('ResourceWithComplexAttributesType',
                                 generic_rsrc.ResourceWithComplexAttributes)

        self.m.ReplayAll()

    scenarios = [
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
        ('get_simple_object',
         dict(hot_tpl=hot_tpl_complex_attrs,
              snippet={'Value': {'get_attr': ['resource1',
                                              'simple_object',
                                              'first']}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.
                  simple_object.first})),
        ('get_complex_object',
         dict(hot_tpl=hot_tpl_complex_attrs,
              snippet={'Value': {'get_attr': ['resource1',
                                              'complex_object',
                                              'second',
                                              'key1']}},
              resource_name='resource1',
              expected={
                  'Value':
                  generic_rsrc.ResourceWithComplexAttributes.
                  complex_object.second['key1']})),
        ('get_complex_object_invalid_argument',
         dict(hot_tpl=hot_tpl_complex_attrs,
              snippet={'Value': {'get_attr': ['resource1',
                                              'complex_object',
                                              'not_there']}},
              resource_name='resource1',
              expected={'Value': ''})),
        ('get_attr_none',
         dict(hot_tpl=hot_tpl_complex_attrs,
              snippet={'Value': {'get_attr': ['resource1',
                                              'none',
                                              'who_cares']}},
              resource_name='resource1',
              expected={'Value': ''}))
    ]

    @utils.stack_delete_after
    def test_get_attr(self):
        """Test resolution of get_attr occurrences in HOT template."""

        self.stack = parser.Stack(self.ctx, 'test_get_attr',
                                  template.Template(self.hot_tpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        rsrc = self.stack[self.resource_name]
        for action, status in (
                (rsrc.CREATE, rsrc.IN_PROGRESS),
                (rsrc.CREATE, rsrc.COMPLETE),
                (rsrc.RESUME, rsrc.IN_PROGRESS),
                (rsrc.RESUME, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.IN_PROGRESS),
                (rsrc.UPDATE, rsrc.COMPLETE)):
            rsrc.state_set(action, status)

            resolved = hot.HOTemplate.resolve_attributes(self.snippet,
                                                         self.stack)
            self.assertEqual(self.expected, resolved)


class StackParametersTest(HeatTestCase):
    """
    Test stack get_param function when stack was created from HOT template.
    """
    class AnObject(object):
        def __init__(self, first, second, third):
            self.first = first
            self.second = second
            self.third = third

    simple_object = AnObject('a', 'b', 'c')
    complex_object = AnObject('a',
                              {'key1': 'val1', 'key2': 'val2', 'key3': 'val3'},
                              simple_object)

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
         dict(params={'list': ['foo', 'bar']},
              snippet={'properties': {'prop1': {'get_param': ['list', 1]}}},
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
        ('get_simple_object',
         dict(params={'simple_object': simple_object},
              snippet={'properties': {'prop1': {'get_param':
                                                ['simple_object',
                                                 'first']}}},
              expected={'properties': {'prop1': 'a'}})),
        ('get_complex_object',
         dict(params={'complex_object': complex_object},
              snippet={'properties': {'prop1': {'get_param':
                                                ['complex_object',
                                                 'second',
                                                 'key1']}}},
              expected={'properties': {'prop1': 'val1'}})),
        ('get_complex_object_invalid_argument',
         dict(params={'complex_object': complex_object},
              snippet={'properties': {'prop1': {'get_param':
                                                ['complex_object',
                                                 'not_there']}}},
              expected={'properties': {'prop1': ''}})),
        ('get_attr_none',
         dict(params={'none': None},
              snippet={'properties': {'prop1': {'get_param':
                                                ['none',
                                                 'who_cares']}}},
              expected={'properties': {'prop1': ''}})),
    ]

    def test_param_refs(self):
        """Test if parameter references work."""
        tmpl = parser.Template(hot_tpl_empty)
        self.assertEqual(self.expected,
                         tmpl.resolve_param_refs(self.snippet, self.params))


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
