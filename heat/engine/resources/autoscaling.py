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

import copy
import math

from heat.engine import resource
from heat.engine import signal_responder

from heat.common import short_id
from heat.common import exception
from heat.common import timeutils as iso8601utils
from heat.openstack.common import log as logging
from heat.openstack.common import timeutils
from heat.engine.properties import Properties
from heat.engine import constraints
from heat.engine import properties
from heat.engine import scheduler
from heat.engine import stack_resource

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


class InstanceGroup(stack_resource.StackResource):

    PROPERTIES = (
        AVAILABILITY_ZONES, LAUNCH_CONFIGURATION_NAME, SIZE,
        LOAD_BALANCER_NAMES, TAGS,
    ) = (
        'AvailabilityZones', 'LaunchConfigurationName', 'Size',
        'LoadBalancerNames', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        AVAILABILITY_ZONES: properties.Schema(
            properties.Schema.LIST,
            _('Not Implemented.'),
            required=True
        ),
        LAUNCH_CONFIGURATION_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of LaunchConfiguration resource.'),
            required=True,
            update_allowed=True
        ),
        SIZE: properties.Schema(
            properties.Schema.NUMBER,
            _('Desired number of instances.'),
            required=True,
            update_allowed=True
        ),
        LOAD_BALANCER_NAMES: properties.Schema(
            properties.Schema.LIST,
            _('List of LoadBalancer resources.')
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('Tags to attach to this group.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    TAG_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    TAG_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
            )
        ),
    }

    update_allowed_keys = ('Properties', 'UpdatePolicy',)

    attributes_schema = {
        "InstanceList": _("A comma-delimited list of server ip addresses. "
                          "(Heat extension).")
    }
    rolling_update_schema = {
        'MinInstancesInService': properties.Schema(properties.Schema.NUMBER,
                                                   default=0),
        'MaxBatchSize': properties.Schema(properties.Schema.NUMBER, default=1),
        'PauseTime': properties.Schema(properties.Schema.STRING,
                                       default='PT0S')
    }
    update_policy_schema = {
        'RollingUpdate': properties.Schema(properties.Schema.MAP,
                                           schema=rolling_update_schema)
    }

    def __init__(self, name, json_snippet, stack):
        """
        UpdatePolicy is currently only specific to InstanceGroup and
        AutoScalingGroup. Therefore, init is overridden to parse for the
        UpdatePolicy.
        """
        super(InstanceGroup, self).__init__(name, json_snippet, stack)
        self.update_policy = Properties(self.update_policy_schema,
                                        self.t.get('UpdatePolicy', {}),
                                        parent_name=self.name)

    def validate(self):
        """
        Add validation for update_policy
        """
        super(InstanceGroup, self).validate()

        if self.update_policy:
            self.update_policy.validate()
            policy_name = self.update_policy_schema.keys()[0]
            if self.update_policy[policy_name]:
                pause_time = self.update_policy[policy_name]['PauseTime']
                if iso8601utils.parse_isoduration(pause_time) > 3600:
                    raise ValueError('Maximum PauseTime is 1 hour.')

    def get_instance_names(self):
        """Get a list of resource names of the instances in this InstanceGroup.

        Failed resources will be ignored.
        """
        return [r.name for r in self.get_instances()]

    def get_instances(self):
        """Get a list of all the instance resources managed by this group.

        Sort the list of instances first by created_time then by name.
        """
        resources = []
        if self.nested():
            resources = [resource for resource in self.nested().itervalues()
                         if resource.status != resource.FAILED]
        return sorted(resources, key=lambda r: (r.created_time, r.name))

    def handle_create(self):
        """Create a nested stack and add the initial resources to it."""
        num_instances = int(self.properties[self.SIZE])
        initial_template = self._create_template(num_instances)
        return self.create_with_template(initial_template, {})

    def check_create_complete(self, task):
        """
        When stack creation is done, update the load balancer.

        If any instances failed to be created, delete them.
        """
        done = super(InstanceGroup, self).check_create_complete(task)
        if done:
            self._lb_reload()
        return done

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """
        If Properties has changed, update self.properties, so we
        get the new values during any subsequent adjustment.
        """
        if tmpl_diff:
            # parse update policy
            if 'UpdatePolicy' in tmpl_diff:
                self.update_policy = Properties(
                    self.update_policy_schema,
                    json_snippet.get('UpdatePolicy', {}),
                    parent_name=self.name)

        if prop_diff:
            self.properties = Properties(self.properties_schema,
                                         json_snippet.get('Properties', {}),
                                         self.stack.resolve_runtime_data,
                                         self.name)

            # Replace instances first if launch configuration has changed
            if (self.update_policy['RollingUpdate'] and
                    self.LAUNCH_CONFIGURATION_NAME in prop_diff):
                policy = self.update_policy['RollingUpdate']
                self._replace(int(policy['MinInstancesInService']),
                              int(policy['MaxBatchSize']),
                              policy['PauseTime'])

            # Get the current capacity, we may need to adjust if
            # Size has changed
            if self.SIZE in prop_diff:
                inst_list = self.get_instances()
                if len(inst_list) != int(self.properties[self.SIZE]):
                    self.resize(int(self.properties[self.SIZE]))

    def _tags(self):
        """
        Make sure that we add a tag that Ceilometer can pick up.
        These need to be prepended with 'metering.'.
        """
        tags = self.properties.get(self.TAGS) or []
        for t in tags:
            if t[self.TAG_KEY].startswith('metering.'):
                # the user has added one, don't add another.
                return tags
        return tags + [{self.TAG_KEY: 'metering.groupname',
                        self.TAG_VALUE: self.FnGetRefId()}]

    def handle_delete(self):
        return self.delete_nested()

    def _get_instance_definition(self):
        conf_name = self.properties[self.LAUNCH_CONFIGURATION_NAME]
        conf = self.stack.resource_by_refid(conf_name)
        instance_definition = copy.deepcopy(conf.t)
        instance_definition['Type'] = 'AWS::EC2::Instance'
        instance_definition['Properties']['Tags'] = self._tags()
        if self.properties.get('VPCZoneIdentifier'):
            instance_definition['Properties']['SubnetId'] = \
                self.properties['VPCZoneIdentifier'][0]
        # resolve references within the context of this stack.
        return self.stack.resolve_runtime_data(instance_definition)

    def _create_template(self, num_instances, num_replace=0):
        """
        Create the template for the nested stack of existing and new instances

        For rolling update, if launch configuration is different, the
        instance definition should come from the existing instance instead
        of using the new launch configuration.
        """
        instances = self.get_instances()[-num_instances:]
        instance_definition = self._get_instance_definition()
        num_create = num_instances - len(instances)
        num_replace -= num_create

        def instance_templates(num_replace):
            for i in range(num_instances):
                if i < len(instances):
                    inst = instances[i]
                    if inst.t != instance_definition and num_replace > 0:
                        num_replace -= 1
                        yield inst.name, instance_definition
                    else:
                        yield inst.name, inst.t
                else:
                    yield short_id.generate_id(), instance_definition

        return {"Resources": dict(instance_templates(num_replace))}

    def _replace(self, min_in_service, batch_size, pause_time):
        """
        Replace the instances in the group using updated launch configuration
        """
        def changing_instances(tmpl):
            instances = self.get_instances()
            current = set((i.name, str(i.t)) for i in instances)
            updated = set((k, str(v)) for k, v in tmpl['Resources'].items())
            # includes instances to be updated and deleted
            affected = set(k for k, v in current ^ updated)
            return set(i.FnGetRefId() for i in instances if i.name in affected)

        def pause_between_batch():
            while True:
                try:
                    yield
                except scheduler.Timeout:
                    return

        capacity = len(self.nested()) if self.nested() else 0
        efft_bat_sz = min(batch_size, capacity)
        efft_min_sz = min(min_in_service, capacity)
        pause_sec = iso8601utils.parse_isoduration(pause_time)

        batch_cnt = (capacity + efft_bat_sz - 1) // efft_bat_sz
        if pause_sec * (batch_cnt - 1) >= self.stack.timeout_mins * 60:
            raise ValueError('The current UpdatePolicy will result '
                             'in stack update timeout.')

        # effective capacity includes temporary capacity added to accomodate
        # the minimum number of instances in service during update
        efft_capacity = max(capacity - efft_bat_sz, efft_min_sz) + efft_bat_sz

        try:
            remainder = capacity
            while remainder > 0 or efft_capacity > capacity:
                if capacity - remainder >= efft_min_sz:
                    efft_capacity = capacity
                template = self._create_template(efft_capacity, efft_bat_sz)
                self._lb_reload(exclude=changing_instances(template))
                updater = self.update_with_template(template, {})
                updater.run_to_completion()
                self.check_update_complete(updater)
                remainder -= efft_bat_sz
                if remainder > 0 and pause_sec > 0:
                    self._lb_reload()
                    waiter = scheduler.TaskRunner(pause_between_batch)
                    waiter(timeout=pause_sec)
        finally:
            self._lb_reload()

    def resize(self, new_capacity):
        """
        Resize the instance group to the new capacity.

        When shrinking, the oldest instances will be removed.
        """
        new_template = self._create_template(new_capacity)
        try:
            updater = self.update_with_template(new_template, {})
            updater.run_to_completion()
            self.check_update_complete(updater)
        finally:
            # Reload the LB in any case, so it's only pointing at healthy
            # nodes.
            self._lb_reload()

    def _lb_reload(self, exclude=[]):
        '''
        Notify the LoadBalancer to reload its config to include
        the changes in instances we have just made.

        This must be done after activation (instance in ACTIVE state),
        otherwise the instances' IP addresses may not be available.
        '''
        if self.properties[self.LOAD_BALANCER_NAMES]:
            id_list = [inst.FnGetRefId() for inst in self.get_instances()
                       if inst.FnGetRefId() not in exclude]
            for lb in self.properties[self.LOAD_BALANCER_NAMES]:
                lb_resource = self.stack[lb]
                if 'Instances' in lb_resource.properties_schema:
                    lb_resource.json_snippet['Properties']['Instances'] = (
                        id_list)
                elif 'members' in lb_resource.properties_schema:
                    lb_resource.json_snippet['Properties']['members'] = (
                        id_list)
                else:
                    raise exception.Error(
                        "Unsupported resource '%s' in LoadBalancerNames" %
                        (lb,))
                resolved_snippet = self.stack.resolve_static_data(
                    lb_resource.json_snippet)
                scheduler.TaskRunner(lb_resource.update, resolved_snippet)()

    def FnGetRefId(self):
        return self.physical_resource_name()

    def _resolve_attribute(self, name):
        '''
        heat extension: "InstanceList" returns comma delimited list of server
        ip addresses.
        '''
        if name == 'InstanceList':
            return u','.join(inst.FnGetAtt('PublicIp')
                             for inst in self.get_instances()) or None


class AutoScalingGroup(InstanceGroup, CooldownMixin):

    PROPERTIES = (
        AVAILABILITY_ZONES, LAUNCH_CONFIGURATION_NAME, MAX_SIZE, MIN_SIZE,
        COOLDOWN, DESIRED_CAPACITY, HEALTH_CHECK_GRACE_PERIOD,
        HEALTH_CHECK_TYPE, LOAD_BALANCER_NAMES, VPCZONE_IDENTIFIER, TAGS,
    ) = (
        'AvailabilityZones', 'LaunchConfigurationName', 'MaxSize', 'MinSize',
        'Cooldown', 'DesiredCapacity', 'HealthCheckGracePeriod',
        'HealthCheckType', 'LoadBalancerNames', 'VPCZoneIdentifier', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        AVAILABILITY_ZONES: properties.Schema(
            properties.Schema.LIST,
            _('Not Implemented.'),
            required=True
        ),
        LAUNCH_CONFIGURATION_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of LaunchConfiguration resource.'),
            required=True,
            update_allowed=True
        ),
        MAX_SIZE: properties.Schema(
            properties.Schema.STRING,
            _('Maximum number of instances in the group.'),
            required=True,
            update_allowed=True
        ),
        MIN_SIZE: properties.Schema(
            properties.Schema.STRING,
            _('Minimum number of instances in the group.'),
            required=True,
            update_allowed=True
        ),
        COOLDOWN: properties.Schema(
            properties.Schema.STRING,
            _('Cooldown period, in seconds.'),
            update_allowed=True
        ),
        DESIRED_CAPACITY: properties.Schema(
            properties.Schema.NUMBER,
            _('Desired initial number of instances.'),
            update_allowed=True
        ),
        HEALTH_CHECK_GRACE_PERIOD: properties.Schema(
            properties.Schema.INTEGER,
            _('Not Implemented.'),
            implemented=False
        ),
        HEALTH_CHECK_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            constraints=[
                constraints.AllowedValues(['EC2', 'ELB']),
            ],
            implemented=False
        ),
        LOAD_BALANCER_NAMES: properties.Schema(
            properties.Schema.LIST,
            _('List of LoadBalancer resources.')
        ),
        VPCZONE_IDENTIFIER: properties.Schema(
            properties.Schema.LIST,
            _('List of VPC subnet identifiers.')
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('Tags to attach to this group.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    TAG_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    TAG_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
            )
        ),
    }

    rolling_update_schema = {
        'MinInstancesInService': properties.Schema(properties.Schema.NUMBER,
                                                   default=0),
        'MaxBatchSize': properties.Schema(properties.Schema.NUMBER, default=1),
        'PauseTime': properties.Schema(properties.Schema.STRING,
                                       default='PT0S')
    }
    update_policy_schema = {
        'AutoScalingRollingUpdate': properties.Schema(properties.Schema.MAP,
                                                      schema=
                                                      rolling_update_schema)
    }

    update_allowed_keys = ('Properties', 'UpdatePolicy')

    def handle_create(self):
        if self.properties[self.DESIRED_CAPACITY]:
            num_to_create = int(self.properties[self.DESIRED_CAPACITY])
        else:
            num_to_create = int(self.properties[self.MIN_SIZE])
        initial_template = self._create_template(num_to_create)
        return self.create_with_template(initial_template, {})

    def check_create_complete(self, task):
        """Invoke the cooldown after creation succeeds."""
        done = super(AutoScalingGroup, self).check_create_complete(task)
        if done:
            self._cooldown_timestamp(
                "%s : %s" % ('ExactCapacity', len(self.get_instances())))
        return done

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """
        If Properties has changed, update self.properties, so we get the new
        values during any subsequent adjustment.
        """
        if tmpl_diff:
            # parse update policy
            if 'UpdatePolicy' in tmpl_diff:
                self.update_policy = Properties(
                    self.update_policy_schema,
                    json_snippet.get('UpdatePolicy', {}),
                    parent_name=self.name)

        if prop_diff:
            self.properties = Properties(self.properties_schema,
                                         json_snippet.get('Properties', {}),
                                         self.stack.resolve_runtime_data,
                                         self.name)

            # Replace instances first if launch configuration has changed
            if (self.update_policy['AutoScalingRollingUpdate'] and
                    'LaunchConfigurationName' in prop_diff):
                policy = self.update_policy['AutoScalingRollingUpdate']
                self._replace(int(policy['MinInstancesInService']),
                              int(policy['MaxBatchSize']),
                              policy['PauseTime'])

            # Get the current capacity, we may need to adjust if
            # MinSize or MaxSize has changed
            capacity = len(self.get_instances())

            # Figure out if an adjustment is required
            new_capacity = None
            if self.MIN_SIZE in prop_diff:
                if capacity < int(self.properties[self.MIN_SIZE]):
                    new_capacity = int(self.properties[self.MIN_SIZE])
            if self.MAX_SIZE in prop_diff:
                if capacity > int(self.properties[self.MAX_SIZE]):
                    new_capacity = int(self.properties[self.MAX_SIZE])
            if self.DESIRED_CAPACITY in prop_diff:
                if self.properties[self.DESIRED_CAPACITY]:
                    new_capacity = int(self.properties[self.DESIRED_CAPACITY])

            if new_capacity is not None:
                self.adjust(new_capacity, adjustment_type='ExactCapacity')

    def adjust(self, adjustment, adjustment_type='ChangeInCapacity'):
        """
        Adjust the size of the scaling group if the cooldown permits.
        """
        if self._cooldown_inprogress():
            logger.info(_("%(name)s NOT performing scaling adjustment, "
                        "cooldown %(cooldown)s") % {
                        'name': self.name,
                        'cooldown': self.properties[self.COOLDOWN]})
            return

        capacity = len(self.get_instances())
        if adjustment_type == 'ChangeInCapacity':
            new_capacity = capacity + adjustment
        elif adjustment_type == 'ExactCapacity':
            new_capacity = adjustment
        else:
            # PercentChangeInCapacity
            delta = capacity * adjustment / 100.0
            if math.fabs(delta) < 1.0:
                rounded = int(math.ceil(delta) if delta > 0.0
                              else math.floor(delta))
            else:
                rounded = int(math.floor(delta) if delta > 0.0
                              else math.ceil(delta))
            new_capacity = capacity + rounded

        upper = int(self.properties[self.MAX_SIZE])
        lower = int(self.properties[self.MIN_SIZE])

        if new_capacity > upper:
            if upper > capacity:
                logger.info(_('truncating growth to %s') % upper)
                new_capacity = upper
            else:
                logger.warn(_('can not exceed %s') % upper)
                return
        if new_capacity < lower:
            if lower < capacity:
                logger.info(_('truncating shrinkage to %s') % lower)
                new_capacity = lower
            else:
                logger.warn(_('can not be less than %s') % lower)
                return

        if new_capacity == capacity:
            logger.debug(_('no change in capacity %d') % capacity)
            return

        result = self.resize(new_capacity)

        self._cooldown_timestamp("%s : %s" % (adjustment_type, adjustment))

        return result

    def _tags(self):
        """Add Identifing Tags to all servers in the group.

        This is so the Dimensions received from cfn-push-stats all include
        the groupname and stack id.
        Note: the group name must match what is returned from FnGetRefId
        """
        autoscaling_tag = [{self.TAG_KEY: 'AutoScalingGroupName',
                            self.TAG_VALUE: self.FnGetRefId()}]
        return super(AutoScalingGroup, self)._tags() + autoscaling_tag

    def validate(self):
        res = super(AutoScalingGroup, self).validate()
        if res:
            return res

        # TODO(pasquier-s): once Neutron is able to assign subnets to
        # availability zones, it will be possible to specify multiple subnets.
        # For now, only one subnet can be specified. The bug #1096017 tracks
        # this issue.
        if self.properties.get(self.VPCZONE_IDENTIFIER) and \
                len(self.properties[self.VPCZONE_IDENTIFIER]) != 1:
            raise exception.NotSupported(feature=_("Anything other than one "
                                         "VPCZoneIdentifier"))


class LaunchConfiguration(resource.Resource):

    PROPERTIES = (
        IMAGE_ID, INSTANCE_TYPE, KEY_NAME, USER_DATA, SECURITY_GROUPS,
        KERNEL_ID, RAM_DISK_ID, BLOCK_DEVICE_MAPPINGS, NOVA_SCHEDULER_HINTS,
    ) = (
        'ImageId', 'InstanceType', 'KeyName', 'UserData', 'SecurityGroups',
        'KernelId', 'RamDiskId', 'BlockDeviceMappings', 'NovaSchedulerHints',
    )

    _NOVA_SCHEDULER_HINT_KEYS = (
        NOVA_SCHEDULER_HINT_KEY, NOVA_SCHEDULER_HINT_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Glance image ID or name.'),
            required=True
        ),
        INSTANCE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Nova instance type (flavor).'),
            required=True
        ),
        KEY_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Optional Nova keypair name.')
        ),
        USER_DATA: properties.Schema(
            properties.Schema.STRING,
            _('User data to pass to instance.')
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('Security group names to assign.')
        ),
        KERNEL_ID: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        RAM_DISK_ID: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        BLOCK_DEVICE_MAPPINGS: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            implemented=False
        ),
        NOVA_SCHEDULER_HINTS: properties.Schema(
            properties.Schema.LIST,
            _('Scheduler hints to pass to Nova (Heat extension).'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NOVA_SCHEDULER_HINT_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    NOVA_SCHEDULER_HINT_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
            )
        ),
    }

    def FnGetRefId(self):
        return unicode(self.physical_resource_name())


class ScalingPolicy(signal_responder.SignalResponder, CooldownMixin):
    PROPERTIES = (
        AUTO_SCALING_GROUP_NAME, SCALING_ADJUSTMENT, ADJUSTMENT_TYPE,
        COOLDOWN,
    ) = (
        'AutoScalingGroupName', 'ScalingAdjustment', 'AdjustmentType',
        'Cooldown',
    )

    properties_schema = {
        AUTO_SCALING_GROUP_NAME: properties.Schema(
            properties.Schema.STRING,
            _('AutoScaling group name to apply policy to.'),
            required=True
        ),
        SCALING_ADJUSTMENT: properties.Schema(
            properties.Schema.NUMBER,
            _('Size of adjustment.'),
            required=True,
            update_allowed=True
        ),
        ADJUSTMENT_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of adjustment (absolute or percentage).'),
            required=True,
            constraints=[
                constraints.AllowedValues(['ChangeInCapacity',
                                           'ExactCapacity',
                                           'PercentChangeInCapacity']),
            ],
            update_allowed=True
        ),
        COOLDOWN: properties.Schema(
            properties.Schema.NUMBER,
            _('Cooldown period, in seconds.'),
            update_allowed=True
        ),
    }

    update_allowed_keys = ('Properties',)

    attributes_schema = {
        "AlarmUrl": _("A signed url to handle the alarm. "
                      "(Heat extension).")
    }

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """
        If Properties has changed, update self.properties, so we get the new
        values during any subsequent adjustment.
        """
        if prop_diff:
            self.properties = Properties(self.properties_schema,
                                         json_snippet.get('Properties', {}),
                                         self.stack.resolve_runtime_data,
                                         self.name)

    def handle_signal(self, details=None):
        # ceilometer sends details like this:
        # {u'alarm_id': ID, u'previous': u'ok', u'current': u'alarm',
        #  u'reason': u'...'})
        # in this policy we currently assume that this gets called
        # only when there is an alarm. But the template writer can
        # put the policy in all the alarm notifiers (nodata, and ok).
        #
        # our watchrule has upper case states so lower() them all.
        if details is None:
            alarm_state = 'alarm'
        else:
            alarm_state = details.get('current',
                                      details.get('state', 'alarm')).lower()

        logger.info(_('%(name)s Alarm, new state %(state)s') % {
                    'name': self.name, 'state': alarm_state})

        if alarm_state != 'alarm':
            return
        if self._cooldown_inprogress():
            logger.info(_("%(name)s NOT performing scaling action, "
                        "cooldown %(cooldown)s") % {
                        'name': self.name,
                        'cooldown': self.properties[self.COOLDOWN]})
            return

        asgn_id = self.properties[self.AUTO_SCALING_GROUP_NAME]
        group = self.stack.resource_by_refid(asgn_id)

        logger.info(_('%(name)s Alarm, adjusting Group %(group)s '
                    'by %(filter)s') % {
                    'name': self.name, 'group': group.name,
                    'filter': self.properties[self.SCALING_ADJUSTMENT]})
        group.adjust(int(self.properties[self.SCALING_ADJUSTMENT]),
                     self.properties[self.ADJUSTMENT_TYPE])

        self._cooldown_timestamp("%s : %s" %
                                 (self.properties[self.ADJUSTMENT_TYPE],
                                  self.properties[self.SCALING_ADJUSTMENT]))

    def _resolve_attribute(self, name):
        '''
        heat extension: "AlarmUrl" returns the url to post to the policy
        when there is an alarm.
        '''
        if name == 'AlarmUrl' and self.resource_id is not None:
            return unicode(self._get_signed_url())

    def FnGetRefId(self):
        if self.resource_id is not None:
            return unicode(self._get_signed_url())
        else:
            return unicode(self.name)


def resource_mapping():
    return {
        'AWS::AutoScaling::LaunchConfiguration': LaunchConfiguration,
        'AWS::AutoScaling::AutoScalingGroup': AutoScalingGroup,
        'AWS::AutoScaling::ScalingPolicy': ScalingPolicy,
        'OS::Heat::InstanceGroup': InstanceGroup,
    }
