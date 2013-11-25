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

from heat.common import exception
from heat.openstack.common import log as logging
from heat.openstack.common import timeutils
from heat.engine.properties import Properties
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
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}
    properties_schema = {
        'AvailabilityZones': {
            'Required': True,
            'Type': 'List',
            'Description': _('Not Implemented.')},
        'LaunchConfigurationName': {
            'Required': True,
            'Type': 'String',
            'Description': _('Name of LaunchConfiguration resource.')},
        'Size': {
            'Required': True,
            'Type': 'Number',
            'Description': _('Desired number of instances.')},
        'LoadBalancerNames': {
            'Type': 'List',
            'Description': _('List of LoadBalancer resources.')},
        'Tags': {
            'Type': 'List',
            'Schema': {'Type': 'Map', 'Schema': tags_schema},
            'Description': _('Tags to attach to this group.')}
    }
    update_allowed_keys = ('Properties', 'UpdatePolicy',)
    update_allowed_properties = ('Size', 'LaunchConfigurationName',)
    attributes_schema = {
        "InstanceList": _("A comma-delimited list of server ip addresses. "
                          "(Heat extension).")
    }
    rolling_update_schema = {
        'MinInstancesInService': properties.Schema(properties.NUMBER,
                                                   default=0),
        'MaxBatchSize': properties.Schema(properties.NUMBER,
                                          default=1),
        'PauseTime': properties.Schema(properties.STRING,
                                       default='PT0S')
    }
    update_policy_schema = {
        'RollingUpdate': properties.Schema(properties.MAP,
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

    def get_instance_names(self):
        """Get a list of resource names of the instances in this InstanceGroup.

        Failed resources will be ignored.
        """
        return sorted(x.name for x in self.get_instances())

    def get_instances(self):
        """Get a set of all the instance resources managed by this group."""
        return [resource for resource in self.nested()
                if resource.state[1] != resource.FAILED]

    def handle_create(self):
        """Create a nested stack and add the initial resources to it."""
        num_instances = int(self.properties['Size'])
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

            # Get the current capacity, we may need to adjust if
            # Size has changed
            if 'Size' in prop_diff:
                inst_list = self.get_instances()
                if len(inst_list) != int(self.properties['Size']):
                    self.resize(int(self.properties['Size']))

    def _tags(self):
        """
        Make sure that we add a tag that Ceilometer can pick up.
        These need to be prepended with 'metering.'.
        """
        tags = self.properties.get('Tags') or []
        for t in tags:
            if t['Key'].startswith('metering.'):
                # the user has added one, don't add another.
                return tags
        return tags + [{'Key': 'metering.groupname',
                        'Value': self.FnGetRefId()}]

    def handle_delete(self):
        return self.delete_nested()

    def _create_template(self, num_instances):
        """
        Create a template with a number of instance definitions based on the
        launch configuration.
        """
        conf_name = self.properties['LaunchConfigurationName']
        conf = self.stack.resource_by_refid(conf_name)
        instance_definition = copy.deepcopy(conf.t)
        instance_definition['Type'] = 'AWS::EC2::Instance'
        instance_definition['Properties']['Tags'] = self._tags()
        if self.properties.get('VPCZoneIdentifier'):
            instance_definition['Properties']['SubnetId'] = \
                self.properties['VPCZoneIdentifier'][0]
        # resolve references within the context of this stack.
        fully_parsed = self.stack.resolve_runtime_data(instance_definition)

        resources = {}
        for i in range(num_instances):
            resources["%s-%d" % (self.name, i)] = fully_parsed
        return {"Resources": resources}

    def resize(self, new_capacity):
        """
        Resize the instance group to the new capacity.

        When shrinking, the newest instances will be removed.
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

    def _lb_reload(self):
        '''
        Notify the LoadBalancer to reload its config to include
        the changes in instances we have just made.

        This must be done after activation (instance in ACTIVE state),
        otherwise the instances' IP addresses may not be available.
        '''
        if self.properties['LoadBalancerNames']:
            id_list = [inst.FnGetRefId() for inst in self.get_instances()]
            for lb in self.properties['LoadBalancerNames']:
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
            ips = [inst.FnGetAtt('PublicIp')
                   for inst in self.nested().resources.values()]
            if ips:
                return unicode(','.join(ips))


class AutoScalingGroup(InstanceGroup, CooldownMixin):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}
    properties_schema = {
        'AvailabilityZones': {
            'Required': True,
            'Type': 'List',
            'Description': _('Not Implemented.')},
        'LaunchConfigurationName': {
            'Required': True,
            'Type': 'String',
            'Description': _('Name of LaunchConfiguration resource.')},
        'MaxSize': {
            'Required': True,
            'Type': 'String',
            'Description': _('Maximum number of instances in the group.')},
        'MinSize': {
            'Required': True,
            'Type': 'String',
            'Description': _('Minimum number of instances in the group.')},
        'Cooldown': {
            'Type': 'String',
            'Description': _('Cooldown period, in seconds.')},
        'DesiredCapacity': {
            'Type': 'Number',
            'Description': _('Desired initial number of instances.')},
        'HealthCheckGracePeriod': {
            'Type': 'Integer',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'HealthCheckType': {
            'Type': 'String',
            'AllowedValues': ['EC2', 'ELB'],
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'LoadBalancerNames': {
            'Type': 'List',
            'Description': _('List of LoadBalancer resources.')},
        'VPCZoneIdentifier': {
            'Type': 'List',
            'Description': _('List of VPC subnet identifiers.')},
        'Tags': {
            'Type': 'List',
            'Schema': {'Type': 'Map', 'Schema': tags_schema},
            'Description': _('Tags to attach to this group.')}
    }
    rolling_update_schema = {
        'MinInstancesInService': properties.Schema(properties.NUMBER,
                                                   default=0),
        'MaxBatchSize': properties.Schema(properties.NUMBER,
                                          default=1),
        'PauseTime': properties.Schema(properties.STRING,
                                       default='PT0S')
    }
    update_policy_schema = {
        'AutoScalingRollingUpdate': properties.Schema(
            properties.MAP, schema=rolling_update_schema)
    }

    # template keys and properties supported for handle_update,
    # note trailing comma is required for a single item to get a tuple
    update_allowed_keys = ('Properties', 'UpdatePolicy',)
    update_allowed_properties = ('LaunchConfigurationName',
                                 'MaxSize', 'MinSize',
                                 'Cooldown', 'DesiredCapacity',)

    def handle_create(self):
        if self.properties['DesiredCapacity']:
            num_to_create = int(self.properties['DesiredCapacity'])
        else:
            num_to_create = int(self.properties['MinSize'])
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

            # Get the current capacity, we may need to adjust if
            # MinSize or MaxSize has changed
            capacity = len(self.get_instances())

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
                self.adjust(new_capacity, adjustment_type='ExactCapacity')

    def adjust(self, adjustment, adjustment_type='ChangeInCapacity'):
        """
        Adjust the size of the scaling group if the cooldown permits.
        """
        if self._cooldown_inprogress():
            logger.info("%s NOT performing scaling adjustment, cooldown %s" %
                        (self.name, self.properties['Cooldown']))
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

        upper = int(self.properties['MaxSize'])
        lower = int(self.properties['MinSize'])

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
            logger.debug('no change in capacity %d' % capacity)
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
        autoscaling_tag = [{'Key': 'AutoScalingGroupName',
                            'Value': self.FnGetRefId()}]
        return super(AutoScalingGroup, self)._tags() + autoscaling_tag

    def validate(self):
        res = super(AutoScalingGroup, self).validate()
        if res:
            return res

        # TODO(pasquier-s): once Neutron is able to assign subnets to
        # availability zones, it will be possible to specify multiple subnets.
        # For now, only one subnet can be specified. The bug #1096017 tracks
        # this issue.
        if self.properties.get('VPCZoneIdentifier') and \
                len(self.properties['VPCZoneIdentifier']) != 1:
            raise exception.NotSupported(feature=_("Anything other than one "
                                         "VPCZoneIdentifier"))


class LaunchConfiguration(resource.Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}
    properties_schema = {
        'ImageId': {
            'Type': 'String',
            'Required': True,
            'Description': _('Glance image ID or name.')},
        'InstanceType': {
            'Type': 'String',
            'Required': True,
            'Description': _('Nova instance type (flavor).')},
        'KeyName': {
            'Type': 'String',
            'Description': _('Optional Nova keypair name.')},
        'UserData': {
            'Type': 'String',
            'Description': _('User data to pass to instance.')},
        'SecurityGroups': {
            'Type': 'List',
            'Description': _('Security group names to assign.')},
        'KernelId': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'RamDiskId': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'BlockDeviceMappings': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'NovaSchedulerHints': {
            'Type': 'List',
            'Schema': {'Type': 'Map', 'Schema': tags_schema},
            'Description': _('Scheduler hints to pass '
                             'to Nova (Heat extension).')},
    }

    def FnGetRefId(self):
        return unicode(self.physical_resource_name())


class ScalingPolicy(signal_responder.SignalResponder, CooldownMixin):
    properties_schema = {
        'AutoScalingGroupName': {
            'Type': 'String',
            'Required': True,
            'Description': _('AutoScaling group name to apply policy to.')},
        'ScalingAdjustment': {
            'Type': 'Number',
            'Required': True,
            'Description': _('Size of adjustment.')},
        'AdjustmentType': {
            'Type': 'String',
            'AllowedValues': ['ChangeInCapacity',
                              'ExactCapacity',
                              'PercentChangeInCapacity'],
            'Required': True,
            'Description': _('Type of adjustment (absolute or percentage).')},
        'Cooldown': {
            'Type': 'Number',
            'Description': _('Cooldown period, in seconds.')},
    }

    update_allowed_keys = ('Properties',)
    update_allowed_properties = ('ScalingAdjustment', 'AdjustmentType',
                                 'Cooldown',)
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

        logger.info('%s Alarm, new state %s' % (self.name, alarm_state))

        if alarm_state != 'alarm':
            return
        if self._cooldown_inprogress():
            logger.info("%s NOT performing scaling action, cooldown %s" %
                        (self.name, self.properties['Cooldown']))
            return

        asgn_id = self.properties['AutoScalingGroupName']
        group = self.stack.resource_by_refid(asgn_id)

        logger.info('%s Alarm, adjusting Group %s by %s' %
                    (self.name, group.name,
                     self.properties['ScalingAdjustment']))
        group.adjust(int(self.properties['ScalingAdjustment']),
                     self.properties['AdjustmentType'])

        self._cooldown_timestamp("%s : %s" %
                                 (self.properties['AdjustmentType'],
                                  self.properties['ScalingAdjustment']))

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
