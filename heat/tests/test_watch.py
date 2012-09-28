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
import nose
from nose.plugins.attrib import attr
from nose import with_setup
import unittest
from nose.exc import SkipTest
import logging
from heat.common import context
import heat.db as db_api

from heat.openstack.common import timeutils
try:
    from heat.engine import watchrule
except:
    raise SkipTest("unable to import watchrule, skipping")


logger = logging.getLogger('test_watch')


class WatchData:
    def __init__(self, data, created_at):
        self.created_at = created_at
        self.data = {'test_metric': {'Value': data,
                                     'Unit': 'Count'}}


@attr(tag=['unit', 'watchrule'])
@attr(speed='fast')
class WatchRuleTest(unittest.TestCase):

    def setUp(self):
        self.username = 'watchrule_test_user'

        self.m = mox.Mox()

        self.ctx = context.get_admin_context()
        self.m.StubOutWithMock(self.ctx, 'username')
        self.ctx.username = self.username

        self.m.ReplayAll()

    def tearDown(self):
        self.m.UnsetStubs()

    def test_minimum(self):
        rule = {
        'EvaluationPeriods': '1',
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
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        data.append(WatchData(25, now - datetime.timedelta(seconds=250)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')

    def test_maximum(self):
        rule = {
        'EvaluationPeriods': '1',
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
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        data.append(WatchData(35, now - datetime.timedelta(seconds=150)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')

    def test_samplecount(self):

        rule = {
        'EvaluationPeriods': '1',
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
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        # only 3 samples -> ALARM
        data.append(WatchData(1, now - datetime.timedelta(seconds=200)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')

        # only 3 samples (one old) -> NORMAL
        data.pop(0)
        data.append(WatchData(1, now - datetime.timedelta(seconds=400)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

    def test_sum(self):
        rule = {
        'EvaluationPeriods': '1',
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
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        # sum > 100 -> ALARM
        data.append(WatchData(85, now - datetime.timedelta(seconds=150)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')

    def test_ave(self):
        rule = {
        'EvaluationPeriods': '1',
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
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        data.append(WatchData(195, now - datetime.timedelta(seconds=250)))
        watcher = watchrule.WatchRule(context=self.ctx,
                                      watch_name="testwatch",
                                      rule=rule,
                                      stack_name="teststack",
                                      watch_data=data,
                                      last_evaluated=last)
        watcher.now = now
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')

    def test_load(self):
        # Insert two dummy watch rules into the DB
        values = {'stack_name': u'wordpress_ha', 'state': 'NORMAL',
                  'name': u'HttpFailureAlarm',
                   'rule': {
                        u'EvaluationPeriods': u'1',
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
            self.assertEqual(wr.stack_name, values['stack_name'])
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
                                 rule=rule, stack_name='teststack')
        wr.store()

        dbwr = db_api.watch_rule_get_by_name(self.ctx, 'storetest')
        self.assertNotEqual(dbwr, None)
        self.assertEqual(dbwr.name, 'storetest')
        self.assertEqual(dbwr.state, watchrule.WatchRule.NORMAL)
        self.assertEqual(dbwr.stack_name, 'teststack')
        self.assertEqual(dbwr.rule, rule)

        # Cleanup
        db_api.watch_rule_delete(self.ctx, 'storetest')
