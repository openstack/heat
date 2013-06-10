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


class ParameterTest(testtools.TestCase):
    def test_new_string(self):
        p = parameters.Parameter('p', {'Type': 'String'})
        self.assertTrue(isinstance(p, parameters.StringParam))

    def test_new_number(self):
        p = parameters.Parameter('p', {'Type': 'Number'})
        self.assertTrue(isinstance(p, parameters.NumberParam))

    def test_new_list(self):
        p = parameters.Parameter('p', {'Type': 'CommaDelimitedList'})
        self.assertTrue(isinstance(p, parameters.CommaDelimitedListParam))

    def test_new_bad_type(self):
        self.assertRaises(ValueError, parameters.Parameter,
                          'p', {'Type': 'List'})

    def test_new_no_type(self):
        self.assertRaises(KeyError, parameters.Parameter,
                          'p', {'Default': 'blarg'})

    def test_default_no_override(self):
        p = parameters.Parameter('defaulted', {'Type': 'String',
                                               'Default': 'blarg'})
        self.assertTrue(p.has_default())
        self.assertEqual(p.default(), 'blarg')
        self.assertEqual(p.value(), 'blarg')

    def test_default_override(self):
        p = parameters.Parameter('defaulted',
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
            parameters.Parameter('p', schema, 'foo')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_no_echo_true(self):
        p = parameters.Parameter('anechoic',
                                 {'Type': 'String',
                                 'NoEcho': 'true'},
                                 'wibble')
        self.assertTrue(p.no_echo())
        self.assertNotEqual(str(p), 'wibble')

    def test_no_echo_true_caps(self):
        p = parameters.Parameter('anechoic',
                                 {'Type': 'String',
                                 'NoEcho': 'TrUe'},
                                 'wibble')
        self.assertTrue(p.no_echo())
        self.assertNotEqual(str(p), 'wibble')

    def test_no_echo_false(self):
        p = parameters.Parameter('echoic',
                                 {'Type': 'String',
                                 'NoEcho': 'false'},
                                 'wibble')
        self.assertFalse(p.no_echo())
        self.assertEqual(str(p), 'wibble')

    def test_description(self):
        description = 'Description of the parameter'
        p = parameters.Parameter('p', {'Type': 'String',
                                       'Description': description})
        self.assertEqual(p.description(), description)

    def test_no_description(self):
        p = parameters.Parameter('p', {'Type': 'String'})
        self.assertEqual(p.description(), '')

    def test_string_len_good(self):
        schema = {'Type': 'String',
                  'MinLength': '3',
                  'MaxLength': '3'}
        p = parameters.Parameter('p', schema, 'foo')
        self.assertEqual(p.value(), 'foo')

    def test_string_underflow(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'MinLength': '4'}
        try:
            parameters.Parameter('p', schema, 'foo')
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
            parameters.Parameter('p', schema, 'foo')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_string_pattern_good(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = parameters.Parameter('p', schema, 'foo')
        self.assertEqual(p.value(), 'foo')

    def test_string_pattern_bad_prefix(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedPattern': '[a-z]*'}
        try:
            parameters.Parameter('p', schema, '1foo')
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
            parameters.Parameter('p', schema, 'foo1')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_string_value_list_good(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = parameters.Parameter('p', schema, 'bar')
        self.assertEqual(p.value(), 'bar')

    def test_string_value_list_bad(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        try:
            parameters.Parameter('p', schema, 'blarg')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_number_int_good(self):
        schema = {'Type': 'Number',
                  'MinValue': '3',
                  'MaxValue': '3'}
        p = parameters.Parameter('p', schema, '3')
        self.assertEqual(p.value(), '3')

    def test_number_float_good(self):
        schema = {'Type': 'Number',
                  'MinValue': '3.0',
                  'MaxValue': '3.0'}
        p = parameters.Parameter('p', schema, '3.0')
        self.assertEqual(p.value(), '3.0')

    def test_number_low(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'MinValue': '4'}
        try:
            parameters.Parameter('p', schema, '3')
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
            parameters.Parameter('p', schema, '3')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_number_value_list_good(self):
        schema = {'Type': 'Number',
                  'AllowedValues': ['1', '3', '5']}
        p = parameters.Parameter('p', schema, '5')
        self.assertEqual(p.value(), '5')

    def test_number_value_list_bad(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['1', '3', '5']}
        try:
            parameters.Parameter('p', schema, '2')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')

    def test_list_value_list_good(self):
        schema = {'Type': 'CommaDelimitedList',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = parameters.Parameter('p', schema, 'baz,foo,bar')
        self.assertEqual(p.value(), 'baz,foo,bar')

    def test_list_value_list_bad(self):
        schema = {'Type': 'CommaDelimitedList',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        try:
            parameters.Parameter('p', schema, 'foo,baz,blarg')
        except ValueError as ve:
            msg = str(ve)
            self.assertNotEqual(msg.find('wibble'), -1)
        else:
            self.fail('ValueError not raised')


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
    def test_pseudo_params(self):
        params = parameters.Parameters('test_stack', {"Parameters": {}})

        self.assertEqual(params['AWS::StackName'], 'test_stack')
        self.assertEqual(params['AWS::StackId'], 'None')
        self.assertTrue('AWS::Region' in params)

    def test_pseudo_param_stackid(self):
        params = parameters.Parameters('test_stack', {'Parameters': {}},
                                       stack_id='123::foo')

        self.assertEqual(params['AWS::StackId'], '123::foo')
        params.set_stack_id('456::bar')
        self.assertEqual(params['AWS::StackId'], '456::bar')

    def test_user_param(self):
        user_params = {'User': 'wibble'}
        params = parameters.Parameters('test', params_schema, user_params)
        self.assertEqual(params.user_parameters(), user_params)

    def test_user_param_nonexist(self):
        params = parameters.Parameters('test', params_schema)
        self.assertEqual(params.user_parameters(), {})

    def test_schema_invariance(self):
        params1 = parameters.Parameters('test', params_schema,
                                        {'Defaulted': 'wibble'})
        self.assertEqual(params1['Defaulted'], 'wibble')

        params2 = parameters.Parameters('test', params_schema)
        self.assertEqual(params2['Defaulted'], 'foobar')

    def test_to_dict(self):
        template = {'Parameters': {'Foo': {'Type': 'String'},
                                   'Bar': {'Type': 'Number', 'Default': '42'}}}
        params = parameters.Parameters('test_params', template, {'Foo': 'foo'})

        as_dict = dict(params)
        self.assertEqual(as_dict['Foo'], 'foo')
        self.assertEqual(as_dict['Bar'], '42')
        self.assertEqual(as_dict['AWS::StackName'], 'test_params')
        self.assertTrue('AWS::Region' in as_dict)

    def test_map(self):
        template = {'Parameters': {'Foo': {'Type': 'String'},
                                   'Bar': {'Type': 'Number', 'Default': '42'}}}
        params = parameters.Parameters('test_params', template, {'Foo': 'foo'})

        expected = {'Foo': False,
                    'Bar': True,
                    'AWS::Region': True,
                    'AWS::StackId': True,
                    'AWS::StackName': True}

        self.assertEqual(params.map(lambda p: p.has_default()), expected)

    def test_map_str(self):
        template = {'Parameters': {'Foo': {'Type': 'String'},
                                   'Bar': {'Type': 'Number'}}}
        params = parameters.Parameters('test_params', template, {
            'Foo': 'foo', 'Bar': 42})

        expected = {'Foo': 'foo',
                    'Bar': '42',
                    'AWS::Region': 'ap-southeast-1',
                    'AWS::StackId': 'None',
                    'AWS::StackName': 'test_params'}

        self.assertEqual(params.map(str), expected)

    def test_unknown_params(self):
        user_params = {'Foo': 'wibble'}
        self.assertRaises(exception.UnknownUserParameter,
                          parameters.Parameters,
                          'test',
                          params_schema,
                          user_params)
