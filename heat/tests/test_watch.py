
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

import mox

from heat.common import exception
import heat.db.api as db_api
from heat.engine import parser
from heat.engine import watchrule
from heat.openstack.common import timeutils
from heat.tests.common import HeatTestCase
from heat.tests import utils


class WatchData(object):
    def __init__(self, data, created_at):
        self.created_at = created_at
        self.data = {'test_metric': {'Value': data,
                                     'Unit': 'Count'}}


class DummyAction(object):
    signal = "DummyAction"


class WatchRuleTest(HeatTestCase):
    stack_id = None

    @classmethod
    def setUpDatabase(cls):
        if cls.stack_id is not None:
            return
        # Create a dummy stack in the DB as WatchRule instances
        # must be associated with a stack
        utils.setup_dummy_db()
        ctx = utils.dummy_context()
        ctx.auth_token = 'abcd1234'
        empty_tmpl = {"template": {}}
        tmpl = parser.Template(empty_tmpl)
        stack_name = 'dummystack'
        dummy_stack = parser.Stack(ctx, stack_name, tmpl)
        dummy_stack.state_set(dummy_stack.CREATE, dummy_stack.COMPLETE,
                              'Testing')
        dummy_stack.store()

        cls.stack_id = dummy_stack.id

    def setUp(self):
        super(WatchRuleTest, self).setUp()
        self.setUpDatabase()
        self.username = 'watchrule_test_user'

        self.ctx = utils.dummy_context()
        self.ctx.auth_token = 'abcd1234'

        self.m.ReplayAll()

    def _action_set_stubs(self, now, action_expected=True):
        # Setup stubs for the action tests
        self.m.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().MultipleTimes().AndReturn(now)

        if action_expected:
            dummy_action = DummyAction()
            self.m.StubOutWithMock(parser.Stack, 'resource_by_refid')
            parser.Stack.resource_by_refid(mox.IgnoreArg()).\
                MultipleTimes().AndReturn(dummy_action)

        self.m.ReplayAll()

    def test_minimum(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Minimum',
                'ComparisonOperator': 'LessThanOrEqualToThreshold',
                'Threshold': '50'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(77, now - datetime.timedelta(seconds=100))]
        data.append(WatchData(53, now - datetime.timedelta(seconds=150)))

        # all > 50 -> NORMAL
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        new_state = self.wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        data.append(WatchData(25, now - datetime.timedelta(seconds=250)))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        new_state = self.wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

    def test_maximum(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(7, now - datetime.timedelta(seconds=100))]
        data.append(WatchData(23, now - datetime.timedelta(seconds=150)))

        # all < 30 -> NORMAL
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        self.wr.now = now
        new_state = self.wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        data.append(WatchData(35, now - datetime.timedelta(seconds=150)))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        self.wr.now = now
        new_state = self.wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

    def test_samplecount(self):

        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'SampleCount',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '3'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(1, now - datetime.timedelta(seconds=100))]
        data.append(WatchData(1, now - datetime.timedelta(seconds=150)))

        # only 2 samples -> NORMAL
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        self.wr.now = now
        new_state = self.wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        # only 3 samples -> ALARM
        data.append(WatchData(1, now - datetime.timedelta(seconds=200)))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        self.wr.now = now
        new_state = self.wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

        # only 3 samples (one old) -> NORMAL
        data.pop(0)
        data.append(WatchData(1, now - datetime.timedelta(seconds=400)))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        self.wr.now = now
        new_state = self.wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

    def test_sum(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Sum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '100'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(17, now - datetime.timedelta(seconds=100))]
        data.append(WatchData(23, now - datetime.timedelta(seconds=150)))

        # all < 40 -> NORMAL
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        self.wr.now = now
        new_state = self.wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        # sum > 100 -> ALARM
        data.append(WatchData(85, now - datetime.timedelta(seconds=150)))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        self.wr.now = now
        new_state = self.wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

    def test_ave(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Average',
                'ComparisonOperator': 'GreaterThanThreshold',
                'Threshold': '100'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(117, now - datetime.timedelta(seconds=100))]
        data.append(WatchData(23, now - datetime.timedelta(seconds=150)))

        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        self.wr.now = now
        new_state = self.wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        data.append(WatchData(195, now - datetime.timedelta(seconds=250)))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        self.wr.now = now
        new_state = self.wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

    @utils.wr_delete_after
    def test_load(self):
        # Insert two dummy watch rules into the DB
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}
        self.wr = []
        self.wr.append(watchrule.WatchRule(context=self.ctx,
                                           watch_name='HttpFailureAlarm',
                                           rule=rule,
                                           watch_data=[],
                                           stack_id=self.stack_id,
                                           state='NORMAL'))
        self.wr[0].store()

        self.wr.append(watchrule.WatchRule(context=self.ctx,
                                           watch_name='AnotherWatch',
                                           rule=rule,
                                           watch_data=[],
                                           stack_id=self.stack_id,
                                           state='NORMAL'))
        self.wr[1].store()

        # Then use WatchRule.load() to retrieve each by name
        # and check that the object properties match the data above
        for wn in ('HttpFailureAlarm', 'AnotherWatch'):
            wr = watchrule.WatchRule.load(self.ctx, wn)
            self.assertIsInstance(wr, watchrule.WatchRule)
            self.assertEqual(wn, wr.name)
            self.assertEqual('NORMAL', wr.state)
            self.assertEqual(rule, wr.rule)
            self.assertEqual(datetime.timedelta(seconds=int(rule['Period'])),
                             wr.timeperiod)

    @utils.wr_delete_after
    def test_store(self):
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}
        self.wr = watchrule.WatchRule(context=self.ctx, watch_name='storetest',
                                      stack_id=self.stack_id, rule=rule)
        self.wr.store()

        dbwr = db_api.watch_rule_get_by_name(self.ctx, 'storetest')
        self.assertIsNotNone(dbwr)
        self.assertEqual('storetest', dbwr.name)
        self.assertEqual(watchrule.WatchRule.NODATA, dbwr.state)
        self.assertEqual(rule, dbwr.rule)

    @utils.wr_delete_after
    def test_evaluate(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self.m.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().MultipleTimes().AndReturn(now)
        self.m.ReplayAll()

        # It's not time to evaluate, so should stay NODATA
        last = now - datetime.timedelta(seconds=299)
        data = WatchData(25, now - datetime.timedelta(seconds=150))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = self.wr.evaluate()
        self.assertEqual('NODATA', self.wr.state)
        self.assertEqual([], actions)

        # now - last == Period, so should set NORMAL
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(25, now - datetime.timedelta(seconds=150))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = self.wr.evaluate()
        self.assertEqual('NORMAL', self.wr.state)
        self.assertEqual(now, self.wr.last_evaluated)
        self.assertEqual([], actions)

        # Now data breaches Threshold, so should set ALARM
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = self.wr.evaluate()
        self.assertEqual('ALARM', self.wr.state)
        self.assertEqual(now, self.wr.last_evaluated)
        self.assertEqual([], actions)

    @utils.wr_delete_after
    def test_evaluate_suspend(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self.m.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().MultipleTimes().AndReturn(now)
        self.m.ReplayAll()

        # Now data breaches Threshold, but we're suspended
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        self.wr.state_set(self.wr.SUSPENDED)

        actions = self.wr.evaluate()
        self.assertEqual(self.wr.SUSPENDED, self.wr.state)
        self.assertEqual([], actions)

    @utils.wr_delete_after
    def test_rule_actions_alarm_normal(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._action_set_stubs(now, action_expected=False)

        # Set data so rule evaluates to NORMAL state
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(25, now - datetime.timedelta(seconds=150))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = self.wr.evaluate()
        self.assertEqual('NORMAL', self.wr.state)
        self.assertEqual([], actions)
        self.m.VerifyAll()

    @utils.wr_delete_after
    def test_rule_actions_alarm_alarm(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._action_set_stubs(now)

        # Set data so rule evaluates to ALARM state
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = self.wr.evaluate()
        self.assertEqual('ALARM', self.wr.state)
        self.assertEqual(['DummyAction'], actions)

        # re-set last_evaluated so the rule will be evaluated again.
        last = now - datetime.timedelta(seconds=300)
        self.wr.last_evaluated = last
        actions = self.wr.evaluate()
        self.assertEqual('ALARM', self.wr.state)
        self.assertEqual(['DummyAction'], actions)
        self.m.VerifyAll()

    @utils.wr_delete_after
    def test_rule_actions_alarm_two_actions(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction', 'AnotherDummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._action_set_stubs(now)

        # Set data so rule evaluates to ALARM state
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = self.wr.evaluate()
        self.assertEqual('ALARM', self.wr.state)
        self.assertEqual(['DummyAction', 'DummyAction'], actions)
        self.m.VerifyAll()

    @utils.wr_delete_after
    def test_rule_actions_ok_alarm(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'OKActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._action_set_stubs(now, action_expected=False)

        # On creation the rule evaluates to NODATA state
        last = now - datetime.timedelta(seconds=300)
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = self.wr.evaluate()
        self.assertEqual('NODATA', self.wr.state)
        self.assertEqual([], actions)

        # Move time forward and add data below threshold so we transition from
        # ALARM -> NORMAL, so evaluate() should output a 'DummyAction'
        now = now + datetime.timedelta(seconds=300)
        self.m.VerifyAll()
        self.m.UnsetStubs()
        self._action_set_stubs(now)

        data = WatchData(25, now - datetime.timedelta(seconds=150))
        self.wr.watch_data = [data]

        actions = self.wr.evaluate()
        self.assertEqual('NORMAL', self.wr.state)
        self.assertEqual(['DummyAction'], actions)
        self.m.VerifyAll()

    @utils.wr_delete_after
    def test_rule_actions_nodata(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'InsufficientDataActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._action_set_stubs(now, action_expected=False)

        # Set data so rule evaluates to ALARM state
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = self.wr.evaluate()
        self.assertEqual('ALARM', self.wr.state)
        self.assertEqual([], actions)

        # Move time forward and don't add data so we transition from
        # ALARM -> NODATA, so evaluate() should output a 'DummyAction'
        now = now + datetime.timedelta(seconds=300)
        self.m.VerifyAll()
        self.m.UnsetStubs()
        self._action_set_stubs(now)

        actions = self.wr.evaluate()
        self.assertEqual('NODATA', self.wr.state)
        self.assertEqual(['DummyAction'], actions)
        self.m.VerifyAll()

    @utils.wr_delete_after
    def test_create_watch_data(self):
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'CreateDataMetric'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='create_data_test',
                                      stack_id=self.stack_id, rule=rule)

        self.wr.store()

        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": []}}
        self.wr.create_watch_data(data)

        dbwr = db_api.watch_rule_get_by_name(self.ctx, 'create_data_test')
        self.assertEqual(data, dbwr.watch_data[0].data)

        # Note, would be good to write another datapoint and check it
        # but sqlite seems to not interpret the backreference correctly
        # so dbwr.watch_data is always a list containing only the latest
        # datapoint.  In non-test use on mysql this is not the case, we
        # correctly get a list of all datapoints where watch_rule_id ==
        # watch_rule.id, so leave it as a single-datapoint test for now.

    @utils.wr_delete_after
    def test_create_watch_data_suspended(self):
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'CreateDataMetric'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='create_data_test',
                                      stack_id=self.stack_id, rule=rule,
                                      state=watchrule.WatchRule.SUSPENDED)

        self.wr.store()

        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": []}}
        self.wr.create_watch_data(data)

        dbwr = db_api.watch_rule_get_by_name(self.ctx, 'create_data_test')
        self.assertEqual([], dbwr.watch_data)

    @utils.wr_delete_after
    def test_create_watch_data_match(self):
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='create_data_test',
                                      stack_id=self.stack_id, rule=rule)
        self.wr.store()

        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": [{u'AutoScalingGroupName':
                                                      u'group_x'}]}}
        self.assertTrue(watchrule.rule_can_use_sample(self.wr, data))

    @utils.wr_delete_after
    def test_create_watch_data_match_2(self):
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='create_data_test',
                                      stack_id=self.stack_id, rule=rule)
        self.wr.store()

        data = {u'not_interesting': {"Unit": "Counter",
                                     "Value": "1",
                                     "Dimensions": [
                                         {u'AutoScalingGroupName':
                                          u'group_x'}]},
                u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": [
                                          {u'AutoScalingGroupName':
                                           u'group_x'}]}}
        self.assertTrue(watchrule.rule_can_use_sample(self.wr, data))

    def test_create_watch_data_match_3(self):
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='create_data_test',
                                      stack_id=self.stack_id, rule=rule)
        self.wr.store()

        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": [
                                          {u'AutoScalingGroupName':
                                           u'not_this'}]},
                u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": [
                                          {u'AutoScalingGroupName':
                                           u'group_x'}]}}
        self.assertTrue(watchrule.rule_can_use_sample(self.wr, data))

    def test_create_watch_data_not_match_metric(self):
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='create_data_test',
                                      stack_id=self.stack_id, rule=rule)
        self.wr.store()

        data = {u'not_this': {"Unit": "Counter",
                              "Value": "1",
                              "Dimensions": [
                                  {u'AutoScalingGroupName':
                                   u'group_x'}]},
                u'nor_this': {"Unit": "Counter",
                              "Value": "1",
                              "Dimensions": [
                                  {u'AutoScalingGroupName':
                                   u'group_x'}]}}
        self.assertFalse(watchrule.rule_can_use_sample(self.wr, data))

    def test_create_watch_data_not_match_dimensions(self):
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='create_data_test',
                                      stack_id=self.stack_id, rule=rule)
        self.wr.store()

        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": [
                                          {u'AutoScalingGroupName':
                                           u'not_this'}]},
                u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": [
                                          {u'wrong_key':
                                           u'group_x'}]}}
        self.assertFalse(watchrule.rule_can_use_sample(self.wr, data))

    def test_destroy(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        last = timeutils.utcnow()
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch_destroy",
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        self.wr.store()

        check = watchrule.WatchRule.load(context=self.ctx,
                                         watch_name="testwatch_destroy")
        self.assertIsInstance(check, watchrule.WatchRule)

        self.wr.destroy()
        self.assertRaises(exception.WatchRuleNotFound,
                          watchrule.WatchRule.load, context=self.ctx,
                          watch_name="testwatch_destroy")

    def test_state_set(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        last = timeutils.utcnow()
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch_set_state",
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        watcher.state_set(watcher.SUSPENDED)
        self.assertEqual(watcher.SUSPENDED, watcher.state)

        check = watchrule.WatchRule.load(context=self.ctx,
                                         watch_name="testwatch_set_state")
        self.assertEqual(watchrule.WatchRule.SUSPENDED, check.state)

    def test_set_watch_state(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._action_set_stubs(now)

        # Set data so rule evaluates to ALARM state
        last = now - datetime.timedelta(seconds=200)
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = self.wr.set_watch_state(watchrule.WatchRule.NODATA)
        self.assertEqual([], actions)

        actions = self.wr.set_watch_state(watchrule.WatchRule.NORMAL)
        self.assertEqual([], actions)

        actions = self.wr.set_watch_state(watchrule.WatchRule.ALARM)
        self.assertEqual(['DummyAction'], actions)
        self.m.VerifyAll()

    def test_set_watch_state_invalid(self):
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()

        last = now - datetime.timedelta(seconds=200)
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        self.assertRaises(ValueError, self.wr.set_watch_state, None)

        self.assertRaises(ValueError, self.wr.set_watch_state, "BADSTATE")
