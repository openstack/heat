# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from heat.common import timeutils as util
from heat.tests.common import HeatTestCase
from heat.tests import utils


class ISO8601UtilityTest(HeatTestCase):

    def setUp(self):
        super(ISO8601UtilityTest, self).setUp()
        utils.setup_dummy_db()

    def test_valid_durations(self):
        self.assertEqual(util.parse_isoduration('PT'), 0)
        self.assertEqual(util.parse_isoduration('PT1H'), 3600)
        self.assertEqual(util.parse_isoduration('PT2M'), 120)
        self.assertEqual(util.parse_isoduration('PT3S'), 3)
        self.assertEqual(util.parse_isoduration('PT1H5M'), 3900)
        self.assertEqual(util.parse_isoduration('PT1H5S'), 3605)
        self.assertEqual(util.parse_isoduration('PT5M3S'), 303)
        self.assertEqual(util.parse_isoduration('PT1H5M3S'), 3903)
        self.assertEqual(util.parse_isoduration('PT24H'), 24 * 3600)

    def test_invalid_durations(self):
        self.assertRaises(ValueError, util.parse_isoduration, 'P1Y')
        self.assertRaises(ValueError, util.parse_isoduration, 'P1DT12H')
        self.assertRaises(ValueError, util.parse_isoduration, 'PT1Y1D')
        self.assertRaises(ValueError, util.parse_isoduration, 'PTAH1M0S')
        self.assertRaises(ValueError, util.parse_isoduration, 'PT1HBM0S')
        self.assertRaises(ValueError, util.parse_isoduration, 'PT1H1MCS')
        self.assertRaises(ValueError, util.parse_isoduration, 'PT1H1H')
        self.assertRaises(ValueError, util.parse_isoduration, 'PT1MM')
        self.assertRaises(ValueError, util.parse_isoduration, 'PT1S0S')
        self.assertRaises(ValueError, util.parse_isoduration, 'ABCDEFGH')
