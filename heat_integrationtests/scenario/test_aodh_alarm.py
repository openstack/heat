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

import datetime
from heat.common import timeutils
from oslo_log import log as logging

from heat_integrationtests.common import test
from heat_integrationtests.scenario import scenario_base

LOG = logging.getLogger(__name__)


class AodhAlarmTest(scenario_base.ScenarioTestsBase):
    """Class is responsible for testing of aodh usage."""
    def setUp(self):
        super(AodhAlarmTest, self).setUp()
        self.template = self._load_template(__file__,
                                            'test_aodh_alarm.yaml',
                                            'templates')

    def check_instance_count(self, stack_identifier, expected):
        stack = self.client.stacks.get(stack_identifier)
        actual = self._stack_output(stack, 'asg_size')
        if actual != expected:
            LOG.warning('check_instance_count exp:%d, act:%s' % (expected,
                                                                 actual))
        return actual == expected

    def test_alarm(self):
        """Confirm we can create an alarm and trigger it."""
        # create metric
        metric = self.metric_client.metric.create({
            'name': 'my_metric',
            'archive_policy_name': 'high',
        })

        # create the stack
        parameters = {'metric_id': metric['id']}
        stack_identifier = self.stack_create(template=self.template,
                                             parameters=parameters)
        measures = [{'timestamp': timeutils.isotime(datetime.datetime.now()),
                     'value': 100}, {'timestamp': timeutils.isotime(
                         datetime.datetime.now() + datetime.timedelta(
                             minutes=1)), 'value': 100}]
        # send measures(should cause the alarm to fire)
        self.metric_client.metric.add_measures(metric['id'], measures)

        # confirm we get a scaleup.
        # Note: there is little point waiting more than 60s+time to scale up.
        self.assertTrue(test.call_until_true(
            120, 2, self.check_instance_count, stack_identifier, 2))

        # cleanup metric
        self.metric_client.metric.delete(metric['id'])
