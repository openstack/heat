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

from heat.engine.resources import iso_8601
from heat.tests.common import HeatTestCase


class TestISO8601Constraint(HeatTestCase):

    def setUp(self):
        super(TestISO8601Constraint, self).setUp()
        self.constraint = iso_8601.ISO8601Constraint()

    def test_validate_date_format(self):
        date = '2050-01-01'
        self.assertTrue(self.constraint.validate(date, None))

    def test_validate_datetime_format(self):
        self.assertTrue(self.constraint.validate('2050-01-01T23:59:59', None))

    def test_validate_datetime_format_with_utc_offset(self):
        date = '2050-01-01T23:59:59+00:00'
        self.assertTrue(self.constraint.validate(date, None))

    def test_validate_datetime_format_with_utc_offset_alternate(self):
        date = '2050-01-01T23:59:59+0000'
        self.assertTrue(self.constraint.validate(date, None))

    def test_validate_refuses_other_formats(self):
        self.assertFalse(self.constraint.validate('Fri 13th, 2050', None))
