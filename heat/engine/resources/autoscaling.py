
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

import functools
import json
import math

from heat.common import exception
from heat.common import timeutils as iso8601utils
from heat.engine import constraints
from heat.engine import environment
from heat.engine import function
from heat.engine.notification import autoscaling as notification
from heat.engine import properties
from heat.engine.properties import Properties
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import signal_responder
from heat.engine import stack_resource
from heat.openstack.common import excutils
from heat.openstack.common import log as logging
from heat.openstack.common import timeutils
from heat.scaling import template

logger = logging.getLogger(__name__)


(SCALED_RESOURCE_TYPE,) = ('OS::Heat::ScaledResource',)


(EXACT_CAPACITY, CHANGE_IN_CAPACITY, PERCENT_CHANGE_IN_CAPACITY) = (
    'ExactCapacity', 'ChangeInCapacity', 'PercentChangeInCapacity')


class CooldownMixin(object):
    '''
    Utility class to encapsulate Cooldown related logic which is shared
    between AutoScalingGroup and ScalingPolicy
    '''
    def _cooldown_inprogress(self):
        inprogress = False
        try:
            # Negative values don't make sense, so they are clamped to zero
            cooldown = max(0, self.properties[self.COOLDOWN])
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

    _ROLLING_UPDATE_SCHEMA_KEYS = (
        MIN_INSTANCES_IN_SERVICE, MAX_BATCH_SIZE, PAUSE_TIME
    ) = (
        'MinInstancesInService', 'MaxBatchSize', 'PauseTime'
    )

    _UPDATE_POLICY_SCHEMA_KEYS = (ROLLING_UPDATE,) = ('RollingUpdate',)

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
            properties.Schema.INTEGER,
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
        MIN_INSTANCES_IN_SERVICE: properties.Schema(properties.Schema.NUMBER,
                                                    default=0),
        MAX_BATCH_SIZE: properties.Schema(properties.Schema.NUMBER,
                                          default=1),
        PAUSE_TIME: properties.Schema(properties.Schema.STRING,
                                      default='PT0S')
    }
    update_policy_schema = {
        ROLLING_UPDATE: properties.Schema(properties.Schema.MAP,
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
                                        parent_name=self.name,
                                        context=self.context)

    def validate(self):
        """
        Add validation for update_policy
        """
        super(InstanceGroup, self).validate()

        if self.update_policy:
            self.update_policy.validate()
            policy_name = self.update_policy_schema.keys()[0]
            if self.update_policy[policy_name]:
                pause_time = self.update_policy[policy_name][self.PAUSE_TIME]
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

    def _environment(self):
        """Return the environment for the nested stack."""
        return {
            environment.PARAMETERS: {},
            environment.RESOURCE_REGISTRY: {
                SCALED_RESOURCE_TYPE: 'AWS::EC2::Instance',
            },
        }

    def handle_create(self):
        """Create a nested stack and add the initial resources to it."""
        num_instances = self.properties[self.SIZE]
        initial_template = self._create_template(num_instances)
        return self.create_with_template(initial_template, self._environment())

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
                    parent_name=self.name,
                    context=self.context)

        if prop_diff:
            self.properties = Properties(self.properties_schema,
                                         json_snippet.get('Properties', {}),
                                         self.stack.resolve_runtime_data,
                                         self.name,
                                         self.context)

            # Replace instances first if launch configuration has changed
            if (self.update_policy[self.ROLLING_UPDATE] and
                    self.LAUNCH_CONFIGURATION_NAME in prop_diff):
                policy = self.update_policy[self.ROLLING_UPDATE]
                self._replace(policy[self.MIN_INSTANCES_IN_SERVICE],
                              policy[self.MAX_BATCH_SIZE],
                              policy[self.PAUSE_TIME])

            # Get the current capacity, we may need to adjust if
            # Size has changed
            if self.SIZE in prop_diff:
                inst_list = self.get_instances()
                if len(inst_list) != self.properties[self.SIZE]:
                    self.resize(self.properties[self.SIZE])

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
        instance_definition = function.resolve(conf.t)
        instance_definition['Type'] = SCALED_RESOURCE_TYPE
        instance_definition['Properties']['Tags'] = self._tags()
        if self.properties.get('VPCZoneIdentifier'):
            instance_definition['Properties']['SubnetId'] = \
                self.properties['VPCZoneIdentifier'][0]
        # resolve references within the context of this stack.
        return self.stack.resolve_runtime_data(instance_definition)

    def _get_instance_templates(self):
        """Get templates for resource instances."""
        return [(instance.name, instance.t)
                for instance in self.get_instances()]

    def _create_template(self, num_instances, num_replace=0):
        """
        Create a template to represent autoscaled instances.

        Also see heat.scaling.template.resource_templates.
        """
        instance_definition = self._get_instance_definition()
        old_resources = self._get_instance_templates()
        templates = template.resource_templates(
            old_resources, instance_definition, num_instances, num_replace)
        return {"Resources": dict(templates)}

    def _replace(self, min_in_service, batch_size, pause_time):
        """
        Replace the instances in the group using updated launch configuration
        """
        def changing_instances(tmpl):
            instances = self.get_instances()
            serialize_template = functools.partial(json.dumps, sort_keys=True)
            current = set((i.name, serialize_template(i.t)) for i in instances)
            updated = set((k, serialize_template(v))
                          for k, v in tmpl['Resources'].items())
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
        if pause_sec * (batch_cnt - 1) >= self.stack.timeout_secs():
            raise ValueError('The current UpdatePolicy will result '
                             'in stack update timeout.')

        # effective capacity includes temporary capacity added to accommodate
        # the minimum number of instances in service during update
        efft_capacity = max(capacity - efft_bat_sz, efft_min_sz) + efft_bat_sz

        try:
            remainder = capacity
            while remainder > 0 or efft_capacity > capacity:
                if capacity - remainder >= efft_min_sz:
                    efft_capacity = capacity
                template = self._create_template(efft_capacity, efft_bat_sz)
                self._lb_reload(exclude=changing_instances(template))
                updater = self.update_with_template(template,
                                                    self._environment())
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
            updater = self.update_with_template(new_template,
                                                self._environment())
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
                        _("Unsupported resource '%s' in LoadBalancerNames") %
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

    def child_template(self):
        num_instances = int(self.properties[self.SIZE])
        return self._create_template(num_instances)

    def child_params(self):
        return self._environment()


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

    _UPDATE_POLICY_SCHEMA_KEYS = (
        ROLLING_UPDATE
    ) = (
        'AutoScalingRollingUpdate'
    )

    _ROLLING_UPDATE_SCHEMA_KEYS = (
        MIN_INSTANCES_IN_SERVICE, MAX_BATCH_SIZE, PAUSE_TIME
    ) = (
        'MinInstancesInService', 'MaxBatchSize', 'PauseTime'
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
            properties.Schema.INTEGER,
            _('Maximum number of instances in the group.'),
            required=True,
            update_allowed=True
        ),
        MIN_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Minimum number of instances in the group.'),
            required=True,
            update_allowed=True
        ),
        COOLDOWN: properties.Schema(
            properties.Schema.NUMBER,
            _('Cooldown period, in seconds.'),
            update_allowed=True
        ),
        DESIRED_CAPACITY: properties.Schema(
            properties.Schema.INTEGER,
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
        MIN_INSTANCES_IN_SERVICE: properties.Schema(properties.Schema.INTEGER,
                                                    default=0),
        MAX_BATCH_SIZE: properties.Schema(properties.Schema.INTEGER,
                                          default=1),
        PAUSE_TIME: properties.Schema(properties.Schema.STRING,
                                      default='PT0S')
    }

    update_policy_schema = {
        ROLLING_UPDATE: properties.Schema(
            properties.Schema.MAP,
            schema=rolling_update_schema)
    }

    update_allowed_keys = ('Properties', 'UpdatePolicy')

    def handle_create(self):
        if self.properties[self.DESIRED_CAPACITY]:
            num_to_create = self.properties[self.DESIRED_CAPACITY]
        else:
            num_to_create = self.properties[self.MIN_SIZE]
        initial_template = self._create_template(num_to_create)
        return self.create_with_template(initial_template,
                                         self._environment())

    def check_create_complete(self, task):
        """Invoke the cooldown after creation succeeds."""
        done = super(AutoScalingGroup, self).check_create_complete(task)
        if done:
            self._cooldown_timestamp(
                "%s : %s" % (EXACT_CAPACITY, len(self.get_instances())))
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
                    parent_name=self.name,
                    context=self.context)

        if prop_diff:
            self.properties = Properties(self.properties_schema,
                                         json_snippet.get('Properties', {}),
                                         self.stack.resolve_runtime_data,
                                         self.name,
                                         self.context)

            # Replace instances first if launch configuration has changed
            if (self.update_policy[self.ROLLING_UPDATE] and
                    self.LAUNCH_CONFIGURATION_NAME in prop_diff):
                policy = self.update_policy[self.ROLLING_UPDATE]
                self._replace(policy[self.MIN_INSTANCES_IN_SERVICE],
                              policy[self.MAX_BATCH_SIZE],
                              policy[self.PAUSE_TIME])

            # Get the current capacity, we may need to adjust if
            # MinSize or MaxSize has changed
            capacity = len(self.get_instances())

            # Figure out if an adjustment is required
            new_capacity = None
            if self.MIN_SIZE in prop_diff:
                if capacity < self.properties[self.MIN_SIZE]:
                    new_capacity = self.properties[self.MIN_SIZE]
            if self.MAX_SIZE in prop_diff:
                if capacity > self.properties[self.MAX_SIZE]:
                    new_capacity = self.properties[self.MAX_SIZE]
            if self.DESIRED_CAPACITY in prop_diff:
                if self.properties[self.DESIRED_CAPACITY]:
                    new_capacity = self.properties[self.DESIRED_CAPACITY]

            if new_capacity is not None:
                self.adjust(new_capacity, adjustment_type=EXACT_CAPACITY)

    def adjust(self, adjustment, adjustment_type=CHANGE_IN_CAPACITY):
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
        if adjustment_type == CHANGE_IN_CAPACITY:
            new_capacity = capacity + adjustment
        elif adjustment_type == EXACT_CAPACITY:
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

        upper = self.properties[self.MAX_SIZE]
        lower = self.properties[self.MIN_SIZE]

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

        # send a notification before, on-error and on-success.
        notif = {
            'stack': self.stack,
            'adjustment': adjustment,
            'adjustment_type': adjustment_type,
            'capacity': capacity,
            'groupname': self.FnGetRefId(),
            'message': _("Start resizing the group %(group)s") % {
                'group': self.FnGetRefId()},
            'suffix': 'start',
        }
        notification.send(**notif)
        try:
            self.resize(new_capacity)
        except Exception as resize_ex:
            with excutils.save_and_reraise_exception():
                try:
                    notif.update({'suffix': 'error',
                                  'message': str(resize_ex),
                                  })
                    notification.send(**notif)
                except Exception:
                    logger.exception(_('Failed sending error notification'))
        else:
            notif.update({
                'suffix': 'end',
                'capacity': new_capacity,
                'message': _("End resizing the group %(group)s") % {
                    'group': notif['groupname']},
            })
            notification.send(**notif)

        self._cooldown_timestamp("%s : %s" % (adjustment_type, adjustment))

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

        # check validity of group size
        min_size = self.properties[self.MIN_SIZE]
        max_size = self.properties[self.MAX_SIZE]

        if max_size < min_size:
            msg = _("MinSize can not be greater than MaxSize")
            raise exception.StackValidationFailed(message=msg)

        if min_size < 0:
            msg = _("The size of AutoScalingGroup can not be less than zero")
            raise exception.StackValidationFailed(message=msg)

        if self.properties[self.DESIRED_CAPACITY]:
            desired_capacity = self.properties[self.DESIRED_CAPACITY]
            if desired_capacity < min_size or desired_capacity > max_size:
                msg = _("DesiredCapacity must be between MinSize and MaxSize")
                raise exception.StackValidationFailed(message=msg)

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


class AutoScalingResourceGroup(AutoScalingGroup):
    """An autoscaling group that can scale arbitrary resources."""

    PROPERTIES = (
        RESOURCE, MAX_SIZE, MIN_SIZE, COOLDOWN, DESIRED_CAPACITY
    ) = (
        'resource', 'max_size', 'min_size', 'cooldown', 'desired_capacity'
    )

    properties_schema = {
        RESOURCE: properties.Schema(
            properties.Schema.MAP,
            _('Resource definition for the resources in the group, in HOT '
              'format. The value of this property is the definition of a '
              'resource just as if it had been declared in the template '
              'itself.'),
            required=True
        ),
        MAX_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Maximum number of resources in the group.'),
            required=True,
            update_allowed=True,
            constraints=[constraints.Range(min=0)],
        ),
        MIN_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Minimum number of resources in the group.'),
            required=True,
            update_allowed=True,
            constraints=[constraints.Range(min=0)]
        ),
        COOLDOWN: properties.Schema(
            properties.Schema.INTEGER,
            _('Cooldown period, in seconds.'),
            update_allowed=True
        ),
        DESIRED_CAPACITY: properties.Schema(
            properties.Schema.INTEGER,
            _('Desired initial number of resources.'),
            update_allowed=True
        ),
    }

    update_allowed_keys = ('Properties',)

    # Override the InstanceGroup attributes_schema; we don't want any
    # attributes.
    attributes_schema = {}

    def _get_instance_definition(self):
        resource_definition = self.properties[self.RESOURCE]
        # resolve references within the context of this stack.
        return self.stack.resolve_runtime_data(resource_definition)

    def _lb_reload(self, exclude=None):
        """AutoScalingResourceGroup does not maintain load balancer
        connections, so we just ignore calls to update the LB.
        """
        pass

    def _get_instance_templates(self):
        """
        Get templates for resource instances in HOT format.

        AutoScalingResourceGroup uses HOT as template format for scaled
        resources. Templates for existing resources use CFN syntax and
        have to be converted to HOT since those templates get used for
        generating scaled resource templates.
        """
        CFN_TO_HOT_ATTRS = {'Type': 'type',
                            'Properties': 'properties',
                            'Metadata': 'metadata',
                            'DependsOn': 'depends_on',
                            'DeletionPolicy': 'deletion_policy',
                            'UpdatePolicy': 'update_policy'}

        def to_hot(template):
            hot_template = {}

            for attr, attr_value in template.iteritems():
                hot_attr = CFN_TO_HOT_ATTRS.get(attr, attr)
                hot_template[hot_attr] = attr_value

            return hot_template

        return [(instance.name, to_hot(instance.t))
                for instance in self.get_instances()]

    def _create_template(self, *args, **kwargs):
        """Use a HOT format for the template in the nested stack."""
        tpl = super(AutoScalingResourceGroup, self)._create_template(
            *args, **kwargs)
        tpl['heat_template_version'] = '2013-05-23'
        tpl['resources'] = tpl.pop('Resources')
        return tpl


class ScalingPolicy(signal_responder.SignalResponder, CooldownMixin):
    PROPERTIES = (
        AUTO_SCALING_GROUP_NAME, SCALING_ADJUSTMENT, ADJUSTMENT_TYPE,
        COOLDOWN,
    ) = (
        'AutoScalingGroupName', 'ScalingAdjustment', 'AdjustmentType',
        'Cooldown',
    )

    EXACT_CAPACITY, CHANGE_IN_CAPACITY, PERCENT_CHANGE_IN_CAPACITY = (
        'ExactCapacity', 'ChangeInCapacity', 'PercentChangeInCapacity')

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
                constraints.AllowedValues([CHANGE_IN_CAPACITY,
                                           EXACT_CAPACITY,
                                           PERCENT_CHANGE_IN_CAPACITY]),
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

    def handle_create(self):
        super(ScalingPolicy, self).handle_create()
        self.resource_id_set(self._get_user_id())

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """
        If Properties has changed, update self.properties, so we get the new
        values during any subsequent adjustment.
        """
        if prop_diff:
            self.properties = Properties(self.properties_schema,
                                         json_snippet.get('Properties', {}),
                                         self.stack.resolve_runtime_data,
                                         self.name,
                                         self.context)

    def _get_adjustement_type(self):
        return self.properties[self.ADJUSTMENT_TYPE]

    def handle_signal(self, details=None):
        if self.action in (self.SUSPEND, self.DELETE):
            msg = _('Cannot signal resource during %s') % self.action
            raise Exception(msg)

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
        if group is None:
            raise exception.NotFound(_('Alarm %(alarm)s could not find '
                                       'scaling group named "%(group)s"') % {
                                           'alarm': self.name,
                                           'group': asgn_id})

        logger.info(_('%(name)s Alarm, adjusting Group %(group)s with id '
                    '%(asgn_id)s by %(filter)s') % {
                        'name': self.name, 'group': group.name,
                        'asgn_id': asgn_id,
                        'filter': self.properties[self.SCALING_ADJUSTMENT]})
        adjustment_type = self._get_adjustement_type()
        group.adjust(self.properties[self.SCALING_ADJUSTMENT], adjustment_type)

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


class AutoScalingPolicy(ScalingPolicy):
    """A resource to manage scaling of `OS::Heat::AutoScalingGroup`.

    **Note** while it may incidentally support
    `AWS::AutoScaling::AutoScalingGroup` for now, please don't use it for that
    purpose and use `AWS::AutoScaling::ScalingPolicy` instead.
    """
    PROPERTIES = (
        AUTO_SCALING_GROUP_NAME, SCALING_ADJUSTMENT, ADJUSTMENT_TYPE,
        COOLDOWN,
    ) = (
        'auto_scaling_group_id', 'scaling_adjustment', 'adjustment_type',
        'cooldown',
    )

    EXACT_CAPACITY, CHANGE_IN_CAPACITY, PERCENT_CHANGE_IN_CAPACITY = (
        'exact_capacity', 'change_in_capacity', 'percent_change_in_capacity')

    properties_schema = {
        AUTO_SCALING_GROUP_NAME: properties.Schema(
            properties.Schema.STRING,
            _('AutoScaling group ID to apply policy to.'),
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
                constraints.AllowedValues([CHANGE_IN_CAPACITY,
                                           EXACT_CAPACITY,
                                           PERCENT_CHANGE_IN_CAPACITY]),
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
        "alarm_url": _("A signed url to handle the alarm.")
    }

    def _get_adjustement_type(self):
        adjustment_type = self.properties[self.ADJUSTMENT_TYPE]
        return ''.join([t.capitalize() for t in adjustment_type.split('_')])

    def _resolve_attribute(self, name):
        if name == 'alarm_url' and self.resource_id is not None:
            return unicode(self._get_signed_url())

    def FnGetRefId(self):
        return resource.Resource.FnGetRefId(self)


def resource_mapping():
    return {
        'AWS::AutoScaling::LaunchConfiguration': LaunchConfiguration,
        'AWS::AutoScaling::AutoScalingGroup': AutoScalingGroup,
        'AWS::AutoScaling::ScalingPolicy': ScalingPolicy,
        'OS::Heat::InstanceGroup': InstanceGroup,
        'OS::Heat::AutoScalingGroup': AutoScalingResourceGroup,
        'OS::Heat::ScalingPolicy': AutoScalingPolicy,
    }
