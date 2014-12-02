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

import math
from oslo.utils import excutils
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LE
from heat.common.i18n import _LI
from heat.engine import constraints
from heat.engine.notification import autoscaling as notification
from heat.engine import properties
from heat.engine.resources import instance_group as instgrp
from heat.engine import support
from heat.openstack.common import log as logging
from heat.scaling import cooldown

LOG = logging.getLogger(__name__)


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
        LOG.debug('truncating growth to %s' % maximum)
        return maximum

    if new_capacity < minimum:
        LOG.debug('truncating shrinkage to %s' % minimum)
        return minimum

    return new_capacity


class AutoScalingGroup(instgrp.InstanceGroup, cooldown.CooldownMixin):

    support_status = support.SupportStatus(version='2014.1')

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
            _('The reference to a LaunchConfiguration resource.'),
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
        self.validate_launchconfig()
        return self.create_with_template(self.child_template(),
                                         self._environment())

    def _get_conf_properties(self):
        conf, props = super(AutoScalingGroup, self)._get_conf_properties()
        vpc_zone_ids = self.properties.get(AutoScalingGroup.VPCZONE_IDENTIFIER)
        if vpc_zone_ids:
            props['SubnetId'] = vpc_zone_ids[0]

        return conf, props

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
            LOG.info(_LI("%(name)s NOT performing scaling adjustment, "
                         "cooldown %(cooldown)s"),
                     {'name': self.name,
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
                    LOG.exception(_LE('Failed sending error notification'))
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


def resource_mapping():
    return {
        'AWS::AutoScaling::AutoScalingGroup': AutoScalingGroup,
    }
