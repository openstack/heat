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


import unittest
from nose.plugins.attrib import attr

from heat.engine import properties
from heat.common import exception


@attr(tag=['unit', 'properties'])
@attr(speed='fast')
class PropertyTest(unittest.TestCase):
    def test_required_default(self):
        p = properties.Property({'Type': 'String'})
        self.assertFalse(p.required())

    def test_required_false(self):
        p = properties.Property({'Type': 'String', 'Required': False})
        self.assertFalse(p.required())

    def test_required_true(self):
        p = properties.Property({'Type': 'String', 'Required': True})
        self.assertTrue(p.required())

    def test_implemented_default(self):
        p = properties.Property({'Type': 'String'})
        self.assertTrue(p.implemented())

    def test_implemented_false(self):
        p = properties.Property({'Type': 'String', 'Implemented': False})
        self.assertFalse(p.implemented())

    def test_implemented_true(self):
        p = properties.Property({'Type': 'String', 'Implemented': True})
        self.assertTrue(p.implemented())

    def test_no_default(self):
        p = properties.Property({'Type': 'String'})
        self.assertFalse(p.has_default())

    def test_default(self):
        p = properties.Property({'Type': 'String', 'Default': 'wibble'})
        self.assertEqual(p.default(), 'wibble')

    def test_type(self):
        p = properties.Property({'Type': 'String'})
        self.assertEqual(p.type(), 'String')

    def test_bad_type(self):
        self.assertRaises(AssertionError,
                          properties.Property, {'Type': 'Fish'})

    def test_bad_key(self):
        self.assertRaises(AssertionError,
                          properties.Property,
                          {'Type': 'String', 'Foo': 'Bar'})

    def test_string_pattern_good(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = properties.Property(schema)
        self.assertEqual(p.validate_data('foo'), 'foo')

    def test_string_pattern_bad_prefix(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, '1foo')

    def test_string_pattern_bad_suffix(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, 'foo1')

    def test_string_value_list_good(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = properties.Property(schema)
        self.assertEqual(p.validate_data('bar'), 'bar')

    def test_string_value_list_bad(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, 'blarg')

    def test_int_good(self):
        schema = {'Type': 'Integer',
                  'MinValue': 3,
                  'MaxValue': 3}
        p = properties.Property(schema)
        self.assertEqual(p.validate_data(3), 3)

    def test_int_bad(self):
        schema = {'Type': 'Integer'}
        p = properties.Property(schema)
        self.assertRaises(TypeError, p.validate_data, '3')

    def test_integer_low(self):
        schema = {'Type': 'Integer',
                  'MinValue': 4}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, 3)

    def test_integer_high(self):
        schema = {'Type': 'Integer',
                  'MaxValue': 2}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, 3)

    def test_integer_value_list_good(self):
        schema = {'Type': 'Integer',
                  'AllowedValues': [1, 3, 5]}
        p = properties.Property(schema)
        self.assertEqual(p.validate_data(5), 5)

    def test_integer_value_list_bad(self):
        schema = {'Type': 'Integer',
                  'AllowedValues': [1, 3, 5]}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, 2)

    def test_number_good(self):
        schema = {'Type': 'Number',
                  'MinValue': '3',
                  'MaxValue': '3'}
        p = properties.Property(schema)
        self.assertEqual(p.validate_data('3'), '3')

    def test_number_value_list_good(self):
        schema = {'Type': 'Number',
                  'AllowedValues': ['1', '3', '5']}
        p = properties.Property(schema)
        self.assertEqual(p.validate_data('5'), '5')

    def test_number_value_list_bad(self):
        schema = {'Type': 'Number',
                  'AllowedValues': ['1', '3', '5']}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, '2')

    def test_number_low(self):
        schema = {'Type': 'Number',
                  'MinValue': '4'}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, '3')

    def test_number_high(self):
        schema = {'Type': 'Number',
                  'MaxValue': '2'}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, '3')

    def test_boolean_true(self):
        p = properties.Property({'Type': 'Boolean'})
        self.assertEqual(p.validate_data('True'), True)
        self.assertEqual(p.validate_data('true'), True)
        self.assertEqual(p.validate_data(True), True)

    def test_boolean_false(self):
        p = properties.Property({'Type': 'Boolean'})
        self.assertEqual(p.validate_data('False'), False)
        self.assertEqual(p.validate_data('false'), False)
        self.assertEqual(p.validate_data(False), False)

    def test_boolean_invalid(self):
        p = properties.Property({'Type': 'Boolean'})
        self.assertRaises(ValueError, p.validate_data, 'fish')

    def test_list_string(self):
        p = properties.Property({'Type': 'List'})
        self.assertRaises(TypeError, p.validate_data, 'foo')

    def test_list_good(self):
        p = properties.Property({'Type': 'List'})
        self.assertEqual(p.validate_data(['foo', 'bar']), ['foo', 'bar'])

    def test_list_dict(self):
        p = properties.Property({'Type': 'List'})
        self.assertRaises(TypeError, p.validate_data, {'foo': 'bar'})

    def test_list_value_list_bad(self):
        schema = {'Type': 'List',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = properties.Property(schema)
        self.assertRaises(ValueError, p.validate_data, ['foo', 'wibble'])

    def test_list_value_list_good(self):
        schema = {'Type': 'List',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = properties.Property(schema)
        self.assertEqual(p.validate_data(['bar', 'foo']), ['bar', 'foo'])

    def test_map_string(self):
        p = properties.Property({'Type': 'Map'})
        self.assertRaises(TypeError, p.validate_data, 'foo')

    def test_map_list(self):
        p = properties.Property({'Type': 'Map'})
        self.assertRaises(TypeError, p.validate_data, ['foo'])

    def test_map_schema_good(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        p = properties.Property({'Type': 'Map', 'Schema': map_schema})
        self.assertEqual(p.validate_data({'valid': 'TRUE'}), {'valid': True})

    def test_map_schema_bad_data(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        p = properties.Property({'Type': 'Map', 'Schema': map_schema})
        self.assertRaises(ValueError, p.validate_data, {'valid': 'fish'})

    def test_map_schema_missing_data(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        p = properties.Property({'Type': 'Map', 'Schema': map_schema})
        self.assertEqual(p.validate_data({}), {'valid': None})

    def test_map_schema_missing_required_data(self):
        map_schema = {'valid': {'Type': 'Boolean', 'Required': True}}
        p = properties.Property({'Type': 'Map', 'Schema': map_schema})
        self.assertRaises(ValueError, p.validate_data, {})

    def test_list_schema_good(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        list_schema = {'Type': 'Map', 'Schema': map_schema}
        p = properties.Property({'Type': 'List', 'Schema': list_schema})
        self.assertEqual(p.validate_data(
            [{'valid': 'TRUE'}, {'valid': 'False'}]),
            [{'valid': True}, {'valid': False}])

    def test_list_schema_bad_data(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        list_schema = {'Type': 'Map', 'Schema': map_schema}
        p = properties.Property({'Type': 'List', 'Schema': list_schema})
        self.assertRaises(ValueError, p.validate_data, [{'valid': 'True'},
                                                        {'valid': 'fish'}])

    def test_list_schema_int_good(self):
        list_schema = {'Type': 'Integer'}
        p = properties.Property({'Type': 'List', 'Schema': list_schema})
        self.assertEqual(p.validate_data([1, 2, 3]), [1, 2, 3])

    def test_list_schema_int_bad_data(self):
        list_schema = {'Type': 'Integer'}
        p = properties.Property({'Type': 'List', 'Schema': list_schema})
        self.assertRaises(TypeError, p.validate_data, [42, 'fish'])


@attr(tag=['unit', 'properties'])
@attr(speed='fast')
class PropertiesTest(unittest.TestCase):
    def setUp(self):
        schema = {
            'int': {'Type': 'Integer'},
            'string': {'Type': 'String'},
            'required_int': {'Type': 'Integer', 'Required': True},
            'bad_int': {'Type': 'Integer'},
            'missing': {'Type': 'Integer'},
            'defaulted': {'Type': 'Integer', 'Default': 1},
            'default_override': {'Type': 'Integer', 'Default': 1},
        }
        data = {
            'int': 21,
            'string': 'foo',
            'bad_int': 'foo',
            'default_override': 21,
        }
        double = lambda d: d * 2
        self.props = properties.Properties(schema, data, double, 'wibble')

    def test_integer_good(self):
        self.assertEqual(self.props['int'], 42)

    def test_string_good(self):
        self.assertEqual(self.props['string'], 'foofoo')

    def test_missing_required(self):
        self.assertRaises(ValueError, self.props.get, 'required_int')

    def test_integer_bad(self):
        self.assertRaises(TypeError, self.props.get, 'bad_int')

    def test_missing(self):
        self.assertEqual(self.props['missing'], None)

    def test_default(self):
        self.assertEqual(self.props['defaulted'], 1)

    def test_default_override(self):
        self.assertEqual(self.props['default_override'], 42)

    def test_bad_key(self):
        self.assertEqual(self.props.get('foo', 'wibble'), 'wibble')

    def test_none_string(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual('', props['foo'])

    def test_none_integer(self):
        schema = {'foo': {'Type': 'Integer'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(0, props['foo'])

    def test_none_number(self):
        schema = {'foo': {'Type': 'Number'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(0, props['foo'])

    def test_none_boolean(self):
        schema = {'foo': {'Type': 'Boolean'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(False, props['foo'])

    def test_none_map(self):
        schema = {'foo': {'Type': 'Map'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual({}, props['foo'])

    def test_none_list(self):
        schema = {'foo': {'Type': 'List'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual([], props['foo'])

    def test_none_default_string(self):
        schema = {'foo': {'Type': 'String', 'Default': 'bar'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual('bar', props['foo'])

    def test_none_default_integer(self):
        schema = {'foo': {'Type': 'Integer', 'Default': 42}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(42, props['foo'])

        schema = {'foo': {'Type': 'Integer', 'Default': 0}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(0, props['foo'])

        schema = {'foo': {'Type': 'Integer', 'Default': -273}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(-273, props['foo'])

    def test_none_default_number(self):
        schema = {'foo': {'Type': 'Number', 'Default': 42.0}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(42.0, props['foo'])

        schema = {'foo': {'Type': 'Number', 'Default': 0.0}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(0.0, props['foo'])

        schema = {'foo': {'Type': 'Number', 'Default': -273.15}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(-273.15, props['foo'])

    def test_none_default_boolean(self):
        schema = {'foo': {'Type': 'Boolean', 'Default': True}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(True, props['foo'])

    def test_none_default_map(self):
        schema = {'foo': {'Type': 'Map', 'Default': {'bar': 'baz'}}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual({'bar': 'baz'}, props['foo'])

    def test_none_default_list(self):
        schema = {'foo': {'Type': 'List', 'Default': ['one', 'two']}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(['one', 'two'], props['foo'])


@attr(tag=['unit', 'properties'])
@attr(speed='fast')
class PropertiesValidationTest(unittest.TestCase):
    def test_required(self):
        schema = {'foo': {'Type': 'String', 'Required': True}}
        props = properties.Properties(schema, {'foo': 'bar'})
        self.assertEqual(props.validate(), None)

    def test_missing_required(self):
        schema = {'foo': {'Type': 'String', 'Required': True}}
        props = properties.Properties(schema, {})
        self.assertRaises(exception.StackValidationFailed, props.validate)

    def test_missing_unimplemented(self):
        schema = {'foo': {'Type': 'String', 'Implemented': False}}
        props = properties.Properties(schema, {})
        self.assertEqual(props.validate(), None)

    def test_present_unimplemented(self):
        schema = {'foo': {'Type': 'String', 'Implemented': False}}
        props = properties.Properties(schema, {'foo': 'bar'})
        self.assertRaises(exception.StackValidationFailed, props.validate)

    def test_missing(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {})
        self.assertEqual(props.validate(), None)

    def test_bad_data(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {'foo': 42})
        self.assertRaises(exception.StackValidationFailed, props.validate)

    def test_unknown_typo(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {'food': 42})
        self.assertRaises(exception.StackValidationFailed, props.validate)

    def test_none_string(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_integer(self):
        schema = {'foo': {'Type': 'Integer'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_number(self):
        schema = {'foo': {'Type': 'Number'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_boolean(self):
        schema = {'foo': {'Type': 'Boolean'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_map(self):
        schema = {'foo': {'Type': 'Map'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_list(self):
        schema = {'foo': {'Type': 'List'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_default_string(self):
        schema = {'foo': {'Type': 'String', 'Default': 'bar'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_default_integer(self):
        schema = {'foo': {'Type': 'Integer', 'Default': 42}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_default_number(self):
        schema = {'foo': {'Type': 'Number', 'Default': 42.0}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_default_boolean(self):
        schema = {'foo': {'Type': 'Boolean', 'Default': True}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_default_map(self):
        schema = {'foo': {'Type': 'Map', 'Default': {'bar': 'baz'}}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)

    def test_none_default_list(self):
        schema = {'foo': {'Type': 'List', 'Default': ['one', 'two']}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(props.validate(), None)
