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

from heat.common import environment_format
from heat.common import grouputils
from heat.common.i18n import _
from heat.common import short_id
from heat.common import timeutils as iso8601utils
from heat.engine import attributes
from heat.engine import environment
from heat.engine import function
from heat.engine import properties
from heat.engine.resources import stack_resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.scaling import lbutils
from heat.scaling import rolling_update
from heat.scaling import template


(SCALED_RESOURCE_TYPE,) = ('OS::Heat::ScaledResource',)


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
            _('The reference to a LaunchConfiguration resource.'),
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
              "(Heat extension)."),
            type=attributes.Schema.STRING
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

        if self.update_policy is not None:
            policy_name = self.ROLLING_UPDATE
            if (policy_name in self.update_policy and
                    self.update_policy[policy_name] is not None):
                pause_time = self.update_policy[policy_name][self.PAUSE_TIME]
                if iso8601utils.parse_isoduration(pause_time) > 3600:
                    msg = _('Maximum %s is 1 hour.') % self.PAUSE_TIME
                    raise ValueError(msg)

    def validate_launchconfig(self):
        # It seems to be a common error to not have a dependency on the
        # launchconfiguration. This can happen if the the actual resource
        # name is used instead of {get_resource: launch_conf} and no
        # depends_on is used.

        conf_refid = self.properties.get(self.LAUNCH_CONFIGURATION_NAME)
        if conf_refid:
            conf = self.stack.resource_by_refid(conf_refid)
            if conf is None:
                raise ValueError(_('%(lc)s (%(ref)s)'
                                   ' reference can not be found.')
                                 % dict(lc=self.LAUNCH_CONFIGURATION_NAME,
                                        ref=conf_refid))
            if self.name not in conf.required_by():
                raise ValueError(_('%(lc)s (%(ref)s)'
                                   ' requires a reference to the'
                                   ' configuration not just the name of the'
                                   ' resource.') % dict(
                                       lc=self.LAUNCH_CONFIGURATION_NAME,
                                       ref=conf_refid))

    def handle_create(self):
        """Create a nested stack and add the initial resources to it."""
        self.validate_launchconfig()
        num_instances = self.properties[self.SIZE]
        initial_template = self._create_template(num_instances)
        return self.create_with_template(initial_template)

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
            if rsrc_defn.UPDATE_POLICY in tmpl_diff:
                up = json_snippet.update_policy(self.update_policy_schema,
                                                self.context)
                self.update_policy = up

        self.properties = json_snippet.properties(self.properties_schema,
                                                  self.context)
        if prop_diff:
            # Replace instances first if launch configuration has changed
            self._try_rolling_update(prop_diff)

        # Get the current capacity, we may need to adjust if
        # Size has changed
        if self.properties[self.SIZE] is not None:
            self.resize(self.properties[self.SIZE])
        else:
            curr_size = grouputils.get_size(self)
            self.resize(curr_size)

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

    def _get_conf_properties(self):
        conf_refid = self.properties[self.LAUNCH_CONFIGURATION_NAME]
        conf = self.stack.resource_by_refid(conf_refid)
        props = function.resolve(conf.properties.data)
        if 'InstanceId' in props:
            props = conf.rebuild_lc_properties(props['InstanceId'])

        props['Tags'] = self._tags()
        # if the launch configuration is created from an existing instance.
        # delete the 'InstanceId' property
        props.pop('InstanceId', None)

        return conf, props

    def _get_instance_definition(self):
        conf, props = self._get_conf_properties()
        return rsrc_defn.ResourceDefinition(None,
                                            SCALED_RESOURCE_TYPE,
                                            props,
                                            conf.t.metadata())

    def _get_instance_templates(self):
        """Get templates for resource instances."""
        return [(instance.name, instance.t)
                for instance in grouputils.get_members(self)]

    def _create_template(self, num_instances, num_replace=0,
                         template_version=('HeatTemplateFormatVersion',
                                           '2012-12-12')):
        """
        Create a template to represent autoscaled instances.

        Also see heat.scaling.template.member_definitions.
        """
        instance_definition = self._get_instance_definition()
        old_resources = self._get_instance_templates()
        definitions = template.member_definitions(
            old_resources, instance_definition, num_instances, num_replace,
            short_id.generate_id)

        child_env = environment.get_child_environment(
            self.stack.env,
            self.child_params(), item_to_remove=self.resource_info)

        return template.make_template(definitions, version=template_version,
                                      child_env=child_env)

    def _try_rolling_update(self, prop_diff):
        if (self.update_policy[self.ROLLING_UPDATE] and
                self.LAUNCH_CONFIGURATION_NAME in prop_diff):
            policy = self.update_policy[self.ROLLING_UPDATE]
            pause_sec = iso8601utils.parse_isoduration(policy[self.PAUSE_TIME])
            self._replace(policy[self.MIN_INSTANCES_IN_SERVICE],
                          policy[self.MAX_BATCH_SIZE],
                          pause_sec)

    def _update_timeout(self, batch_cnt, pause_sec):
        total_pause_time = pause_sec * max(batch_cnt - 1, 0)
        if total_pause_time >= self.stack.timeout_secs():
            msg = _('The current %s will result in stack update '
                    'timeout.') % rsrc_defn.UPDATE_POLICY
            raise ValueError(msg)
        return self.stack.timeout_secs() - total_pause_time

    def _replace(self, min_in_service, batch_size, pause_sec):
        """
        Replace the instances in the group using updated launch configuration
        """
        def changing_instances(tmpl):
            instances = grouputils.get_members(self)
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
        batches = list(self._get_batches(capacity, batch_size, min_in_service))

        update_timeout = self._update_timeout(len(batches), pause_sec)

        try:
            for index, (total_capacity, efft_bat_sz) in enumerate(batches):
                template = self._create_template(total_capacity, efft_bat_sz)
                self._lb_reload(exclude=changing_instances(template))
                updater = self.update_with_template(template)
                checker = scheduler.TaskRunner(self._check_for_completion,
                                               updater)
                checker(timeout=update_timeout)
                if index < (len(batches) - 1) and pause_sec > 0:
                    self._lb_reload()
                    waiter = scheduler.TaskRunner(pause_between_batch)
                    waiter(timeout=pause_sec)
        finally:
            self._lb_reload()

    @staticmethod
    def _get_batches(capacity, batch_size, min_in_service):
        """
        Return an iterator over the batches in a batched update.

        Each batch is a tuple comprising the total size of the group after
        processing the batch, and the number of members that can receive the
        new definition in that batch (either by creating a new member or
        updating an existing one).
        """

        efft_capacity = capacity
        updated = 0

        while rolling_update.needs_update(capacity, efft_capacity, updated):
            batch = rolling_update.next_batch(capacity, efft_capacity,
                                              updated, batch_size,
                                              min_in_service)
            yield batch
            efft_capacity, num_updates = batch
            updated += num_updates

    def _check_for_completion(self, updater):
        while not self.check_update_complete(updater):
            yield

    def resize(self, new_capacity):
        """Resize the instance group to the new capacity.

        When shrinking, the oldest instances will be removed.
        """
        new_template = self._create_template(new_capacity)
        try:
            updater = self.update_with_template(new_template)
            checker = scheduler.TaskRunner(self._check_for_completion, updater)
            checker(timeout=self.stack.timeout_secs())
        finally:
            # Reload the LB in any case, so it's only pointing at healthy
            # nodes.
            self._lb_reload()

    def _lb_reload(self, exclude=None):
        lb_names = self.properties.get(self.LOAD_BALANCER_NAMES, None)
        if lb_names:
            lb_dict = dict((name, self.stack[name]) for name in lb_names)
            lbutils.reload_loadbalancers(self, lb_dict, exclude)

    def FnGetRefId(self):
        return self.physical_resource_name_or_FnGetRefId()

    def _resolve_attribute(self, name):
        '''
        heat extension: "InstanceList" returns comma delimited list of server
        ip addresses.
        '''
        if name == self.INSTANCE_LIST:
            return u','.join(inst.FnGetAtt('PublicIp')
                             for inst in grouputils.get_members(self)) or None

    def child_template(self):
        num_instances = int(self.properties[self.SIZE])
        return self._create_template(num_instances)

    def child_params(self):
        """Return the environment for the nested stack."""
        return {
            environment_format.PARAMETERS: {},
            environment_format.RESOURCE_REGISTRY: {
                SCALED_RESOURCE_TYPE: 'AWS::EC2::Instance',
            },
        }


def resource_mapping():
    return {
        'OS::Heat::InstanceGroup': InstanceGroup,
    }
