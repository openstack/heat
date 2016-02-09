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
import six

from heat.common import exception
from heat.engine.hot import functions as hot_funcs
from heat.engine import parameters
from heat.engine import properties
from heat.engine import translation
from heat.tests import common


class TestTranslationRule(common.HeatTestCase):

    def test_translation_rule(self):
        for r in translation.TranslationRule.RULE_KEYS:
            props = properties.Properties({}, {})
            rule = translation.TranslationRule(
                props,
                r,
                ['any'],
                ['value'] if r == 'Add' else 'value',
                'value_name' if r == 'Replace' else None)
            self.assertEqual(rule.properties, props)
            self.assertEqual(rule.rule, r)
            if r == 'Add':
                self.assertEqual(['value'], rule.value)
            else:
                self.assertEqual('value', rule.value)
            if r == 'Replace':
                self.assertEqual('value_name', rule.value_name)
            else:
                self.assertIsNone(rule.value_name)

    def test_invalid_translation_rule(self):
        props = properties.Properties({}, {})
        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                'proppy', mock.ANY,
                                mock.ANY)
        self.assertEqual('Properties must be Properties type. '
                         'Found %s.' % str, six.text_type(exc))

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                'EatTheCookie',
                                mock.ANY,
                                mock.ANY)
        self.assertEqual('There is no rule EatTheCookie. List of allowed '
                         'rules is: Add, Replace, Delete.',
                         six.text_type(exc))

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                translation.TranslationRule.ADD,
                                'networks.network',
                                'value')
        self.assertEqual('source_path should be a list with path instead of '
                         '%s.' % str, six.text_type(exc))

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                translation.TranslationRule.ADD,
                                [],
                                mock.ANY)
        self.assertEqual('source_path must be non-empty list with path.',
                         six.text_type(exc))

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                translation.TranslationRule.ADD,
                                ['any'],
                                mock.ANY,
                                'value_name')
        self.assertEqual('Use value_name only for replacing list elements.',
                         six.text_type(exc))

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                translation.TranslationRule.ADD,
                                ['any'],
                                'value')
        self.assertEqual('value must be list type when rule is Add.',
                         six.text_type(exc))

    def test_add_rule_exist(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.LIST,
                schema=properties.Schema(
                    properties.Schema.MAP,
                    schema={
                        'red': properties.Schema(
                            properties.Schema.STRING
                        )
                    }
                )
            ),
            'bar': properties.Schema(
                properties.Schema.STRING
            )}

        data = {
            'far': [
                {'red': 'blue'}
            ],
            'bar': 'dak'
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.ADD,
            ['far'],
            [{'red': props.get('bar')}])
        rule.execute_rule()

        self.assertIn({'red': 'dak'}, props.get('far'))

    def test_add_rule_dont_exist(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.LIST,
                schema=properties.Schema(
                    properties.Schema.MAP,
                    schema={
                        'red': properties.Schema(
                            properties.Schema.STRING
                        )
                    }
                )
            ),
            'bar': properties.Schema(
                properties.Schema.STRING
            )}

        data = {
            'bar': 'dak'
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.ADD,
            ['far'],
            [{'red': props.get('bar')}])
        rule.execute_rule()

        self.assertEqual([{'red': 'dak'}], props.get('far'))

    def test_add_rule_invalid(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.MAP,
                schema={
                    'red': properties.Schema(
                        properties.Schema.STRING
                    )
                }
            ),
            'bar': properties.Schema(
                properties.Schema.STRING
            )}

        data = {
            'far': 'tran',
            'bar': 'dak'
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.ADD,
            ['far'],
            [props.get('bar')])
        exc = self.assertRaises(ValueError, rule.execute_rule)

        self.assertEqual('Add rule must be used only for lists.',
                         six.text_type(exc))

    def test_replace_rule_map_exist(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.MAP,
                schema={
                    'red': properties.Schema(
                        properties.Schema.STRING
                    )
                }
            ),
            'bar': properties.Schema(
                properties.Schema.STRING
            )}

        data = {
            'far': {'red': 'tran'},
            'bar': 'dak'
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'red'],
            props.get('bar'))
        rule.execute_rule()

        self.assertEqual({'red': 'dak'}, props.get('far'))

    def test_replace_rule_map_dont_exist(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.MAP,
                schema={
                    'red': properties.Schema(
                        properties.Schema.STRING
                    )
                }
            ),
            'bar': properties.Schema(
                properties.Schema.STRING
            )}

        data = {
            'bar': 'dak'
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'red'],
            props.get('bar'))
        rule.execute_rule()

        self.assertEqual({'red': 'dak'}, props.get('far'))

    def test_replace_rule_list_different(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.LIST,
                schema=properties.Schema(
                    properties.Schema.MAP,
                    schema={
                        'red': properties.Schema(
                            properties.Schema.STRING
                        )
                    }
                )
            ),
            'bar': properties.Schema(
                properties.Schema.STRING
            )}

        data = {
            'far': [{'red': 'blue'},
                    {'red': 'roses'}],
            'bar': 'dak'
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'red'],
            props.get('bar'))
        rule.execute_rule()

        self.assertEqual([{'red': 'dak'}, {'red': 'dak'}], props.get('far'))

    def test_replace_rule_list_same(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.LIST,
                schema=properties.Schema(
                    properties.Schema.MAP,
                    schema={
                        'red': properties.Schema(
                            properties.Schema.STRING
                        ),
                        'blue': properties.Schema(
                            properties.Schema.STRING
                        )
                    }
                )
            )}

        data = {
            'far': [{'blue': 'white'},
                    {'red': 'roses'}]
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'red'],
            None,
            'blue')
        rule.execute_rule()

        self.assertEqual([{'red': 'white', 'blue': None},
                          {'blue': None, 'red': 'roses'}],
                         props.get('far'))

    def test_replace_rule_str(self):
        schema = {
            'far': properties.Schema(properties.Schema.STRING),
            'bar': properties.Schema(properties.Schema.STRING)
        }

        data = {'far': 'one', 'bar': 'two'}

        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['bar'],
            props.get('far'))
        rule.execute_rule()

        self.assertEqual('one', props.get('bar'))
        self.assertEqual('one', props.get('far'))

    def test_replace_rule_str_value_path_error(self):
        schema = {
            'far': properties.Schema(properties.Schema.STRING),
            'bar': properties.Schema(properties.Schema.STRING)
        }

        data = {'far': 'one', 'bar': 'two'}

        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['bar'],
            value_path=['far'])
        ex = self.assertRaises(ValueError, rule.execute_rule)
        self.assertEqual('Cannot use bar and far at the same time.',
                         six.text_type(ex))

    def test_replace_rule_str_value_path(self):
        schema = {
            'far': properties.Schema(properties.Schema.STRING),
            'bar': properties.Schema(properties.Schema.STRING)
        }

        data = {'far': 'one'}

        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['bar'],
            value_path=['far'])
        rule.execute_rule()

        self.assertEqual('one', props.get('bar'))
        self.assertIsNone(props.get('far'))

    def test_replace_rule_str_invalid(self):
        schema = {
            'far': properties.Schema(properties.Schema.STRING),
            'bar': properties.Schema(properties.Schema.INTEGER)
        }

        data = {'far': 'one', 'bar': 2}

        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['bar'],
            props.get('far'))
        rule.execute_rule()

        exc = self.assertRaises(exception.StackValidationFailed,
                                props.validate)
        self.assertEqual("Property error: bar: Value 'one' is not an integer",
                         six.text_type(exc))

    def test_delete_rule_list(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.LIST,
                schema=properties.Schema(
                    properties.Schema.MAP,
                    schema={
                        'red': properties.Schema(
                            properties.Schema.STRING
                        )
                    }
                )
            )}

        data = {
            'far': [{'red': 'blue'},
                    {'red': 'roses'}],
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.DELETE,
            ['far', 'red'])
        rule.execute_rule()

        self.assertEqual([{'red': None}, {'red': None}], props.get('far'))

    def test_delete_rule_other(self):
        schema = {
            'far': properties.Schema(properties.Schema.STRING)
        }

        data = {'far': 'one'}

        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.DELETE,
            ['far'])
        rule.execute_rule()

        self.assertIsNone(props.get('far'))

    def test_property_json_param_correct_translation(self):
        """Test case when property with sub-schema takes json param."""
        schema = {
            'far': properties.Schema(properties.Schema.MAP,
                                     schema={
                                         'bar': properties.Schema(
                                             properties.Schema.STRING,
                                         ),
                                         'dar': properties.Schema(
                                             properties.Schema.STRING
                                         )
                                     })
        }

        class DummyStack(dict):
            @property
            def parameters(self):
                return mock.Mock()

        param = hot_funcs.GetParam(DummyStack(json_far='json_far'),
                                   'get_param',
                                   'json_far')
        param.parameters = {
            'json_far': parameters.JsonParam(
                'json_far',
                {'Type': 'Json'},
                '{"dar": "rad"}').value()}
        data = {'far': param}

        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'bar'],
            value_path=['far', 'dar'])

        rule.execute_rule()

        self.assertEqual('rad', props.get('far').get('bar'))

    def test_property_json_param_to_list_correct_translation(self):
        """Test case when list property with sub-schema takes json param."""
        schema = {
            'far': properties.Schema(properties.Schema.LIST,
                                     schema=properties.Schema(
                                         properties.Schema.MAP,
                                         schema={
                                             'bar': properties.Schema(
                                                 properties.Schema.STRING,
                                             ),
                                             'dar': properties.Schema(
                                                 properties.Schema.STRING
                                             )
                                         }
                                     ))
        }

        class DummyStack(dict):
            @property
            def parameters(self):
                return mock.Mock()

        param = hot_funcs.GetParam(DummyStack(json_far='json_far'),
                                   'get_param',
                                   'json_far')
        param.parameters = {
            'json_far': parameters.JsonParam(
                'json_far',
                {'Type': 'Json'},
                '{"dar": "rad"}').value()}
        data = {'far': [param]}

        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'bar'],
            value_name='dar')

        rule.execute_rule()

        self.assertEqual([{'dar': None, 'bar': 'rad'}], props.get('far'))

    def test_property_commadelimitedlist_param_correct_translation(self):
        """Test when property with sub-schema takes comma_delimited_list."""
        schema = {
            'far': properties.Schema(
                properties.Schema.LIST,
                schema=properties.Schema(
                    properties.Schema.STRING,
                )
            ),
            'boo': properties.Schema(
                properties.Schema.STRING
            )}

        class DummyStack(dict):
            @property
            def parameters(self):
                return mock.Mock()

        param = hot_funcs.GetParam(DummyStack(list_far='list_far'),
                                   'get_param',
                                   'list_far')
        param.parameters = {
            'list_far': parameters.CommaDelimitedListParam(
                'list_far',
                {'Type': 'CommaDelimitedList'},
                "white,roses").value()}
        data = {'far': param, 'boo': 'chrysanthemums'}

        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.ADD,
            ['far'],
            [props.get('boo')])
        rule.execute_rule()

        self.assertEqual(['white', 'roses', 'chrysanthemums'],
                         props.get('far'))

    def test_property_no_translation_removed_function(self):
        """Test case when list property with sub-schema takes json param."""
        schema = {
            'far': properties.Schema(properties.Schema.LIST,
                                     schema=properties.Schema(
                                         properties.Schema.MAP,
                                         schema={
                                             'bar': properties.Schema(
                                                 properties.Schema.STRING,
                                             ),
                                             'dar': properties.Schema(
                                                 properties.Schema.STRING
                                             )
                                         }
                                     ))
        }

        class DummyStack(dict):
            @property
            def parameters(self):
                return mock.Mock()

        param = hot_funcs.Removed(DummyStack(json_far='json_far'),
                                  'Ref',
                                  'json_far')
        param.parameters = {
            'json_far': parameters.JsonParam(
                'json_far',
                {'Type': 'Json'},
                '{"dar": "rad"}').value()}
        data = {'far': [param]}

        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'bar'],
            value_name='dar')

        rule.execute_rule()

        self.assertEqual([param], props.data.get('far'))
