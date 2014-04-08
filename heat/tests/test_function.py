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

from heat.tests.common import HeatTestCase

from heat.engine import function


class TestFunction(function.Function):
    def validate(self):
        if len(self.args) < 2:
            raise Exception(_('Need more arguments'))

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
        self.assertEqual('Need more arguments', str(ex))

    def test_validate_dict(self):
        snippet = {'foo': 'bar', 'blarg': self.func}
        function.validate(snippet)

        self.func = TestFunction(None, 'foo', ['bar'])
        snippet = {'foo': 'bar', 'blarg': self.func}
        ex = self.assertRaises(Exception, function.validate, snippet)
        self.assertEqual('Need more arguments', str(ex))

    def test_validate_list(self):
        snippet = ['foo', 'bar', 'baz', 'blarg', self.func]
        function.validate(snippet)

        self.func = TestFunction(None, 'foo', ['bar'])
        snippet = {'foo': 'bar', 'blarg': self.func}
        ex = self.assertRaises(Exception, function.validate, snippet)
        self.assertEqual('Need more arguments', str(ex))

    def test_validate_all(self):
        snippet = ['foo', {'bar': ['baz', {'blarg': self.func}]}]
        function.validate(snippet)

        self.func = TestFunction(None, 'foo', ['bar'])
        snippet = {'foo': 'bar', 'blarg': self.func}
        ex = self.assertRaises(Exception, function.validate, snippet)
        self.assertEqual('Need more arguments', str(ex))
