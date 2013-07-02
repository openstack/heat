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

from heat.common import exception
from heat.engine import resource
from heat.engine import scheduler

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
    attributes_schema = {
        "InstanceList": ("A comma-delimited list of server ip addresses. "
                         "(Heat extension)")
    }

    def handle_create(self):
        return self.resize(int(self.properties['Size']), raise_on_error=True)

    def check_create_complete(self, creator):
        if creator is None:
            return True

        return creator.step()

    def _wait_for_activation(self, creator):
        if creator is not None:
            creator.run_to_completion()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
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
                    creator = self.resize(int(self.properties['Size']),
                                          raise_on_error=True)
                    self._wait_for_activation(creator)

    def _make_instance(self, name):

        Instance = resource.get_class('AWS::EC2::Instance',
                                      resource_name=name,
                                      environment=self.stack.env)

        class GroupedInstance(Instance):
            '''
            Subclass instance.Instance to supress event transitions, since the
            scaling-group instances are not "real" resources, ie defined in the
            template, which causes problems for event handling since we can't
            look up the resources via parser.Stack
            '''
            def state_set(self, action, status, reason="state changed"):
                self._store_or_update(action, status, reason)

        conf = self.properties['LaunchConfigurationName']
        instance_definition = self.stack.t['Resources'][conf]
        return GroupedInstance(name, instance_definition, self.stack)

    def _instances(self):
        '''
        Convert the stored instance list into a list of GroupedInstance objects
        '''
        gi_list = []
        if self.resource_id is not None:
            inst_list = self.resource_id.split(',')
            for i in inst_list:
                gi_list.append(self._make_instance(i))
        return gi_list

    def handle_delete(self):
        for inst in self._instances():
            logger.debug('handle_delete %s' % inst.name)
            inst.destroy()

    def handle_suspend(self):
        cookie_list = []
        for inst in self._instances():
            logger.debug('handle_suspend %s' % inst.name)
            inst_cookie = inst.handle_suspend()
            cookie_list.append((inst, inst_cookie))
        return cookie_list

    def check_suspend_complete(self, cookie_list):
        for inst, inst_cookie in cookie_list:
            if not inst.check_suspend_complete(inst_cookie):
                return False
        return True

    def handle_resume(self):
        cookie_list = []
        for inst in self._instances():
            logger.debug('handle_resume %s' % inst.name)
            inst_cookie = inst.handle_resume()
            cookie_list.append((inst, inst_cookie))
        return cookie_list

    def check_resume_complete(self, cookie_list):
        for inst, inst_cookie in cookie_list:
            if not inst.check_resume_complete(inst_cookie):
                return False
        return True

    @scheduler.wrappertask
    def _scale(self, instance_task, indices):
        group = scheduler.PollingTaskGroup.from_task_with_args(instance_task,
                                                               indices)
        yield group()

        # When all instance tasks are complete, reload the LB config
        self._lb_reload()

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

        @scheduler.wrappertask
        def create_instance(index):
            name = '%s-%d' % (self.name, index)
            inst = self._make_instance(name)

            logger.debug('Creating %s instance %d' % (str(self), index))

            try:
                yield inst.create()
            except exception.ResourceFailure as ex:
                if raise_on_error:
                    raise
                # Handle instance creation failure locally by destroying the
                # failed instance to avoid orphaned instances costing user
                # extra memory
                logger.warn('Creating %s instance %d failed %s, destroying'
                            % (str(self), index, str(ex)))
                inst.destroy()
            else:
                inst_list.append(name)
                self.resource_id_set(','.join(inst_list))

        if new_capacity > capacity:
            # grow
            creator = scheduler.TaskRunner(self._scale,
                                           create_instance,
                                           xrange(capacity, new_capacity))
            creator.start()
            return creator
        else:
            # shrink (kill largest numbered first)
            del_list = inst_list[new_capacity:]
            for victim in reversed(del_list):
                inst = self._make_instance(victim)
                inst.destroy()
                inst_list.remove(victim)
                # If we shrink to zero, set resource_id back to None
                self.resource_id_set(','.join(inst_list) or None)

            self._lb_reload()

    def _lb_reload(self):
        '''
        Notify the LoadBalancer to reload it's config to include
        the changes in instances we have just made.

        This must be done after activation (instance in ACTIVE state),
        otherwise the instances' IP addresses may not be available.
        '''
        if self.properties['LoadBalancerNames']:
            inst_list = []
            if self.resource_id is not None:
                inst_list = sorted(self.resource_id.split(','))
            # convert the list of instance names into a list of instance id's
            id_list = []
            for inst_name in inst_list:
                inst = self._make_instance(inst_name)
                id_list.append(inst.FnGetRefId())

            for lb in self.properties['LoadBalancerNames']:
                self.stack[lb].json_snippet['Properties']['Instances'] = \
                    inst_list
                resolved_snippet = self.stack.resolve_static_data(
                    self.stack[lb].json_snippet)
                self.stack[lb].update(resolved_snippet)

    def FnGetRefId(self):
        return unicode(self.name)

    def _resolve_attribute(self, name):
        '''
        heat extension: "InstanceList" returns comma delimited list of server
        ip addresses.
        '''
        if name == 'InstanceList':
            if self.resource_id is None:
                return None
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

    def handle_create(self):

        if self.properties['DesiredCapacity']:
            num_to_create = int(self.properties['DesiredCapacity'])
        else:
            num_to_create = int(self.properties['MinSize'])

        return self._adjust(num_to_create)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
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
                creator = self._adjust(new_capacity)
                self._wait_for_activation(creator)

    def adjust(self, adjustment, adjustment_type='ChangeInCapacity'):
        creator = self._adjust(adjustment, adjustment_type, False)
        self._wait_for_activation(creator)

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

        result = self.resize(new_capacity, raise_on_error=raise_on_error)

        self._cooldown_timestamp("%s : %s" % (adjustment_type, adjustment))

        return result

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
        'SecurityGroups': {'Type': 'List'},
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

    update_allowed_keys = ('Properties',)
    update_allowed_properties = ('ScalingAdjustment', 'AdjustmentType',
                                 'Cooldown',)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        # If Properties has changed, update self.properties, so we
        # get the new values during any subsequent adjustment
        if prop_diff:
            self.properties = Properties(self.properties_schema,
                                         json_snippet.get('Properties', {}),
                                         self.stack.resolve_runtime_data,
                                         self.name)

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
