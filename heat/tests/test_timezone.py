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

import six

from heat.engine.constraint.common import timezone as tz
from heat.tests import common
from heat.tests import utils


class TimezoneConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(TimezoneConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.constraint = tz.TimezoneConstraint()

    def test_validation(self):
        self.assertTrue(self.constraint.validate("Asia/Taipei", self.ctx))

    def test_validation_error(self):
        timezone = "wrong_timezone"
        expected = "Invalid timezone: '%s'" % timezone

        self.assertFalse(self.constraint.validate(timezone, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_none(self):
        self.assertTrue(self.constraint.validate(None, self.ctx))
