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

from heat.common import exception
from heat.engine import resource

from heat.openstack.common import log as logging
from heat.openstack.common import timeutils
from heat.engine.properties import Properties

logger = logging.getLogger(__name__)


class CooldownMixin(object):
    '''
    Utility class to encapsulate Cooldown related logic which is shared
    between AutoScalingGroup and ScalingPolicy
    '''
    def _cooldown_inprogress(self):
        inprogress = False
        try:
            # Negative values don't make sense, so they are clamped to zero
            cooldown = max(0, int(self.properties['Cooldown']))
        except TypeError:
            # If not specified, it will be None, same as cooldown == 0
            cooldown = 0

        metadata = self.metadata
        if metadata and cooldown != 0:
            last_adjust = metadata.keys()[0]
            if not timeutils.is_older_than(last_adjust, cooldown):
                inprogress = True
        return inprogress

    def _cooldown_timestamp(self, reason):
        # Save resource metadata with a timestamp and reason
        # If we wanted to implement the AutoScaling API like AWS does,
        # we could maintain event history here, but since we only need
        # the latest event for cooldown, just store that for now
        metadata = {timeutils.strtime(): reason}
        self.metadata = metadata


class InstanceGroup(resource.Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}
    properties_schema = {
        'AvailabilityZones': {'Required': True,
                              'Type': 'List'},
        'LaunchConfigurationName': {'Required': True,
                                    'Type': 'String'},
        'Size': {'Required': True,
                 'Type': 'Number'},
        'LoadBalancerNames': {'Type': 'List'},
        'Tags': {'Type': 'List',
                 'Schema': {'Type': 'Map',
                            'Schema': tags_schema}}
    }
    update_allowed_keys = ('Properties',)
    update_allowed_properties = ('Size',)

    def __init__(self, name, json_snippet, stack):
        super(InstanceGroup, self).__init__(name, json_snippet, stack)
        self._activating = []

    def handle_create(self):
        self.resize(int(self.properties['Size']), raise_on_error=True)

    def check_active(self):
        active = all(i.check_active(override=False) for i in self._activating)
        if active:
            self._activating = []
        return active

    def _wait_for_activation(self):
        while not self.check_active():
            eventlet.sleep(1)

    def handle_update(self, json_snippet):
        try:
            tmpl_diff = self.update_template_diff(json_snippet)
        except NotImplementedError:
            logger.error("Could not update %s, invalid key" % self.name)
            return self.UPDATE_REPLACE

        try:
            prop_diff = self.update_template_diff_properties(json_snippet)
        except NotImplementedError:
            logger.error("Could not update %s, invalid Property" % self.name)
            return self.UPDATE_REPLACE

        # If Properties has changed, update self.properties, so we
        # get the new values during any subsequent adjustment
        if prop_diff:
            self.properties = Properties(self.properties_schema,
                                         json_snippet.get('Properties', {}),
                                         self.stack.resolve_runtime_data,
                                         self.name)

            # Get the current capacity, we may need to adjust if
            # Size has changed
            if 'Size' in prop_diff:
                inst_list = []
                if self.resource_id is not None:
                    inst_list = sorted(self.resource_id.split(','))

                if len(inst_list) != int(self.properties['Size']):
                    self.resize(int(self.properties['Size']),
                                raise_on_error=True)
                    self._wait_for_activation()

        return self.UPDATE_COMPLETE

    def _make_instance(self, name):

        Instance = resource.get_class('AWS::EC2::Instance')

        class GroupedInstance(Instance):
            '''
            Subclass instance.Instance to supress event transitions, since the
            scaling-group instances are not "real" resources, ie defined in the
            template, which causes problems for event handling since we can't
            look up the resources via parser.Stack
            '''
            def state_set(self, new_state, reason="state changed"):
                self._store_or_update(new_state, reason)

            def check_active(self, override=True):
                '''
                By default, report that the instance is active so that we
                won't wait for it in create().
                '''
                if override:
                    return True
                return super(GroupedInstance, self).check_active()

        conf = self.properties['LaunchConfigurationName']
        instance_definition = self.stack.t['Resources'][conf]
        return GroupedInstance(name, instance_definition, self.stack)

    def handle_delete(self):
        if self.resource_id is not None:
            inst_list = self.resource_id.split(',')
            logger.debug('handle_delete %s' % str(inst_list))
            for victim in inst_list:
                logger.debug('handle_delete %s' % victim)
                inst = self._make_instance(victim)
                error_str = inst.destroy()
                if error_str is not None:
                    # try suck out the grouped resouces failure reason
                    # and re-raise
                    raise exception.NestedResourceFailure(message=error_str)

    def resize(self, new_capacity, raise_on_error=False):
        inst_list = []
        if self.resource_id is not None:
            inst_list = sorted(self.resource_id.split(','))

        capacity = len(inst_list)
        if new_capacity == capacity:
            logger.debug('no change in capacity %d' % capacity)
            return
        logger.debug('adjusting capacity from %d to %d' % (capacity,
                                                           new_capacity))

        if new_capacity > capacity:
            # grow
            for x in range(capacity, new_capacity):
                name = '%s-%d' % (self.name, x)
                inst = self._make_instance(name)
                inst_list.append(name)
                self._activating.append(inst)
                self.resource_id_set(','.join(inst_list))
                logger.info('creating inst')
                error_str = inst.create()
                if raise_on_error and error_str is not None:
                    # try suck out the grouped resouces failure reason
                    # and re-raise
                    raise exception.NestedResourceFailure(message=error_str)
        else:
            # shrink (kill largest numbered first)
            del_list = inst_list[new_capacity:]
            for victim in reversed(del_list):
                inst = self._make_instance(victim)
                inst.destroy()
                inst_list.remove(victim)
                self.resource_id_set(','.join(inst_list))

        # notify the LoadBalancer to reload it's config to include
        # the changes in instances we have just made.
        if self.properties['LoadBalancerNames']:
            # convert the list of instance names into a list of instance id's
            id_list = []
            for inst_name in inst_list:
                inst = self._make_instance(inst_name)
                id_list.append(inst.FnGetRefId())

            for lb in self.properties['LoadBalancerNames']:
                self.stack[lb].reload(id_list)

    def FnGetRefId(self):
        return unicode(self.name)

    def FnGetAtt(self, key):
        '''
        heat extension: "InstanceList" returns comma delimited list of server
        ip addresses.
        '''
        if key == 'InstanceList':
            if self.resource_id is None:
                return ''
            name_list = sorted(self.resource_id.split(','))
            inst_list = []
            for name in name_list:
                inst = self._make_instance(name)
                inst_list.append(inst.FnGetAtt('PublicIp'))
            return unicode(','.join(inst_list))


class AutoScalingGroup(InstanceGroup, CooldownMixin):
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
        'DesiredCapacity': {'Type': 'Number'},
        'HealthCheckGracePeriod': {'Type': 'Integer',
                                   'Implemented': False},
        'HealthCheckType': {'Type': 'String',
                            'AllowedValues': ['EC2', 'ELB'],
                            'Implemented': False},
        'LoadBalancerNames': {'Type': 'List'},
        'Tags': {'Type': 'List', 'Schema': {'Type': 'Map',
                                            'Schema': tags_schema}}
    }

    # template keys and properties supported for handle_update,
    # note trailing comma is required for a single item to get a tuple
    update_allowed_keys = ('Properties',)
    update_allowed_properties = ('MaxSize', 'MinSize',
                                 'Cooldown', 'DesiredCapacity',)

    def __init__(self, name, json_snippet, stack):
        super(AutoScalingGroup, self).__init__(name, json_snippet, stack)
        # resource_id is a list of resources

    def handle_create(self):

        if self.properties['DesiredCapacity']:
            num_to_create = int(self.properties['DesiredCapacity'])
        else:
            num_to_create = int(self.properties['MinSize'])

        self._adjust(num_to_create)

    def handle_update(self, json_snippet):
        try:
            tmpl_diff = self.update_template_diff(json_snippet)
        except NotImplementedError:
            logger.error("Could not update %s, invalid key" % self.name)
            return self.UPDATE_REPLACE

        try:
            prop_diff = self.update_template_diff_properties(json_snippet)
        except NotImplementedError:
            logger.error("Could not update %s, invalid Property" % self.name)
            return self.UPDATE_REPLACE

        # If Properties has changed, update self.properties, so we
        # get the new values during any subsequent adjustment
        if prop_diff:
            self.properties = Properties(self.properties_schema,
                                         json_snippet.get('Properties', {}),
                                         self.stack.resolve_runtime_data,
                                         self.name)

            # Get the current capacity, we may need to adjust if
            # MinSize or MaxSize has changed
            inst_list = []
            if self.resource_id is not None:
                inst_list = sorted(self.resource_id.split(','))

            capacity = len(inst_list)

            # Figure out if an adjustment is required
            new_capacity = None
            if 'MinSize' in prop_diff:
                if capacity < int(self.properties['MinSize']):
                    new_capacity = int(self.properties['MinSize'])
            if 'MaxSize' in prop_diff:
                if capacity > int(self.properties['MaxSize']):
                    new_capacity = int(self.properties['MaxSize'])
            if 'DesiredCapacity' in prop_diff:
                    if self.properties['DesiredCapacity']:
                        new_capacity = int(self.properties['DesiredCapacity'])

            if new_capacity is not None:
                self._adjust(new_capacity)
                self._wait_for_activation()

        return self.UPDATE_COMPLETE

    def adjust(self, adjustment, adjustment_type='ChangeInCapacity'):
        self._adjust(adjustment, adjustment_type, False)
        self._wait_for_activation()

    def _adjust(self, adjustment, adjustment_type='ExactCapacity',
                raise_on_error=True):

        if self._cooldown_inprogress():
            logger.info("%s NOT performing scaling adjustment, cooldown %s" %
                        (self.name, self.properties['Cooldown']))
            return

        inst_list = []
        if self.resource_id is not None:
            inst_list = sorted(self.resource_id.split(','))

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
            logger.debug('no change in capacity %d' % capacity)
            return

        self.resize(new_capacity, raise_on_error=raise_on_error)

        self._cooldown_timestamp("%s : %s" % (adjustment_type, adjustment))

    def FnGetRefId(self):
        return unicode(self.name)


class LaunchConfiguration(resource.Resource):
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
                               'Schema': {'Type': 'Map',
                                          'Schema': tags_schema}},
    }

    def __init__(self, name, json_snippet, stack):
        super(LaunchConfiguration, self).__init__(name, json_snippet, stack)


class ScalingPolicy(resource.Resource, CooldownMixin):
    properties_schema = {
        'AutoScalingGroupName': {'Type': 'String',
                                 'Required': True},
        'ScalingAdjustment': {'Type': 'Number',
                              'Required': True},
        'AdjustmentType': {'Type': 'String',
                           'AllowedValues': ['ChangeInCapacity',
                                             'ExactCapacity',
                                             'PercentChangeInCapacity'],
                           'Required': True},
        'Cooldown': {'Type': 'Number'},
    }

    def __init__(self, name, json_snippet, stack):
        super(ScalingPolicy, self).__init__(name, json_snippet, stack)

    def alarm(self):
        if self._cooldown_inprogress():
            logger.info("%s NOT performing scaling action, cooldown %s" %
                        (self.name, self.properties['Cooldown']))
            return

        group = self.stack.resources[self.properties['AutoScalingGroupName']]

        logger.info('%s Alarm, adjusting Group %s by %s' %
                    (self.name, group.name,
                     self.properties['ScalingAdjustment']))
        group.adjust(int(self.properties['ScalingAdjustment']),
                     self.properties['AdjustmentType'])

        self._cooldown_timestamp("%s : %s" %
                                 (self.properties['AdjustmentType'],
                                  self.properties['ScalingAdjustment']))


def resource_mapping():
    return {
        'AWS::AutoScaling::LaunchConfiguration': LaunchConfiguration,
        'AWS::AutoScaling::AutoScalingGroup': AutoScalingGroup,
        'AWS::AutoScaling::ScalingPolicy': ScalingPolicy,
        'OS::Heat::InstanceGroup': InstanceGroup,
    }
