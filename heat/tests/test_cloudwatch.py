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

from mock import patch

from heat.common import exception
from heat.common import template_format
from heat.tests import common
from heat.tests import utils
from heat.engine import scheduler
from heat.engine import watchrule


AWS_CloudWatch_Alarm = '''
HeatTemplateFormatVersion: '2012-12-12'
Description: Template which tests alarms
Resources:
  test_me:
    Type: AWS::CloudWatch::Alarm
    Properties:
      MetricName: cpu_util
      Namespace: AWS/EC2
      Statistic: Average
      Period: '60'
      EvaluationPeriods: '1'
      Threshold: '50'
      ComparisonOperator: GreaterThanThreshold
'''


class CloudWatchAlarmTest(common.HeatTestCase):

    def setUp(self):
        super(CloudWatchAlarmTest, self).setUp()
        utils.setup_dummy_db()

    def parse_stack(self):
        t = template_format.parse(AWS_CloudWatch_Alarm)
        return utils.parse_stack(t)

    @utils.wr_delete_after
    def test_resource_create_good(self):
        s = self.parse_stack()
        self.wr = s['test_me']
        self.assertEqual(None, scheduler.TaskRunner(s['test_me'].create)())

    def test_resource_create_failed(self):
        s = self.parse_stack()
        with patch.object(watchrule.WatchRule, 'store') as bad_store:
            bad_store.side_effect = KeyError('any random failure')
            task_func = scheduler.TaskRunner(s['test_me'].create)
            self.assertRaises(exception.ResourceFailure, task_func)

    def test_resource_delete_good(self):
        s = self.parse_stack()
        self.assertEqual(None, scheduler.TaskRunner(s['test_me'].create)())
        self.assertEqual(None, scheduler.TaskRunner(s['test_me'].delete)())

    @utils.wr_delete_after
    def test_resource_delete_notfound(self):
        # if a resource is not found, handle_delete() should not raise
        # an exception.
        s = self.parse_stack()
        self.wr = s['test_me']
        self.assertEqual(None, scheduler.TaskRunner(s['test_me'].create)())
        with patch.object(watchrule.WatchRule, 'destroy') as bad_destroy:
            bad_destroy.side_effect = exception.WatchRuleNotFound
            self.assertEqual(None, scheduler.TaskRunner(s['test_me'].delete)())
