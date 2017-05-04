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

from testtools import matchers

from heat.common import timeutils as util
from heat.tests import common


class ISO8601UtilityTest(common.HeatTestCase):

    def test_valid_durations(self):
        self.assertEqual(0, util.parse_isoduration('PT'))
        self.assertEqual(3600, util.parse_isoduration('PT1H'))
        self.assertEqual(120, util.parse_isoduration('PT2M'))
        self.assertEqual(3, util.parse_isoduration('PT3S'))
        self.assertEqual(3900, util.parse_isoduration('PT1H5M'))
        self.assertEqual(3605, util.parse_isoduration('PT1H5S'))
        self.assertEqual(303, util.parse_isoduration('PT5M3S'))
        self.assertEqual(3903, util.parse_isoduration('PT1H5M3S'))
        self.assertEqual(24 * 3600, util.parse_isoduration('PT24H'))

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


class DurationTest(common.HeatTestCase):

    def setUp(self):
        super(DurationTest, self).setUp()
        st = util.wallclock()
        mock_clock = self.patchobject(util, 'wallclock')
        mock_clock.side_effect = [st, st + 0.5]

    def test_duration_not_expired(self):
        self.assertFalse(util.Duration(1.0).expired())

    def test_duration_expired(self):
        self.assertTrue(util.Duration(0.1).expired())


class RetryBackoffExponentialTest(common.HeatTestCase):

    scenarios = [(
        '0_0',
        dict(
            attempt=0,
            scale_factor=0.0,
            delay=0.0,
        )
    ), (
        '0_1',
        dict(
            attempt=0,
            scale_factor=1.0,
            delay=1.0,
        )
    ), (
        '1_1',
        dict(
            attempt=1,
            scale_factor=1.0,
            delay=2.0,
        )
    ), (
        '2_1',
        dict(
            attempt=2,
            scale_factor=1.0,
            delay=4.0,
        )
    ), (
        '3_1',
        dict(
            attempt=3,
            scale_factor=1.0,
            delay=8.0,
        )
    ), (
        '4_1',
        dict(
            attempt=4,
            scale_factor=1.0,
            delay=16.0,
        )
    ), (
        '4_4',
        dict(
            attempt=4,
            scale_factor=4.0,
            delay=64.0,
        )
    )]

    def test_backoff_delay(self):
        delay = util.retry_backoff_delay(
            self.attempt, self.scale_factor)
        self.assertEqual(self.delay, delay)


class RetryBackoffJitterTest(common.HeatTestCase):

    scenarios = [(
        '0_0_1',
        dict(
            attempt=0,
            scale_factor=0.0,
            jitter_max=1.0,
            delay_from=0.0,
            delay_to=1.0
        )
    ), (
        '1_1_1',
        dict(
            attempt=1,
            scale_factor=1.0,
            jitter_max=1.0,
            delay_from=2.0,
            delay_to=3.0
        )
    ), (
        '1_1_5',
        dict(
            attempt=1,
            scale_factor=1.0,
            jitter_max=5.0,
            delay_from=2.0,
            delay_to=7.0
        )
    )]

    def test_backoff_delay(self):
        for _ in range(100):
            delay = util.retry_backoff_delay(
                self.attempt, self.scale_factor, self.jitter_max)
            self.assertThat(delay, matchers.GreaterThan(self.delay_from))
            self.assertThat(delay, matchers.LessThan(self.delay_to))
