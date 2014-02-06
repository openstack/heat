
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


import copy

from heat.common import template_format
from heat.engine import resource
from heat.engine.resources import cloud_watch
from heat.engine import scheduler
from heat.engine import watchrule
from heat.tests.common import HeatTestCase
from heat.tests import utils


alarm_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Alarm Test",
  "Parameters" : {},
  "Resources" : {
    "MEMAlarmHigh": {
     "Type": "AWS::CloudWatch::Alarm",
     "Properties": {
        "AlarmDescription": "Scale-up if MEM > 50% for 1 minute",
        "MetricName": "MemoryUtilization",
        "Namespace": "system/linux",
        "Statistic": "Average",
        "Period": "60",
        "EvaluationPeriods": "1",
        "Threshold": "50",
        "AlarmActions": [],
        "Dimensions": [],
        "ComparisonOperator": "GreaterThanThreshold"
      }
    }
  }
}
'''


class CloudWatchAlarmTest(HeatTestCase):
    def setUp(self):
        super(CloudWatchAlarmTest, self).setUp()
        utils.setup_dummy_db()

    def create_alarm(self, t, stack, resource_name):
        rsrc = cloud_watch.CloudWatchAlarm(resource_name,
                                           t['Resources'][resource_name],
                                           stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_mem_alarm_high_update_no_replace(self):
        '''
        Make sure that we can change the update-able properties
        without replacing the Alarm rsrc.
        '''
        t = template_format.parse(alarm_template)

        #short circuit the alarm's references
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        properties['AlarmActions'] = ['a']
        properties['Dimensions'] = [{'a': 'v'}]

        stack = utils.parse_stack(t)
        # the watch rule needs a valid stack_id
        stack.store()

        self.m.ReplayAll()
        rsrc = self.create_alarm(t, stack, 'MEMAlarmHigh')
        snippet = copy.deepcopy(rsrc.parsed_template())
        snippet['Properties']['ComparisonOperator'] = 'LessThanThreshold'
        snippet['Properties']['AlarmDescription'] = 'fruity'
        snippet['Properties']['EvaluationPeriods'] = '2'
        snippet['Properties']['Period'] = '90'
        snippet['Properties']['Statistic'] = 'Maximum'
        snippet['Properties']['Threshold'] = '39'

        scheduler.TaskRunner(rsrc.update, snippet)()

        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_mem_alarm_high_update_replace(self):
        '''
        Make sure that the Alarm resource IS replaced when non-update-able
        properties are changed.
        '''
        t = template_format.parse(alarm_template)

        #short circuit the alarm's references
        properties = t['Resources']['MEMAlarmHigh']['Properties']
        properties['AlarmActions'] = ['a']
        properties['Dimensions'] = [{'a': 'v'}]

        stack = utils.parse_stack(t)
        # the watch rule needs a valid stack_id
        stack.store()

        self.m.ReplayAll()
        rsrc = self.create_alarm(t, stack, 'MEMAlarmHigh')
        snippet = copy.deepcopy(rsrc.parsed_template())
        snippet['Properties']['MetricName'] = 'temp'

        updater = scheduler.TaskRunner(rsrc.update, snippet)
        self.assertRaises(resource.UpdateReplace, updater)

        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_suspend_resume(self):
        t = template_format.parse(alarm_template)
        stack = utils.parse_stack(t)
        # the watch rule needs a valid stack_id
        stack.store()

        self.m.ReplayAll()
        rsrc = self.create_alarm(t, stack, 'MEMAlarmHigh')
        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)

        self.ctx = utils.dummy_context()

        wr = watchrule.WatchRule.load(
            self.ctx, watch_name="test_stack-MEMAlarmHigh")

        self.assertEqual(watchrule.WatchRule.SUSPENDED, wr.state)

        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)

        wr = watchrule.WatchRule.load(
            self.ctx, watch_name="test_stack-MEMAlarmHigh")

        self.assertEqual(watchrule.WatchRule.NODATA, wr.state)

        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()
