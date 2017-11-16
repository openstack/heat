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
import uuid

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine.cfn import functions
from heat.engine import environment
from heat.engine import function
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import stack
from heat.engine import stk_defn
from heat.engine import template
from heat.tests import common
from heat.tests import utils


class TestFunction(function.Function):
    def validate(self):
        if len(self.args) < 2:
            raise TypeError(_('Need more arguments'))

    def dependencies(self, path):
        return ['foo', 'bar']

    def result(self):
        return 'wibble'


class TestFunctionKeyError(function.Function):
    def result(self):
        raise TypeError


class TestFunctionValueError(function.Function):
    def result(self):
        raise ValueError


class TestFunctionResult(function.Function):
    def result(self):
        return super(TestFunctionResult, self).result()


class FunctionTest(common.HeatTestCase):
    def test_equal(self):
        func = TestFunction(None, 'foo', ['bar', 'baz'])
        self.assertTrue(func == 'wibble')
        self.assertTrue('wibble' == func)

    def test_not_equal(self):
        func = TestFunction(None, 'foo', ['bar', 'baz'])
        self.assertTrue(func != 'foo')
        self.assertTrue('foo' != func)

    def test_equal_func(self):
        func1 = TestFunction(None, 'foo', ['bar', 'baz'])
        func2 = TestFunction(None, 'blarg', ['wibble', 'quux'])
        self.assertTrue(func1 == func2)

    def test_function_str_value(self):
        func1 = TestFunction(None, 'foo', ['bar', 'baz'])
        expected = '%s %s' % ("<heat.tests.test_function.TestFunction",
                              "{foo: ['bar', 'baz']} -> 'wibble'>")
        self.assertEqual(expected, six.text_type(func1))

    def test_function_stack_reference_none(self):
        func1 = TestFunction(None, 'foo', ['bar', 'baz'])
        self.assertIsNone(func1.stack)

    def test_function_exception_key_error(self):
        func1 = TestFunctionKeyError(None, 'foo', ['bar', 'baz'])
        expected = '%s %s' % ("<heat.tests.test_function.TestFunctionKeyError",
                              "{foo: ['bar', 'baz']} -> ???>")
        self.assertEqual(expected, six.text_type(func1))

    def test_function_eq_exception_key_error(self):
        func1 = TestFunctionKeyError(None, 'foo', ['bar', 'baz'])
        func2 = TestFunctionKeyError(None, 'foo', ['bar', 'baz'])
        result = func1.__eq__(func2)
        self.assertEqual(result, NotImplemented)

    def test_function_ne_exception_key_error(self):
        func1 = TestFunctionKeyError(None, 'foo', ['bar', 'baz'])
        func2 = TestFunctionKeyError(None, 'foo', ['bar', 'baz'])
        result = func1.__ne__(func2)
        self.assertEqual(result, NotImplemented)

    def test_function_exception_value_error(self):
        func1 = TestFunctionValueError(None, 'foo', ['bar', 'baz'])
        expected = '%s %s' % (
            "<heat.tests.test_function.TestFunctionValueError",
            "{foo: ['bar', 'baz']} -> ???>")
        self.assertEqual(expected, six.text_type(func1))

    def test_function_eq_exception_value_error(self):
        func1 = TestFunctionValueError(None, 'foo', ['bar', 'baz'])
        func2 = TestFunctionValueError(None, 'foo', ['bar', 'baz'])
        result = func1.__eq__(func2)
        self.assertEqual(result, NotImplemented)

    def test_function_ne_exception_value_error(self):
        func1 = TestFunctionValueError(None, 'foo', ['bar', 'baz'])
        func2 = TestFunctionValueError(None, 'foo', ['bar', 'baz'])
        result = func1.__ne__(func2)
        self.assertEqual(result, NotImplemented)

    def test_function_abstract_result(self):
        func1 = TestFunctionResult(None, 'foo', ['bar', 'baz'])
        expected = '%s %s -> %s' % (
            "<heat.tests.test_function.TestFunctionResult",
            "{foo: ['bar', 'baz']}",
            "{'foo': ['bar', 'baz']}>")
        self.assertEqual(expected, six.text_type(func1))

    def test_copy(self):
        func = TestFunction(None, 'foo', ['bar', 'baz'])
        self.assertEqual({'foo': ['bar', 'baz']}, copy.deepcopy(func))


class ResolveTest(common.HeatTestCase):
    def test_resolve_func(self):
        func = TestFunction(None, 'foo', ['bar', 'baz'])

        result = function.resolve(func)

        self.assertEqual('wibble', result)
        self.assertIsInstance(result, str)

    def test_resolve_dict(self):
        func = TestFunction(None, 'foo', ['bar', 'baz'])
        snippet = {'foo': 'bar', 'blarg': func}

        result = function.resolve(snippet)

        self.assertEqual({'foo': 'bar', 'blarg': 'wibble'}, result)
        self.assertIsNot(result, snippet)

    def test_resolve_list(self):
        func = TestFunction(None, 'foo', ['bar', 'baz'])
        snippet = ['foo', 'bar', 'baz', 'blarg', func]

        result = function.resolve(snippet)

        self.assertEqual(['foo', 'bar', 'baz', 'blarg', 'wibble'], result)
        self.assertIsNot(result, snippet)

    def test_resolve_all(self):
        func = TestFunction(None, 'foo', ['bar', 'baz'])
        snippet = ['foo', {'bar': ['baz', {'blarg': func}]}]

        result = function.resolve(snippet)

        self.assertEqual(['foo', {'bar': ['baz', {'blarg': 'wibble'}]}],
                         result)
        self.assertIsNot(result, snippet)


class ValidateTest(common.HeatTestCase):
    def setUp(self):
        super(ValidateTest, self).setUp()
        self.func = TestFunction(None, 'foo', ['bar', 'baz'])

    def test_validate_func(self):
        self.assertIsNone(function.validate(self.func))
        self.func = TestFunction(None, 'foo', ['bar'])
        self.assertRaisesRegex(exception.StackValidationFailed,
                               'foo: Need more arguments',
                               function.validate, self.func)

    def test_validate_dict(self):
        snippet = {'foo': 'bar', 'blarg': self.func}
        function.validate(snippet)

        self.func = TestFunction(None, 'foo', ['bar'])
        snippet = {'foo': 'bar', 'blarg': self.func}
        self.assertRaisesRegex(exception.StackValidationFailed,
                               'blarg.foo: Need more arguments',
                               function.validate, snippet)

    def test_validate_list(self):
        snippet = ['foo', 'bar', 'baz', 'blarg', self.func]
        function.validate(snippet)

        self.func = TestFunction(None, 'foo', ['bar'])
        snippet = {'foo': 'bar', 'blarg': self.func}
        self.assertRaisesRegex(exception.StackValidationFailed,
                               'blarg.foo: Need more arguments',
                               function.validate, snippet)

    def test_validate_all(self):
        snippet = ['foo', {'bar': ['baz', {'blarg': self.func}]}]
        function.validate(snippet)

        self.func = TestFunction(None, 'foo', ['bar'])
        snippet = {'foo': 'bar', 'blarg': self.func}
        self.assertRaisesRegex(exception.StackValidationFailed,
                               'blarg.foo: Need more arguments',
                               function.validate, snippet)


class DependenciesTest(common.HeatTestCase):
    func = TestFunction(None, 'test', None)

    scenarios = [
        ('function', dict(snippet=func)),
        ('nested_map', dict(snippet={'wibble': func})),
        ('nested_list', dict(snippet=['wibble', func])),
        ('deep_nested', dict(snippet=[{'wibble': ['wibble', func]}])),
    ]

    def test_dependencies(self):
        deps = list(function.dependencies(self.snippet))
        self.assertIn('foo', deps)
        self.assertIn('bar', deps)
        self.assertEqual(2, len(deps))


class ValidateGetAttTest(common.HeatTestCase):
    def setUp(self):
        super(ValidateGetAttTest, self).setUp()

        env = environment.Environment()
        env.load({u'resource_registry':
                  {u'OS::Test::GenericResource': u'GenericResourceType'}})

        env.load({u'resource_registry':
                  {u'OS::Test::FakeResource': u'OverwrittenFnGetAttType'}})

        tmpl = template.Template({"HeatTemplateFormatVersion": "2012-12-12",
                                  "Resources": {
                                      "test_rsrc": {
                                          "Type": "OS::Test::GenericResource"
                                      },
                                      "get_att_rsrc": {
                                          "Type": "OS::Heat::Value",
                                          "Properties": {
                                              "value": {
                                                  "Fn::GetAtt": ["test_rsrc",
                                                                 "Foo"]
                                              }
                                          }
                                      }
                                  }},
                                 env=env)
        self.stack = stack.Stack(
            utils.dummy_context(), 'test_stack',
            tmpl,
            stack_id=str(uuid.uuid4()))
        self.rsrc = self.stack['test_rsrc']
        self.stack.validate()

    def test_resource_is_appear_in_stack(self):
        func = functions.GetAtt(self.stack.defn, 'Fn::GetAtt',
                                [self.rsrc.name, 'Foo'])
        self.assertIsNone(func.validate())

    def test_resource_is_not_appear_in_stack(self):
        self.stack.remove_resource(self.rsrc.name)

        func = functions.GetAtt(self.stack.defn, 'Fn::GetAtt',
                                [self.rsrc.name, 'Foo'])
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               func.validate)
        self.assertEqual('The specified reference "test_rsrc" (in unknown) '
                         'is incorrect.', six.text_type(ex))

    def test_resource_no_attribute_with_default_fn_get_att(self):
        res_defn = rsrc_defn.ResourceDefinition('test_rsrc',
                                                'ResWithStringPropAndAttr')
        self.rsrc = resource.Resource('test_rsrc', res_defn, self.stack)
        self.stack.add_resource(self.rsrc)
        stk_defn.update_resource_data(self.stack.defn, self.rsrc.name,
                                      self.rsrc.node_data())
        self.stack.validate()

        func = functions.GetAtt(self.stack.defn, 'Fn::GetAtt',
                                [self.rsrc.name, 'Bar'])
        ex = self.assertRaises(exception.InvalidTemplateAttribute,
                               func.validate)
        self.assertEqual('The Referenced Attribute (test_rsrc Bar) '
                         'is incorrect.', six.text_type(ex))

    def test_resource_no_attribute_with_overwritten_fn_get_att(self):
        res_defn = rsrc_defn.ResourceDefinition('test_rsrc',
                                                'OS::Test::FakeResource')
        self.rsrc = resource.Resource('test_rsrc', res_defn, self.stack)
        self.rsrc.attributes_schema = {}
        self.stack.add_resource(self.rsrc)
        stk_defn.update_resource_data(self.stack.defn, self.rsrc.name,
                                      self.rsrc.node_data())
        self.stack.validate()

        func = functions.GetAtt(self.stack.defn, 'Fn::GetAtt',
                                [self.rsrc.name, 'Foo'])
        self.assertIsNone(func.validate())

    def test_get_attr_without_attribute_name(self):
        ex = self.assertRaises(ValueError, functions.GetAtt,
                               self.stack.defn, 'Fn::GetAtt', [self.rsrc.name])
        self.assertEqual('Arguments to "Fn::GetAtt" must be '
                         'of the form [resource_name, attribute]',
                         six.text_type(ex))
