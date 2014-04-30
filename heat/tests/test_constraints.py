
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

from heat.engine import constraints
from heat.engine import environment


class SchemaTest(testtools.TestCase):
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

    def test_schema_all(self):
        d = {
            'type': 'string',
            'description': 'A string',
            'default': 'wibble',
            'required': True,
            'constraints': [
                {'length': {'min': 4, 'max': 8}},
            ]
        }
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble', required=True,
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
                    'required': True,
                    'constraints': [
                        {'length': {'min': 4, 'max': 8}},
                    ]
                }
            },
            'required': False,
        }
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble', required=True,
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
                    'required': True,
                    'constraints': [
                        {'length': {'min': 4, 'max': 8}},
                    ]
                }
            },
            'required': False,
        }
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble', required=True,
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
                            'required': True,
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
                               default='wibble', required=True,
                               constraints=[constraints.Length(4, 8)])
        m = constraints.Schema(constraints.Schema.MAP, 'A map',
                               schema={'Foo': s})
        l = constraints.Schema(constraints.Schema.LIST, 'A list', schema=m)
        self.assertEqual(d, dict(l))

    def test_invalid_type(self):
        self.assertRaises(constraints.InvalidSchemaError, constraints.Schema,
                          'Fish')

    def test_schema_invalid_type(self):
        self.assertRaises(constraints.InvalidSchemaError,
                          constraints.Schema,
                          'String',
                          schema=constraints.Schema('String'))

    def test_range_invalid_type(self):
        schema = constraints.Schema('String',
                                    constraints=[constraints.Range(1, 10)])
        err = self.assertRaises(constraints.InvalidSchemaError,
                                schema.validate)
        self.assertIn('Range constraint invalid for String', str(err))

    def test_length_invalid_type(self):
        schema = constraints.Schema('Integer',
                                    constraints=[constraints.Length(1, 10)])
        err = self.assertRaises(constraints.InvalidSchemaError,
                                schema.validate)
        self.assertIn('Length constraint invalid for Integer', str(err))

    def test_allowed_pattern_invalid_type(self):
        schema = constraints.Schema(
            'Integer',
            constraints=[constraints.AllowedPattern('[0-9]*')]
        )
        err = self.assertRaises(constraints.InvalidSchemaError,
                                schema.validate)
        self.assertIn('AllowedPattern constraint invalid for Integer',
                      str(err))

    def test_range_vals_invalid_type(self):
        self.assertRaises(constraints.InvalidSchemaError,
                          constraints.Range, '1', 10)
        self.assertRaises(constraints.InvalidSchemaError,
                          constraints.Range, 1, '10')

    def test_length_vals_invalid_type(self):
        self.assertRaises(constraints.InvalidSchemaError,
                          constraints.Length, '1', 10)
        self.assertRaises(constraints.InvalidSchemaError,
                          constraints.Length, 1, '10')

    def test_schema_validate_good(self):
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble', required=True,
                               constraints=[constraints.Length(4, 8)])
        self.assertIsNone(s.validate())

    def test_schema_validate_fail(self):
        s = constraints.Schema(constraints.Schema.STRING, 'A string',
                               default='wibble', required=True,
                               constraints=[constraints.Range(max=4)])
        err = self.assertRaises(constraints.InvalidSchemaError, s.validate)
        self.assertIn('Range constraint invalid for String', str(err))

    def test_schema_nested_validate_good(self):
        nested = constraints.Schema(constraints.Schema.STRING, 'A string',
                                    default='wibble', required=True,
                                    constraints=[constraints.Length(4, 8)])
        s = constraints.Schema(constraints.Schema.MAP, 'A map',
                               schema={'Foo': nested})
        self.assertIsNone(s.validate())

    def test_schema_nested_validate_fail(self):
        nested = constraints.Schema(constraints.Schema.STRING, 'A string',
                                    default='wibble', required=True,
                                    constraints=[constraints.Range(max=4)])
        s = constraints.Schema(constraints.Schema.MAP, 'A map',
                               schema={'Foo': nested})
        err = self.assertRaises(constraints.InvalidSchemaError, s.validate)
        self.assertIn('Range constraint invalid for String', str(err))


class CustomConstraintTest(testtools.TestCase):

    def setUp(self):
        super(CustomConstraintTest, self).setUp()
        self.env = environment.Environment({})

    def test_validation(self):
        class ZeroConstraint(object):
            def validate(self, value, context):
                return value == 0

        self.env.register_constraint("zero", ZeroConstraint)

        constraint = constraints.CustomConstraint("zero", environment=self.env)
        self.assertEqual("Value must be of type zero", str(constraint))
        self.assertIsNone(constraint.validate(0))
        error = self.assertRaises(ValueError, constraint.validate, 1)
        self.assertEqual('"1" does not validate zero', str(error))

    def test_custom_error(self):
        class ZeroConstraint(object):

            def error(self, value):
                return "%s is not 0" % value

            def validate(self, value, context):
                return value == 0

        self.env.register_constraint("zero", ZeroConstraint)

        constraint = constraints.CustomConstraint("zero", environment=self.env)
        error = self.assertRaises(ValueError, constraint.validate, 1)
        self.assertEqual("1 is not 0", str(error))

    def test_custom_message(self):
        class ZeroConstraint(object):
            message = "Only zero!"

            def validate(self, value, context):
                return value == 0

        self.env.register_constraint("zero", ZeroConstraint)

        constraint = constraints.CustomConstraint("zero", environment=self.env)
        self.assertEqual("Only zero!", str(constraint))

    def test_unknown_constraint(self):
        constraint = constraints.CustomConstraint("zero", environment=self.env)
        error = self.assertRaises(ValueError, constraint.validate, 1)
        self.assertEqual('"1" does not validate zero (constraint not found)',
                         str(error))

    def test_constraints(self):
        class ZeroConstraint(object):
            def validate(self, value, context):
                return value == 0

        self.env.register_constraint("zero", ZeroConstraint)

        constraint = constraints.CustomConstraint("zero", environment=self.env)
        self.assertEqual("zero", constraint["custom_constraint"])
