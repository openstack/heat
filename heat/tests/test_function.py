
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
