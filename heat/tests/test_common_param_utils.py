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
from heat.tests.common import HeatTestCase


class TestExtractBool(HeatTestCase):
    def test_extract_bool(self):
        for value in ('True', 'true', 'TRUE', True):
            self.assertTrue(param_utils.extract_bool(value))
        for value in ('False', 'false', 'FALSE', False):
            self.assertFalse(param_utils.extract_bool(value))
        for value in ('foo', 't', 'f', 'yes', 'no', 'y', 'n', '1', '0', None):
            self.assertRaises(ValueError, param_utils.extract_bool, value)
