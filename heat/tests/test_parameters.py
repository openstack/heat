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


import testtools
import json

from heat.common import exception
from heat.engine import parameters
from heat.engine import template


class ParameterTest(testtools.TestCase):

    def new_parameter(self, name, schema, value=None,
                      validate_value=True):
        tmpl = template.Template({template.PARAMETERS: {name:
                                                        schema}})
        schema = tmpl.param_schemata()[name]
        return parameters.Parameter(name, schema, value,
                                    validate_value)

    def test_new_string(self):
        p = self.new_parameter('p', {'Type': 'String'}, validate_value=False)
        self.assertTrue(isinstance(p, parameters.StringParam))

    def test_new_number(self):
        p = self.new_parameter('p', {'Type': 'Number'}, validate_value=False)
        self.assertTrue(isinstance(p, parameters.NumberParam))

    def test_new_list(self):
        p = self.new_parameter('p', {'Type': 'CommaDelimitedList'},
                               validate_value=False)
        self.assertTrue(isinstance(p, parameters.CommaDelimitedListParam))

    def test_new_json(self):
        p = self.new_parameter('p', {'Type': 'Json'}, validate_value=False)
        self.assertTrue(isinstance(p, parameters.JsonParam))

    def test_new_bad_type(self):
        self.assertRaises(ValueError, self.new_parameter, 'p',
                          {'Type': 'List'})

    def test_new_no_type(self):
        self.assertRaises(KeyError, self.new_parameter,
                          'p', {'Default': 'blarg'})

    def test_default_no_override(self):
        p = self.new_parameter('defaulted', {'Type': 'String',
                                             'Default': 'blarg'})
        self.assertTrue(p.has_default())
        self.assertEqual(p.default(), 'blarg')
        self.assertEqual(p.value(), 'blarg')

    def test_default_override(self):
        p = self.new_parameter('defaulted',
                               {'Type': 'String',
                                'Default': 'blarg'},
                               'wibble')
        self.assertTrue(p.has_default())
        self.assertEqual(p.default(), 'blarg')
        self.assertEqual(p.value(), 'wibble')

    def test_default_invalid(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo'],
                  'ConstraintDescription': 'wibble',
                  'Default': 'bar'}
        try:
            self.new_parameter('p', schema, 'foo')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_no_echo_true(self):
        p = self.new_parameter('anechoic',
                               {'Type': 'String',
                                'NoEcho': 'true'},
                               'wibble')
        self.assertTrue(p.no_echo())
        self.assertNotEqual(str(p), 'wibble')

    def test_no_echo_true_caps(self):
        p = self.new_parameter('anechoic',
                               {'Type': 'String',
                                'NoEcho': 'TrUe'},
                               'wibble')
        self.assertTrue(p.no_echo())
        self.assertNotEqual(str(p), 'wibble')

    def test_no_echo_false(self):
        p = self.new_parameter('echoic',
                               {'Type': 'String',
                                'NoEcho': 'false'},
                               'wibble')
        self.assertFalse(p.no_echo())
        self.assertEqual(str(p), 'wibble')

    def test_description(self):
        description = 'Description of the parameter'
        p = self.new_parameter('p', {'Type': 'String',
                                     'Description': description},
                               validate_value=False)
        self.assertEqual(p.description(), description)

    def test_no_description(self):
        p = self.new_parameter('p', {'Type': 'String'}, validate_value=False)
        self.assertEqual(p.description(), '')

    def test_string_len_good(self):
        schema = {'Type': 'String',
                  'MinLength': '3',
                  'MaxLength': '3'}
        p = self.new_parameter('p', schema, 'foo')
        self.assertEqual(p.value(), 'foo')

    def test_string_underflow(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'MinLength': '4'}
        try:
            self.new_parameter('p', schema, 'foo')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_string_overflow(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'MaxLength': '2'}
        try:
            self.new_parameter('p', schema, 'foo')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_string_pattern_good(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = self.new_parameter('p', schema, 'foo')
        self.assertEqual(p.value(), 'foo')

    def test_string_pattern_bad_prefix(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedPattern': '[a-z]*'}
        try:
            self.new_parameter('p', schema, '1foo')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_string_pattern_bad_suffix(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedPattern': '[a-z]*'}
        try:
            self.new_parameter('p', schema, 'foo1')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_string_value_list_good(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = self.new_parameter('p', schema, 'bar')
        self.assertEqual(p.value(), 'bar')

    def test_string_value_list_bad(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        try:
            self.new_parameter('p', schema, 'blarg')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_number_int_good(self):
        schema = {'Type': 'Number',
                  'MinValue': '3',
                  'MaxValue': '3'}
        p = self.new_parameter('p', schema, '3')
        self.assertEqual(p.value(), 3)

    def test_number_float_good(self):
        schema = {'Type': 'Number',
                  'MinValue': '3.0',
                  'MaxValue': '4.0'}
        p = self.new_parameter('p', schema, '3.5')
        self.assertEqual(p.value(), 3.5)

    def test_number_low(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'MinValue': '4'}
        try:
            self.new_parameter('p', schema, '3')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_number_high(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'MaxValue': '2'}
        try:
            self.new_parameter('p', schema, '3')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_number_value_list_good(self):
        schema = {'Type': 'Number',
                  'AllowedValues': ['1', '3', '5']}
        p = self.new_parameter('p', schema, '5')
        self.assertEqual(p.value(), 5)

    def test_number_value_list_bad(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['1', '3', '5']}
        try:
            self.new_parameter('p', schema, '2')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_list_value_list_good(self):
        schema = {'Type': 'CommaDelimitedList',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = self.new_parameter('p', schema, 'baz,foo,bar')
        self.assertEqual(p.value(), 'baz,foo,bar'.split(','))
        schema['Default'] = []
        p = self.new_parameter('p', schema)
        self.assertEqual(p.value(), [])
        schema['Default'] = 'baz,foo,bar'
        p = self.new_parameter('p', schema)
        self.assertEqual(p.value(), 'baz,foo,bar'.split(','))

    def test_list_value_list_bad(self):
        schema = {'Type': 'CommaDelimitedList',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        try:
            self.new_parameter('p', schema, 'foo,baz,blarg')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_map_value(self):
        '''Happy path for value thats already a map.'''
        schema = {'Type': 'Json'}
        val = {"foo": "bar", "items": [1, 2, 3]}
        val_s = json.dumps(val)
        p = self.new_parameter('p', schema, val)
        self.assertEqual(val_s, p.value())
        self.assertEqual(val, p.parsed)

    def test_map_value_bad(self):
        '''Map value is not JSON parsable.'''
        schema = {'Type': 'Json',
                  'ConstraintDescription': 'wibble'}
        val = {"foo": "bar", "not_json": len}
        try:
            self.new_parameter('p', schema, val)
        except ValueError as verr:
            self.assertIn('Value must be valid JSON', str(verr))
        else:
            self.fail("Value error not raised")

    def test_map_value_parse(self):
        '''Happy path for value that's a string.'''
        schema = {'Type': 'Json'}
        val = {"foo": "bar", "items": [1, 2, 3]}
        val_s = json.dumps(val)
        p = self.new_parameter('p', schema, val_s)
        self.assertEqual(val_s, p.value())
        self.assertEqual(val, p.parsed)

    def test_map_value_bad_parse(self):
        '''Test value error for unparsable string value.'''
        schema = {'Type': 'Json',
                  'ConstraintDescription': 'wibble'}
        val = "I am not a map"
        try:
            self.new_parameter('p', schema, val)
        except ValueError as verr:
            self.assertIn('Value must be valid JSON', str(verr))
        else:
            self.fail("Value error not raised")

    def test_map_values_good(self):
        '''Happy path for map keys.'''
        schema = {'Type': 'Json',
                  'AllowedValues': ["foo", "bar", "baz"]}
        val = {"foo": "bar", "baz": [1, 2, 3]}
        val_s = json.dumps(val)
        p = self.new_parameter('p', schema, val_s)
        self.assertEqual(val_s, p.value())
        self.assertEqual(val, p.parsed)

    def test_map_values_bad(self):
        '''Test failure of invalid map keys.'''
        schema = {'Type': 'Json',
                  'AllowedValues': ["foo", "bar", "baz"]}
        val = {"foo": "bar", "items": [1, 2, 3]}
        try:
            self.new_parameter('p', schema, val)
        except ValueError as verr:
            self.assertIn("items", str(verr))
        else:
            self.fail("Value error not raised")

    def test_map_underrun(self):
        '''Test map length under MIN_LEN.'''
        schema = {'Type': 'Json',
                  'MinLength': 3}
        val = {"foo": "bar", "items": [1, 2, 3]}
        try:
            self.new_parameter('p', schema, val)
        except ValueError as verr:
            self.assertIn('underflows', str(verr))
        else:
            self.fail("Value error not raised")

    def test_map_overrun(self):
        '''Test map length over MAX_LEN.'''
        schema = {'Type': 'Json',
                  'MaxLength': 1}
        val = {"foo": "bar", "items": [1, 2, 3]}
        try:
            self.new_parameter('p', schema, val)
        except ValueError as verr:
            self.assertIn('overflows', str(verr))
        else:
            self.fail("Value error not raised")

    def test_missing_param(self):
        '''Test missing user parameter.'''
        self.assertRaises(exception.UserParameterMissing,
                          self.new_parameter, 'p',
                          {'Type': 'String'})


params_schema = json.loads('''{
  "Parameters" : {
    "User" : { "Type": "String" },
    "Defaulted" : {
      "Type": "String",
      "Default": "foobar"
    }
  }
}''')


class ParametersTest(testtools.TestCase):
    def new_parameters(self, stack_name, tmpl, user_params={}, stack_id=None,
                       validate_value=True):
        tmpl = template.Template(tmpl)
        return parameters.Parameters(stack_name, tmpl, user_params, stack_id,
                                     validate_value)

    def test_pseudo_params(self):
        params = self.new_parameters('test_stack', {"Parameters": {}})

        self.assertEqual(params['AWS::StackName'], 'test_stack')
        self.assertEqual(params['AWS::StackId'], 'None')
        self.assertTrue('AWS::Region' in params)

    def test_pseudo_param_stackid(self):
        params = self.new_parameters('test_stack', {'Parameters': {}},
                                     stack_id='123::foo')

        self.assertEqual(params['AWS::StackId'], '123::foo')
        params.set_stack_id('456::bar')
        self.assertEqual(params['AWS::StackId'], '456::bar')

    def test_schema_invariance(self):
        params1 = self.new_parameters('test', params_schema,
                                      {'User': 'foo',
                                       'Defaulted': 'wibble'})
        self.assertEqual(params1['Defaulted'], 'wibble')

        params2 = self.new_parameters('test', params_schema, {'User': 'foo'})
        self.assertEqual(params2['Defaulted'], 'foobar')

    def test_to_dict(self):
        template = {'Parameters': {'Foo': {'Type': 'String'},
                                   'Bar': {'Type': 'Number', 'Default': '42'}}}
        params = self.new_parameters('test_params', template, {'Foo': 'foo'})

        as_dict = dict(params)
        self.assertEqual(as_dict['Foo'], 'foo')
        self.assertEqual(as_dict['Bar'], 42)
        self.assertEqual(as_dict['AWS::StackName'], 'test_params')
        self.assertTrue('AWS::Region' in as_dict)

    def test_map(self):
        template = {'Parameters': {'Foo': {'Type': 'String'},
                                   'Bar': {'Type': 'Number', 'Default': '42'}}}
        params = self.new_parameters('test_params', template, {'Foo': 'foo'})

        expected = {'Foo': False,
                    'Bar': True,
                    'AWS::Region': True,
                    'AWS::StackId': True,
                    'AWS::StackName': True}

        self.assertEqual(params.map(lambda p: p.has_default()), expected)

    def test_map_str(self):
        template = {'Parameters': {'Foo': {'Type': 'String'},
                                   'Bar': {'Type': 'Number'}}}
        params = self.new_parameters('test_params', template,
                                     {'Foo': 'foo', 'Bar': '42'})

        expected = {'Foo': 'foo',
                    'Bar': '42',
                    'AWS::Region': 'ap-southeast-1',
                    'AWS::StackId': 'None',
                    'AWS::StackName': 'test_params'}

        self.assertEqual(params.map(str), expected)

    def test_unknown_params(self):
        user_params = {'Foo': 'wibble'}
        self.assertRaises(exception.UnknownUserParameter,
                          self.new_parameters,
                          'test',
                          params_schema,
                          user_params)

    def test_missing_params(self):
        user_params = {}
        self.assertRaises(exception.UserParameterMissing,
                          self.new_parameters,
                          'test',
                          params_schema,
                          user_params)

    def test_missing_attribute_params(self):
        params = {'Parameters': {'Foo': {'Type': 'String'},
                                 'NoAttr': 'No attribute.',
                                 'Bar': {'Type': 'Number', 'Default': '1'}}}
        self.assertRaises(exception.InvalidTemplateParameter,
                          self.new_parameters,
                          'test',
                          params)
