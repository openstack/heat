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
import six
import uuid

from heat.common import exception
from heat.engine.cfn import functions
from heat.engine import environment
from heat.engine import function
from heat.engine import parser
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.tests.common import HeatTestCase
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils


class TestFunction(function.Function):
    def validate(self):
        if len(self.args) < 2:
            raise Exception(_('Need more arguments'))

    def dependencies(self, path):
        return ['foo', 'bar']

    def result(self):
        return 'wibble'


class FunctionTest(HeatTestCase):
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

    def test_copy(self):
        func = TestFunction(None, 'foo', ['bar', 'baz'])
        self.assertEqual({'foo': ['bar', 'baz']}, copy.deepcopy(func))


class ResolveTest(HeatTestCase):
    def test_resolve_func(self):
        func = TestFunction(None, 'foo', ['bar', 'baz'])

        result = function.resolve(func)

        self.assertEqual('wibble', result)
        self.assertTrue(isinstance(result, str))

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


class ValidateTest(HeatTestCase):
    def setUp(self):
        super(ValidateTest, self).setUp()
        self.func = TestFunction(None, 'foo', ['bar', 'baz'])

    def test_validate_func(self):
        self.assertIsNone(function.validate(self.func))
        self.func = TestFunction(None, 'foo', ['bar'])
        ex = self.assertRaises(Exception, function.validate, self.func)
        self.assertEqual('Need more arguments', six.text_type(ex))

    def test_validate_dict(self):
        snippet = {'foo': 'bar', 'blarg': self.func}
        function.validate(snippet)

        self.func = TestFunction(None, 'foo', ['bar'])
        snippet = {'foo': 'bar', 'blarg': self.func}
        ex = self.assertRaises(Exception, function.validate, snippet)
        self.assertEqual('Need more arguments', six.text_type(ex))

    def test_validate_list(self):
        snippet = ['foo', 'bar', 'baz', 'blarg', self.func]
        function.validate(snippet)

        self.func = TestFunction(None, 'foo', ['bar'])
        snippet = {'foo': 'bar', 'blarg': self.func}
        ex = self.assertRaises(Exception, function.validate, snippet)
        self.assertEqual('Need more arguments', six.text_type(ex))

    def test_validate_all(self):
        snippet = ['foo', {'bar': ['baz', {'blarg': self.func}]}]
        function.validate(snippet)

        self.func = TestFunction(None, 'foo', ['bar'])
        snippet = {'foo': 'bar', 'blarg': self.func}
        ex = self.assertRaises(Exception, function.validate, snippet)
        self.assertEqual('Need more arguments', six.text_type(ex))


class DependenciesTest(HeatTestCase):
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


class ValidateGetAttTest(HeatTestCase):
    def setUp(self):
        super(ValidateGetAttTest, self).setUp()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)

        env = environment.Environment()
        env.load({u'resource_registry':
                  {u'OS::Test::GenericResource': u'GenericResourceType'}})

        class FakeResource(generic_rsrc.GenericResource):
            def FnGetAtt(self, name):
                pass

        resource._register_class('OverwrittenFnGetAttType', FakeResource)
        env.load({u'resource_registry':
                  {u'OS::Test::FakeResource': u'OverwrittenFnGetAttType'}})

        self.stack = parser.Stack(
            utils.dummy_context(), 'test_stack',
            parser.Template({"HeatTemplateFormatVersion": "2012-12-12"}),
            env=env, stack_id=str(uuid.uuid4()))
        res_defn = rsrc_defn.ResourceDefinition('test_rsrc',
                                                'OS::Test::GenericResource')
        self.rsrc = resource.Resource('test_rsrc', res_defn, self.stack)
        self.stack.add_resource(self.rsrc)

    def test_resource_is_appear_in_stack(self):
        func = functions.GetAtt(self.stack, 'Fn::GetAtt',
                                [self.rsrc.name, 'Foo'])
        self.assertIsNone(func.validate())

    def test_resource_is_not_appear_in_stack(self):
        self.stack.remove_resource(self.rsrc.name)

        func = functions.GetAtt(self.stack, 'Fn::GetAtt',
                                [self.rsrc.name, 'Foo'])
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               func.validate)
        self.assertEqual('The specified reference "test_rsrc" (in unknown) '
                         'is incorrect.', six.text_type(ex))

    def test_resource_no_attribute_with_default_fn_get_att(self):
        func = functions.GetAtt(self.stack, 'Fn::GetAtt',
                                [self.rsrc.name, 'Bar'])
        ex = self.assertRaises(exception.InvalidTemplateAttribute,
                               func.validate)
        self.assertEqual('The Referenced Attribute (test_rsrc Bar) '
                         'is incorrect.', six.text_type(ex))

    def test_resource_no_attribute_with_overwritten_fn_get_att(self):
        res_defn = rsrc_defn.ResourceDefinition('test_rsrc',
                                                'OS::Test::FakeResource')
        self.rsrc = resource.Resource('test_rsrc', res_defn, self.stack)
        self.stack.add_resource(self.rsrc)
        self.rsrc.attributes_schema = {}

        func = functions.GetAtt(self.stack, 'Fn::GetAtt',
                                [self.rsrc.name, 'Foo'])
        self.assertIsNone(func.validate())
