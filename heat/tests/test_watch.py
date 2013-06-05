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


import datetime
import mox
from heat.common import context
import heat.db.api as db_api

from heat.openstack.common import timeutils
from heat.engine import watchrule
from heat.engine import parser
from heat.tests.common import HeatTestCase
from heat.tests import utils


class WatchData:
    def __init__(self, data, created_at):
        self.created_at = created_at
        self.data = {'test_metric': {'Value': data,
                                     'Unit': 'Count'}}


class DummyAction:
    alarm = "DummyAction"


class WatchRuleTest(HeatTestCase):
    stack_id = None

    @classmethod
    def setUpDatabase(cls):
        if cls.stack_id is not None:
            return
        # Create a dummy stack in the DB as WatchRule instances
        # must be associated with a stack
        utils.setup_dummy_db()
        ctx = context.get_admin_context()
        ctx.username = 'dummyuser'
        ctx.tenant_id = '123456'
        empty_tmpl = {"template": {}}
        tmpl = parser.Template(empty_tmpl)
        stack_name = 'dummystack'
        params = parser.Parameters(stack_name, tmpl, {})
        dummy_stack = parser.Stack(ctx, stack_name, tmpl, params)
        dummy_stack.state_set(dummy_stack.CREATE_COMPLETE, 'Testing')
        dummy_stack.store()

        cls.stack_id = dummy_stack.id

    def setUp(self):
        super(WatchRuleTest, self).setUp()
        self.setUpDatabase()
        self.username = 'watchrule_test_user'

        self.ctx = context.get_admin_context()
        self.ctx.username = self.username
        self.ctx.tenant_id = u'123456'

        self.m.ReplayAll()

    def _action_set_stubs(self, now, action_expected=True):
        # Setup stubs for the action tests
        self.m.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().MultipleTimes().AndReturn(now)

        if action_expected:
            dummy_action = DummyAction()
            self.m.StubOutWithMock(parser.Stack, '__getitem__')
            parser.Stack.__getitem__(mox.IgnoreArg()
                                     ).MultipleTimes().AndReturn(dummy_action)

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'NORMAL')

        data.append(WatchData(25, now - datetime.timedelta(seconds=250)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'ALARM')

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'NORMAL')

        data.append(WatchData(35, now - datetime.timedelta(seconds=150)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'ALARM')

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'NORMAL')

        # only 3 samples -> ALARM
        data.append(WatchData(1, now - datetime.timedelta(seconds=200)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'ALARM')

        # only 3 samples (one old) -> NORMAL
        data.pop(0)
        data.append(WatchData(1, now - datetime.timedelta(seconds=400)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'NORMAL')

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'NORMAL')

        # sum > 100 -> ALARM
        data.append(WatchData(85, now - datetime.timedelta(seconds=150)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'ALARM')

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

        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'NORMAL')

        data.append(WatchData(195, now - datetime.timedelta(seconds=250)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=data,
                                      stack_id=self.stack_id,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        self.assertEqual(new_state, 'ALARM')

    def test_load(self):
        # Insert two dummy watch rules into the DB
        values = {'stack_id': self.stack_id,
                  'state': 'NORMAL',
                  'name': u'HttpFailureAlarm',
                  'rule': {u'EvaluationPeriods': u'1',
                           u'AlarmActions': [u'WebServerRestartPolicy'],
                           u'AlarmDescription': u'Restart the WikiDatabase',
                           u'Namespace': u'system/linux',
                           u'Period': u'300',
                           u'ComparisonOperator': u'GreaterThanThreshold',
                           u'Statistic': u'SampleCount',
                           u'Threshold': u'2',
                           u'MetricName': u'ServiceFailure'}}
        db_ret = db_api.watch_rule_create(self.ctx, values)
        self.assertNotEqual(db_ret, None)
        values['name'] = 'AnotherWatch'
        db_ret = db_api.watch_rule_create(self.ctx, values)
        self.assertNotEqual(db_ret, None)

        # Then use WatchRule.load() to retrieve each by name
        # and check that the object properties match the data above
        for wn in ('HttpFailureAlarm', 'AnotherWatch'):
            wr = watchrule.WatchRule.load(self.ctx, wn)
            self.assertEqual(type(wr), watchrule.WatchRule)
            self.assertEqual(wr.name, wn)
            self.assertEqual(wr.state, values['state'])
            self.assertEqual(wr.rule, values['rule'])
            self.assertEqual(wr.timeperiod, datetime.timedelta(
                             seconds=int(values['rule']['Period'])))

        # Cleanup
        db_api.watch_rule_delete(self.ctx, 'HttpFailureAlarm')
        db_api.watch_rule_delete(self.ctx, 'AnotherWatch')

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
        wr = watchrule.WatchRule(context=self.ctx, watch_name='storetest',
                                 stack_id=self.stack_id, rule=rule)
        wr.store()

        dbwr = db_api.watch_rule_get_by_name(self.ctx, 'storetest')
        self.assertNotEqual(dbwr, None)
        self.assertEqual(dbwr.name, 'storetest')
        self.assertEqual(dbwr.state, watchrule.WatchRule.NODATA)
        self.assertEqual(dbwr.rule, rule)

        # Cleanup
        db_api.watch_rule_delete(self.ctx, 'storetest')

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'NODATA')
        self.assertEqual(actions, [])

        # now - last == Period, so should set NORMAL
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(25, now - datetime.timedelta(seconds=150))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'NORMAL')
        self.assertEqual(watcher.last_evaluated, now)
        self.assertEqual(actions, [])

        # Now data breaches Threshold, so should set ALARM
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'ALARM')
        self.assertEqual(watcher.last_evaluated, now)
        self.assertEqual(actions, [])

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'NORMAL')
        self.assertEqual(actions, [])
        self.m.VerifyAll()

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'ALARM')
        self.assertEqual(actions, ['DummyAction'])

        # re-set last_evaluated so the rule will be evaluated again,
        # but since we're already in ALARM state, we should not generate
        # any additional actions
        last = now - datetime.timedelta(seconds=300)
        watcher.last_evaluated = last
        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'ALARM')
        self.assertEqual(actions, [])
        self.m.VerifyAll()

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'ALARM')
        self.assertEqual(actions, ['DummyAction', 'DummyAction'])
        self.m.VerifyAll()

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'NODATA')
        self.assertEqual(actions, [])

        # Move time forward and add data below threshold so we transition from
        # ALARM -> NORMAL, so evaluate() should output a 'DummyAction'
        now = now + datetime.timedelta(seconds=300)
        self.m.VerifyAll()
        self.m.UnsetStubs()
        self._action_set_stubs(now)

        data = WatchData(25, now - datetime.timedelta(seconds=150))
        watcher.watch_data = [data]

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'NORMAL')
        self.assertEqual(actions, ['DummyAction'])
        self.m.VerifyAll()

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[data],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'ALARM')
        self.assertEqual(actions, [])

        # Move time forward and don't add data so we transition from
        # ALARM -> NODATA, so evaluate() should output a 'DummyAction'
        now = now + datetime.timedelta(seconds=300)
        self.m.VerifyAll()
        self.m.UnsetStubs()
        self._action_set_stubs(now)

        actions = watcher.evaluate()
        self.assertEqual(watcher.state, 'NODATA')
        self.assertEqual(actions, ['DummyAction'])
        self.m.VerifyAll()

    def test_create_watch_data(self):
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'CreateDataMetric'}
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='create_data_test',
                                 stack_id=self.stack_id, rule=rule)

        wr.store()

        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": []}}
        wr.create_watch_data(data)

        dbwr = db_api.watch_rule_get_by_name(self.ctx, 'create_data_test')
        self.assertEqual(dbwr.watch_data[0].data, data)

        # Note, would be good to write another datapoint and check it
        # but sqlite seems to not interpret the backreference correctly
        # so dbwr.watch_data is always a list containing only the latest
        # datapoint.  In non-test use on mysql this is not the case, we
        # correctly get a list of all datapoints where watch_rule_id ==
        # watch_rule.id, so leave it as a single-datapoint test for now.

        # Cleanup
        db_api.watch_rule_delete(self.ctx, 'create_data_test')

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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        actions = watcher.set_watch_state(watchrule.WatchRule.NODATA)
        self.assertEqual(actions, [])

        actions = watcher.set_watch_state(watchrule.WatchRule.NORMAL)
        self.assertEqual(actions, [])

        actions = watcher.set_watch_state(watchrule.WatchRule.ALARM)
        self.assertEqual(actions, ['DummyAction'])
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
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack_id,
                                      last_evaluated=last)

        self.assertRaises(ValueError, watcher.set_watch_state, None)

        self.assertRaises(ValueError, watcher.set_watch_state, "BADSTATE")
