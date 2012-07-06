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
from heat.engine import instance
from heat.engine.resources import Resource

logger = logging.getLogger('heat.engine.autoscaling')


class AutoScalingGroup(Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}
    properties_schema = {
        'AvailabilityZones': {'Required': True,
                              'Type': 'List'},
        'LaunchConfigurationName': {'Required': True,
                                    'Type': 'String'},
        'MaxSize': {'Required': True,
                    'Type': 'String'},
        'MinSize': {'Required': True,
                    'Type': 'String'},
        'Cooldown': {'Type': 'String'},
        'DesiredCapacity': {'Type': 'String',
                            'Implemented': False},
        'HealthCheckGracePeriod': {'Type': 'Integer',
                                   'Implemented': False},
        'HealthCheckType': {'Type': 'String',
                            'AllowedValues': ['EC2', 'ELB'],
                            'Implemented': False},
        'LoadBalancerNames': {'Type': 'List'},
        'Tags': {'Type': 'List',
                 'Schema': tags_schema}
    }

    def __init__(self, name, json_snippet, stack):
        super(AutoScalingGroup, self).__init__(name, json_snippet, stack)
        # instance_id is a list of resources

    def handle_create(self):
        self.adjust(int(self.properties['MinSize']),
                    adjustment_type='ExactCapacity')

    def handle_delete(self):
        if self.instance_id is not None:
            conf = self.properties['LaunchConfigurationName']
            inst_list = self.instance_id.split(',')
            logger.debug('handle_delete %s' % str(inst_list))
            for victim in inst_list:
                logger.debug('handle_delete %s' % victim)
                inst = instance.Instance(victim,
                                         self.stack.t['Resources'][conf],
                                         self.stack)
                inst.destroy()

    def adjust(self, adjustment, adjustment_type='ChangeInCapacity'):
        self.calculate_properties()

        inst_list = []
        if self.instance_id is not None:
            inst_list = sorted(self.instance_id.split(','))

        capacity = len(inst_list)
        if adjustment_type == 'ChangeInCapacity':
            new_capacity = capacity + adjustment
        elif adjustment_type == 'ExactCapacity':
            new_capacity = adjustment
        else:
            # PercentChangeInCapacity
            new_capacity = capacity + (capacity * adjustment / 100)

        if new_capacity > int(self.properties['MaxSize']):
            logger.warn('can not exceed %s' % self.properties['MaxSize'])
            return
        if new_capacity < int(self.properties['MinSize']):
            logger.warn('can not be less than %s' % self.properties['MinSize'])
            return

        if new_capacity == capacity:
            return

        conf = self.properties['LaunchConfigurationName']
        if new_capacity > capacity:
            # grow
            for x in range(capacity, new_capacity):
                inst = instance.Instance('%s-%d' % (self.name, x),
                                         self.stack.t['Resources'][conf],
                                         self.stack)
                inst_list.append('%s-%d' % (self.name, x))
                self.instance_id_set(','.join(inst_list))
                inst.create()
        else:
            # shrink (kill largest numbered first)
            del_list = inst_list[:]
            for victim in reversed(del_list):
                inst = instance.Instance(victim,
                                         self.stack.t['Resources'][conf],
                                         self.stack)
                inst.destroy()
                inst_list.remove(victim)
                self.instance_id_set(','.join(inst_list))


class LaunchConfiguration(Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}
    properties_schema = {
        'ImageId': {'Type': 'String',
                    'Required': True},
        'InstanceType': {'Type': 'String',
                         'Required': True},
        'KeyName': {'Type': 'String'},
        'UserData': {'Type': 'String'},
        'SecurityGroups': {'Type': 'String'},
        'KernelId': {'Type': 'String',
                     'Implemented': False},
        'RamDiskId': {'Type': 'String',
                      'Implemented': False},
        'BlockDeviceMappings': {'Type': 'String',
                                'Implemented': False},
        'NovaSchedulerHints': {'Type': 'List',
                               'Schema': tags_schema},
    }

    def __init__(self, name, json_snippet, stack):
        super(LaunchConfiguration, self).__init__(name, json_snippet, stack)
