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

from heat.common import param_utils
from heat.tests import common


class TestExtractBool(common.HeatTestCase):
    def test_extract_bool(self):
        for value in ('True', 'true', 'TRUE', True):
            self.assertTrue(param_utils.extract_bool('bool', value))
        for value in ('False', 'false', 'FALSE', False):
            self.assertFalse(param_utils.extract_bool('bool', value))
        for value in ('foo', 't', 'f', 'yes', 'no', 'y', 'n', '1', '0', None):
            self.assertRaises(ValueError, param_utils.extract_bool,
                              'bool', value)


class TestExtractInt(common.HeatTestCase):
    def test_extract_int(self):
        # None case
        self.assertIsNone(param_utils.extract_int('num', None))

        # 0 case
        self.assertEqual(0, param_utils.extract_int('num', 0))
        self.assertEqual(0, param_utils.extract_int('num', 0, allow_zero=True))
        self.assertEqual(0, param_utils.extract_int('num', '0'))
        self.assertEqual(0, param_utils.extract_int('num', '0',
                                                    allow_zero=True))
        self.assertRaises(ValueError,
                          param_utils.extract_int,
                          'num', 0, allow_zero=False)
        self.assertRaises(ValueError,
                          param_utils.extract_int,
                          'num', '0', allow_zero=False)

        # positive values
        self.assertEqual(1, param_utils.extract_int('num', 1))
        self.assertEqual(1, param_utils.extract_int('num', '1'))
        self.assertRaises(ValueError, param_utils.extract_int, 'num', '1.1')
        self.assertRaises(ValueError, param_utils.extract_int, 'num', 1.1)

        # negative values
        self.assertEqual(-1, param_utils.extract_int('num', -1,
                                                     allow_negative=True))
        self.assertEqual(-1, param_utils.extract_int('num', '-1',
                                                     allow_negative=True))
        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', '-1.1',
                          allow_negative=True)
        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', -1.1,
                          allow_negative=True)

        self.assertRaises(ValueError, param_utils.extract_int, 'num', -1)
        self.assertRaises(ValueError, param_utils.extract_int, 'num', '-1')
        self.assertRaises(ValueError, param_utils.extract_int, 'num', '-1.1')
        self.assertRaises(ValueError, param_utils.extract_int, 'num', -1.1)

        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', -1,
                          allow_negative=False)
        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', '-1',
                          allow_negative=False)
        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', '-1.1',
                          allow_negative=False)
        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', -1.1,
                          allow_negative=False)

        # Non-int value
        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', 'abc')
        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', '')
        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', 'true')
        self.assertRaises(ValueError,
                          param_utils.extract_int, 'num', True)


class TestExtractTags(common.HeatTestCase):
    def test_extract_tags(self):
        self.assertRaises(ValueError, param_utils.extract_tags, "aaaaaaaaaaaaa"
                          "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                          "aaaaaaaaaaaaaaaaa,a")
        self.assertEqual(["foo", "bar"], param_utils.extract_tags('foo,bar'))
