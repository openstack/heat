
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

import testtools

from heat.common import exception
from heat.common import identifier
from heat.engine import constraints as constr
from heat.engine import parameters
from heat.engine import template


class ParameterTest(testtools.TestCase):

    def new_parameter(self, name, schema, value=None,
                      validate_value=True):
        tmpl = template.Template({'Parameters': {name: schema}})
        schema = tmpl.param_schemata()[name]
        param = parameters.Parameter(name, schema, value)
        param.validate(validate_value)
        return param

    def test_new_string(self):
        p = self.new_parameter('p', {'Type': 'String'}, validate_value=False)
        self.assertIsInstance(p, parameters.StringParam)

    def test_new_number(self):
        p = self.new_parameter('p', {'Type': 'Number'}, validate_value=False)
        self.assertIsInstance(p, parameters.NumberParam)

    def test_new_list(self):
        p = self.new_parameter('p', {'Type': 'CommaDelimitedList'},
                               validate_value=False)
        self.assertIsInstance(p, parameters.CommaDelimitedListParam)

    def test_new_json(self):
        p = self.new_parameter('p', {'Type': 'Json'}, validate_value=False)
        self.assertIsInstance(p, parameters.JsonParam)

    def test_new_bad_type(self):
        self.assertRaises(constr.InvalidSchemaError, self.new_parameter, 'p',
                          {'Type': 'List'}, validate_value=False)

    def test_default_no_override(self):
        p = self.new_parameter('defaulted', {'Type': 'String',
                                             'Default': 'blarg'})
        self.assertTrue(p.has_default())
        self.assertEqual('blarg', p.default())
        self.assertEqual('blarg', p.value())

    def test_default_override(self):
        p = self.new_parameter('defaulted',
                               {'Type': 'String',
                                'Default': 'blarg'},
                               'wibble')
        self.assertTrue(p.has_default())
        self.assertEqual('blarg', p.default())
        self.assertEqual('wibble', p.value())

    def test_default_invalid(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo'],
                  'ConstraintDescription': 'wibble',
                  'Default': 'bar'}
        err = self.assertRaises(constr.InvalidSchemaError,
                                self.new_parameter, 'p', schema, 'foo')
        self.assertIn('wibble', str(err))

    def test_no_echo_true(self):
        p = self.new_parameter('anechoic',
                               {'Type': 'String',
                                'NoEcho': 'true'},
                               'wibble')
        self.assertTrue(p.hidden())
        self.assertNotEqual(str(p), 'wibble')

    def test_no_echo_true_caps(self):
        p = self.new_parameter('anechoic',
                               {'Type': 'String',
                                'NoEcho': 'TrUe'},
                               'wibble')
        self.assertTrue(p.hidden())
        self.assertNotEqual(str(p), 'wibble')

    def test_no_echo_false(self):
        p = self.new_parameter('echoic',
                               {'Type': 'String',
                                'NoEcho': 'false'},
                               'wibble')
        self.assertFalse(p.hidden())
        self.assertEqual('wibble', str(p))

    def test_description(self):
        description = 'Description of the parameter'
        p = self.new_parameter('p', {'Type': 'String',
                                     'Description': description},
                               validate_value=False)
        self.assertEqual(description, p.description())

    def test_no_description(self):
        p = self.new_parameter('p', {'Type': 'String'}, validate_value=False)
        self.assertEqual('', p.description())

    def test_string_len_good(self):
        schema = {'Type': 'String',
                  'MinLength': '3',
                  'MaxLength': '3'}
        p = self.new_parameter('p', schema, 'foo')
        self.assertEqual('foo', p.value())

    def test_string_underflow(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'MinLength': '4'}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, 'foo')
        self.assertIn('wibble', str(err))

    def test_string_overflow(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'MaxLength': '2'}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, 'foo')
        self.assertIn('wibble', str(err))

    def test_string_pattern_good(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = self.new_parameter('p', schema, 'foo')
        self.assertEqual('foo', p.value())

    def test_string_pattern_bad_prefix(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedPattern': '[a-z]*'}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, '1foo')
        self.assertIn('wibble', str(err))

    def test_string_pattern_bad_suffix(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedPattern': '[a-z]*'}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, 'foo1')
        self.assertIn('wibble', str(err))

    def test_string_value_list_good(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = self.new_parameter('p', schema, 'bar')
        self.assertEqual('bar', p.value())

    def test_string_value_unicode(self):
        schema = {'Type': 'String'}
        p = self.new_parameter('p', schema, u'test\u2665')
        self.assertEqual(u'test\u2665', p.value())

    def test_string_value_list_bad(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, 'blarg')
        self.assertIn('wibble', str(err))

    def test_number_int_good(self):
        schema = {'Type': 'Number',
                  'MinValue': '3',
                  'MaxValue': '3'}
        p = self.new_parameter('p', schema, '3')
        self.assertEqual(3, p.value())

    def test_number_float_good(self):
        schema = {'Type': 'Number',
                  'MinValue': '3.0',
                  'MaxValue': '4.0'}
        p = self.new_parameter('p', schema, '3.5')
        self.assertEqual(3.5, p.value())

    def test_number_low(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'MinValue': '4'}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, '3')
        self.assertIn('wibble', str(err))

    def test_number_high(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'MaxValue': '2'}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, '3')
        self.assertIn('wibble', str(err))

    def test_number_value_list_good(self):
        schema = {'Type': 'Number',
                  'AllowedValues': ['1', '3', '5']}
        p = self.new_parameter('p', schema, '5')
        self.assertEqual(5, p.value())

    def test_number_value_list_bad(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['1', '3', '5']}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, '2')
        self.assertIn('wibble', str(err))

    def test_list_value_list_good(self):
        schema = {'Type': 'CommaDelimitedList',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = self.new_parameter('p', schema, 'baz,foo,bar')
        self.assertEqual('baz,foo,bar'.split(','), p.value())
        schema['Default'] = []
        p = self.new_parameter('p', schema)
        self.assertEqual([], p.value())
        schema['Default'] = 'baz,foo,bar'
        p = self.new_parameter('p', schema)
        self.assertEqual('baz,foo,bar'.split(','), p.value())

    def test_list_value_list_bad(self):
        schema = {'Type': 'CommaDelimitedList',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        err = self.assertRaises(ValueError, self.new_parameter,
                                'p', schema, 'foo,baz,blarg')
        self.assertIn('wibble', str(err))

    def test_map_value(self):
        '''Happy path for value thats already a map.'''
        schema = {'Type': 'Json'}
        val = {"foo": "bar", "items": [1, 2, 3]}
        p = self.new_parameter('p', schema, val)
        self.assertEqual(val, p.value())
        self.assertEqual(val, p.parsed)

    def test_map_value_bad(self):
        '''Map value is not JSON parsable.'''
        schema = {'Type': 'Json',
                  'ConstraintDescription': 'wibble'}
        val = {"foo": "bar", "not_json": len}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, val)
        self.assertIn('Value must be valid JSON', str(err))

    def test_map_value_parse(self):
        '''Happy path for value that's a string.'''
        schema = {'Type': 'Json'}
        val = {"foo": "bar", "items": [1, 2, 3]}
        val_s = json.dumps(val)
        p = self.new_parameter('p', schema, val_s)
        self.assertEqual(val, p.value())
        self.assertEqual(val, p.parsed)

    def test_map_value_bad_parse(self):
        '''Test value error for unparsable string value.'''
        schema = {'Type': 'Json',
                  'ConstraintDescription': 'wibble'}
        val = "I am not a map"
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, val)
        self.assertIn('Value must be valid JSON', str(err))

    def test_map_underrun(self):
        '''Test map length under MIN_LEN.'''
        schema = {'Type': 'Json',
                  'MinLength': 3}
        val = {"foo": "bar", "items": [1, 2, 3]}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, val)
        self.assertIn('out of range', str(err))

    def test_map_overrun(self):
        '''Test map length over MAX_LEN.'''
        schema = {'Type': 'Json',
                  'MaxLength': 1}
        val = {"foo": "bar", "items": [1, 2, 3]}
        err = self.assertRaises(ValueError,
                                self.new_parameter, 'p', schema, val)
        self.assertIn('out of range', str(err))

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
        params = tmpl.parameters(
            identifier.HeatIdentifier('', stack_name, stack_id),
            user_params)
        params.validate(validate_value)
        return params

    def test_pseudo_params(self):
        stack_name = 'test_stack'
        params = self.new_parameters(stack_name, {"Parameters": {}})

        self.assertEqual('test_stack', params['AWS::StackName'])
        self.assertEqual(
            'arn:openstack:heat:::stacks/{0}/{1}'.format(stack_name, 'None'),
            params['AWS::StackId'])

        self.assertIn('AWS::Region', params)

    def test_pseudo_param_stackid(self):
        stack_name = 'test_stack'
        params = self.new_parameters(stack_name, {'Parameters': {}},
                                     stack_id='abc123')

        self.assertEqual(
            'arn:openstack:heat:::stacks/{0}/{1}'.format(stack_name, 'abc123'),
            params['AWS::StackId'])
        stack_identifier = identifier.HeatIdentifier('', '', 'def456')
        params.set_stack_id(stack_identifier)
        self.assertEqual(stack_identifier.arn(), params['AWS::StackId'])

    def test_schema_invariance(self):
        params1 = self.new_parameters('test', params_schema,
                                      {'User': 'foo',
                                       'Defaulted': 'wibble'})
        self.assertEqual('wibble', params1['Defaulted'])

        params2 = self.new_parameters('test', params_schema, {'User': 'foo'})
        self.assertEqual('foobar', params2['Defaulted'])

    def test_to_dict(self):
        template = {'Parameters': {'Foo': {'Type': 'String'},
                                   'Bar': {'Type': 'Number', 'Default': '42'}}}
        params = self.new_parameters('test_params', template, {'Foo': 'foo'})

        as_dict = dict(params)
        self.assertEqual('foo', as_dict['Foo'])
        self.assertEqual(42, as_dict['Bar'])
        self.assertEqual('test_params', as_dict['AWS::StackName'])
        self.assertIn('AWS::Region', as_dict)

    def test_map(self):
        template = {'Parameters': {'Foo': {'Type': 'String'},
                                   'Bar': {'Type': 'Number', 'Default': '42'}}}
        params = self.new_parameters('test_params', template, {'Foo': 'foo'})

        expected = {'Foo': False,
                    'Bar': True,
                    'AWS::Region': True,
                    'AWS::StackId': True,
                    'AWS::StackName': True}

        self.assertEqual(expected, params.map(lambda p: p.has_default()))

    def test_map_str(self):
        template = {'Parameters': {'Foo': {'Type': 'String'},
                                   'Bar': {'Type': 'Number'},
                                   'Uni': {'Type': 'String'}}}
        stack_name = 'test_params'
        params = self.new_parameters(stack_name, template,
                                     {'Foo': 'foo',
                                      'Bar': '42',
                                      'Uni': u'test\u2665'})

        expected = {'Foo': 'foo',
                    'Bar': '42',
                    'Uni': 'test\xe2\x99\xa5',
                    'AWS::Region': 'ap-southeast-1',
                    'AWS::StackId':
                    'arn:openstack:heat:::stacks/{0}/{1}'.format(
                        stack_name,
                        'None'),
                    'AWS::StackName': 'test_params'}

        self.assertEqual(expected, params.map(str))

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
        self.assertRaises(constr.InvalidSchemaError,
                          self.new_parameters,
                          'test',
                          params)


class ParameterSchemaTest(testtools.TestCase):

    def test_validate_schema_wrong_key(self):
        error = self.assertRaises(constr.InvalidSchemaError,
                                  parameters.Schema.from_dict, {"foo": "bar"})
        self.assertEqual("Invalid key 'foo' for parameter", str(error))

    def test_validate_schema_no_type(self):
        error = self.assertRaises(constr.InvalidSchemaError,
                                  parameters.Schema.from_dict,
                                  {"Description": "Hi!"})
        self.assertEqual("Missing parameter type", str(error))
