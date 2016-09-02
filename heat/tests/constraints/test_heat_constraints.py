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

from heat.engine.constraint import heat_constraints as hc
from heat.tests import common


class ResourceTypeConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(ResourceTypeConstraintTest, self).setUp()
        self.constraint = hc.ResourceTypeConstraint()

        self.mock_template = mock.MagicMock()
        self.mock_env = mock.MagicMock()
        self.mock_template.env = self.mock_env

    def test_validate(self):
        # Setup
        value = ['OS::Heat::None']

        # Test
        result = self.constraint.validate(value, None, self.mock_template)

        # Verify
        self.assertTrue(result)
        self.mock_env.get_class.assert_called_once_with(value[0])

    def test_validate_failure(self):
        # Setup
        value = ['OS::Heat::None']
        self.mock_env.get_class.side_effect = Exception()

        # Test
        result = self.constraint.validate(value, None, self.mock_template)

        # Verify
        self.assertFalse(result)
        self.assertIn('OS::Heat::None', self.constraint._error_message)
        self.mock_env.get_class.assert_called_once_with(value[0])

    def test_validate_multiple_failures(self):
        # Setup
        value = ['OS::Heat::None', 'OS::Heat::RandomString']
        self.mock_env.get_class.side_effect = [Exception(), Exception()]

        # Test
        result = self.constraint.validate(value, None, self.mock_template)

        # Verify
        self.assertFalse(result)
        self.assertTrue('OS::Heat::None,OS::Heat::RandomString'
                        in self.constraint._error_message)
        self.mock_env.get_class.assert_has_calls([mock.call(value[0]),
                                                  mock.call(value[1])])

    def test_validate_single_item(self):
        # Setup
        value = 'OS::Heat::None'

        # Test
        result = self.constraint.validate(value, None, self.mock_template)

        # Verify
        self.assertTrue(result)
        self.mock_env.get_class.assert_called_once_with(value)

    def test_validate_non_string(self):
        result = self.constraint.validate(dict(), None, self.mock_template)
        self.assertFalse(result)
