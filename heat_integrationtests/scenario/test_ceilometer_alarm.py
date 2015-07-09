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

from oslo_log import log as logging

from heat_integrationtests.common import test

LOG = logging.getLogger(__name__)


class CeilometerAlarmTest(test.HeatIntegrationTest):
    """Class is responsible for testing of ceilometer usage."""
    def setUp(self):
        super(CeilometerAlarmTest, self).setUp()
        self.client = self.orchestration_client
        self.template = self._load_template(__file__,
                                            'test_ceilometer_alarm.yaml',
                                            'templates')

    def check_instance_count(self, stack_identifier, expected):
        stack = self.client.stacks.get(stack_identifier)
        actual = self._stack_output(stack, 'asg_size')
        if actual != expected:
            LOG.warn('check_instance_count exp:%d, act:%s' % (expected,
                                                              actual))
        return actual == expected

    def test_alarm(self):
        """Confirm we can create an alarm and trigger it."""

        # 1. create the stack
        stack_identifier = self.stack_create(template=self.template)

        # 2. send ceilometer a metric (should cause the alarm to fire)
        sample = {}
        sample['counter_type'] = 'gauge'
        sample['counter_name'] = 'test_meter'
        sample['counter_volume'] = 1
        sample['counter_unit'] = 'count'
        sample['resource_metadata'] = {'metering.stack_id':
                                       stack_identifier.split('/')[-1]}
        sample['resource_id'] = 'shouldnt_matter'
        self.metering_client.samples.create(**sample)

        # 3. confirm we get a scaleup.
        # Note: there is little point waiting more than 60s+time to scale up.
        self.assertTrue(test.call_until_true(
            120, 2, self.check_instance_count, stack_identifier, 2))
