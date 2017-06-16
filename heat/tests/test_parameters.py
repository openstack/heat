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

from oslo_serialization import jsonutils as json
import six

from heat.common import exception
from heat.common import identifier
from heat.engine import parameters
from heat.engine import template
from heat.tests import common


def new_parameter(name, schema, value=None, validate_value=True):
    tmpl = template.Template({'HeatTemplateFormatVersion': '2012-12-12',
                              'Parameters': {name: schema}})
    schema = tmpl.param_schemata()[name]
    param = parameters.Parameter(name, schema, value)
    param.validate(validate_value)
    return param


class ParameterTestCommon(common.HeatTestCase):
    scenarios = [
        ('type_string', dict(p_type='String',
                             inst=parameters.StringParam,
                             value='test',
                             expected='test',
                             allowed_value=['foo'],
                             zero='',
                             default='default')),
        ('type_number', dict(p_type='Number',
                             inst=parameters.NumberParam,
                             value=10,
                             expected='10',
                             allowed_value=[42],
                             zero=0,
                             default=13)),
        ('type_list', dict(p_type='CommaDelimitedList',
                           inst=parameters.CommaDelimitedListParam,
                           value=['a', 'b', 'c'],
                           expected='a,b,c',
                           allowed_value=['foo'],
                           zero=[],
                           default=['d', 'e', 'f'])),
        ('type_json', dict(p_type='Json',
                           inst=parameters.JsonParam,
                           value={'a': '1'},
                           expected='{"a": "1"}',
                           allowed_value=[{'foo': 'bar'}],
                           zero={},
                           default={'d': '1'})),
        ('type_int_json', dict(p_type='Json',
                               inst=parameters.JsonParam,
                               value={'a': 1},
                               expected='{"a": 1}',
                               allowed_value=[{'foo': 'bar'}],
                               zero={},
                               default={'d': 1})),
        ('type_boolean', dict(p_type='Boolean',
                              inst=parameters.BooleanParam,
                              value=True,
                              expected='True',
                              allowed_value=[False],
                              zero=False,
                              default=True)),
        ('type_int_string', dict(p_type='String',
                                 inst=parameters.StringParam,
                                 value='111',
                                 expected='111',
                                 allowed_value=['111'],
                                 zero='',
                                 default='0')),
        ('type_string_json', dict(p_type='Json',
                                  inst=parameters.JsonParam,
                                  value={'1': 1},
                                  expected='{"1": 1}',
                                  allowed_value=[{'2': '2'}],
                                  zero={},
                                  default={'3': 3}))
    ]

    def test_new_param(self):
        p = new_parameter('p', {'Type': self.p_type}, validate_value=False)
        self.assertIsInstance(p, self.inst)

    def test_param_to_str(self):
        p = new_parameter('p', {'Type': self.p_type}, self.value)
        if self.p_type == 'Json':
            self.assertEqual(json.loads(self.expected), json.loads(str(p)))
        else:
            self.assertEqual(self.expected, str(p))

    def test_default_no_override(self):
        p = new_parameter('defaulted', {'Type': self.p_type,
                                        'Default': self.default})
        self.assertTrue(p.has_default())
        self.assertEqual(self.default, p.default())
        self.assertEqual(self.default, p.value())

    def test_default_override(self):
        p = new_parameter('defaulted', {'Type': self.p_type,
                                        'Default': self.default},
                          self.value)
        self.assertTrue(p.has_default())
        self.assertEqual(self.default, p.default())
        self.assertEqual(self.value, p.value())

    def test_default_invalid(self):
        schema = {'Type': self.p_type,
                  'AllowedValues': self.allowed_value,
                  'ConstraintDescription': 'wibble',
                  'Default': self.default}
        if self.p_type == 'Json':
            err = self.assertRaises(exception.InvalidSchemaError,
                                    new_parameter, 'p', schema)
            self.assertIn('AllowedValues constraint invalid for Json',
                          six.text_type(err))
        else:
            err = self.assertRaises(exception.InvalidSchemaError,
                                    new_parameter, 'p', schema)
            self.assertIn('wibble', six.text_type(err))

    def test_description(self):
        description = 'Description of the parameter'
        p = new_parameter('p', {'Type': self.p_type,
                                'Description': description},
                          validate_value=False)
        self.assertEqual(description, p.description())

    def test_no_description(self):
        p = new_parameter('p', {'Type': self.p_type}, validate_value=False)
        self.assertEqual('', p.description())

    def test_no_echo_true(self):
        p = new_parameter('anechoic', {'Type': self.p_type,
                                       'NoEcho': 'true'},
                          self.value)
        self.assertTrue(p.hidden())
        self.assertEqual('******', str(p))

    def test_no_echo_true_caps(self):
        p = new_parameter('anechoic', {'Type': self.p_type,
                                       'NoEcho': 'TrUe'},
                          self.value)
        self.assertTrue(p.hidden())
        self.assertEqual('******', str(p))

    def test_no_echo_false(self):
        p = new_parameter('echoic', {'Type': self.p_type,
                                     'NoEcho': 'false'},
                          self.value)
        self.assertFalse(p.hidden())
        if self.p_type == 'Json':
            self.assertEqual(json.loads(self.expected), json.loads(str(p)))
        else:
            self.assertEqual(self.expected, str(p))

    def test_default_empty(self):
        p = new_parameter('defaulted', {'Type': self.p_type,
                                        'Default': self.zero})
        self.assertTrue(p.has_default())
        self.assertEqual(self.zero, p.default())
        self.assertEqual(self.zero, p.value())

    def test_default_no_empty_user_value_empty(self):
        p = new_parameter('defaulted', {'Type': self.p_type,
                                        'Default': self.default},
                          self.zero)
        self.assertTrue(p.has_default())
        self.assertEqual(self.default, p.default())
        self.assertEqual(self.zero, p.value())


class ParameterTestSpecific(common.HeatTestCase):
    def test_new_bad_type(self):
        self.assertRaises(exception.InvalidSchemaError, new_parameter,
                          'p', {'Type': 'List'}, validate_value=False)

    def test_string_len_good(self):
        schema = {'Type': 'String',
                  'MinLength': '3',
                  'MaxLength': '3'}
        p = new_parameter('p', schema, 'foo')
        self.assertEqual('foo', p.value())

    def test_string_underflow(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'MinLength': '4'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, 'foo')
        self.assertIn('wibble', six.text_type(err))

    def test_string_overflow(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'MaxLength': '2'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, 'foo')
        self.assertIn('wibble', six.text_type(err))

    def test_string_pattern_good(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = new_parameter('p', schema, 'foo')
        self.assertEqual('foo', p.value())

    def test_string_pattern_bad_prefix(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedPattern': '[a-z]*'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, '1foo')
        self.assertIn('wibble', six.text_type(err))

    def test_string_pattern_bad_suffix(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedPattern': '[a-z]*'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, 'foo1')
        self.assertIn('wibble', six.text_type(err))

    def test_string_value_list_good(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = new_parameter('p', schema, 'bar')
        self.assertEqual('bar', p.value())

    def test_string_value_unicode(self):
        schema = {'Type': 'String'}
        p = new_parameter('p', schema, u'test\u2665')
        self.assertEqual(u'test\u2665', p.value())

    def test_string_value_list_bad(self):
        schema = {'Type': 'String',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, 'blarg')
        self.assertIn('wibble', six.text_type(err))

    def test_number_int_good(self):
        schema = {'Type': 'Number',
                  'MinValue': '3',
                  'MaxValue': '3'}
        p = new_parameter('p', schema, '3')
        self.assertEqual(3, p.value())

    def test_number_float_good_string(self):
        schema = {'Type': 'Number',
                  'MinValue': '3.0',
                  'MaxValue': '4.0'}
        p = new_parameter('p', schema, '3.5')
        self.assertEqual(3.5, p.value())

    def test_number_float_good_number(self):
        schema = {'Type': 'Number',
                  'MinValue': '3.0',
                  'MaxValue': '4.0'}
        p = new_parameter('p', schema, 3.5)
        self.assertEqual(3.5, p.value())

    def test_number_low(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'MinValue': '4'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, '3')
        self.assertIn('wibble', six.text_type(err))

    def test_number_high(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'MaxValue': '2'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, '3')
        self.assertIn('wibble', six.text_type(err))

    def test_number_bad(self):
        schema = {'Type': 'Number'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, 'str')
        self.assertIn('float', six.text_type(err))

    def test_number_bad_type(self):
        schema = {'Type': 'Number'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, ['foo'])
        self.assertIn('int', six.text_type(err))

    def test_number_value_list_good(self):
        schema = {'Type': 'Number',
                  'AllowedValues': ['1', '3', '5']}
        p = new_parameter('p', schema, '5')
        self.assertEqual(5, p.value())

    def test_number_value_list_bad(self):
        schema = {'Type': 'Number',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['1', '3', '5']}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, '2')
        self.assertIn('wibble', six.text_type(err))

    def test_list_value_list_default_empty(self):
        schema = {'Type': 'CommaDelimitedList', 'Default': ''}
        p = new_parameter('p', schema)
        self.assertEqual([], p.value())

    def test_list_value_list_good(self):
        schema = {'Type': 'CommaDelimitedList',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = new_parameter('p', schema, 'baz,foo,bar')
        self.assertEqual('baz,foo,bar'.split(','), p.value())
        schema['Default'] = []
        p = new_parameter('p', schema)
        self.assertEqual([], p.value())
        schema['Default'] = 'baz,foo,bar'
        p = new_parameter('p', schema)
        self.assertEqual('baz,foo,bar'.split(','), p.value())
        schema['AllowedValues'] = ['1', '3', '5']
        schema['Default'] = []
        p = new_parameter('p', schema, [1, 3, 5])
        self.assertEqual('1,3,5', str(p))
        schema['Default'] = [1, 3, 5]
        p = new_parameter('p', schema)
        self.assertEqual('1,3,5'.split(','), p.value())

    def test_list_value_list_bad(self):
        schema = {'Type': 'CommaDelimitedList',
                  'ConstraintDescription': 'wibble',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema,
                                'foo,baz,blarg')
        self.assertIn('wibble', six.text_type(err))

    def test_list_validate_good(self):
        schema = {'Type': 'CommaDelimitedList'}
        val = ['foo', 'bar', 'baz']
        val_s = 'foo,bar,baz'
        p = new_parameter('p', schema, val_s, validate_value=False)
        p.validate()
        self.assertEqual(val, p.value())
        self.assertEqual(val, p.parsed)

    def test_list_validate_bad(self):
        schema = {'Type': 'CommaDelimitedList'}
        # just need something here that is growing to throw an AttributeError
        # when .split() is called
        val_s = 0
        p = new_parameter('p', schema, validate_value=False)
        p.user_value = val_s
        err = self.assertRaises(exception.StackValidationFailed,
                                p.validate)
        self.assertIn('Parameter \'p\' is invalid', six.text_type(err))

    def test_map_value(self):
        '''Happy path for value that's already a map.'''
        schema = {'Type': 'Json'}
        val = {"foo": "bar", "items": [1, 2, 3]}
        p = new_parameter('p', schema, val)
        self.assertEqual(val, p.value())
        self.assertEqual(val, p.parsed)

    def test_map_value_bad(self):
        '''Map value is not JSON parsable.'''
        schema = {'Type': 'Json',
                  'ConstraintDescription': 'wibble'}
        val = {"foo": "bar", "not_json": len}
        err = self.assertRaises(ValueError,
                                new_parameter, 'p', schema, val)
        self.assertIn('Value must be valid JSON', six.text_type(err))

    def test_map_value_parse(self):
        '''Happy path for value that's a string.'''
        schema = {'Type': 'Json'}
        val = {"foo": "bar", "items": [1, 2, 3]}
        val_s = json.dumps(val)
        p = new_parameter('p', schema, val_s)
        self.assertEqual(val, p.value())
        self.assertEqual(val, p.parsed)

    def test_map_value_bad_parse(self):
        '''Test value error for unparsable string value.'''
        schema = {'Type': 'Json',
                  'ConstraintDescription': 'wibble'}
        val = "I am not a map"
        err = self.assertRaises(ValueError,
                                new_parameter, 'p', schema, val)
        self.assertIn('Value must be valid JSON', six.text_type(err))

    def test_map_underrun(self):
        '''Test map length under MIN_LEN.'''
        schema = {'Type': 'Json',
                  'MinLength': 3}
        val = {"foo": "bar", "items": [1, 2, 3]}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, val)
        self.assertIn('out of range', six.text_type(err))

    def test_map_overrun(self):
        '''Test map length over MAX_LEN.'''
        schema = {'Type': 'Json',
                  'MaxLength': 1}
        val = {"foo": "bar", "items": [1, 2, 3]}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'p', schema, val)
        self.assertIn('out of range', six.text_type(err))

    def test_json_list(self):
        schema = {'Type': 'Json'}
        val = ["fizz", "buzz"]
        p = new_parameter('p', schema, val)
        self.assertIsInstance(p.value(), list)
        self.assertIn("fizz", p.value())
        self.assertIn("buzz", p.value())

    def test_json_string_list(self):
        schema = {'Type': 'Json'}
        val = '["fizz", "buzz"]'
        p = new_parameter('p', schema, val)
        self.assertIsInstance(p.value(), list)
        self.assertIn("fizz", p.value())
        self.assertIn("buzz", p.value())

    def test_json_validate_good(self):
        schema = {'Type': 'Json'}
        val = {"foo": "bar", "items": [1, 2, 3]}
        val_s = json.dumps(val)
        p = new_parameter('p', schema, val_s, validate_value=False)
        p.validate()
        self.assertEqual(val, p.value())
        self.assertEqual(val, p.parsed)

    def test_json_validate_bad(self):
        schema = {'Type': 'Json'}
        val_s = '{"foo": "bar", "invalid": ]}'
        p = new_parameter('p', schema, validate_value=False)
        p.user_value = val_s
        err = self.assertRaises(exception.StackValidationFailed,
                                p.validate)
        self.assertIn('Parameter \'p\' is invalid', six.text_type(err))

    def test_bool_value_true(self):
        schema = {'Type': 'Boolean'}
        for val in ('1', 't', 'true', 'on', 'y', 'yes', True, 1):
            bo = new_parameter('bo', schema, val)
            self.assertTrue(bo.value())

    def test_bool_value_false(self):
        schema = {'Type': 'Boolean'}
        for val in ('0', 'f', 'false', 'off', 'n', 'no', False, 0):
            bo = new_parameter('bo', schema, val)
            self.assertFalse(bo.value())

    def test_bool_value_invalid(self):
        schema = {'Type': 'Boolean'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'bo', schema, 'foo')
        self.assertIn("Unrecognized value 'foo'", six.text_type(err))

    def test_missing_param_str(self):
        '''Test missing user parameter.'''
        self.assertRaises(exception.UserParameterMissing,
                          new_parameter, 'p',
                          {'Type': 'String'})

    def test_missing_param_list(self):
        '''Test missing user parameter.'''
        self.assertRaises(exception.UserParameterMissing,
                          new_parameter, 'p',
                          {'Type': 'CommaDelimitedList'})

    def test_missing_param_map(self):
        '''Test missing user parameter.'''
        self.assertRaises(exception.UserParameterMissing,
                          new_parameter, 'p',
                          {'Type': 'Json'})

    def test_param_name_in_error_message(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        err = self.assertRaises(exception.StackValidationFailed,
                                new_parameter, 'testparam', schema, '234')
        expected = ("Parameter 'testparam' is invalid: "
                    '"234" does not match pattern "[a-z]*"')
        self.assertEqual(expected, six.text_type(err))


params_schema = json.loads('''{
  "Parameters" : {
    "User" : { "Type": "String" },
    "Defaulted" : {
      "Type": "String",
      "Default": "foobar"
    }
  }
}''')


class ParametersBase(common.HeatTestCase):
    def new_parameters(self, stack_name, tmpl, user_params=None,
                       stack_id=None, validate_value=True,
                       param_defaults=None):
        user_params = user_params or {}
        tmpl.update({'HeatTemplateFormatVersion': '2012-12-12'})
        tmpl = template.Template(tmpl)
        params = tmpl.parameters(
            identifier.HeatIdentifier('', stack_name, stack_id),
            user_params, param_defaults=param_defaults)
        params.validate(validate_value)
        return params


class ParametersTest(ParametersBase):

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
                    'Uni': b'test\xe2\x99\xa5',
                    'AWS::Region': 'ap-southeast-1',
                    'AWS::StackId':
                    'arn:openstack:heat:::stacks/{0}/{1}'.format(
                        stack_name,
                        'None'),
                    'AWS::StackName': 'test_params'}

        mapped_params = params.map(six.text_type)
        mapped_params['Uni'] = mapped_params['Uni'].encode('utf-8')
        self.assertEqual(expected, mapped_params)

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
        self.assertRaises(exception.InvalidSchemaError,
                          self.new_parameters,
                          'test',
                          params)


class ParameterDefaultsTest(ParametersBase):
    scenarios = [
        ('type_list', dict(p_type='CommaDelimitedList',
                           value='1,1,1',
                           expected=[['4', '2'], ['7', '7'], ['1', '1', '1']],
                           param_default='7,7',
                           default='4,2')),
        ('type_number', dict(p_type='Number',
                             value=111,
                             expected=[42, 77, 111],
                             param_default=77,
                             default=42)),
        ('type_string', dict(p_type='String',
                             value='111',
                             expected=['42', '77', '111'],
                             param_default='77',
                             default='42')),
        ('type_json', dict(p_type='Json',
                           value={'1': '11'},
                           expected=[{'4': '2'}, {'7': '7'}, {'1': '11'}],
                           param_default={'7': '7'},
                           default={'4': '2'})),
        ('type_boolean1', dict(p_type='Boolean',
                               value=True,
                               expected=[False, False, True],
                               param_default=False,
                               default=False)),
        ('type_boolean2', dict(p_type='Boolean',
                               value=False,
                               expected=[False, True, False],
                               param_default=True,
                               default=False)),
        ('type_boolean3', dict(p_type='Boolean',
                               value=False,
                               expected=[True, False, False],
                               param_default=False,
                               default=True))]

    def test_use_expected_default(self):
        template = {'Parameters': {'a': {'Type': self.p_type,
                                         'Default': self.default}}}
        params = self.new_parameters('test_params', template)
        self.assertEqual(self.expected[0], params['a'])

        params = self.new_parameters('test_params', template,
                                     param_defaults={'a': self.param_default})
        self.assertEqual(self.expected[1], params['a'])

        params = self.new_parameters('test_params', template,
                                     {'a': self.value},
                                     param_defaults={'a': self.param_default})
        self.assertEqual(self.expected[2], params['a'])


class ParameterSchemaTest(common.HeatTestCase):

    def test_validate_schema_wrong_key(self):
        error = self.assertRaises(exception.InvalidSchemaError,
                                  parameters.Schema.from_dict, 'param_name',
                                  {"foo": "bar"})
        self.assertEqual("Invalid key 'foo' for parameter (param_name)",
                         six.text_type(error))

    def test_validate_schema_no_type(self):
        error = self.assertRaises(exception.InvalidSchemaError,
                                  parameters.Schema.from_dict,
                                  'broken',
                                  {"Description": "Hi!"})
        self.assertEqual("Missing parameter type for parameter: broken",
                         six.text_type(error))
