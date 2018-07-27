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

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine.resources.openstack.heat import delay
from heat.engine import status
from heat.tests import common
from heat.tests import utils

from oslo_utils import fixture as utils_fixture
from oslo_utils import timeutils


class TestDelay(common.HeatTestCase):

    simple_template = template_format.parse('''
heat_template_version: '2016-10-14'
resources:
  constant:
    type: OS::Heat::Delay
    properties:
      min_wait: 3
  variable:
    type: OS::Heat::Delay
    properties:
      min_wait: 1.6
      max_jitter: 4.2
      actions:
        - CREATE
        - DELETE
  variable_prod:
    type: OS::Heat::Delay
    properties:
      min_wait: 2
      max_jitter: 666
      jitter_multiplier: 0.1
      actions:
        - DELETE
''')

    def test_delay_params(self):
        stk = utils.parse_stack(self.simple_template)

        self.assertEqual((3, 0), stk['constant']._delay_parameters())

        self.assertEqual((1.6, 4.2), stk['variable']._delay_parameters())

        min_wait, max_jitter = stk['variable_prod']._delay_parameters()
        self.assertEqual(2, min_wait)
        self.assertAlmostEqual(66.6, max_jitter)

    def test_wait_secs_create(self):
        stk = utils.parse_stack(self.simple_template)
        action = status.ResourceStatus.CREATE

        self.assertEqual(3, stk['constant']._wait_secs(action))

        variable = stk['variable']._wait_secs(action)
        self.assertGreaterEqual(variable, 1.6)
        self.assertLessEqual(variable, 5.8)
        self.assertNotEqual(variable, stk['variable']._wait_secs(action))

        self.assertEqual(0, stk['variable_prod']._wait_secs(action))

    def test_wait_secs_delete(self):
        stk = utils.parse_stack(self.simple_template)
        action = status.ResourceStatus.DELETE

        self.assertEqual(0, stk['constant']._wait_secs(action))

        variable = stk['variable']._wait_secs(action)
        self.assertGreaterEqual(variable, 1.6)
        self.assertLessEqual(variable, 5.8)
        self.assertNotEqual(variable, stk['variable']._wait_secs(action))

        variable_prod = stk['variable_prod']._wait_secs(action)
        self.assertGreaterEqual(variable_prod, 2.0)
        self.assertLessEqual(variable_prod, 68.6)
        self.assertNotEqual(variable_prod,
                            stk['variable_prod']._wait_secs(action))

    def test_wait_secs_update(self):
        stk = utils.parse_stack(self.simple_template)
        action = status.ResourceStatus.UPDATE

        self.assertEqual(0, stk['constant']._wait_secs(action))
        self.assertEqual(0, stk['variable']._wait_secs(action))
        self.assertEqual(0, stk['variable_prod']._wait_secs(action))

    def test_validate_success(self):
        stk = utils.parse_stack(self.simple_template)
        for res in stk.resources.values():
            self.assertIsNone(res.validate())

    def test_validate_failure(self):
        stk = utils.parse_stack(self.simple_template)
        stk.timeout_mins = 1
        self.assertRaises(exception.StackValidationFailed,
                          stk['variable_prod'].validate)


class DelayCompletionTest(common.HeatTestCase):
    def setUp(self):
        super(DelayCompletionTest, self).setUp()
        self.time_fixture = utils_fixture.TimeFixture()
        self.useFixture(self.time_fixture)

    def test_complete_no_wait(self):
        now = timeutils.utcnow()
        self.time_fixture.advance_time_seconds(-1)
        self.assertEqual(True, delay.Delay._check_complete(now, 0))

    def test_complete(self):
        now = timeutils.utcnow()
        self.time_fixture.advance_time_seconds(5.1)
        self.assertEqual(True, delay.Delay._check_complete(now, 5.1))

    def test_already_complete(self):
        now = timeutils.utcnow()
        self.time_fixture.advance_time_seconds(5.1)
        self.assertEqual(True, delay.Delay._check_complete(now, 5))

    def test_incomplete_short_delay(self):
        now = timeutils.utcnow()
        self.time_fixture.advance_time_seconds(2)
        self.assertEqual(False, delay.Delay._check_complete(now, 5))

    def test_incomplete_moderate_delay(self):
        now = timeutils.utcnow()
        self.time_fixture.advance_time_seconds(2)
        poll_del = self.assertRaises(resource.PollDelay,
                                     delay.Delay._check_complete,
                                     now, 6)
        self.assertEqual(2, poll_del.period)

    def test_incomplete_long_delay(self):
        now = timeutils.utcnow()
        self.time_fixture.advance_time_seconds(0.1)
        poll_del = self.assertRaises(resource.PollDelay,
                                     delay.Delay._check_complete,
                                     now, 62)
        self.assertEqual(30, poll_del.period)
