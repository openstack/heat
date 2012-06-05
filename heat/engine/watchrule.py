# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import logging
from heat.openstack.common import timeutils

logger = logging.getLogger('heat.engine.watchrule')


class WatchRule(object):
    ALARM = 'ALARM'
    NORMAL = 'NORMAL'
    NODATA = 'NODATA'

    def __init__(self, rule, dataset, last_evaluated, now):
        self.rule = rule
        self.data = dataset
        self.last_evaluated = last_evaluated
        self.now = now
        self.timeperiod = datetime.timedelta(seconds=int(self.rule['Period']))

    def do_data_cmp(self, data, threshold):
        op = self.rule['ComparisonOperator']
        if op == 'GreaterThanThreshold':
            return data > threshold
        elif op == 'GreaterThanOrEqualToThreshold':
            return data >= threshold
        elif op == 'LessThanThreshold':
            return data < threshold
        elif op == 'LessThanOrEqualToThreshold':
            return data <= threshold
        else:
            return False

    def do_Maximum(self):
        data = 0
        have_data = False
        for d in self.data:
            if d.created_at < self.now - self.timeperiod:
                continue
            if not have_data:
                data = int(d.data[self.rule['MetricName']]['Value'])
                have_data = True
            if int(d.data[self.rule['MetricName']]['Value']) > data:
                data = int(d.data[self.rule['MetricName']]['Value'])

        if not have_data:
            return self.NODATA

        if self.do_data_cmp(data,
                            int(self.rule['Threshold'])):
            return self.ALARM
        else:
            return self.NORMAL

    def do_Minimum(self):
        data = 0
        have_data = False
        for d in self.data:
            if d.created_at < self.now - self.timeperiod:
                continue
            if not have_data:
                data = int(d.data[self.rule['MetricName']]['Value'])
                have_data = True
            elif int(d.data[self.rule['MetricName']]['Value']) < data:
                data = int(d.data[self.rule['MetricName']]['Value'])

        if not have_data:
            return self.NODATA

        if self.do_data_cmp(data,
                            int(self.rule['Threshold'])):
            return self.ALARM
        else:
            return self.NORMAL

    def do_SampleCount(self):
        '''
        count all samples within the specified period
        '''
        data = 0
        for d in self.data:
            if d.created_at < self.now - self.timeperiod:
                continue
            data = data + 1

        if self.do_data_cmp(data,
                            int(self.rule['Threshold'])):
            return self.ALARM
        else:
            return self.NORMAL

    def do_Average(self):
        data = 0
        samples = 0
        for d in self.data:
            if d.created_at < self.now - self.timeperiod:
                continue
            samples = samples + 1
            data = data + int(d.data[self.rule['MetricName']]['Value'])

        if samples == 0:
            return self.NODATA

        data = data / samples
        if self.do_data_cmp(data,
                            int(self.rule['Threshold'])):
            return self.ALARM
        else:
            return self.NORMAL

    def do_Sum(self):
        data = 0
        for d in self.data:
            if d.created_at < self.now - self.timeperiod:
                logger.debug('ignoring %s' % str(d.data))
                continue
            data = data + int(d.data[self.rule['MetricName']]['Value'])

        if self.do_data_cmp(data,
                            int(self.rule['Threshold'])):
            return self.ALARM
        else:
            return self.NORMAL

    def get_alarm_state(self):
        fn = getattr(self, 'do_%s' % self.rule['Statistic'])
        return fn()
