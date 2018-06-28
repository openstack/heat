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

import mock
from oslo_serialization import jsonutils
import six

from heat.common import exception
from heat.engine import constraints
from heat.engine.hot import functions as hot_funcs
from heat.engine.hot import parameters as hot_param
from heat.engine import parameters
from heat.engine import plugin_manager
from heat.engine import properties
from heat.engine import resources
from heat.engine import support
from heat.engine import translation
from heat.tests import common


class PropertySchemaTest(common.HeatTestCase):
    def test_schema_all(self):
        d = {
            'type': 'string',
            'description': 'A string',
            'default': 'wibble',
            'required': False,
            'update_allowed': False,
            'immutable': False,
            'constraints': [
                {'length': {'min': 4, 'max': 8}},
            ]
        }
        s = properties.Schema(properties.Schema.STRING, 'A string',
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
                    'update_allowed': False,
                    'immutable': False,
                    'constraints': [
                        {'length': {'min': 4, 'max': 8}},
                    ]
                }
            },
            'required': False,
            'update_allowed': False,
            'immutable': False,
        }
        s = properties.Schema(properties.Schema.STRING, 'A string',
                              default='wibble',
                              constraints=[constraints.Length(4, 8)])
        l = properties.Schema(properties.Schema.LIST, 'A list', schema=s)
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
                    'update_allowed': False,
                    'immutable': False,
                    'constraints': [
                        {'length': {'min': 4, 'max': 8}},
                    ]
                }
            },
            'required': False,
            'update_allowed': False,
            'immutable': False,
        }
        s = properties.Schema(properties.Schema.STRING, 'A string',
                              default='wibble',
                              constraints=[constraints.Length(4, 8)])
        m = properties.Schema(properties.Schema.MAP, 'A map',
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
                            'update_allowed': False,
                            'immutable': False,
                            'constraints': [
                                {'length': {'min': 4, 'max': 8}},
                            ]
                        }
                    },
                    'required': False,
                    'update_allowed': False,
                    'immutable': False,
                }
            },
            'required': False,
            'update_allowed': False,
            'immutable': False,
        }
        s = properties.Schema(properties.Schema.STRING, 'A string',
                              default='wibble',
                              constraints=[constraints.Length(4, 8)])
        m = properties.Schema(properties.Schema.MAP, 'A map',
                              schema={'Foo': s})
        l = properties.Schema(properties.Schema.LIST, 'A list', schema=m)
        self.assertEqual(d, dict(l))

    def test_all_resource_schemata(self):
        for resource_type in resources.global_env().get_types():
            for schema in six.itervalues(getattr(resource_type,
                                                 'properties_schema',
                                                 {})):
                properties.Schema.from_legacy(schema)

    def test_from_legacy_idempotency(self):
        s = properties.Schema(properties.Schema.STRING)
        self.assertTrue(properties.Schema.from_legacy(s) is s)

    def test_from_legacy_minimal_string(self):
        s = properties.Schema.from_legacy({
            'Type': 'String',
        })
        self.assertEqual(properties.Schema.STRING, s.type)
        self.assertIsNone(s.description)
        self.assertIsNone(s.default)
        self.assertFalse(s.required)
        self.assertEqual(0, len(s.constraints))

    def test_from_legacy_string(self):
        s = properties.Schema.from_legacy({
            'Type': 'String',
            'Description': 'a string',
            'Default': 'wibble',
            'Implemented': False,
            'MinLength': 4,
            'MaxLength': 8,
            'AllowedValues': ['blarg', 'wibble'],
            'AllowedPattern': '[a-z]*',
        })
        self.assertEqual(properties.Schema.STRING, s.type)
        self.assertEqual('a string', s.description)
        self.assertEqual('wibble', s.default)
        self.assertFalse(s.required)
        self.assertEqual(3, len(s.constraints))
        self.assertFalse(s.immutable)

    def test_from_legacy_min_length(self):
        s = properties.Schema.from_legacy({
            'Type': 'String',
            'MinLength': 4,
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.Length)
        self.assertEqual(4, c.min)
        self.assertIsNone(c.max)

    def test_from_legacy_max_length(self):
        s = properties.Schema.from_legacy({
            'Type': 'String',
            'MaxLength': 8,
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.Length)
        self.assertIsNone(c.min)
        self.assertEqual(8, c.max)

    def test_from_legacy_minmax_length(self):
        s = properties.Schema.from_legacy({
            'Type': 'String',
            'MinLength': 4,
            'MaxLength': 8,
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.Length)
        self.assertEqual(4, c.min)
        self.assertEqual(8, c.max)

    def test_from_legacy_minmax_string_length(self):
        s = properties.Schema.from_legacy({
            'Type': 'String',
            'MinLength': '4',
            'MaxLength': '8',
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.Length)
        self.assertEqual(4, c.min)
        self.assertEqual(8, c.max)

    def test_from_legacy_min_value(self):
        s = properties.Schema.from_legacy({
            'Type': 'Integer',
            'MinValue': 4,
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.Range)
        self.assertEqual(4, c.min)
        self.assertIsNone(c.max)

    def test_from_legacy_max_value(self):
        s = properties.Schema.from_legacy({
            'Type': 'Integer',
            'MaxValue': 8,
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.Range)
        self.assertIsNone(c.min)
        self.assertEqual(8, c.max)

    def test_from_legacy_minmax_value(self):
        s = properties.Schema.from_legacy({
            'Type': 'Integer',
            'MinValue': 4,
            'MaxValue': 8,
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.Range)
        self.assertEqual(4, c.min)
        self.assertEqual(8, c.max)

    def test_from_legacy_minmax_string_value(self):
        s = properties.Schema.from_legacy({
            'Type': 'Integer',
            'MinValue': '4',
            'MaxValue': '8',
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.Range)
        self.assertEqual(4, c.min)
        self.assertEqual(8, c.max)

    def test_from_legacy_allowed_values(self):
        s = properties.Schema.from_legacy({
            'Type': 'String',
            'AllowedValues': ['blarg', 'wibble'],
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.AllowedValues)
        self.assertEqual(('blarg', 'wibble'), c.allowed)

    def test_from_legacy_allowed_pattern(self):
        s = properties.Schema.from_legacy({
            'Type': 'String',
            'AllowedPattern': '[a-z]*',
        })
        self.assertEqual(1, len(s.constraints))
        c = s.constraints[0]
        self.assertIsInstance(c, constraints.AllowedPattern)
        self.assertEqual('[a-z]*', c.pattern)

    def test_from_legacy_list(self):
        l = properties.Schema.from_legacy({
            'Type': 'List',
            'Default': ['wibble'],
            'Schema': {
                'Type': 'String',
                'Default': 'wibble',
                'MaxLength': 8,
            }
        })
        self.assertEqual(properties.Schema.LIST, l.type)
        self.assertEqual(['wibble'], l.default)

        ss = l.schema[0]
        self.assertEqual(properties.Schema.STRING, ss.type)
        self.assertEqual('wibble', ss.default)

    def test_from_legacy_map(self):
        l = properties.Schema.from_legacy({
            'Type': 'Map',
            'Schema': {
                'foo': {
                    'Type': 'String',
                    'Default': 'wibble',
                }
            }
        })
        self.assertEqual(properties.Schema.MAP, l.type)

        ss = l.schema['foo']
        self.assertEqual(properties.Schema.STRING, ss.type)
        self.assertEqual('wibble', ss.default)

    def test_from_legacy_invalid_key(self):
        self.assertRaises(exception.InvalidSchemaError,
                          properties.Schema.from_legacy,
                          {'Type': 'String', 'Foo': 'Bar'})

    def test_from_string_param(self):
        description = "WebServer EC2 instance type"
        allowed_values = ["t1.micro", "m1.small", "m1.large", "m1.xlarge",
                          "m2.xlarge", "m2.2xlarge", "m2.4xlarge",
                          "c1.medium", "c1.xlarge", "cc1.4xlarge"]
        constraint_desc = "Must be a valid EC2 instance type."
        param = parameters.Schema.from_dict('name', {
            "Type": "String",
            "Description": description,
            "Default": "m1.large",
            "AllowedValues": allowed_values,
            "ConstraintDescription": constraint_desc,
        })

        schema = properties.Schema.from_parameter(param)

        self.assertEqual(properties.Schema.STRING, schema.type)
        self.assertEqual(description, schema.description)
        self.assertIsNone(schema.default)
        self.assertFalse(schema.required)
        self.assertEqual(1, len(schema.constraints))

        allowed_constraint = schema.constraints[0]

        self.assertEqual(tuple(allowed_values), allowed_constraint.allowed)
        self.assertEqual(constraint_desc, allowed_constraint.description)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_string_allowed_pattern(self):
        description = "WebServer EC2 instance type"
        allowed_pattern = "[A-Za-z0-9.]*"
        constraint_desc = "Must contain only alphanumeric characters."
        param = parameters.Schema.from_dict('name', {
            "Type": "String",
            "Description": description,
            "Default": "m1.large",
            "AllowedPattern": allowed_pattern,
            "ConstraintDescription": constraint_desc,
        })

        schema = properties.Schema.from_parameter(param)

        self.assertEqual(properties.Schema.STRING, schema.type)
        self.assertEqual(description, schema.description)
        self.assertIsNone(schema.default)
        self.assertFalse(schema.required)
        self.assertEqual(1, len(schema.constraints))

        allowed_constraint = schema.constraints[0]

        self.assertEqual(allowed_pattern, allowed_constraint.pattern)
        self.assertEqual(constraint_desc, allowed_constraint.description)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_string_multi_constraints(self):
        description = "WebServer EC2 instance type"
        allowed_pattern = "[A-Za-z0-9.]*"
        constraint_desc = "Must contain only alphanumeric characters."
        param = parameters.Schema.from_dict('name', {
            "Type": "String",
            "Description": description,
            "Default": "m1.large",
            "MinLength": "7",
            "AllowedPattern": allowed_pattern,
            "ConstraintDescription": constraint_desc,
        })

        schema = properties.Schema.from_parameter(param)

        self.assertEqual(properties.Schema.STRING, schema.type)
        self.assertEqual(description, schema.description)
        self.assertIsNone(schema.default)
        self.assertFalse(schema.required)
        self.assertEqual(2, len(schema.constraints))

        len_constraint = schema.constraints[0]
        allowed_constraint = schema.constraints[1]

        self.assertEqual(7, len_constraint.min)
        self.assertIsNone(len_constraint.max)
        self.assertEqual(allowed_pattern, allowed_constraint.pattern)
        self.assertEqual(constraint_desc, allowed_constraint.description)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_param_string_min_len(self):
        param = parameters.Schema.from_dict('name', {
            "Description": "WebServer EC2 instance type",
            "Type": "String",
            "Default": "m1.large",
            "MinLength": "7",
        })
        schema = properties.Schema.from_parameter(param)

        self.assertFalse(schema.required)
        self.assertIsNone(schema.default)
        self.assertEqual(1, len(schema.constraints))

        len_constraint = schema.constraints[0]

        self.assertEqual(7, len_constraint.min)
        self.assertIsNone(len_constraint.max)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_param_string_max_len(self):
        param = parameters.Schema.from_dict('name', {
            "Description": "WebServer EC2 instance type",
            "Type": "String",
            "Default": "m1.large",
            "MaxLength": "11",
        })
        schema = properties.Schema.from_parameter(param)

        self.assertFalse(schema.required)
        self.assertIsNone(schema.default)
        self.assertEqual(1, len(schema.constraints))

        len_constraint = schema.constraints[0]

        self.assertIsNone(len_constraint.min)
        self.assertEqual(11, len_constraint.max)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_param_string_min_max_len(self):
        param = parameters.Schema.from_dict('name', {
            "Description": "WebServer EC2 instance type",
            "Type": "String",
            "Default": "m1.large",
            "MinLength": "7",
            "MaxLength": "11",
        })
        schema = properties.Schema.from_parameter(param)

        self.assertFalse(schema.required)
        self.assertIsNone(schema.default)
        self.assertEqual(1, len(schema.constraints))

        len_constraint = schema.constraints[0]

        self.assertEqual(7, len_constraint.min)
        self.assertEqual(11, len_constraint.max)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_param_no_default(self):
        param = parameters.Schema.from_dict('name', {
            "Description": "WebServer EC2 instance type",
            "Type": "String",
        })
        schema = properties.Schema.from_parameter(param)

        self.assertTrue(schema.required)
        self.assertIsNone(schema.default)
        self.assertEqual(0, len(schema.constraints))
        self.assertFalse(schema.allow_conversion)

        props = properties.Properties({'name': schema}, {'name': 'm1.large'})
        props.validate()

    def test_from_number_param_min(self):
        param = parameters.Schema.from_dict('name', {
            "Type": "Number",
            "Default": "42",
            "MinValue": "10",
        })

        schema = properties.Schema.from_parameter(param)

        self.assertEqual(properties.Schema.NUMBER, schema.type)
        self.assertIsNone(schema.default)
        self.assertFalse(schema.required)
        self.assertEqual(1, len(schema.constraints))

        value_constraint = schema.constraints[0]

        self.assertEqual(10, value_constraint.min)
        self.assertIsNone(value_constraint.max)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_number_param_max(self):
        param = parameters.Schema.from_dict('name', {
            "Type": "Number",
            "Default": "42",
            "MaxValue": "100",
        })

        schema = properties.Schema.from_parameter(param)

        self.assertEqual(properties.Schema.NUMBER, schema.type)
        self.assertIsNone(schema.default)
        self.assertFalse(schema.required)
        self.assertEqual(1, len(schema.constraints))

        value_constraint = schema.constraints[0]

        self.assertIsNone(value_constraint.min)
        self.assertEqual(100, value_constraint.max)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_number_param_min_max(self):
        param = parameters.Schema.from_dict('name', {
            "Type": "Number",
            "Default": "42",
            "MinValue": "10",
            "MaxValue": "100",
        })

        schema = properties.Schema.from_parameter(param)

        self.assertEqual(properties.Schema.NUMBER, schema.type)
        self.assertIsNone(schema.default)
        self.assertFalse(schema.required)
        self.assertEqual(1, len(schema.constraints))

        value_constraint = schema.constraints[0]

        self.assertEqual(10, value_constraint.min)
        self.assertEqual(100, value_constraint.max)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_number_param_allowed_vals(self):
        constraint_desc = "The quick brown fox jumps over the lazy dog."
        param = parameters.Schema.from_dict('name', {
            "Type": "Number",
            "Default": "42",
            "AllowedValues": ["10", "42", "100"],
            "ConstraintDescription": constraint_desc,
        })

        schema = properties.Schema.from_parameter(param)

        self.assertEqual(properties.Schema.NUMBER, schema.type)
        self.assertIsNone(schema.default)
        self.assertFalse(schema.required)
        self.assertEqual(1, len(schema.constraints))
        self.assertFalse(schema.allow_conversion)

        allowed_constraint = schema.constraints[0]

        self.assertEqual(('10', '42', '100'), allowed_constraint.allowed)
        self.assertEqual(constraint_desc, allowed_constraint.description)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_list_param(self):
        param = parameters.Schema.from_dict('name', {
            "Type": "CommaDelimitedList",
            "Default": "foo,bar,baz"
        })

        schema = properties.Schema.from_parameter(param)

        self.assertEqual(properties.Schema.LIST, schema.type)
        self.assertIsNone(schema.default)
        self.assertFalse(schema.required)
        self.assertTrue(schema.allow_conversion)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_from_json_param(self):
        param = parameters.Schema.from_dict('name', {
            "Type": "Json",
            "Default": {"foo": "bar", "blarg": "wibble"}
        })

        schema = properties.Schema.from_parameter(param)

        self.assertEqual(properties.Schema.MAP, schema.type)
        self.assertIsNone(schema.default)
        self.assertFalse(schema.required)
        self.assertTrue(schema.allow_conversion)

        props = properties.Properties({'test': schema}, {})
        props.validate()

    def test_no_mismatch_in_update_policy(self):
        manager = plugin_manager.PluginManager('heat.engine.resources')
        resource_mapping = plugin_manager.PluginMapping('resource')
        res_plugin_mappings = resource_mapping.load_all(manager)
        all_resources = {}
        for mapping in res_plugin_mappings:
            name, cls = mapping
            all_resources[name] = cls

        def check_update_policy(resource_type, prop_key, prop, update=False):
            if prop.update_allowed:
                update = True
            sub_schema = prop.schema
            if sub_schema:
                for sub_prop_key, sub_prop in six.iteritems(sub_schema):
                    if not update:
                        self.assertEqual(update, sub_prop.update_allowed,
                                         "Mismatch in update policies: "
                                         "resource %(res)s, properties "
                                         "'%(prop)s' and '%(nested_prop)s'." %
                                         {'res': resource_type,
                                          'prop': prop_key,
                                          'nested_prop': sub_prop_key})
                    if sub_prop_key == '*':
                        check_update_policy(resource_type, prop_key,
                                            sub_prop, update)
                    else:
                        check_update_policy(resource_type, sub_prop_key,
                                            sub_prop, update)

        for resource_type, resource_class in six.iteritems(all_resources):
            props_schemata = properties.schemata(
                resource_class.properties_schema)

            for prop_key, prop in six.iteritems(props_schemata):
                check_update_policy(resource_type, prop_key, prop)


class PropertyTest(common.HeatTestCase):
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
        self.assertEqual('wibble', p.default())

    def test_type(self):
        p = properties.Property({'Type': 'String'})
        self.assertEqual('String', p.type())

    def test_bad_type(self):
        self.assertRaises(exception.InvalidSchemaError,
                          properties.Property, {'Type': 'Fish'})

    def test_bad_key(self):
        self.assertRaises(exception.InvalidSchemaError,
                          properties.Property,
                          {'Type': 'String', 'Foo': 'Bar'})

    def test_string_pattern_good(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = properties.Property(schema)
        self.assertEqual('foo', p.get_value('foo', True))

    def test_string_pattern_bad_prefix(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, '1foo', True)

    def test_string_pattern_bad_suffix(self):
        schema = {'Type': 'String',
                  'AllowedPattern': '[a-z]*'}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, 'foo1', True)

    def test_string_value_list_good(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = properties.Property(schema)
        self.assertEqual('bar', p.get_value('bar', True))

    def test_string_value_list_bad(self):
        schema = {'Type': 'String',
                  'AllowedValues': ['foo', 'bar', 'baz']}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, 'blarg', True)

    def test_string_maxlength_good(self):
        schema = {'Type': 'String',
                  'MaxLength': '5'}
        p = properties.Property(schema)
        self.assertEqual('abcd', p.get_value('abcd', True))

    def test_string_exceeded_maxlength(self):
        schema = {'Type': 'String',
                  'MaxLength': '5'}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, 'abcdef', True)

    def test_string_length_in_range(self):
        schema = {'Type': 'String',
                  'MinLength': '5',
                  'MaxLength': '10'}
        p = properties.Property(schema)
        self.assertEqual('abcdef', p.get_value('abcdef', True))

    def test_string_minlength_good(self):
        schema = {'Type': 'String',
                  'MinLength': '5'}
        p = properties.Property(schema)
        self.assertEqual('abcde', p.get_value('abcde', True))

    def test_string_smaller_than_minlength(self):
        schema = {'Type': 'String',
                  'MinLength': '5'}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, 'abcd', True)

    def test_int_good(self):
        schema = {'Type': 'Integer',
                  'MinValue': 3,
                  'MaxValue': 3}
        p = properties.Property(schema)
        self.assertEqual(3, p.get_value(3, True))

    def test_int_bad(self):
        schema = {'Type': 'Integer'}
        p = properties.Property(schema)
        # python 3.4.3 returns another error message
        # try to handle this by regexp
        self.assertRaisesRegex(
            TypeError, r"int\(\) argument must be a string"
                       "(, a bytes-like object)?"
                       " or a number, not 'list'", p.get_value, [1])

    def test_str_from_int(self):
        schema = {'Type': 'String'}
        p = properties.Property(schema)
        self.assertEqual('3', p.get_value(3))

    def test_str_from_bool(self):
        schema = {'Type': 'String'}
        p = properties.Property(schema)
        self.assertEqual('True', p.get_value(True))

    def test_int_from_str_good(self):
        schema = {'Type': 'Integer'}
        p = properties.Property(schema)
        self.assertEqual(3, p.get_value('3'))

    def test_int_from_str_bad(self):
        schema = {'Type': 'Integer'}
        p = properties.Property(schema)
        ex = self.assertRaises(TypeError, p.get_value, '3a')
        self.assertEqual("Value '3a' is not an integer", six.text_type(ex))

    def test_integer_low(self):
        schema = {'Type': 'Integer',
                  'MinValue': 4}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed, p.get_value, 3,
                          True)

    def test_integer_high(self):
        schema = {'Type': 'Integer',
                  'MaxValue': 2}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed, p.get_value, 3,
                          True)

    def test_integer_value_list_good(self):
        schema = {'Type': 'Integer',
                  'AllowedValues': [1, 3, 5]}
        p = properties.Property(schema)
        self.assertEqual(5, p.get_value(5), True)

    def test_integer_value_list_bad(self):
        schema = {'Type': 'Integer',
                  'AllowedValues': [1, 3, 5]}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed, p.get_value, 2,
                          True)

    def test_number_good(self):
        schema = {'Type': 'Number',
                  'MinValue': '3',
                  'MaxValue': '3'}
        p = properties.Property(schema)
        self.assertEqual(3, p.get_value(3, True))

    def test_numbers_from_strings(self):
        """Numbers can be converted from strings."""
        schema = {'Type': 'Number',
                  'MinValue': '3',
                  'MaxValue': '3'}
        p = properties.Property(schema)
        self.assertEqual(3, p.get_value('3'))

    def test_number_value_list_good(self):
        schema = {'Type': 'Number',
                  'AllowedValues': [1, 3, 5]}
        p = properties.Property(schema)
        self.assertEqual(5, p.get_value('5', True))

    def test_number_value_list_bad(self):
        schema = {'Type': 'Number',
                  'AllowedValues': ['1', '3', '5']}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, '2', True)

    def test_number_low(self):
        schema = {'Type': 'Number',
                  'MinValue': '4'}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, '3', True)

    def test_number_high(self):
        schema = {'Type': 'Number',
                  'MaxValue': '2'}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, '3', True)

    def test_boolean_true(self):
        p = properties.Property({'Type': 'Boolean'})
        self.assertIs(True, p.get_value('True'))
        self.assertIs(True, p.get_value('true'))
        self.assertIs(True, p.get_value(True))

    def test_boolean_false(self):
        p = properties.Property({'Type': 'Boolean'})
        self.assertIs(False, p.get_value('False'))
        self.assertIs(False, p.get_value('false'))
        self.assertIs(False, p.get_value(False))

    def test_boolean_invalid_string(self):
        p = properties.Property({'Type': 'Boolean'})
        self.assertRaises(ValueError, p.get_value, 'fish')

    def test_boolean_invalid_int(self):
        p = properties.Property({'Type': 'Boolean'})
        self.assertRaises(TypeError, p.get_value, 5)

    def test_list_string(self):
        p = properties.Property({'Type': 'List'})
        self.assertRaises(TypeError, p.get_value, 'foo')

    def test_list_good(self):
        p = properties.Property({'Type': 'List'})
        self.assertEqual(['foo', 'bar'], p.get_value(['foo', 'bar']))

    def test_list_dict(self):
        p = properties.Property({'Type': 'List'})
        self.assertRaises(TypeError, p.get_value, {'foo': 'bar'})

    def test_list_is_delimited(self):
        p = properties.Property({'Type': 'List'})
        self.assertRaises(TypeError, p.get_value, 'foo,bar')
        p.schema.allow_conversion = True
        self.assertEqual(['foo', 'bar'], p.get_value('foo,bar'))
        self.assertEqual(['foo'], p.get_value('foo'))

    def test_map_path(self):
        p = properties.Property({'Type': 'Map'}, name='test', path='parent')
        self.assertEqual('parent.test', p.path)

    def test_list_path(self):
        p = properties.Property({'Type': 'List'}, name='0', path='parent')
        self.assertEqual('parent.0', p.path)

    def test_list_maxlength_good(self):
        schema = {'Type': 'List',
                  'MaxLength': '3'}
        p = properties.Property(schema)
        self.assertEqual(['1', '2'], p.get_value(['1', '2'], True))

    def test_list_exceeded_maxlength(self):
        schema = {'Type': 'List',
                  'MaxLength': '2'}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, ['1', '2', '3'], True)

    def test_list_length_in_range(self):
        schema = {'Type': 'List',
                  'MinLength': '2',
                  'MaxLength': '4'}
        p = properties.Property(schema)
        self.assertEqual(['1', '2', '3'], p.get_value(['1', '2', '3'], True))

    def test_list_minlength_good(self):
        schema = {'Type': 'List',
                  'MinLength': '3'}
        p = properties.Property(schema)
        self.assertEqual(['1', '2', '3'], p.get_value(['1', '2', '3'], True))

    def test_list_smaller_than_minlength(self):
        schema = {'Type': 'List',
                  'MinLength': '4'}
        p = properties.Property(schema)
        self.assertRaises(exception.StackValidationFailed,
                          p.get_value, ['1', '2', '3'], True)

    def test_map_list_default(self):
        schema = {'Type': 'Map',
                  'Default': ['foo', 'bar']}
        p = properties.Property(schema)
        p.schema.allow_conversion = True
        self.assertEqual(jsonutils.dumps(['foo', 'bar']),
                         p.get_value(None))

    def test_map_list_default_empty(self):
        schema = {'Type': 'Map',
                  'Default': []}
        p = properties.Property(schema)
        p.schema.allow_conversion = True
        self.assertEqual(jsonutils.dumps([]), p.get_value(None))

    def test_map_list_no_default(self):
        schema = {'Type': 'Map'}
        p = properties.Property(schema)
        p.schema.allow_conversion = True
        self.assertEqual({}, p.get_value(None))

    def test_map_string(self):
        p = properties.Property({'Type': 'Map'})
        self.assertRaises(TypeError, p.get_value, 'foo')

    def test_map_list(self):
        p = properties.Property({'Type': 'Map'})
        self.assertRaises(TypeError, p.get_value, ['foo'])

    def test_map_allow_conversion(self):
        p = properties.Property({'Type': 'Map'})
        p.schema.allow_conversion = True
        self.assertEqual('foo', p.get_value('foo'))
        self.assertEqual(jsonutils.dumps(['foo']), p.get_value(['foo']))

    def test_map_schema_good(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        p = properties.Property({'Type': 'Map', 'Schema': map_schema})
        self.assertEqual({'valid': True}, p.get_value({'valid': 'TRUE'}))

    def test_map_schema_bad_data(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        p = properties.Property({'Type': 'Map', 'Schema': map_schema})
        ex = self.assertRaises(exception.StackValidationFailed,
                               p.get_value, {'valid': 'fish'}, True)
        self.assertEqual('Property error: valid: "fish" is not a '
                         'valid boolean', six.text_type(ex))

    def test_map_schema_missing_data(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        p = properties.Property({'Type': 'Map', 'Schema': map_schema})
        self.assertEqual({'valid': None}, p.get_value({}))

    def test_map_schema_missing_required_data(self):
        map_schema = {'valid': {'Type': 'Boolean', 'Required': True}}
        p = properties.Property({'Type': 'Map', 'Schema': map_schema})
        ex = self.assertRaises(exception.StackValidationFailed,
                               p.get_value, {}, True)
        self.assertEqual('Property error: Property valid not assigned',
                         six.text_type(ex))

    def test_list_schema_good(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        list_schema = {'Type': 'Map', 'Schema': map_schema}
        p = properties.Property({'Type': 'List', 'Schema': list_schema})
        self.assertEqual([{'valid': True},
                          {'valid': False}],
                         p.get_value([{'valid': 'TRUE'},
                                      {'valid': 'False'}]))

    def test_list_schema_bad_data(self):
        map_schema = {'valid': {'Type': 'Boolean'}}
        list_schema = {'Type': 'Map', 'Schema': map_schema}
        p = properties.Property({'Type': 'List', 'Schema': list_schema})
        ex = self.assertRaises(exception.StackValidationFailed,
                               p.get_value,
                               [{'valid': 'True'}, {'valid': 'fish'}], True)
        self.assertEqual('Property error: [1].valid: "fish" is not '
                         'a valid boolean', six.text_type(ex))

    def test_list_schema_int_good(self):
        list_schema = {'Type': 'Integer'}
        p = properties.Property({'Type': 'List', 'Schema': list_schema})
        self.assertEqual([1, 2, 3], p.get_value([1, 2, 3]))

    def test_list_schema_int_bad_data(self):
        list_schema = {'Type': 'Integer'}
        p = properties.Property({'Type': 'List', 'Schema': list_schema})
        ex = self.assertRaises(exception.StackValidationFailed,
                               p.get_value, [42, 'fish'], True)
        self.assertEqual("Property error: [1]: Value 'fish' is not "
                         "an integer", six.text_type(ex))


class PropertiesTest(common.HeatTestCase):
    def setUp(self):
        super(PropertiesTest, self).setUp()
        schema = {
            'int': {'Type': 'Integer'},
            'string': {'Type': 'String'},
            'required_int': {'Type': 'Integer', 'Required': True},
            'bad_int': {'Type': 'Integer'},
            'missing': {'Type': 'Integer'},
            'defaulted': {'Type': 'Integer', 'Default': 1},
            'default_override': {'Type': 'Integer', 'Default': 1},
            'default_bool': {'Type': 'Boolean', 'Default': 'false'},
        }
        data = {
            'int': 21,
            'string': 'foo',
            'bad_int': 'foo',
            'default_override': 21,
        }

        def double(d):
            return d * 2

        self.props = properties.Properties(schema, data, double, 'wibble')

    def test_integer_good(self):
        self.assertEqual(42, self.props['int'])

    def test_string_good(self):
        self.assertEqual('foofoo', self.props['string'])

    def test_bool_not_str(self):
        self.assertFalse(self.props['default_bool'])

    def test_missing_required(self):
        self.assertRaises(ValueError, self.props.get, 'required_int')

    @mock.patch.object(translation.Translation, 'has_translation')
    @mock.patch.object(translation.Translation, 'translate')
    def test_required_with_translate_no_value(self, m_t, m_ht):
        m_t.return_value = None
        m_ht.return_value = True

        self.assertRaises(ValueError, self.props.get, 'required_int')

    def test_integer_bad(self):
        self.assertRaises(ValueError, self.props.get, 'bad_int')

    def test_missing(self):
        self.assertIsNone(self.props['missing'])

    def test_default(self):
        self.assertEqual(1, self.props['defaulted'])

    def test_default_override(self):
        self.assertEqual(42, self.props['default_override'])

    def test_get_user_value(self):
        self.assertIsNone(self.props.get_user_value('defaulted'))
        self.assertEqual(42, self.props.get_user_value('default_override'))

    def test_get_user_value_key_error(self):
        ex = self.assertRaises(KeyError, self.props.get_user_value, 'foo')
        # Note we have to use args here: https://bugs.python.org/issue2651
        self.assertEqual('Invalid Property foo',
                         six.text_type(ex.args[0]))

    def test_bad_key(self):
        self.assertEqual('wibble', self.props.get('foo', 'wibble'))

    def test_key_error(self):
        ex = self.assertRaises(KeyError, self.props.__getitem__, 'foo')
        # Note we have to use args here: https://bugs.python.org/issue2651
        self.assertEqual('Invalid Property foo',
                         six.text_type(ex.args[0]))

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
        self.assertIs(False, props['foo'])

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
        self.assertIs(True, props['foo'])

    def test_none_default_map(self):
        schema = {'foo': {'Type': 'Map', 'Default': {'bar': 'baz'}}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual({'bar': 'baz'}, props['foo'])

    def test_none_default_list(self):
        schema = {'foo': {'Type': 'List', 'Default': ['one', 'two']}}
        props = properties.Properties(schema, {'foo': None})
        self.assertEqual(['one', 'two'], props['foo'])

    def test_resolve_returns_none(self):
        schema = {'foo': {'Type': 'String', "MinLength": "5"}}

        def test_resolver(prop):
            return None

        self.patchobject(properties.Properties,
                         '_find_deps_any_in_init').return_value = True

        props = properties.Properties(schema,
                                      {'foo': 'get_attr: [db, value]'},
                                      test_resolver)
        try:
            self.assertIsNone(props.validate())
        except exception.StackValidationFailed:
            self.fail("Constraints should not have been evaluated.")

    def test_resolve_ref_with_constraints(self):
        # create test custom constraint
        class IncorrectConstraint(constraints.BaseCustomConstraint):

            expected_exceptions = (Exception,)

            def validate_with_client(self, client, value):
                raise Exception("Test exception")

        class TestCustomConstraint(constraints.CustomConstraint):
            @property
            def custom_constraint(self):
                return IncorrectConstraint()

        # create schema with test constraint
        schema = {
            'foo': properties.Schema(
                properties.Schema.STRING,
                constraints=[TestCustomConstraint('test_constraint')]
            )
        }

        # define parameters for function
        def test_resolver(prop):
            return 'None'

        class rsrc(object):
            action = INIT = "INIT"

        class DummyStack(dict):
            pass

        stack = DummyStack(another_res=rsrc())

        # define properties with function and constraint
        props = properties.Properties(
            schema,
            {'foo': hot_funcs.GetResource(
                stack, 'get_resource', 'another_res')},
            test_resolver)

        try:
            self.assertIsNone(props.validate())
        except exception.StackValidationFailed:
            self.fail("Constraints should not have been evaluated.")

    def test_schema_from_params(self):
        params_snippet = {
            "DBUsername": {
                "Type": "String",
                "Description": "The WordPress database admin account username",
                "Default": "admin",
                "MinLength": "1",
                "AllowedPattern": "[a-zA-Z][a-zA-Z0-9]*",
                "NoEcho": "true",
                "MaxLength": "16",
                "ConstraintDescription": ("must begin with a letter and "
                                          "contain only alphanumeric "
                                          "characters.")
            },
            "KeyName": {
                "Type": "String",
                "Description": ("Name of an existing EC2 KeyPair to enable "
                                "SSH access to the instances")
            },
            "LinuxDistribution": {
                "Default": "F17",
                "Type": "String",
                "Description": "Distribution of choice",
                "AllowedValues": [
                    "F18",
                    "F17",
                    "U10",
                    "RHEL-6.1",
                    "RHEL-6.2",
                    "RHEL-6.3"
                ]
            },
            "DBPassword": {
                "Type": "String",
                "Description": "The WordPress database admin account password",
                "Default": "admin",
                "MinLength": "1",
                "AllowedPattern": "[a-zA-Z0-9]*",
                "NoEcho": "true",
                "MaxLength": "41",
                "ConstraintDescription": ("must contain only alphanumeric "
                                          "characters.")
            },
            "DBName": {
                "AllowedPattern": "[a-zA-Z][a-zA-Z0-9]*",
                "Type": "String",
                "Description": "The WordPress database name",
                "MaxLength": "64",
                "Default": "wordpress",
                "MinLength": "1",
                "ConstraintDescription": ("must begin with a letter and "
                                          "contain only alphanumeric "
                                          "characters.")
            },
            "InstanceType": {
                "Default": "m1.large",
                "Type": "String",
                "ConstraintDescription": "must be a valid EC2 instance type.",
                "Description": "WebServer EC2 instance type",
                "AllowedValues": [
                    "t1.micro",
                    "m1.small",
                    "m1.large",
                    "m1.xlarge",
                    "m2.xlarge",
                    "m2.2xlarge",
                    "m2.4xlarge",
                    "c1.medium",
                    "c1.xlarge",
                    "cc1.4xlarge"
                ]
            },
            "DBRootPassword": {
                "Type": "String",
                "Description": "Root password for MySQL",
                "Default": "admin",
                "MinLength": "1",
                "AllowedPattern": "[a-zA-Z0-9]*",
                "NoEcho": "true",
                "MaxLength": "41",
                "ConstraintDescription": ("must contain only alphanumeric "
                                          "characters.")
            }
        }
        expected = {
            "DBUsername": {
                "type": "string",
                "description": "The WordPress database admin account username",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"length": {"min": 1, "max": 16},
                     "description": "must begin with a letter and contain "
                                    "only alphanumeric characters."},
                    {"allowed_pattern": "[a-zA-Z][a-zA-Z0-9]*",
                     "description": "must begin with a letter and contain "
                                    "only alphanumeric characters."},
                ]
            },
            "LinuxDistribution": {
                "type": "string",
                "description": "Distribution of choice",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"allowed_values": ["F18", "F17", "U10",
                                        "RHEL-6.1", "RHEL-6.2", "RHEL-6.3"]}
                ]
            },
            "InstanceType": {
                "type": "string",
                "description": "WebServer EC2 instance type",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"allowed_values": ["t1.micro",
                                        "m1.small",
                                        "m1.large",
                                        "m1.xlarge",
                                        "m2.xlarge",
                                        "m2.2xlarge",
                                        "m2.4xlarge",
                                        "c1.medium",
                                        "c1.xlarge",
                                        "cc1.4xlarge"],
                     "description": "must be a valid EC2 instance type."},
                ]
            },
            "DBRootPassword": {
                "type": "string",
                "description": "Root password for MySQL",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"length": {"min": 1, "max": 41},
                     "description": "must contain only alphanumeric "
                                    "characters."},
                    {"allowed_pattern": "[a-zA-Z0-9]*",
                     "description": "must contain only alphanumeric "
                                    "characters."},
                ]
            },
            "KeyName": {
                "type": "string",
                "description": ("Name of an existing EC2 KeyPair to enable "
                                "SSH access to the instances"),
                "required": True,
                'update_allowed': True,
                'immutable': False,
            },
            "DBPassword": {
                "type": "string",
                "description": "The WordPress database admin account password",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"length": {"min": 1, "max": 41},
                     "description": "must contain only alphanumeric "
                                    "characters."},
                    {"allowed_pattern": "[a-zA-Z0-9]*",
                     "description": "must contain only alphanumeric "
                                    "characters."},
                ]
            },
            "DBName": {
                "type": "string",
                "description": "The WordPress database name",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"length": {"min": 1, "max": 64},
                     "description": "must begin with a letter and contain "
                                    "only alphanumeric characters."},
                    {"allowed_pattern": "[a-zA-Z][a-zA-Z0-9]*",
                     "description": "must begin with a letter and contain "
                                    "only alphanumeric characters."},
                ]
            },
        }
        params = dict((n, parameters.Schema.from_dict(n, s)) for n, s
                      in params_snippet.items())
        props_schemata = properties.Properties.schema_from_params(params)

        self.assertEqual(expected,
                         dict((n, dict(s)) for n, s in props_schemata.items()))

    def test_schema_from_hot_params(self):
        params_snippet = {
            "KeyName": {
                "type": "string",
                "description": ("Name of an existing EC2 KeyPair to enable "
                                "SSH access to the instances")
            },
            "InstanceType": {
                "default": "m1.large",
                "type": "string",
                "description": "WebServer EC2 instance type",
                "constraints": [
                    {"allowed_values": ["t1.micro", "m1.small", "m1.large",
                                        "m1.xlarge", "m2.xlarge", "m2.2xlarge",
                                        "m2.4xlarge", "c1.medium", "c1.xlarge",
                                        "cc1.4xlarge"],
                     "description": "Must be a valid EC2 instance type."}
                ]
            },
            "LinuxDistribution": {
                "default": "F17",
                "type": "string",
                "description": "Distribution of choice",
                "constraints": [
                    {"allowed_values": ["F18", "F17", "U10", "RHEL-6.1",
                                        "RHEL-6.2", "RHEL-6.3"],
                     "description": "Must be a valid Linux distribution"}
                ]
            },
            "DBName": {
                "type": "string",
                "description": "The WordPress database name",
                "default": "wordpress",
                "constraints": [
                    {"length": {"min": 1, "max": 64},
                     "description": "Length must be between 1 and 64"},
                    {"allowed_pattern": "[a-zA-Z][a-zA-Z0-9]*",
                     "description": ("Must begin with a letter and contain "
                                     "only alphanumeric characters.")}
                ]
            },
            "DBUsername": {
                "type": "string",
                "description": "The WordPress database admin account username",
                "default": "admin",
                "hidden": "true",
                "constraints": [
                    {"length": {"min": 1, "max": 16},
                     "description": "Length must be between 1 and 16"},
                    {"allowed_pattern": "[a-zA-Z][a-zA-Z0-9]*",
                     "description": ("Must begin with a letter and only "
                                     "contain alphanumeric characters")}
                ]
            },
            "DBPassword": {
                "type": "string",
                "description": "The WordPress database admin account password",
                "default": "admin",
                "hidden": "true",
                "constraints": [
                    {"length": {"min": 1, "max": 41},
                     "description": "Length must be between 1 and 41"},
                    {"allowed_pattern": "[a-zA-Z0-9]*",
                     "description": ("Must contain only alphanumeric "
                                     "characters")}
                ]
            },
            "DBRootPassword": {
                "type": "string",
                "description": "Root password for MySQL",
                "default": "admin",
                "hidden": "true",
                "constraints": [
                    {"length": {"min": 1, "max": 41},
                     "description": "Length must be between 1 and 41"},
                    {"allowed_pattern": "[a-zA-Z0-9]*",
                     "description": ("Must contain only alphanumeric "
                                     "characters")}
                ]
            }
        }
        expected = {
            "KeyName": {
                "type": "string",
                "description": ("Name of an existing EC2 KeyPair to enable "
                                "SSH access to the instances"),
                "required": True,
                'update_allowed': True,
                'immutable': False,
            },
            "InstanceType": {
                "type": "string",
                "description": "WebServer EC2 instance type",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"allowed_values": ["t1.micro", "m1.small", "m1.large",
                                        "m1.xlarge", "m2.xlarge", "m2.2xlarge",
                                        "m2.4xlarge", "c1.medium", "c1.xlarge",
                                        "cc1.4xlarge"],
                     "description": "Must be a valid EC2 instance type."},
                ]
            },
            "LinuxDistribution": {
                "type": "string",
                "description": "Distribution of choice",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"allowed_values": ["F18", "F17", "U10",
                                        "RHEL-6.1", "RHEL-6.2", "RHEL-6.3"],
                     "description": "Must be a valid Linux distribution"}
                ]
            },
            "DBName": {
                "type": "string",
                "description": "The WordPress database name",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"length": {"min": 1, "max": 64},
                     "description": "Length must be between 1 and 64"},
                    {"allowed_pattern": "[a-zA-Z][a-zA-Z0-9]*",
                     "description": ("Must begin with a letter and contain "
                                     "only alphanumeric characters.")},
                ]
            },
            "DBUsername": {
                "type": "string",
                "description": "The WordPress database admin account username",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"length": {"min": 1, "max": 16},
                     "description": "Length must be between 1 and 16"},
                    {"allowed_pattern": "[a-zA-Z][a-zA-Z0-9]*",
                     "description": ("Must begin with a letter and only "
                                     "contain alphanumeric characters")},
                ]
            },
            "DBPassword": {
                "type": "string",
                "description": "The WordPress database admin account password",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"length": {"min": 1, "max": 41},
                     "description": "Length must be between 1 and 41"},
                    {"allowed_pattern": "[a-zA-Z0-9]*",
                     "description": ("Must contain only alphanumeric "
                                     "characters")},
                ]
            },
            "DBRootPassword": {
                "type": "string",
                "description": "Root password for MySQL",
                "required": False,
                'update_allowed': True,
                'immutable': False,
                "constraints": [
                    {"length": {"min": 1, "max": 41},
                     "description": "Length must be between 1 and 41"},
                    {"allowed_pattern": "[a-zA-Z0-9]*",
                     "description": ("Must contain only alphanumeric "
                                     "characters")},
                ]
            }
        }
        params = dict((n, hot_param.HOTParamSchema.from_dict(n, s)) for n, s
                      in params_snippet.items())
        props_schemata = properties.Properties.schema_from_params(params)

        self.assertEqual(expected,
                         dict((n, dict(s)) for n, s in props_schemata.items()))

    def test_compare_same(self):
        schema = {'foo': {'Type': 'Integer'}}
        props_a = properties.Properties(schema, {'foo': 1})
        props_b = properties.Properties(schema, {'foo': 1})
        self.assertFalse(props_a != props_b)

    def test_compare_different(self):
        schema = {'foo': {'Type': 'Integer'}}
        props_a = properties.Properties(schema, {'foo': 0})
        props_b = properties.Properties(schema, {'foo': 1})
        self.assertTrue(props_a != props_b)


class PropertiesValidationTest(common.HeatTestCase):
    def test_required(self):
        schema = {'foo': {'Type': 'String', 'Required': True}}
        props = properties.Properties(schema, {'foo': 'bar'})
        self.assertIsNone(props.validate())

    def test_missing_required(self):
        schema = {'foo': {'Type': 'String', 'Required': True}}
        props = properties.Properties(schema, {})
        self.assertRaises(exception.StackValidationFailed, props.validate)

    def test_missing_unimplemented(self):
        schema = {'foo': {'Type': 'String', 'Implemented': False}}
        props = properties.Properties(schema, {})
        self.assertIsNone(props.validate())

    def test_present_unimplemented(self):
        schema = {'foo': {'Type': 'String', 'Implemented': False}}
        props = properties.Properties(schema, {'foo': 'bar'})
        self.assertRaises(exception.StackValidationFailed, props.validate)

    def test_missing(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {})
        self.assertIsNone(props.validate())

    def test_unknown_typo(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {'food': 42})
        self.assertRaises(exception.StackValidationFailed, props.validate)

    def test_list_instead_string(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {'foo': ['foo', 'bar']})
        ex = self.assertRaises(exception.StackValidationFailed, props.validate)
        self.assertIn('Property error: foo: Value must be a string',
                      six.text_type(ex))

    def test_dict_instead_string(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {'foo': {'foo': 'bar'}})
        ex = self.assertRaises(exception.StackValidationFailed, props.validate)
        self.assertIn('Property error: foo: Value must be a string',
                      six.text_type(ex))

    def test_none_string(self):
        schema = {'foo': {'Type': 'String'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_integer(self):
        schema = {'foo': {'Type': 'Integer'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_number(self):
        schema = {'foo': {'Type': 'Number'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_boolean(self):
        schema = {'foo': {'Type': 'Boolean'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_map(self):
        schema = {'foo': {'Type': 'Map'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_list(self):
        schema = {'foo': {'Type': 'List'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_default_string(self):
        schema = {'foo': {'Type': 'String', 'Default': 'bar'}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_default_integer(self):
        schema = {'foo': {'Type': 'Integer', 'Default': 42}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_default_number(self):
        schema = {'foo': {'Type': 'Number', 'Default': 42.0}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_default_boolean(self):
        schema = {'foo': {'Type': 'Boolean', 'Default': True}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_default_map(self):
        schema = {'foo': {'Type': 'Map', 'Default': {'bar': 'baz'}}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_none_default_list(self):
        schema = {'foo': {'Type': 'List', 'Default': ['one', 'two']}}
        props = properties.Properties(schema, {'foo': None})
        self.assertIsNone(props.validate())

    def test_schema_to_template_nested_map_map_schema(self):
        nested_schema = {'Key': {'Type': 'String',
                         'Required': True},
                         'Value': {'Type': 'String',
                                   'Default': 'fewaf'}}
        schema = {'foo': {'Type': 'Map', 'Schema': nested_schema}}

        prop_expected = {'foo': {'Ref': 'foo'}}
        param_expected = {'foo': {'Type': 'Json'}}
        (parameters,
         props) = properties.Properties.schema_to_parameters_and_properties(
             schema)
        self.assertEqual(param_expected, parameters)
        self.assertEqual(prop_expected, props)

    def test_schema_to_template_nested_map_list_map_schema(self):
        key_schema = {'bar': {'Type': 'Number'}}
        nested_schema = {'Key': {'Type': 'Map', 'Schema': key_schema},
                         'Value': {'Type': 'String',
                                   'Required': True}}
        schema = {'foo': {'Type': 'List', 'Schema': {'Type': 'Map',
                  'Schema': nested_schema}}}

        prop_expected = {'foo': {'Fn::Split': [",", {'Ref': 'foo'}]}}
        param_expected = {'foo': {'Type': 'CommaDelimitedList'}}
        (parameters,
         props) = properties.Properties.schema_to_parameters_and_properties(
             schema)
        self.assertEqual(param_expected, parameters)
        self.assertEqual(prop_expected, props)

    def test_schema_object_to_template_nested_map_list_map_schema(self):
        key_schema = {'bar': properties.Schema(properties.Schema.NUMBER)}
        nested_schema = {
            'Key': properties.Schema(properties.Schema.MAP, schema=key_schema),
            'Value': properties.Schema(properties.Schema.STRING, required=True)
        }
        schema = {
            'foo': properties.Schema(properties.Schema.LIST,
                                     schema=properties.Schema(
                                         properties.Schema.MAP,
                                         schema=nested_schema))
        }

        prop_expected = {'foo': {'Fn::Split': [",", {'Ref': 'foo'}]}}
        param_expected = {'foo': {'Type': 'CommaDelimitedList'}}
        (parameters,
         props) = properties.Properties.schema_to_parameters_and_properties(
             schema)
        self.assertEqual(param_expected, parameters)
        self.assertEqual(prop_expected, props)

    def test_schema_invalid_parameters_stripped(self):
        schema = {'foo': {'Type': 'String',
                          'Required': True,
                          'Implemented': True}}

        prop_expected = {'foo': {'Ref': 'foo'}}
        param_expected = {'foo': {'Type': 'String'}}

        (parameters,
         props) = properties.Properties.schema_to_parameters_and_properties(
             schema)
        self.assertEqual(param_expected, parameters)
        self.assertEqual(prop_expected, props)

    def test_schema_support_status(self):
        schema = {
            'foo_sup': properties.Schema(
                properties.Schema.STRING,
                default='foo'
            ),
            'bar_dep': properties.Schema(
                properties.Schema.STRING,
                default='bar',
                support_status=support.SupportStatus(
                    support.DEPRECATED,
                    'Do not use this ever')
            )
        }
        props = properties.Properties(schema, {})
        self.assertEqual(support.SUPPORTED,
                         props.props['foo_sup'].support_status().status)
        self.assertEqual(support.DEPRECATED,
                         props.props['bar_dep'].support_status().status)
        self.assertEqual('Do not use this ever',
                         props.props['bar_dep'].support_status().message)

    def test_nested_properties_schema_invalid_property_in_list(self):
        child_schema = {'Key': {'Type': 'String',
                                'Required': True},
                        'Value': {'Type': 'Boolean',
                                  'Default': True}}
        list_schema = {'Type': 'Map', 'Schema': child_schema}
        schema = {'foo': {'Type': 'List', 'Schema': list_schema}}

        valid_data = {'foo': [{'Key': 'Test'}]}
        props = properties.Properties(schema, valid_data)
        self.assertIsNone(props.validate())

        invalid_data = {'foo': [{'Key': 'Test', 'bar': 'baz'}]}
        props = properties.Properties(schema, invalid_data)
        ex = self.assertRaises(exception.StackValidationFailed,
                               props.validate)
        self.assertEqual('Property error: foo[0]: Unknown Property bar',
                         six.text_type(ex))

    def test_nested_properties_schema_invalid_property_in_map(self):
        child_schema = {'Key': {'Type': 'String',
                                'Required': True},
                        'Value': {'Type': 'Boolean',
                                  'Default': True}}
        map_schema = {'boo': {'Type': 'Map', 'Schema': child_schema}}
        schema = {'foo': {'Type': 'Map', 'Schema': map_schema}}

        valid_data = {'foo': {'boo': {'Key': 'Test'}}}
        props = properties.Properties(schema, valid_data)
        self.assertIsNone(props.validate())

        invalid_data = {'foo': {'boo': {'Key': 'Test', 'bar': 'baz'}}}
        props = properties.Properties(schema, invalid_data)
        ex = self.assertRaises(exception.StackValidationFailed,
                               props.validate)
        self.assertEqual('Property error: foo.boo: Unknown Property bar',
                         six.text_type(ex))

    def test_more_nested_properties_schema_invalid_property_in_list(self):
        nested_child_schema = {'Key': {'Type': 'String',
                                       'Required': True}}
        child_schema = {'doo': {'Type': 'Map', 'Schema': nested_child_schema}}
        list_schema = {'Type': 'Map', 'Schema': child_schema}
        schema = {'foo': {'Type': 'List', 'Schema': list_schema}}

        valid_data = {'foo': [{'doo': {'Key': 'Test'}}]}
        props = properties.Properties(schema, valid_data)
        self.assertIsNone(props.validate())

        invalid_data = {'foo': [{'doo': {'Key': 'Test', 'bar': 'baz'}}]}
        props = properties.Properties(schema, invalid_data)
        ex = self.assertRaises(exception.StackValidationFailed,
                               props.validate)
        self.assertEqual('Property error: foo[0].doo: Unknown Property bar',
                         six.text_type(ex))

    def test_more_nested_properties_schema_invalid_property_in_map(self):
        nested_child_schema = {'Key': {'Type': 'String',
                                       'Required': True}}
        child_schema = {'doo': {'Type': 'Map', 'Schema': nested_child_schema}}
        map_schema = {'boo': {'Type': 'Map', 'Schema': child_schema}}
        schema = {'foo': {'Type': 'Map', 'Schema': map_schema}}

        valid_data = {'foo': {'boo': {'doo': {'Key': 'Test'}}}}
        props = properties.Properties(schema, valid_data)
        self.assertIsNone(props.validate())

        invalid_data = {'foo': {'boo': {'doo': {'Key': 'Test', 'bar': 'baz'}}}}
        props = properties.Properties(schema, invalid_data)
        ex = self.assertRaises(exception.StackValidationFailed,
                               props.validate)
        self.assertEqual('Property error: foo.boo.doo: Unknown Property bar',
                         six.text_type(ex))

    def test_schema_to_template_empty_schema(self):
        schema = {}

        (parameters,
         props) = properties.Properties.schema_to_parameters_and_properties(
             schema)
        self.assertEqual({}, parameters)
        self.assertEqual({}, props)

    def test_update_allowed_and_immutable_contradict(self):
        self.assertRaises(exception.InvalidSchemaError,
                          properties.Schema,
                          properties.Schema.STRING,
                          update_allowed=True,
                          immutable=True)
