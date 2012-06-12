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

import eventlet
import logging
import json
import os

from heat.common import exception
from heat.db import api as db_api
from heat.engine.resources import Resource

logger = logging.getLogger('heat.engine.cloud_watch')


class CloudWatchAlarm(Resource):
    properties_schema = {'ComparisonOperator': {'Type': 'String',
                         'AllowedValues': ['GreaterThanOrEqualToThreshold',
                         'GreaterThanThreshold', 'LessThanThreshold',
                         'LessThanOrEqualToThreshold']},
        'AlarmDescription': {'Type': 'String'},
        'EvaluationPeriods': {'Type': 'String'},
        'MetricName': {'Type': 'String'},
        'Namespace': {'Type': 'String'},
        'Period': {'Type': 'String'},
        'Statistic': {'Type': 'String',
                      'AllowedValues': ['SampleCount', 'Average', 'Sum',
                                        'Minimum', 'Maximum']},
        'AlarmActions': {'Type': 'List'},
        'OKActions': {'Type': 'List'},
        'InsufficientDataActions': {'Type': 'List'},
        'Threshold': {'Type': 'String'},
        'Units': {'Type': 'String',
                  'AllowedValues': ['Seconds', 'Microseconds', 'Milliseconds',
                  'Bytes', 'Kilobytes', 'Megabytes', 'Gigabytes',
                  'Terabytes', 'Bits', 'Kilobits', 'Megabits', 'Gigabits',
                  'Terabits', 'Percent', 'Count', 'Bytes/Second',
                  'Kilobytes/Second', 'Megabytes/Second', 'Gigabytes/Second',
                  'Terabytes/Second', 'Bits/Second', 'Kilobits/Second',
                  'Megabits/Second', 'Gigabits/Second', 'Terabits/Second',
                  'Count/Second', None]}}

    def __init__(self, name, json_snippet, stack):
        super(CloudWatchAlarm, self).__init__(name, json_snippet, stack)
        self.instance_id = ''

    def validate(self):
        '''
        Validate the Properties
        '''
        return Resource.validate(self)

    def create(self):
        if self.state in [self.CREATE_IN_PROGRESS, self.CREATE_COMPLETE]:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        Resource.create(self)

        wr_values = {
            'name': self.name,
            'rule': self.parsed_template()['Properties'],
            'state': 'NORMAL',
            'stack_name': self.stack.name
        }

        wr = db_api.watch_rule_create(self.stack.context, wr_values)
        self.instance_id = wr.id

        self.state_set(self.CREATE_COMPLETE)

    def delete(self):
        if self.state in [self.DELETE_IN_PROGRESS, self.DELETE_COMPLETE]:
            return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        try:
            db_api.watch_rule_delete(self.stack.context, self.name)
        except Exception as ex:
            pass

        self.state_set(self.DELETE_COMPLETE)

    def FnGetRefId(self):
        return unicode(self.name)

    def strict_dependency(self):
        return False
