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


import datetime

import mock
from oslo_utils import timeutils

from heat.common import exception
from heat.engine import stack
from heat.engine import template
from heat.engine import watchrule
from heat.objects import watch_rule
from heat.tests import common
from heat.tests import utils


class WatchData(object):
    def __init__(self, data, created_at):
        self.created_at = created_at
        self.data = {'test_metric': {'Value': data,
                                     'Unit': 'Count'}}


class DummyAction(object):
    signal = "DummyAction"


class WatchRuleTest(common.HeatTestCase):
    stack_id = None

    def setUp(self):
        super(WatchRuleTest, self).setUp()

        self.username = 'watchrule_test_user'
        self.ctx = utils.dummy_context()
        self.ctx.auth_token = 'abcd1234'

        self._setup_database()

    def _setup_database(self):
        if self.stack_id is not None:
            return
        # Create a dummy stack in the DB as WatchRule instances
        # must be associated with a stack
        empty_tmpl = {'HeatTemplateFormatVersion': '2012-12-12'}
        tmpl = template.Template(empty_tmpl)
        stack_name = 'dummystack'
        dummy_stack = stack.Stack(self.ctx, stack_name, tmpl)
        dummy_stack.state_set(dummy_stack.CREATE, dummy_stack.COMPLETE,
                              'Testing')
        dummy_stack.store()

        self.stack_id = dummy_stack.id

    def _setup_action_mocks(self, mock_get_resource, now,
                            action_expected=True):
        """Setup stubs for the action tests."""
        timeutils.set_time_override(now)
        self.addCleanup(timeutils.clear_time_override)

        if action_expected:
            dummy_action = DummyAction()
            mock_get_resource.return_value = dummy_action

    def test_minimum(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Minimum',
                'ComparisonOperator': 'LessThanOrEqualToThreshold',
                'Threshold': '50'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(77, now - datetime.timedelta(seconds=100))]

        # Test 1 - Values greater than 0 are normal
        data.append(WatchData(53, now - datetime.timedelta(seconds=150)))
        wr = watchrule.WatchRule(self.ctx,
                                 'testwatch',
                                 rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        new_state = wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        # Test 2
        data.append(WatchData(25, now - datetime.timedelta(seconds=250)))
        wr = watchrule.WatchRule(self.ctx,
                                 'testwatch',
                                 rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        new_state = wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

    def test_maximum(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(7, now - datetime.timedelta(seconds=100))]

        # Test 1 - values less than 30 are normal
        data.append(WatchData(23, now - datetime.timedelta(seconds=150)))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.now = now
        new_state = wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        # Test 2
        data.append(WatchData(35, now - datetime.timedelta(seconds=150)))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.now = now
        new_state = wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

    def test_samplecount(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'SampleCount',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '3'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(1, now - datetime.timedelta(seconds=100))]

        # Test 1 - 2 samples is normal
        data.append(WatchData(1, now - datetime.timedelta(seconds=150)))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.now = now
        new_state = wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        # Test 2 - 3 samples is an alarm
        data.append(WatchData(1, now - datetime.timedelta(seconds=200)))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.now = now
        new_state = wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

        # Test 3 - 3 samples (one old) is normal
        data.pop(0)
        data.append(WatchData(1, now - datetime.timedelta(seconds=400)))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.now = now
        new_state = wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

    def test_sum(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Sum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '100'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(17, now - datetime.timedelta(seconds=100))]

        # Test 1 - values less than 40 are normal
        data.append(WatchData(23, now - datetime.timedelta(seconds=150)))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.now = now
        new_state = wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        # Test 2 - sum greater than 100 is an alarm
        data.append(WatchData(85, now - datetime.timedelta(seconds=150)))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.now = now
        new_state = wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

    def test_average(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Average',
                'ComparisonOperator': 'GreaterThanThreshold',
                'Threshold': '100'}

        now = timeutils.utcnow()
        last = now - datetime.timedelta(seconds=320)
        data = [WatchData(117, now - datetime.timedelta(seconds=100))]

        # Test 1
        data.append(WatchData(23, now - datetime.timedelta(seconds=150)))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.now = now
        new_state = wr.get_alarm_state()
        self.assertEqual('NORMAL', new_state)

        # Test 2
        data.append(WatchData(195, now - datetime.timedelta(seconds=250)))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=data,
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.now = now
        new_state = wr.get_alarm_state()
        self.assertEqual('ALARM', new_state)

    def test_load(self):
        # Setup
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
        rules = []
        rules.append(watchrule.WatchRule(context=self.ctx,
                                         watch_name='HttpFailureAlarm',
                                         rule=rule,
                                         watch_data=[],
                                         stack_id=self.stack_id,
                                         state='NORMAL'))
        rules[0].store()

        rules.append(watchrule.WatchRule(context=self.ctx,
                                         watch_name='AnotherWatch',
                                         rule=rule,
                                         watch_data=[],
                                         stack_id=self.stack_id,
                                         state='NORMAL'))
        rules[1].store()

        # Test
        for wn in ('HttpFailureAlarm', 'AnotherWatch'):
            wr = watchrule.WatchRule.load(self.ctx, wn)
            self.assertIsInstance(wr, watchrule.WatchRule)
            self.assertEqual(wn, wr.name)
            self.assertEqual('NORMAL', wr.state)
            self.assertEqual(rule, wr.rule)
            self.assertEqual(datetime.timedelta(seconds=int(rule['Period'])),
                             wr.timeperiod)

    def test_store(self):
        # Setup
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}

        # Test
        wr = watchrule.WatchRule(context=self.ctx, watch_name='storetest',
                                 stack_id=self.stack_id, rule=rule)
        wr.store()

        # Verify
        dbwr = watch_rule.WatchRule.get_by_name(self.ctx, 'storetest')
        self.assertIsNotNone(dbwr)
        self.assertEqual('storetest', dbwr.name)
        self.assertEqual(watchrule.WatchRule.NODATA, dbwr.state)
        self.assertEqual(rule, dbwr.rule)

    def test_evaluate(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        timeutils.set_time_override(now)
        self.addCleanup(timeutils.clear_time_override)

        # Test 1 - It's not time to evaluate, so should stay NODATA
        last = now - datetime.timedelta(seconds=299)
        data = WatchData(25, now - datetime.timedelta(seconds=150))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[data],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        actions = wr.evaluate()
        self.assertEqual('NODATA', wr.state)
        self.assertEqual([], actions)

        # Test 2 - now - last == Period, so should set NORMAL
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(25, now - datetime.timedelta(seconds=150))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[data],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        actions = wr.evaluate()
        self.assertEqual('NORMAL', wr.state)
        self.assertEqual(now, wr.last_evaluated)
        self.assertEqual([], actions)

        # Test 3 - Now data breaches Threshold, so should set ALARM
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[data],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        actions = wr.evaluate()
        self.assertEqual('ALARM', wr.state)
        self.assertEqual(now, wr.last_evaluated)
        self.assertEqual([], actions)

    def test_evaluate_suspend(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        timeutils.set_time_override(now)
        self.addCleanup(timeutils.clear_time_override)

        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[data],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.state_set(wr.SUSPENDED)

        # Test
        actions = wr.evaluate()
        self.assertEqual(wr.SUSPENDED, wr.state)
        self.assertEqual([], actions)

    def test_evaluate_ceilometer_controlled(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        timeutils.set_time_override(now)
        self.addCleanup(timeutils.clear_time_override)

        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[data],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)
        wr.state_set(wr.CEILOMETER_CONTROLLED)

        # Test
        actions = wr.evaluate()
        self.assertEqual(wr.CEILOMETER_CONTROLLED, wr.state)
        self.assertEqual([], actions)

    @mock.patch('heat.engine.stack.Stack.resource_by_refid')
    def test_rule_actions_alarm_normal(self, mock_get_resource):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._setup_action_mocks(mock_get_resource, now,
                                 action_expected=False)

        # Set data so rule evaluates to NORMAL state
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(25, now - datetime.timedelta(seconds=150))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[data],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        # Test
        actions = wr.evaluate()
        self.assertEqual('NORMAL', wr.state)
        self.assertEqual([], actions)
        self.assertEqual(0, mock_get_resource.call_count)

    @mock.patch('heat.engine.stack.Stack.resource_by_refid')
    def test_rule_actions_alarm_alarm(self, mock_get_resource):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._setup_action_mocks(mock_get_resource, now)

        # Set data so rule evaluates to ALARM state
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[data],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        # Test
        actions = wr.evaluate()
        self.assertEqual('ALARM', wr.state)
        self.assertEqual(['DummyAction'], actions)

        # re-set last_evaluated so the rule will be evaluated again.
        last = now - datetime.timedelta(seconds=300)
        wr.last_evaluated = last
        actions = wr.evaluate()
        self.assertEqual('ALARM', wr.state)
        self.assertEqual(['DummyAction'], actions)
        self.assertTrue(mock_get_resource.call_count > 0)

    @mock.patch('heat.engine.stack.Stack.resource_by_refid')
    def test_rule_actions_alarm_two_actions(self, mock_get_resource):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction', 'AnotherDummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._setup_action_mocks(mock_get_resource, now)

        # Set data so rule evaluates to ALARM state
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[data],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        # Test
        actions = wr.evaluate()
        self.assertEqual('ALARM', wr.state)
        self.assertEqual(['DummyAction', 'DummyAction'], actions)
        self.assertTrue(mock_get_resource.call_count > 0)

    @mock.patch('heat.engine.stack.Stack.resource_by_refid')
    def test_rule_actions_ok_alarm(self, mock_get_resource):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'OKActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._setup_action_mocks(mock_get_resource, now, action_expected=False)

        # On creation the rule evaluates to NODATA state
        last = now - datetime.timedelta(seconds=300)
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        # Test
        actions = wr.evaluate()
        self.assertEqual('NODATA', wr.state)
        self.assertEqual([], actions)

        # Move time forward and add data below threshold so we transition from
        # ALARM -> NORMAL, so evaluate() should output a 'DummyAction'
        now = now + datetime.timedelta(seconds=300)
        self._setup_action_mocks(mock_get_resource, now)

        data = WatchData(25, now - datetime.timedelta(seconds=150))
        wr.watch_data = [data]

        actions = wr.evaluate()
        self.assertEqual('NORMAL', wr.state)
        self.assertEqual(['DummyAction'], actions)
        self.assertTrue(mock_get_resource.call_count > 0)

    @mock.patch('heat.engine.stack.Stack.resource_by_refid')
    def test_rule_actions_nodata(self, mock_get_resource):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'InsufficientDataActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._setup_action_mocks(mock_get_resource, now, action_expected=False)

        # Set data so rule evaluates to ALARM state
        last = now - datetime.timedelta(seconds=300)
        data = WatchData(35, now - datetime.timedelta(seconds=150))
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[data],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        # Test
        actions = wr.evaluate()
        self.assertEqual('ALARM', wr.state)
        self.assertEqual([], actions)

        # Move time forward and don't add data so we transition from
        # ALARM -> NODATA, so evaluate() should output a 'DummyAction'
        now = now + datetime.timedelta(seconds=300)
        self._setup_action_mocks(mock_get_resource, now)

        actions = wr.evaluate()
        self.assertEqual('NODATA', wr.state)
        self.assertEqual(['DummyAction'], actions)
        self.assertTrue(mock_get_resource.call_count > 0)

    @mock.patch('ceilometerclient.openstack.common.apiclient.'
                'client.HTTPClient.client_request')
    @mock.patch('heat.engine.stack.Stack.resource_by_refid')
    def test_to_ceilometer(self, mock_get_resource, mock_client_request):
        # Setup
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'CreateDataMetric'}
        testdata = {u'CreateDataMetric': {"Unit": "Counter", "Value": "1"}}

        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='create_data_test',
                                 stack_id=self.stack_id,
                                 rule=rule)
        wr.store()

        mock_ceilometer_client = mock.MagicMock()

        self.ctx._clients = mock.MagicMock()
        self.ctx._clients.client.return_value = mock_ceilometer_client

        # Test
        wr._to_ceilometer(testdata)

        # Verify
        self.assertEqual(1, mock_ceilometer_client.samples.create.call_count)
        create_kw_args = mock_ceilometer_client.samples.create.call_args[1]
        expected = {
            'counter_type': 'gauge',
            'counter_name': 'CreateDataMetric',
            'counter_volume': '1',
            'counter_unit': 'Counter',
            'resource_metadata': {},
            'resource_id': None,
        }
        self.assertEqual(expected, create_kw_args)

    def test_create_watch_data(self):
        # Setup
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'CreateDataMetric'}
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='create_data_test',
                                 stack_id=self.stack_id,
                                 rule=rule)

        wr.store()

        # Test
        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": []}}
        wr.create_watch_data(data)

        # Verify
        obj_wr = watch_rule.WatchRule.get_by_name(self.ctx, 'create_data_test')
        obj_wds = [wd for wd in obj_wr.watch_data]
        self.assertEqual(data, obj_wds[0].data)

        # Note, would be good to write another datapoint and check it
        # but sqlite seems to not interpret the backreference correctly
        # so dbwr.watch_data is always a list containing only the latest
        # datapoint.  In non-test use on mysql this is not the case, we
        # correctly get a list of all datapoints where watch_rule_id ==
        # watch_rule.id, so leave it as a single-datapoint test for now.

    def test_create_watch_data_suspended(self):
        # Setup
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'CreateDataMetric'}
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='create_data_test',
                                 stack_id=self.stack_id,
                                 rule=rule,
                                 state=watchrule.WatchRule.SUSPENDED)

        wr.store()

        # Test
        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": []}}
        wr.create_watch_data(data)

        # Verify
        obj_wr = watch_rule.WatchRule.get_by_name(self.ctx, 'create_data_test')
        obj_wds = [wd for wd in obj_wr.watch_data]
        self.assertEqual([], obj_wds)

    def test_create_watch_data_match(self):
        # Setup
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='create_data_test',
                                 stack_id=self.stack_id,
                                 rule=rule)
        wr.store()

        # Test
        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": [{u'AutoScalingGroupName':
                                                      u'group_x'}]}}
        self.assertTrue(watchrule.rule_can_use_sample(wr, data))

    def test_create_watch_data_match_2(self):
        # Setup
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='create_data_test',
                                 stack_id=self.stack_id,
                                 rule=rule)
        wr.store()

        # Test
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
        self.assertTrue(watchrule.rule_can_use_sample(wr, data))

    def test_create_watch_data_match_3(self):
        # Setup
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='create_data_test',
                                 stack_id=self.stack_id,
                                 rule=rule)
        wr.store()

        # Test
        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": [
                                          {u'AutoScalingGroupName':
                                           u'group_x'}]}}
        self.assertTrue(watchrule.rule_can_use_sample(wr, data))

    def test_create_watch_data_not_match_metric(self):
        # Setup
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='create_data_test',
                                 stack_id=self.stack_id,
                                 rule=rule)
        wr.store()

        # Test
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
        self.assertFalse(watchrule.rule_can_use_sample(wr, data))

    def test_create_watch_data_not_match_dimensions(self):
        # Setup
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmDescription': u'test alarm',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'Dimensions': [{u'Name': 'AutoScalingGroupName',
                                 u'Value': 'group_x'}],
                u'MetricName': u'CreateDataMetric'}
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='create_data_test',
                                 stack_id=self.stack_id,
                                 rule=rule)
        wr.store()

        # Test
        data = {u'CreateDataMetric': {"Unit": "Counter",
                                      "Value": "1",
                                      "Dimensions": [
                                          {u'wrong_key':
                                           u'group_x'}]}}
        self.assertFalse(watchrule.rule_can_use_sample(wr, data))

    def test_destroy(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        last = timeutils.utcnow()
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name='testwatch_destroy',
                                 rule=rule,
                                 watch_data=[],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        wr.store()

        # Sanity Check
        check = watchrule.WatchRule.load(context=self.ctx,
                                         watch_name='testwatch_destroy')
        self.assertIsInstance(check, watchrule.WatchRule)

        # Test
        wr.destroy()
        ex = self.assertRaises(exception.EntityNotFound,
                               watchrule.WatchRule.load,
                               context=self.ctx,
                               watch_name='testwatch_destroy')
        self.assertEqual('Watch Rule', ex.kwargs.get('entity'))

    def test_state_set(self):
        # Setup
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

        # Test
        watcher.state_set(watcher.SUSPENDED)

        # Verify
        self.assertEqual(watcher.SUSPENDED, watcher.state)
        check = watchrule.WatchRule.load(context=self.ctx,
                                         watch_name='testwatch_set_state')
        self.assertEqual(watchrule.WatchRule.SUSPENDED, check.state)

    @mock.patch('heat.engine.stack.Stack.resource_by_refid')
    def test_set_watch_state(self, mock_get_resource):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()
        self._setup_action_mocks(mock_get_resource, now)

        # Set data so rule evaluates to ALARM state
        last = now - datetime.timedelta(seconds=200)
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        # Test
        actions = wr.set_watch_state(watchrule.WatchRule.NODATA)
        self.assertEqual([], actions)

        actions = wr.set_watch_state(watchrule.WatchRule.NORMAL)
        self.assertEqual([], actions)

        actions = wr.set_watch_state(watchrule.WatchRule.ALARM)
        self.assertEqual(['DummyAction'], actions)
        self.assertTrue(mock_get_resource.call_count > 0)

    def test_set_watch_state_invalid(self):
        # Setup
        rule = {'EvaluationPeriods': '1',
                'MetricName': 'test_metric',
                'AlarmActions': ['DummyAction'],
                'Period': '300',
                'Statistic': 'Maximum',
                'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
                'Threshold': '30'}

        now = timeutils.utcnow()

        last = now - datetime.timedelta(seconds=200)
        wr = watchrule.WatchRule(context=self.ctx,
                                 watch_name="testwatch",
                                 rule=rule,
                                 watch_data=[],
                                 stack_id=self.stack_id,
                                 last_evaluated=last)

        # Test
        self.assertRaises(ValueError, wr.set_watch_state, None)
        self.assertRaises(ValueError, wr.set_watch_state, "BADSTATE")
