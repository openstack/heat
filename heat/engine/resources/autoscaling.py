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

from oslo.utils import excutils
import six

from heat.common import environment_format
from heat.common import exception
from heat.common import timeutils as iso8601utils
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import function
from heat.engine.notification import autoscaling as notification
from heat.engine import properties
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack_resource
from heat.openstack.common import log as logging
from heat.scaling import cooldown
from heat.scaling import template

LOG = logging.getLogger(__name__)


(SCALED_RESOURCE_TYPE,) = ('OS::Heat::ScaledResource',)


(EXACT_CAPACITY, CHANGE_IN_CAPACITY, PERCENT_CHANGE_IN_CAPACITY) = (
    'ExactCapacity', 'ChangeInCapacity', 'PercentChangeInCapacity')


def _calculate_new_capacity(current, adjustment, adjustment_type,
                            minimum, maximum):
    """
    Given the current capacity, calculates the new capacity which results
    from applying the given adjustment of the given adjustment-type.  The
    new capacity will be kept within the maximum and minimum bounds.
    """
    if adjustment_type == CHANGE_IN_CAPACITY:
        new_capacity = current + adjustment
    elif adjustment_type == EXACT_CAPACITY:
        new_capacity = adjustment
    else:
        # PercentChangeInCapacity
        delta = current * adjustment / 100.0
        if math.fabs(delta) < 1.0:
            rounded = int(math.ceil(delta) if delta > 0.0
                          else math.floor(delta))
        else:
            rounded = int(math.floor(delta) if delta > 0.0
                          else math.ceil(delta))
        new_capacity = current + rounded

    if new_capacity > maximum:
        LOG.debug(_('truncating growth to %s') % maximum)
        return maximum

    if new_capacity < minimum:
        LOG.debug(_('truncating shrinkage to %s') % minimum)
        return minimum

    return new_capacity


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

    ATTRIBUTES = (
        INSTANCE_LIST,
    ) = (
        'InstanceList',
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

    attributes_schema = {
        INSTANCE_LIST: attributes.Schema(
            _("A comma-delimited list of server ip addresses. "
              "(Heat extension).")
        ),
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
        self.update_policy = self.t.update_policy(self.update_policy_schema,
                                                  self.context)

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
            environment_format.PARAMETERS: {},
            environment_format.RESOURCE_REGISTRY: {
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
                up = json_snippet.update_policy(self.update_policy_schema,
                                                self.context)
                self.update_policy = up

        if prop_diff:
            self.properties = json_snippet.properties(self.properties_schema,
                                                      self.context)

            # Replace instances first if launch configuration has changed
            self._try_rolling_update(prop_diff)

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
        conf_refid = self.properties[self.LAUNCH_CONFIGURATION_NAME]
        conf = self.stack.resource_by_refid(conf_refid)

        props = function.resolve(conf.properties.data)
        props['Tags'] = self._tags()
        vpc_zone_ids = self.properties.get(AutoScalingGroup.VPCZONE_IDENTIFIER)
        if vpc_zone_ids:
            props['SubnetId'] = vpc_zone_ids[0]

        return rsrc_defn.ResourceDefinition(None,
                                            SCALED_RESOURCE_TYPE,
                                            props,
                                            conf.t.metadata())

    def _get_instance_templates(self):
        """Get templates for resource instances."""
        return [(instance.name, instance.t)
                for instance in self.get_instances()]

    def _create_template(self, num_instances, num_replace=0,
                         template_version=('HeatTemplateFormatVersion',
                                           '2012-12-12')):
        """
        Create a template to represent autoscaled instances.

        Also see heat.scaling.template.resource_templates.
        """
        instance_definition = self._get_instance_definition()
        old_resources = self._get_instance_templates()
        definitions = template.resource_templates(
            old_resources, instance_definition, num_instances, num_replace)

        return template.make_template(definitions, version=template_version)

    def _try_rolling_update(self, prop_diff):
        if (self.update_policy[self.ROLLING_UPDATE] and
                self.LAUNCH_CONFIGURATION_NAME in prop_diff):
            policy = self.update_policy[self.ROLLING_UPDATE]
            pause_sec = iso8601utils.parse_isoduration(policy[self.PAUSE_TIME])
            self._replace(policy[self.MIN_INSTANCES_IN_SERVICE],
                          policy[self.MAX_BATCH_SIZE],
                          pause_sec)

    def _replace(self, min_in_service, batch_size, pause_sec):
        """
        Replace the instances in the group using updated launch configuration
        """
        def changing_instances(tmpl):
            instances = self.get_instances()
            current = set((i.name, i.t) for i in instances)
            updated = set(tmpl.resource_definitions(self.nested()).items())
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

    def _lb_reload(self, exclude=None):
        '''
        Notify the LoadBalancer to reload its config to include
        the changes in instances we have just made.

        This must be done after activation (instance in ACTIVE state),
        otherwise the instances' IP addresses may not be available.
        '''
        exclude = exclude or []
        if self.properties[self.LOAD_BALANCER_NAMES]:
            id_list = [inst.FnGetRefId() for inst in self.get_instances()
                       if inst.FnGetRefId() not in exclude]
            for lb in self.properties[self.LOAD_BALANCER_NAMES]:
                lb_resource = self.stack[lb]

                props = copy.copy(lb_resource.properties.data)
                if 'Instances' in lb_resource.properties_schema:
                    props['Instances'] = id_list
                elif 'members' in lb_resource.properties_schema:
                    props['members'] = id_list
                else:
                    raise exception.Error(
                        _("Unsupported resource '%s' in LoadBalancerNames") %
                        (lb,))

                lb_defn = rsrc_defn.ResourceDefinition(
                    lb_resource.name,
                    lb_resource.type(),
                    props,
                    lb_resource.t.get('Metadata'),
                    deletion_policy=lb_resource.t.get('DeletionPolicy'))

                scheduler.TaskRunner(lb_resource.update, lb_defn)()

    def FnGetRefId(self):
        return self.physical_resource_name_or_FnGetRefId()

    def _resolve_attribute(self, name):
        '''
        heat extension: "InstanceList" returns comma delimited list of server
        ip addresses.
        '''
        if name == self.INSTANCE_LIST:
            return u','.join(inst.FnGetAtt('PublicIp')
                             for inst in self.get_instances()) or None

    def child_template(self):
        num_instances = int(self.properties[self.SIZE])
        return self._create_template(num_instances)

    def child_params(self):
        return self._environment()


class AutoScalingGroup(InstanceGroup, cooldown.CooldownMixin):

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
            _('Use only with Neutron, to list the internal subnet to '
              'which the instance will be attached; '
              'needed only if multiple exist; '
              'list length must be exactly 1.'),
            schema=properties.Schema(
                properties.Schema.STRING,
                _('UUID of the internal subnet to which the instance '
                  'will be attached.')
            )
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

    def handle_create(self):
        return self.create_with_template(self.child_template(),
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
                up = json_snippet.update_policy(self.update_policy_schema,
                                                self.context)
                self.update_policy = up

        if prop_diff:
            self.properties = json_snippet.properties(self.properties_schema,
                                                      self.context)

            # Replace instances first if launch configuration has changed
            self._try_rolling_update(prop_diff)

            if (self.DESIRED_CAPACITY in prop_diff and
                    self.properties[self.DESIRED_CAPACITY] is not None):

                self.adjust(self.properties[self.DESIRED_CAPACITY],
                            adjustment_type=EXACT_CAPACITY)
            else:
                current_capacity = len(self.get_instances())
                self.adjust(current_capacity, adjustment_type=EXACT_CAPACITY)

    def adjust(self, adjustment, adjustment_type=CHANGE_IN_CAPACITY):
        """
        Adjust the size of the scaling group if the cooldown permits.
        """
        if self._cooldown_inprogress():
            LOG.info(_("%(name)s NOT performing scaling adjustment, "
                       "cooldown %(cooldown)s")
                     % {'name': self.name,
                        'cooldown': self.properties[self.COOLDOWN]})
            return

        capacity = len(self.get_instances())
        lower = self.properties[self.MIN_SIZE]
        upper = self.properties[self.MAX_SIZE]

        new_capacity = _calculate_new_capacity(capacity, adjustment,
                                               adjustment_type, lower, upper)

        if new_capacity == capacity:
            LOG.debug('no change in capacity %d' % capacity)
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
                                  'message': six.text_type(resize_ex),
                                  })
                    notification.send(**notif)
                except Exception:
                    LOG.exception(_('Failed sending error notification'))
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
        autoscaling_tag = [{self.TAG_KEY: 'metering.AutoScalingGroupName',
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

        if self.properties[self.DESIRED_CAPACITY] is not None:
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

    def child_template(self):
        if self.properties[self.DESIRED_CAPACITY]:
            num_instances = self.properties[self.DESIRED_CAPACITY]
        else:
            num_instances = self.properties[self.MIN_SIZE]
        return self._create_template(num_instances)


class AutoScalingResourceGroup(AutoScalingGroup):
    """An autoscaling group that can scale arbitrary resources."""

    PROPERTIES = (
        RESOURCE, MAX_SIZE, MIN_SIZE, COOLDOWN, DESIRED_CAPACITY,
        ROLLING_UPDATES,
    ) = (
        'resource', 'max_size', 'min_size', 'cooldown', 'desired_capacity',
        'rolling_updates',
    )

    _ROLLING_UPDATES_SCHEMA = (
        MIN_IN_SERVICE, MAX_BATCH_SIZE, PAUSE_TIME,
    ) = (
        'min_in_service', 'max_batch_size', 'pause_time',
    )

    ATTRIBUTES = (
        OUTPUTS, OUTPUTS_LIST,
    ) = (
        'outputs', 'outputs_list',
    )

    properties_schema = {
        RESOURCE: properties.Schema(
            properties.Schema.MAP,
            _('Resource definition for the resources in the group, in HOT '
              'format. The value of this property is the definition of a '
              'resource just as if it had been declared in the template '
              'itself.'),
            required=True,
            update_allowed=True,
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
        ROLLING_UPDATES: properties.Schema(
            properties.Schema.MAP,
            _('Policy for rolling updates for this scaling group.'),
            required=False,
            update_allowed=True,
            schema={
                MIN_IN_SERVICE: properties.Schema(
                    properties.Schema.NUMBER,
                    _('The minimum number of resources in service while '
                      'rolling updates are being executed.'),
                    constraints=[constraints.Range(min=0)],
                    default=0),
                MAX_BATCH_SIZE: properties.Schema(
                    properties.Schema.NUMBER,
                    _('The maximum number of resources to replace at once.'),
                    constraints=[constraints.Range(min=0)],
                    default=1),
                PAUSE_TIME: properties.Schema(
                    properties.Schema.NUMBER,
                    _('The number of seconds to wait between batches of '
                      'updates.'),
                    constraints=[constraints.Range(min=0)],
                    default=0),
            },
        ),
    }

    attributes_schema = {
        OUTPUTS: attributes.Schema(
            _("A map of resource names to the specified attribute of each "
              "individual resource.")
        ),
        OUTPUTS_LIST: attributes.Schema(
            _("A list of the specified attribute of each individual resource.")
        ),
    }

    def _get_instance_definition(self):
        rsrc = self.properties[self.RESOURCE]
        return rsrc_defn.ResourceDefinition(None,
                                            rsrc['type'],
                                            rsrc.get('properties'),
                                            rsrc.get('metadata'))

    def _lb_reload(self, exclude=None):
        """AutoScalingResourceGroup does not maintain load balancer
        connections, so we just ignore calls to update the LB.
        """
        pass

    def _try_rolling_update(self, prop_diff):
        if (self.properties[self.ROLLING_UPDATES] and
                self.RESOURCE in prop_diff):
            policy = self.properties[self.ROLLING_UPDATES]
            self._replace(policy[self.MIN_IN_SERVICE],
                          policy[self.MAX_BATCH_SIZE],
                          policy[self.PAUSE_TIME])

    def _create_template(self, num_instances, num_replace=0,
                         template_version=('heat_template_version',
                                           '2013-05-23')):
        """Create a template in the HOT format for the nested stack."""
        return super(AutoScalingResourceGroup,
                     self)._create_template(num_instances, num_replace,
                                            template_version=template_version)

    def FnGetAtt(self, key, *path):
        if path:
            attrs = ((rsrc.name,
                      rsrc.FnGetAtt(*path)) for rsrc in self.get_instances())
            if key == self.OUTPUTS:
                return dict(attrs)
            if key == self.OUTPUTS_LIST:
                return [value for name, value in attrs]

        raise exception.InvalidTemplateAttribute(resource=self.name,
                                                 key=key)


def resource_mapping():
    return {
        'AWS::AutoScaling::AutoScalingGroup': AutoScalingGroup,
        'OS::Heat::InstanceGroup': InstanceGroup,
        'OS::Heat::AutoScalingGroup': AutoScalingResourceGroup,
    }
