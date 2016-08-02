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

import six

from heat.common import exception
from heat.engine import constraints
from heat.engine import environment
from heat.tests import common


class SchemaTest(common.HeatTestCase):
    def test_range_schema(self):
        d = {'range': {'min': 5, 'max': 10}, 'description': 'a range'}
        r = constraints.Range(5, 10, description='a range')
        self.assertEqual(d, dict(r))

    def test_range_min_schema(self):
        d = {'range': {'min': 5}, 'description': 'a range'}
        r = constraints.Range(min=5, description='a range')
        self.assertEqual(d, dict(r))

    def test_range_max_schema(self):
        d = {'range': {'max': 10}, 'description': 'a range'}
        r = constraints.Range(max=10, description='a range')
        self.assertEqual(d, dict(r))

    def test_length_schema(self):
        d = {'length': {'min': 5, 'max': 10}, 'description': 'a length range'}
        r = constraints.Length(5, 10, description='a length range')
        self.assertEqual(d, dict(r))

    def test_length_min_schema(self):
        d = {'length': {'min': 5}, 'description': 'a length range'}
        r = constraints.Length(min=5, description='a length range')
        self.assertEqual(d, dict(r))

    def test_length_max_schema(self):
        d = {'length': {'max': 10}, 'description': 'a length range'}
        r = constraints.Length(max=10, description='a length range')
        self.assertEqual(d, dict(r))

    def test_modulo_schema(self):
        d = {'modulo': {'step': 2, 'offset': 1},
             'description': 'a modulo'}
        r = constraints.Modulo(2, 1, description='a modulo')
        self.assertEqual(d, dict(r))

    def test_allowed_values_schema(self):
        d = {'allowed_values': ['foo', 'bar'], 'description': 'allowed values'}
        r = constraints.AllowedValues(['foo', 'bar'],
                                      description='allowed values')
        self.assertEqual(d, dict(r))

    def test_allowed_pattern_schema(self):
        d = {'allowed_pattern': '[A-Za-z0-9]', 'description': 'alphanumeric'}
        r = constraints.AllowedPattern('[A-Za-z0-9]',
                                       description='alphanumeric')
        self.assertEqual(d, dict(r))

    def test_range_validate(self):
        r = constraints.Range(min=5, max=5, description='a range')
        r.validate(5)

    def test_range_min_fail(self):
        r = constraints.Range(min=5, description='a range')
        self.assertRaises(ValueError, r.validate, 4)

    def test_range_max_fail(self):
        r = constraints.Range(max=5, description='a range')
        self.assertRaises(ValueError, r.validate, 6)

    def test_length_validate(self):
        l = constraints.Length(min=5, max=5, description='a range')
        l.validate('abcde')

    def test_length_min_fail(self):
        l = constraints.Length(min=5, description='a range')
        self.assertRaises(ValueError, l.validate, 'abcd')

    def test_length_max_fail(self):
        l = constraints.Length(max=5, description='a range')
        self.assertRaises(ValueError, l.validate, 'abcdef')

    def test_modulo_validate(self):
        r = constraints.Modulo(step=2, offset=1, description='a modulo')
        r.validate(1)
        r.validate(3)
        r.validate(5)
        r.validate(777777)

        r = constraints.Modulo(step=111, offset=0, description='a modulo')
        r.validate(111)
        r.validate(222)
        r.validate(444)
        r.validate(1110)

        r = constraints.Modulo(step=111, offset=11, description='a modulo')
        r.validate(122)
        r.validate(233)
        r.validate(1121)

        r = constraints.Modulo(step=-2, offset=-1, description='a modulo')
        r.validate(-1)
        r.validate(-3)
        r.validate(-5)
        r.validate(-777777)

        r = constraints.Modulo(step=-2, offset=0, description='a modulo')
        r.validate(-2)
        r.validate(-4)
        r.validate(-8888888)

    def test_modulo_validate_fail(self):
        r = constraints.Modulo(step=2, offset=1)
        err = self.assertRaises(ValueError, r.validate, 4)
        self.assertIn('4 is not a multiple of 2 with an offset of 1',
                      six.text_type(err))

        self.assertRaises(ValueError, r.validate, 0)
        self.assertRaises(ValueError, r.validate, 2)
        self.assertRaises(ValueError, r.validate, 888888)

        r = constraints.Modulo(step=2, offset=0)
        self.assertRaises(ValueError, r.validate, 1)
        self.assertRaises(ValueError, r.validate, 3)
        self.assertRaises(ValueError, r.validate, 5)
        self.assertRaises(ValueError, r.validate, 777777)

        err = self.assertRaises(exception.InvalidSchemaError,
                                constraints.Modulo, step=111, offset=111)
        self.assertIn('offset must be smaller (by absolute value) than step',
                      six.text_type(err))

        err = self.assertRaises(exception.InvalidSchemaError,
                                constraints.Modulo, step=111, offset=112)
        self.assertIn('offset must be smaller (by absolute value) than step',
                      six.text_type(err))

        err = self.assertRaises(exception.InvalidSchemaError,
                                constraints.Modulo, step=0, offset=1)
        self.assertIn('step cannot be 0', six.text_type(err))

        err = self.assertRaises(exception.InvalidSchemaError,
                                constraints.Modulo, step=-2, offset=1)
        self.assertIn('step and offset must be both positive or both negative',
                      six.text_type(err))

        err = self.assertRaises(exception.InvalidSchemaError,
                                constraints.Modulo, step=2, offset=-1)
        self.assertIn('step and offset must be both positive or both negative',
                      six.text_type(err))

    def test_schema_all(self):
        d = {
            'type': 'string',
            'description': 'A string',
            'default': 'wibble',
            'required': False,
            'constraints': [
                {'length': {'min': 4, 'max': 8}},
            ]
        }
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble',
                               constraints=[constraints.Length(4, 8)])
        self.assertEqual(d, dict(s))

    def test_schema_list_schema(self):
        d = {
            'type': 'list',
            'description': 'A list',
            'schema': {
                '*': {
                    'type': 'string',
                    'description': 'A string',
                    'default': 'wibble',
                    'required': False,
                    'constraints': [
                        {'length': {'min': 4, 'max': 8}},
                    ]
                }
            },
            'required': False,
        }
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble',
                               constraints=[constraints.Length(4, 8)])
        l = constraints.Schema(constraints.Schema.LIST, 'A list', schema=s)
        self.assertEqual(d, dict(l))

    def test_schema_map_schema(self):
        d = {
            'type': 'map',
            'description': 'A map',
            'schema': {
                'Foo': {
                    'type': 'string',
                    'description': 'A string',
                    'default': 'wibble',
                    'required': False,
                    'constraints': [
                        {'length': {'min': 4, 'max': 8}},
                    ]
                }
            },
            'required': False,
        }
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble',
                               constraints=[constraints.Length(4, 8)])
        m = constraints.Schema(constraints.Schema.MAP, 'A map',
                               schema={'Foo': s})
        self.assertEqual(d, dict(m))

    def test_schema_nested_schema(self):
        d = {
            'type': 'list',
            'description': 'A list',
            'schema': {
                '*': {
                    'type': 'map',
                    'description': 'A map',
                    'schema': {
                        'Foo': {
                            'type': 'string',
                            'description': 'A string',
                            'default': 'wibble',
                            'required': False,
                            'constraints': [
                                {'length': {'min': 4, 'max': 8}},
                            ]
                        }
                    },
                    'required': False,
                }
            },
            'required': False,
        }
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble',
                               constraints=[constraints.Length(4, 8)])
        m = constraints.Schema(constraints.Schema.MAP, 'A map',
                               schema={'Foo': s})
        l = constraints.Schema(constraints.Schema.LIST, 'A list', schema=m)
        self.assertEqual(d, dict(l))

    def test_invalid_type(self):
        self.assertRaises(exception.InvalidSchemaError, constraints.Schema,
                          'Fish')

    def test_schema_invalid_type(self):
        self.assertRaises(exception.InvalidSchemaError,
                          constraints.Schema,
                          'String',
                          schema=constraints.Schema('String'))

    def test_range_invalid_type(self):
        schema = constraints.Schema('String',
                                    constraints=[constraints.Range(1, 10)])
        err = self.assertRaises(exception.InvalidSchemaError,
                                schema.validate)
        self.assertIn('Range constraint invalid for String',
                      six.text_type(err))

    def test_length_invalid_type(self):
        schema = constraints.Schema('Integer',
                                    constraints=[constraints.Length(1, 10)])
        err = self.assertRaises(exception.InvalidSchemaError,
                                schema.validate)
        self.assertIn('Length constraint invalid for Integer',
                      six.text_type(err))

    def test_modulo_invalid_type(self):
        schema = constraints.Schema('String',
                                    constraints=[constraints.Modulo(2, 1)])
        err = self.assertRaises(exception.InvalidSchemaError,
                                schema.validate)
        self.assertIn('Modulo constraint invalid for String',
                      six.text_type(err))

    def test_allowed_pattern_invalid_type(self):
        schema = constraints.Schema(
            'Integer',
            constraints=[constraints.AllowedPattern('[0-9]*')]
        )
        err = self.assertRaises(exception.InvalidSchemaError,
                                schema.validate)
        self.assertIn('AllowedPattern constraint invalid for Integer',
                      six.text_type(err))

    def test_range_vals_invalid_type(self):
        self.assertRaises(exception.InvalidSchemaError,
                          constraints.Range, '1', 10)
        self.assertRaises(exception.InvalidSchemaError,
                          constraints.Range, 1, '10')

    def test_length_vals_invalid_type(self):
        self.assertRaises(exception.InvalidSchemaError,
                          constraints.Length, '1', 10)
        self.assertRaises(exception.InvalidSchemaError,
                          constraints.Length, 1, '10')

    def test_modulo_vals_invalid_type(self):
        self.assertRaises(exception.InvalidSchemaError,
                          constraints.Modulo, '2', 1)
        self.assertRaises(exception.InvalidSchemaError,
                          constraints.Modulo, 2, '1')

    def test_schema_validate_good(self):
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble',
                               constraints=[constraints.Length(4, 8)])
        self.assertIsNone(s.validate())

    def test_schema_validate_fail(self):
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble',
                               constraints=[constraints.Range(max=4)])
        err = self.assertRaises(exception.InvalidSchemaError, s.validate)
        self.assertIn('Range constraint invalid for String',
                      six.text_type(err))

    def test_schema_nested_validate_good(self):
        nested = constraints.Schema(constraints.Schema.STRING, 'A string',
                                    default='wibble',
                                    constraints=[constraints.Length(4, 8)])
        s = constraints.Schema(constraints.Schema.MAP, 'A map',
                               schema={'Foo': nested})
        self.assertIsNone(s.validate())

    def test_schema_nested_validate_fail(self):
        nested = constraints.Schema(constraints.Schema.STRING, 'A string',
                                    default='wibble',
                                    constraints=[constraints.Range(max=4)])
        s = constraints.Schema(constraints.Schema.MAP, 'A map',
                               schema={'Foo': nested})
        err = self.assertRaises(exception.InvalidSchemaError, s.validate)
        self.assertIn('Range constraint invalid for String',
                      six.text_type(err))

    def test_allowed_values_numeric_int(self):
        """Test AllowedValues constraint for numeric integer values.

        Test if the AllowedValues constraint works for numeric values in any
        combination of numeric strings or numbers in the constraint and
        numeric strings or numbers as value.
        """

        # Allowed values defined as integer numbers
        schema = constraints.Schema(
            'Integer',
            constraints=[constraints.AllowedValues([1, 2, 4])]
        )
        # ... and value as number or string
        self.assertIsNone(schema.validate_constraints(1))
        err = self.assertRaises(exception.StackValidationFailed,
                                schema.validate_constraints, 3)
        self.assertEqual('"3" is not an allowed value [1, 2, 4]',
                         six.text_type(err))
        self.assertIsNone(schema.validate_constraints('1'))
        err = self.assertRaises(exception.StackValidationFailed,
                                schema.validate_constraints, '3')
        self.assertEqual('"3" is not an allowed value [1, 2, 4]',
                         six.text_type(err))

        # Allowed values defined as integer strings
        schema = constraints.Schema(
            'Integer',
            constraints=[constraints.AllowedValues(['1', '2', '4'])]
        )
        # ... and value as number or string
        self.assertIsNone(schema.validate_constraints(1))
        err = self.assertRaises(exception.StackValidationFailed,
                                schema.validate_constraints, 3)
        self.assertEqual('"3" is not an allowed value [1, 2, 4]',
                         six.text_type(err))
        self.assertIsNone(schema.validate_constraints('1'))
        err = self.assertRaises(exception.StackValidationFailed,
                                schema.validate_constraints, '3')
        self.assertEqual('"3" is not an allowed value [1, 2, 4]',
                         six.text_type(err))

    def test_allowed_values_numeric_float(self):
        """Test AllowedValues constraint for numeric floating point values.

        Test if the AllowedValues constraint works for numeric values in any
        combination of numeric strings or numbers in the constraint and
        numeric strings or numbers as value.
        """

        # Allowed values defined as numbers
        schema = constraints.Schema(
            'Number',
            constraints=[constraints.AllowedValues([1.1, 2.2, 4.4])]
        )
        # ... and value as number or string
        self.assertIsNone(schema.validate_constraints(1.1))
        err = self.assertRaises(exception.StackValidationFailed,
                                schema.validate_constraints, 3.3)
        self.assertEqual('"3.3" is not an allowed value [1.1, 2.2, 4.4]',
                         six.text_type(err))
        self.assertIsNone(schema.validate_constraints('1.1'))
        err = self.assertRaises(exception.StackValidationFailed,
                                schema.validate_constraints, '3.3')
        self.assertEqual('"3.3" is not an allowed value [1.1, 2.2, 4.4]',
                         six.text_type(err))

        # Allowed values defined as strings
        schema = constraints.Schema(
            'Number',
            constraints=[constraints.AllowedValues(['1.1', '2.2', '4.4'])]
        )
        # ... and value as number or string
        self.assertIsNone(schema.validate_constraints(1.1))
        err = self.assertRaises(exception.StackValidationFailed,
                                schema.validate_constraints, 3.3)
        self.assertEqual('"3.3" is not an allowed value [1.1, 2.2, 4.4]',
                         six.text_type(err))
        self.assertIsNone(schema.validate_constraints('1.1'))
        err = self.assertRaises(exception.StackValidationFailed,
                                schema.validate_constraints, '3.3')
        self.assertEqual('"3.3" is not an allowed value [1.1, 2.2, 4.4]',
                         six.text_type(err))

    def test_to_schema_type_int(self):
        """Test Schema.to_schema_type method for type Integer."""
        schema = constraints.Schema('Integer')
        # test valid values, i.e. integeres as string or number
        res = schema.to_schema_type(1)
        self.assertIsInstance(res, int)
        res = schema.to_schema_type('1')
        self.assertIsInstance(res, int)
        # test invalid numeric values, i.e. floating point numbers
        err = self.assertRaises(ValueError, schema.to_schema_type, 1.5)
        self.assertEqual('Value "1.5" is invalid for data type "Integer".',
                         six.text_type(err))
        err = self.assertRaises(ValueError, schema.to_schema_type, '1.5')
        self.assertEqual('Value "1.5" is invalid for data type "Integer".',
                         six.text_type(err))
        # test invalid string values
        err = self.assertRaises(ValueError, schema.to_schema_type, 'foo')
        self.assertEqual('Value "foo" is invalid for data type "Integer".',
                         six.text_type(err))

    def test_to_schema_type_num(self):
        """Test Schema.to_schema_type method for type Number."""
        schema = constraints.Schema('Number')
        res = schema.to_schema_type(1)
        self.assertIsInstance(res, int)
        res = schema.to_schema_type('1')
        self.assertIsInstance(res, int)
        res = schema.to_schema_type(1.5)
        self.assertIsInstance(res, float)
        res = schema.to_schema_type('1.5')
        self.assertIsInstance(res, float)
        self.assertEqual(1.5, res)
        err = self.assertRaises(ValueError, schema.to_schema_type, 'foo')
        self.assertEqual('Value "foo" is invalid for data type "Number".',
                         six.text_type(err))

    def test_to_schema_type_string(self):
        """Test Schema.to_schema_type method for type String."""
        schema = constraints.Schema('String')
        res = schema.to_schema_type('one')
        self.assertIsInstance(res, six.string_types)
        res = schema.to_schema_type('1')
        self.assertIsInstance(res, six.string_types)
        res = schema.to_schema_type(1)
        self.assertIsInstance(res, six.string_types)
        res = schema.to_schema_type(True)
        self.assertIsInstance(res, six.string_types)
        res = schema.to_schema_type(None)
        self.assertIsInstance(res, six.string_types)

    def test_to_schema_type_boolean(self):
        """Test Schema.to_schema_type method for type Boolean."""
        schema = constraints.Schema('Boolean')

        true_values = [1, '1', True, 'true', 'True', 'yes', 'Yes']
        for v in true_values:
            res = schema.to_schema_type(v)
            self.assertIsInstance(res, bool)
            self.assertTrue(res)

        false_values = [0, '0', False, 'false', 'False', 'No', 'no']
        for v in false_values:
            res = schema.to_schema_type(v)
            self.assertIsInstance(res, bool)
            self.assertFalse(res)

        err = self.assertRaises(ValueError, schema.to_schema_type, 'foo')
        self.assertEqual('Value "foo" is invalid for data type "Boolean".',
                         six.text_type(err))

    def test_to_schema_type_map(self):
        """Test Schema.to_schema_type method for type Map."""
        schema = constraints.Schema('Map')
        res = schema.to_schema_type({'a': 'aa', 'b': 'bb'})
        self.assertIsInstance(res, dict)
        self.assertEqual({'a': 'aa', 'b': 'bb'}, res)

    def test_to_schema_type_list(self):
        """Test Schema.to_schema_type method for type List."""
        schema = constraints.Schema('List')
        res = schema.to_schema_type(['a', 'b'])
        self.assertIsInstance(res, list)
        self.assertEqual(['a', 'b'], res)


class CustomConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(CustomConstraintTest, self).setUp()
        self.env = environment.Environment({})

    def test_validation(self):
        class ZeroConstraint(object):
            def validate(self, value, context):
                return value == 0

        self.env.register_constraint("zero", ZeroConstraint)

        constraint = constraints.CustomConstraint("zero", environment=self.env)
        self.assertEqual("Value must be of type zero",
                         six.text_type(constraint))
        self.assertIsNone(constraint.validate(0))
        error = self.assertRaises(ValueError, constraint.validate, 1)
        self.assertEqual('"1" does not validate zero',
                         six.text_type(error))

    def test_custom_error(self):
        class ZeroConstraint(object):

            def error(self, value):
                return "%s is not 0" % value

            def validate(self, value, context):
                return value == 0

        self.env.register_constraint("zero", ZeroConstraint)

        constraint = constraints.CustomConstraint("zero", environment=self.env)
        error = self.assertRaises(ValueError, constraint.validate, 1)
        self.assertEqual("1 is not 0", six.text_type(error))

    def test_custom_message(self):
        class ZeroConstraint(object):
            message = "Only zero!"

            def validate(self, value, context):
                return value == 0

        self.env.register_constraint("zero", ZeroConstraint)

        constraint = constraints.CustomConstraint("zero", environment=self.env)
        self.assertEqual("Only zero!", six.text_type(constraint))

    def test_unknown_constraint(self):
        constraint = constraints.CustomConstraint("zero", environment=self.env)
        error = self.assertRaises(ValueError, constraint.validate, 1)
        self.assertEqual('"1" does not validate zero (constraint not found)',
                         six.text_type(error))

    def test_constraints(self):
        class ZeroConstraint(object):
            def validate(self, value, context):
                return value == 0

        self.env.register_constraint("zero", ZeroConstraint)

        constraint = constraints.CustomConstraint("zero", environment=self.env)
        self.assertEqual("zero", constraint["custom_constraint"])
