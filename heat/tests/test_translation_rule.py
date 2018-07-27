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

import copy
import mock
import six

from heat.common import exception
from heat.engine.cfn import functions as cfn_funcs
from heat.engine import function
from heat.engine.hot import functions as hot_funcs
from heat.engine import parameters
from heat.engine import properties
from heat.engine import translation
from heat.tests import common


class TestTranslationRule(common.HeatTestCase):

    def setUp(self):
        super(TestTranslationRule, self).setUp()
        self.props = mock.Mock(spec=properties.Properties)

    def test_translation_rule(self):
        for r in translation.TranslationRule.RULE_KEYS:
            props = properties.Properties({}, {})
            rule = translation.TranslationRule(
                props,
                r,
                ['any'],
                ['value'] if r == 'Add' else None,
                'value_name' if r == 'Replace' else None,
                'client_plugin' if r == 'Resolve' else None,
                'finder' if r == 'Resolve' else None)
            self.assertEqual(rule.properties, props)
            self.assertEqual(rule.rule, r)
            if r == 'Add':
                self.assertEqual(['value'], rule.value)
            if r == 'Replace':
                self.assertEqual('value_name', rule.value_name)
            else:
                self.assertIsNone(rule.value_name)

    def test_cmp_rules(self):
        rules = [
            translation.TranslationRule(
                mock.Mock(spec=properties.Properties),
                translation.TranslationRule.DELETE,
                ['any']
            ),
            translation.TranslationRule(
                mock.Mock(spec=properties.Properties),
                translation.TranslationRule.ADD,
                ['any']
            ),
            translation.TranslationRule(
                mock.Mock(spec=properties.Properties),
                translation.TranslationRule.RESOLVE,
                ['any'],
                client_plugin=mock.ANY,
                finder=mock.ANY
            ),
            translation.TranslationRule(
                mock.Mock(spec=properties.Properties),
                translation.TranslationRule.REPLACE,
                ['any']
            )
        ]
        expected = [translation.TranslationRule.ADD,
                    translation.TranslationRule.REPLACE,
                    translation.TranslationRule.RESOLVE,
                    translation.TranslationRule.DELETE]
        result = [rule.rule for rule in sorted(rules)]
        self.assertEqual(expected, result)

    def test_invalid_translation_rule(self):
        props = properties.Properties({}, {})

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                'EatTheCookie',
                                mock.ANY,
                                mock.ANY)
        self.assertEqual('There is no rule EatTheCookie. List of allowed '
                         'rules is: Add, Replace, Delete, Resolve.',
                         six.text_type(exc))

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                translation.TranslationRule.ADD,
                                'networks.network',
                                'value')
        self.assertEqual('"translation_path" should be non-empty list '
                         'with path to translate.',
                         six.text_type(exc))

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                translation.TranslationRule.ADD,
                                [],
                                mock.ANY)
        self.assertEqual('"translation_path" should be non-empty list '
                         'with path to translate.',
                         six.text_type(exc))

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                translation.TranslationRule.ADD,
                                ['any'],
                                'value',
                                'value_name',
                                'some_path')
        self.assertEqual('"value_path", "value" and "value_name" are '
                         'mutually exclusive and cannot be specified '
                         'at the same time.', six.text_type(exc))

        exc = self.assertRaises(ValueError,
                                translation.TranslationRule,
                                props,
                                translation.TranslationRule.ADD,
                                ['any'],
                                'value')
        self.assertEqual('"value" must be list type when rule is Add.',
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
        props = properties.Properties(schema, copy.copy(data))

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.ADD,
            ['far'],
            [{'red': props.get('bar')}])

        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('far'))
        result = tran.translate('far', data['far'])
        self.assertEqual([{'red': 'blue'}, {'red': 'dak'}], result)
        self.assertEqual([{'red': 'blue'}, {'red': 'dak'}],
                         tran.resolved_translations['far'])

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
        props = properties.Properties(schema, copy.copy(data))

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.ADD,
            ['far'],
            [{'red': props.get('bar')}])

        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('far'))
        result = tran.translate('far')
        self.assertEqual([{'red': 'dak'}], result)
        self.assertEqual([{'red': 'dak'}], tran.resolved_translations['far'])

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

        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('far'))
        ex = self.assertRaises(ValueError, tran.translate, 'far', 'tran')
        self.assertEqual('Incorrect translation rule using - cannot '
                         'resolve Add rule for non-list translation '
                         'value "far".', six.text_type(ex))

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

        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('far.red'))
        result = tran.translate('far.red', data['far']['red'])
        self.assertEqual('dak', result)
        self.assertEqual('dak', tran.resolved_translations['far.red'])

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

        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('far.red'))
        result = tran.translate('far.red')
        self.assertEqual('dak', result)
        self.assertEqual('dak', tran.resolved_translations['far.red'])

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

        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('far.red'))
        result = tran.translate('far.0.red', data['far'][0]['red'])
        self.assertEqual('dak', result)
        self.assertEqual('dak', tran.resolved_translations['far.0.red'])

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

        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('far.0.red'))
        result = tran.translate('far.0.red', data['far'][0].get('red'),
                                data['far'][0])
        self.assertEqual('white', result)
        self.assertEqual('white', tran.resolved_translations['far.0.red'])
        self.assertIsNone(tran.resolved_translations['far.0.blue'])
        self.assertTrue(tran.has_translation('far.1.red'))
        result = tran.translate('far.1.red', data['far'][1]['red'],
                                data['far'][1])
        self.assertEqual('roses', result)
        self.assertEqual('roses', tran.resolved_translations['far.1.red'])
        self.assertIsNone(tran.resolved_translations['far.1.blue'])

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

        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('bar'))
        result = tran.translate('bar', data['bar'])
        self.assertEqual('one', result)
        self.assertEqual('one', tran.resolved_translations['bar'])

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

        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('bar'))
        ex = self.assertRaises(exception.StackValidationFailed,
                               tran.translate, 'bar', data['bar'])
        self.assertEqual('Cannot define the following properties at '
                         'the same time: bar, far', six.text_type(ex))

    def test_replace_rule_str_value_path(self):
        schema = {
            'far': properties.Schema(properties.Schema.STRING),
            'bar': properties.Schema(properties.Schema.STRING)
        }

        props = properties.Properties(schema, {'far': 'one'})

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['bar'],
            value_path=['far'])

        props = properties.Properties(schema, {'far': 'one'})
        tran = translation.Translation(props)
        tran.set_rules([rule])

        self.assertTrue(tran.has_translation('bar'))
        result = tran.translate('bar')
        self.assertEqual('one', result)
        self.assertEqual('one', tran.resolved_translations['bar'])
        self.assertIsNone(tran.resolved_translations['far'])

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
        props.update_translation([rule])
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
                        ),
                        'check': properties.Schema(
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

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.red'))
        self.assertIsNone(tran.translate('far.red'))
        self.assertIsNone(tran.resolved_translations['far.red'])

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

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far'))
        self.assertIsNone(tran.translate('far'))
        self.assertIsNone(tran.resolved_translations['far'])

    def _test_resolve_rule(self, is_list=False,
                           check_error=False):
        class FakeClientPlugin(object):
            def find_name_id(self, entity=None,
                             src_value='far'):
                if check_error:
                    raise exception.NotFound()
                if entity == 'rose':
                    return 'pink'
                return 'yellow'

        if is_list:
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
        else:
            schema = {
                'far': properties.Schema(properties.Schema.STRING)
            }
        return FakeClientPlugin(), schema

    def test_resolve_rule_list_populated(self):
        client_plugin, schema = self._test_resolve_rule(is_list=True)
        data = {
            'far': [{'red': 'blue'},
                    {'red': 'roses'}],
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far', 'red'],
            client_plugin=client_plugin,
            finder='find_name_id'
            )

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.red'))
        result = tran.translate('far.0.red', data['far'][0]['red'])
        self.assertEqual('yellow', result)
        self.assertEqual('yellow', tran.resolved_translations['far.0.red'])

    def test_resolve_rule_nested_list_populated(self):
        client_plugin, schema = self._test_resolve_rule_nested_list()
        data = {
            'instances': [{'networks': [{'port': 'port1', 'net': 'net1'}]}]
        }
        props = properties.Properties(schema, data)
        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['instances', 'networks', 'port'],
            client_plugin=client_plugin,
            finder='find_name_id',
            entity='port'
        )
        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('instances.networks.port'))
        result = tran.translate('instances.0.networks.0.port',
                                data['instances'][0]['networks'][0]['port'])
        self.assertEqual('port1_id', result)
        self.assertEqual('port1_id', tran.resolved_translations[
            'instances.0.networks.0.port'])

    def _test_resolve_rule_nested_list(self):
        class FakeClientPlugin(object):
            def find_name_id(self, entity=None, value=None):
                if entity == 'net':
                    return 'net1_id'
                if entity == 'port':
                    return 'port1_id'

        schema = {
            'instances': properties.Schema(
                properties.Schema.LIST,
                schema=properties.Schema(
                    properties.Schema.MAP,
                    schema={
                        'networks': properties.Schema(
                            properties.Schema.LIST,
                            schema=properties.Schema(
                                properties.Schema.MAP,
                                schema={
                                    'port': properties.Schema(
                                        properties.Schema.STRING,
                                    ),
                                    'net': properties.Schema(
                                        properties.Schema.STRING,
                                    ),
                                }
                            )
                        )
                    }
                )
            )}

        return FakeClientPlugin(), schema

    def test_resolve_rule_list_with_function(self):
        client_plugin, schema = self._test_resolve_rule(is_list=True)
        join_func = cfn_funcs.Join(None,
                                   'Fn::Join', ['.', ['bar', 'baz']])
        data = {
            'far': [{'red': 'blue'},
                    {'red': join_func}],
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far', 'red'],
            client_plugin=client_plugin,
            finder='find_name_id'
            )

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.red'))
        result = tran.translate('far.0.red', data['far'][0]['red'])
        self.assertEqual('yellow', result)
        self.assertEqual('yellow', tran.resolved_translations['far.0.red'])

    def test_resolve_rule_list_with_ref(self):
        client_plugin, schema = self._test_resolve_rule(is_list=True)

        class rsrc(object):
            action = INIT = "INIT"

            def FnGetRefId(self):
                return 'resource_id'

        class DummyStack(dict):
            pass

        stack = DummyStack(another_res=rsrc())
        ref = hot_funcs.GetResource(stack, 'get_resource',
                                    'another_res')
        data = {
            'far': [{'red': ref}],
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far', 'red'],
            client_plugin=client_plugin,
            finder='find_name_id'
            )

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.red'))
        result = tran.translate('far.0.red', data['far'][0]['red'])
        self.assertEqual('yellow', result)
        self.assertEqual('yellow', tran.resolved_translations['far.0.red'])

    def test_resolve_rule_list_strings(self):
        client_plugin, schema = self._test_resolve_rule()
        data = {'far': ['one', 'rose']}
        schema = {'far': properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.STRING
            )
        )}
        props = properties.Properties(schema, data)
        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far'],
            client_plugin=client_plugin,
            finder='find_name_id')

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far'))
        result = tran.translate('far', data['far'])
        self.assertEqual(['yellow', 'pink'], result)
        self.assertEqual(['yellow', 'pink'], tran.resolved_translations['far'])

    def test_resolve_rule_ignore_error(self):
        client_plugin, schema = self._test_resolve_rule(check_error=True)
        data = {'far': 'one'}
        props = properties.Properties(schema, data)
        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far'],
            client_plugin=client_plugin,
            finder='find_name_id')

        tran = translation.Translation(props)
        tran.set_rules([rule], ignore_resolve_error=True)
        self.assertTrue(tran.has_translation('far'))
        result = tran.translate('far', data['far'])
        self.assertEqual('one', result)
        self.assertEqual('one', tran.resolved_translations['far'])

    def test_resolve_rule_other(self):
        client_plugin, schema = self._test_resolve_rule()
        data = {'far': 'one'}
        props = properties.Properties(schema, data)
        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far'],
            client_plugin=client_plugin,
            finder='find_name_id')

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far'))
        result = tran.translate('far', data['far'])
        self.assertEqual('yellow', result)
        self.assertEqual('yellow', tran.resolved_translations['far'])

    def test_resolve_rule_other_with_ref(self):
        client_plugin, schema = self._test_resolve_rule()

        class rsrc(object):
            action = INIT = "INIT"

            def FnGetRefId(self):
                return 'resource_id'

        class DummyStack(dict):
            pass

        stack = DummyStack(another_res=rsrc())
        ref = hot_funcs.GetResource(stack, 'get_resource',
                                    'another_res')
        data = {'far': ref}
        props = properties.Properties(schema, data)
        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far'],
            client_plugin=client_plugin,
            finder='find_name_id')

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far'))
        result = tran.translate('far', data['far'])
        self.assertEqual('yellow', result)

    def test_resolve_rule_other_with_function(self):
        client_plugin, schema = self._test_resolve_rule()
        join_func = cfn_funcs.Join(None,
                                   'Fn::Join', ['.', ['bar', 'baz']])
        data = {'far': join_func}
        props = properties.Properties(schema, data)
        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far'],
            client_plugin=client_plugin,
            finder='find_name_id')

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far'))
        result = tran.translate('far', data['far'])
        self.assertEqual('yellow', result)
        self.assertEqual('yellow', tran.resolved_translations['far'])

    def test_resolve_rule_other_with_get_attr(self):
        client_plugin, schema = self._test_resolve_rule()

        class DummyStack(dict):
            pass

        class rsrc(object):
            pass

        stack = DummyStack(another_res=rsrc())
        attr_func = cfn_funcs.GetAtt(stack, 'Fn::GetAtt',
                                     ['another_res', 'name'])
        data = {'far': attr_func}
        props = properties.Properties(schema, data)
        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far'],
            client_plugin=client_plugin,
            finder='find_name_id')

        tran = translation.Translation(props)
        tran.set_rules([rule], client_resolve=False)
        self.assertFalse(tran.store_translated_values)
        self.assertFalse(tran.has_translation('far'))
        result = tran.translate('far', 'no_check', data['far'])
        self.assertEqual('no_check', result)
        self.assertIsNone(tran.resolved_translations.get('far'))

    def test_resolve_rule_other_with_entity(self):
        client_plugin, schema = self._test_resolve_rule()
        data = {'far': 'one'}
        props = properties.Properties(schema, data)
        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.RESOLVE,
            ['far'],
            client_plugin=client_plugin,
            finder='find_name_id',
            entity='rose')

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far'))
        result = tran.translate('far', data['far'])
        self.assertEqual('pink', result)
        self.assertEqual('pink', tran.resolved_translations['far'])

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

        props = properties.Properties(schema, data, resolver=function.resolve)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'bar'],
            value_path=['far', 'dar'])

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.bar'))
        prop_data = props['far']
        result = tran.translate('far.bar', prop_data['bar'], prop_data)
        self.assertEqual('rad', result)
        self.assertEqual('rad', tran.resolved_translations['far.bar'])

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

        props = properties.Properties(schema, data, resolver=function.resolve)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'bar'],
            value_name='dar')

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.0.bar'))
        prop_data = props['far']
        result = tran.translate('far.0.bar', prop_data[0]['bar'],
                                prop_data[0])
        self.assertEqual('rad', result)
        self.assertEqual('rad', tran.resolved_translations['far.0.bar'])

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

        props = properties.Properties(schema, data, resolver=function.resolve)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.ADD,
            ['far'],
            [props.get('boo')])

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far'))
        result = tran.translate('far', props['far'])
        self.assertEqual(['white', 'roses', 'chrysanthemums'], result)
        self.assertEqual(['white', 'roses', 'chrysanthemums'],
                         tran.resolved_translations['far'])

    def test_list_list_add_translation_rule(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.LIST,
                schema=properties.Schema(
                    properties.Schema.MAP,
                    schema={
                        'bar': properties.Schema(
                            properties.Schema.LIST,
                            schema=properties.Schema(properties.Schema.STRING)
                        ),
                        'car': properties.Schema(properties.Schema.STRING)
                    }
                )
            )
        }

        data = {'far': [{'bar': ['shar'], 'car': 'man'}, {'car': 'first'}]}

        props = properties.Properties(schema, data, resolver=function.resolve)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.ADD,
            ['far', 'bar'],
            value_name='car'
        )

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.0.bar'))
        result = tran.translate('far.0.bar', props['far'][0]['bar'],
                                props['far'][0])
        self.assertEqual(['shar', 'man'], result)
        self.assertEqual(['shar', 'man'],
                         tran.resolved_translations['far.0.bar'])
        result = tran.translate('far.1.bar', prop_data=props['far'][1])
        self.assertEqual(['first'], result)
        self.assertEqual(['first'], tran.resolved_translations['far.1.bar'])

    def test_replace_rule_map_with_custom_value_path(self):
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
                properties.Schema.MAP
            )}

        data = {
            'far': {},
            'bar': {'red': 'dak'}
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'red'],
            value_path=['bar'],
            custom_value_path=['red']
        )

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.red'))
        result = tran.translate('far.red')
        self.assertEqual('dak', result)
        self.assertEqual('dak', tran.resolved_translations['far.red'])

    def test_replace_rule_list_with_custom_value_path(self):
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
                            properties.Schema.MAP
                        )
                    }
                )
            )}

        data = {
            'far': [{'blue': {'black': {'white': 'daisy'}}},
                    {'red': 'roses'}]
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.REPLACE,
            ['far', 'red'],
            value_name='blue',
            custom_value_path=['black', 'white']
        )

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.0.red'))
        result = tran.translate('far.0.red', prop_data=data['far'][0])
        self.assertEqual('daisy', result)
        self.assertEqual('daisy', tran.resolved_translations['far.0.red'])

    def test_add_rule_list_with_custom_value_path(self):
        schema = {
            'far': properties.Schema(
                properties.Schema.LIST,
                schema=properties.Schema(
                    properties.Schema.MAP,
                    schema={
                        'red': properties.Schema(
                            properties.Schema.LIST,
                            schema=properties.Schema(properties.Schema.STRING)
                        ),
                        'blue': properties.Schema(
                            properties.Schema.MAP
                        )
                    }
                )
            )}

        data = {
            'far': [{'blue': {'black': {'white': 'daisy', 'check': ['one']}}},
                    {'red': ['roses']}]
        }
        props = properties.Properties(schema, data)

        rule = translation.TranslationRule(
            props,
            translation.TranslationRule.ADD,
            ['far', 'red'],
            value_name='blue',
            custom_value_path=['black', 'check']
        )

        tran = translation.Translation(props)
        tran.set_rules([rule])
        self.assertTrue(tran.has_translation('far.0.red'))
        result = tran.translate('far.0.red', data['far'][0].get('red'),
                                data['far'][0])
        self.assertEqual(['one'], result)
        self.assertEqual(['one'], tran.resolved_translations['far.0.red'])
        self.assertEqual(['roses'], tran.translate('far.1.red',
                                                   data['far'][1]['red'],
                                                   data['far'][1]))

    def test_set_rules_none(self):
        tran = translation.Translation()
        self.assertEqual({}, tran._rules)

    def test_set_no_resolve_rules(self):
        rules = [
            translation.TranslationRule(
                self.props,
                translation.TranslationRule.RESOLVE,
                ['a'],
                client_plugin=mock.ANY,
                finder='finder'
            )
        ]

        tran = translation.Translation()
        tran.set_rules(rules, client_resolve=False)
        self.assertEqual({}, tran._rules)

    def test_translate_add(self):
        rules = [
            translation.TranslationRule(
                self.props,
                translation.TranslationRule.ADD,
                ['a', 'b'],
                value=['check']
            )
        ]

        tran = translation.Translation()
        tran.set_rules(rules)

        result = tran.translate('a.b', ['test'])
        self.assertEqual(['test', 'check'], result)
        self.assertEqual(['test', 'check'], tran.resolved_translations['a.b'])

        # Test without storing
        tran.resolved_translations = {}
        tran.store_translated_values = False
        result = tran.translate('a.b', ['test'])
        self.assertEqual(['test', 'check'], result)
        self.assertEqual({}, tran.resolved_translations)
        tran.store_translated_values = True

        # Test no prop_value
        self.assertEqual(['check'], tran.translate('a.b', None))

        # Check digits in path skipped for rule
        self.assertEqual(['test', 'check'], tran.translate('a.0.b', ['test']))

    def test_translate_delete(self):
        rules = [
            translation.TranslationRule(
                self.props,
                translation.TranslationRule.DELETE,
                ['a']
            )
        ]

        tran = translation.Translation()
        tran.set_rules(rules)

        self.assertIsNone(tran.translate('a'))
        self.assertIsNone(tran.resolved_translations['a'])

        # Test without storing
        tran.resolved_translations = {}
        tran.store_translated_values = False
        self.assertIsNone(tran.translate('a'))
        self.assertEqual({}, tran.resolved_translations)
        tran.store_translated_values = True
