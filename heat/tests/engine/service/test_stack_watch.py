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

import mock
from oslo_messaging.rpc import dispatcher

from heat.common import exception
from heat.engine import service
from heat.engine import service_stack_watch
from heat.engine import stack
from heat.engine import watchrule
from heat.objects import stack as stack_object
from heat.objects import watch_data as watch_data_object
from heat.objects import watch_rule as watch_rule_object
from heat.rpc import api as rpc_api
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import utils


class StackWatchTest(common.HeatTestCase):

    def setUp(self):
        super(StackWatchTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_watch_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')
        # self.eng.engine_id = 'engine-fake-uuid'

    def _create_periodic_tasks(self):
        self.eng.create_periodic_tasks()
        self.eng.manage_thread_grp.wait()

    @mock.patch.object(service_stack_watch.StackWatch, 'start_watch_task')
    @mock.patch.object(stack_object.Stack, 'get_all')
    @mock.patch.object(service.service.Service, 'start')
    def test_start_watches_all_stacks(self, mock_super_start, mock_get_all,
                                      start_watch_task):
        s1 = mock.Mock(id=1)
        s2 = mock.Mock(id=2)
        mock_get_all.return_value = [s1, s2]
        start_watch_task.return_value = None

        self.eng.thread_group_mgr = None
        self._create_periodic_tasks()

        mock_get_all.assert_called_once_with(mock.ANY, tenant_safe=False,
                                             show_hidden=True)
        calls = start_watch_task.call_args_list
        self.assertEqual(2, start_watch_task.call_count)
        self.assertIn(mock.call(1, mock.ANY), calls)
        self.assertIn(mock.call(2, mock.ANY), calls)

    @tools.stack_context('service_show_watch_test_stack', False)
    def test_show_watch(self):
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
                                           watch_name='show_watch_1',
                                           rule=rule,
                                           watch_data=[],
                                           stack_id=self.stack.id,
                                           state='NORMAL'))
        self.wr[0].store()

        self.wr.append(watchrule.WatchRule(context=self.ctx,
                                           watch_name='show_watch_2',
                                           rule=rule,
                                           watch_data=[],
                                           stack_id=self.stack.id,
                                           state='NORMAL'))
        self.wr[1].store()

        # watch_name=None should return all watches
        result = self.eng.show_watch(self.ctx, watch_name=None)
        result_names = [r.get('name') for r in result]
        self.assertIn('show_watch_1', result_names)
        self.assertIn('show_watch_2', result_names)

        result = self.eng.show_watch(self.ctx, watch_name="show_watch_1")
        self.assertEqual(1, len(result))
        self.assertIn('name', result[0])
        self.assertEqual('show_watch_1', result[0]['name'])

        result = self.eng.show_watch(self.ctx, watch_name="show_watch_2")
        self.assertEqual(1, len(result))
        self.assertIn('name', result[0])
        self.assertEqual('show_watch_2', result[0]['name'])

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_watch,
                               self.ctx, watch_name="nonexistent")
        self.assertEqual(exception.WatchRuleNotFound, ex.exc_info[0])

        # Check the response has all keys defined in the engine API
        for key in rpc_api.WATCH_KEYS:
            self.assertIn(key, result[0])

    @tools.stack_context('service_show_watch_metric_test_stack', False)
    def test_show_watch_metric(self):
        # Insert dummy watch rule into the DB
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='show_watch_metric_1',
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack.id,
                                      state='NORMAL')
        self.wr.store()

        # And add a metric datapoint
        watch = watch_rule_object.WatchRule.get_by_name(self.ctx,
                                                        'show_watch_metric_1')
        self.assertIsNotNone(watch)
        values = {'watch_rule_id': watch.id,
                  'data': {u'Namespace': u'system/linux',
                           u'ServiceFailure': {
                               u'Units': u'Counter', u'Value': 1}}}
        watch_data_object.WatchData.create(self.ctx, values)

        # Check there is one result returned
        result = self.eng.show_watch_metric(self.ctx,
                                            metric_namespace=None,
                                            metric_name=None)
        self.assertEqual(1, len(result))

        # Create another metric datapoint and check we get two
        watch_data_object.WatchData.create(self.ctx, values)
        result = self.eng.show_watch_metric(self.ctx,
                                            metric_namespace=None,
                                            metric_name=None)
        self.assertEqual(2, len(result))

        # Check the response has all keys defined in the engine API
        for key in rpc_api.WATCH_DATA_KEYS:
            self.assertIn(key, result[0])

    @tools.stack_context('service_show_watch_state_test_stack')
    @mock.patch.object(stack.Stack, 'resource_by_refid')
    def test_set_watch_state(self, mock_ref):
        self._create_periodic_tasks()
        # Insert dummy watch rule into the DB
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='OverrideAlarm',
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack.id,
                                      state='NORMAL')
        self.wr.store()

        class DummyAction(object):
            def signal(self):
                return "dummyfoo"

        dummy_action = DummyAction()
        mock_ref.return_value = dummy_action

        # Replace the real stack threadgroup with a dummy one, so we can
        # check the function returned on ALARM is correctly scheduled
        dtg = tools.DummyThreadGroup()
        self.eng.thread_group_mgr.groups[self.stack.id] = dtg

        state = watchrule.WatchRule.NODATA
        result = self.eng.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(state, result[rpc_api.WATCH_STATE_VALUE])
        self.assertEqual(
            [], self.eng.thread_group_mgr.groups[self.stack.id].threads)

        state = watchrule.WatchRule.NORMAL
        result = self.eng.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(state, result[rpc_api.WATCH_STATE_VALUE])
        self.assertEqual(
            [], self.eng.thread_group_mgr.groups[self.stack.id].threads)

        state = watchrule.WatchRule.ALARM
        result = self.eng.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(state, result[rpc_api.WATCH_STATE_VALUE])
        self.assertEqual(
            [dummy_action.signal],
            self.eng.thread_group_mgr.groups[self.stack.id].threads)

        mock_ref.assert_called_once_with('WebServerRestartPolicy')

    @tools.stack_context('service_show_watch_state_badstate_test_stack')
    @mock.patch.object(watchrule.WatchRule, 'set_watch_state')
    def test_set_watch_state_badstate(self, mock_set):
        mock_set.side_effect = ValueError
        # Insert dummy watch rule into the DB
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='OverrideAlarm2',
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack.id,
                                      state='NORMAL')
        self.wr.store()

        for state in ["HGJHGJHG", "1234", "!\*(&%"]:
            self.assertRaises(ValueError,
                              self.eng.set_watch_state,
                              self.ctx, watch_name="OverrideAlarm2",
                              state=state)

        calls = [mock.call("HGJHGJHG"),
                 mock.call("1234"),
                 mock.call("!\*(&%")]
        mock_set.assert_has_calls(calls)

    @mock.patch.object(watchrule.WatchRule, 'load')
    def test_set_watch_state_noexist(self, mock_load):
        state = watchrule.WatchRule.ALARM   # State valid
        mock_load.side_effect = exception.WatchRuleNotFound(watch_name='test')

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.set_watch_state,
                               self.ctx, watch_name="nonexistent",
                               state=state)
        self.assertEqual(exception.WatchRuleNotFound, ex.exc_info[0])
        mock_load.assert_called_once_with(self.ctx, "nonexistent")
