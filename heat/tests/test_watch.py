import datetime
import mox
import nose
from nose.plugins.attrib import attr
from nose import with_setup
import unittest
from nose.exc import SkipTest
import logging

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


class WatchRuleTest(unittest.TestCase):

    @attr(tag=['unit', 'watchrule'])
    @attr(speed='fast')
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
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        data.append(WatchData(25, now - datetime.timedelta(seconds=250)))
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')

    @attr(tag=['unit', 'watchrule'])
    @attr(speed='fast')
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
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        data.append(WatchData(35, now - datetime.timedelta(seconds=150)))
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')

    @attr(tag=['unit', 'watchrule'])
    @attr(speed='fast')
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
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        # only 3 samples -> ALARM
        data.append(WatchData(1, now - datetime.timedelta(seconds=200)))
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')

        # only 3 samples (one old) -> NORMAL
        data.pop(0)
        data.append(WatchData(1, now - datetime.timedelta(seconds=400)))
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

    @attr(tag=['unit', 'watchrule'])
    @attr(speed='fast')
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
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        # sum > 100 -> ALARM
        data.append(WatchData(85, now - datetime.timedelta(seconds=150)))
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')

    @attr(tag=['unit', 'watchrule'])
    @attr(speed='fast')
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

        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'NORMAL')

        data.append(WatchData(195, now - datetime.timedelta(seconds=250)))
        watcher = watchrule.WatchRule(rule, data, last, now)
        new_state = watcher.get_alarm_state()
        logger.info(new_state)
        self.assertEqual(new_state, 'ALARM')
