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
import six

from oslo_log import log as logging

from heat.common import environment_format
from heat.common import exception
from heat.common import grouputils
from heat.common.i18n import _
from heat.common import short_id
from heat.common import timeutils as iso8601utils
from heat.engine import attributes
from heat.engine import environment
from heat.engine import output
from heat.engine import properties
from heat.engine.resources import stack_resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.scaling import lbutils
from heat.scaling import rolling_update
from heat.scaling import template

LOG = logging.getLogger(__name__)


(SCALED_RESOURCE_TYPE,) = ('OS::Heat::ScaledResource',)


class InstanceGroup(stack_resource.StackResource):
    """An instance group that can scale arbitrary instances.

    A resource allowing for the creating number of defined with
    AWS::AutoScaling::LaunchConfiguration instances. Allows to associate
    scaled resources with loadbalancer resources.
    """

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

    (OUTPUT_MEMBER_IDS,) = ('references',)

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
                        _('Tag key.'),
                        required=True
                    ),
                    TAG_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        _('Tag value.'),
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

    def validate(self):
        """Add validation for update_policy."""
        self.validate_launchconfig()
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
        # launchconfiguration. This can happen if the actual resource
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
        num_instances = self.properties[self.SIZE]
        initial_template = self._create_template(num_instances)
        return self.create_with_template(initial_template)

    def check_create_complete(self, task):
        """When stack creation is done, update the loadbalancer.

        If any instances failed to be created, delete them.
        """
        done = super(InstanceGroup, self).check_create_complete(task)
        if done:
            self._lb_reload()
        return done

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Updates self.properties, if Properties has changed.

        If Properties has changed, update self.properties, so we
        get the new values during any subsequent adjustment.
        """
        if tmpl_diff:
            # parse update policy
            if tmpl_diff.update_policy_changed():
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
        """Make sure that we add a tag that Ceilometer can pick up.

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
        c_props = conf.frozen_definition().properties(conf.properties_schema,
                                                      conf.context)
        props = {k: v for k, v in c_props.items() if k in c_props.data}
        for key in [conf.BLOCK_DEVICE_MAPPINGS, conf.NOVA_SCHEDULER_HINTS]:
            if props.get(key) is not None:
                props[key] = [{k: v for k, v in prop.items()
                               if k in c_props.data[key][idx]}
                              for idx, prop in enumerate(props[key])]
        if 'InstanceId' in props:
            props = conf.rebuild_lc_properties(props['InstanceId'])
        props['Tags'] = self._tags()
        # if the launch configuration is created from an existing instance.
        # delete the 'InstanceId' property
        props.pop('InstanceId', None)

        return conf, props

    def _get_resource_definition(self):
        conf, props = self._get_conf_properties()
        return rsrc_defn.ResourceDefinition(None,
                                            SCALED_RESOURCE_TYPE,
                                            props,
                                            conf.t.metadata())

    def _create_template(self, num_instances, num_replace=0,
                         template_version=('HeatTemplateFormatVersion',
                                           '2012-12-12')):
        """Create a template to represent autoscaled instances.

        Also see heat.scaling.template.member_definitions.
        """
        instance_definition = self._get_resource_definition()
        old_resources = grouputils.get_member_definitions(self,
                                                          include_failed=True)
        definitions = list(template.member_definitions(
            old_resources, instance_definition, num_instances, num_replace,
            short_id.generate_id))

        child_env = environment.get_child_environment(
            self.stack.env,
            self.child_params(), item_to_remove=self.resource_info)

        tmpl = template.make_template(definitions, version=template_version,
                                      child_env=child_env)

        # Subclasses use HOT templates
        att_func, res_func = 'get_attr', 'get_resource'
        if att_func not in tmpl.functions or res_func not in tmpl.functions:
            att_func, res_func = 'Fn::GetAtt', 'Ref'
        get_attr = functools.partial(tmpl.functions[att_func], None, att_func)
        get_res = functools.partial(tmpl.functions[res_func], None, res_func)
        for odefn in self._nested_output_defns([k for k, d in definitions],
                                               get_attr, get_res):
            tmpl.add_output(odefn)

        return tmpl

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
            msg = _('The current update policy will result in stack update '
                    'timeout.')
            raise ValueError(msg)
        return self.stack.timeout_secs() - total_pause_time

    def _replace(self, min_in_service, batch_size, pause_sec):
        """Replace the instances in the group.

        Replace the instances in the group using updated launch configuration.
        """
        def changing_instances(old_tmpl, new_tmpl):
            updated = set(new_tmpl.resource_definitions(None).items())
            if old_tmpl is not None:
                current = set(old_tmpl.resource_definitions(None).items())
                changing = current ^ updated
            else:
                changing = updated
            # includes instances to be updated and deleted
            return set(k for k, v in changing)

        def pause_between_batch():
            while True:
                try:
                    yield
                except scheduler.Timeout:
                    return

        group_data = self._group_data()
        old_template = group_data.template()

        capacity = group_data.size(include_failed=True)
        batches = list(self._get_batches(capacity, batch_size, min_in_service))

        update_timeout = self._update_timeout(len(batches), pause_sec)

        try:
            for index, (total_capacity, efft_bat_sz) in enumerate(batches):
                template = self._create_template(total_capacity, efft_bat_sz)
                self._lb_reload(exclude=changing_instances(old_template,
                                                           template),
                                refresh_data=False)
                updater = self.update_with_template(template)
                checker = scheduler.TaskRunner(self._check_for_completion,
                                               updater)
                checker(timeout=update_timeout)
                old_template = template
                if index < (len(batches) - 1) and pause_sec > 0:
                    self._lb_reload()
                    waiter = scheduler.TaskRunner(pause_between_batch)
                    waiter(timeout=pause_sec)
        finally:
            self._group_data(refresh=True)
            self._lb_reload()

    @staticmethod
    def _get_batches(capacity, batch_size, min_in_service):
        """Return an iterator over the batches in a batched update.

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

    def _lb_reload(self, exclude=frozenset(), refresh_data=True):
        lb_names = self.properties.get(self.LOAD_BALANCER_NAMES) or []
        if lb_names:
            if refresh_data:
                self._outputs = None
            try:
                all_refids = self.get_output(self.OUTPUT_MEMBER_IDS)
            except (exception.NotFound,
                    exception.TemplateOutputError) as op_err:
                LOG.debug('Falling back to grouputils due to %s', op_err)
                if refresh_data:
                    self._nested = None
                instances = grouputils.get_members(self)
                all_refids = {i.name: i.FnGetRefId() for i in instances}
                names = [i.name for i in instances]
            else:
                group_data = self._group_data(refresh=refresh_data)
                names = group_data.member_names(include_failed=False)

            id_list = [all_refids[n] for n in names
                       if n not in exclude and n in all_refids]
            lbs = [self.stack[name] for name in lb_names]
            lbutils.reconfigure_loadbalancers(lbs, id_list)

    def get_reference_id(self):
        return self.physical_resource_name_or_FnGetRefId()

    def _group_data(self, refresh=False):
        """Return a cached GroupInspector object for the nested stack."""
        if refresh or getattr(self, '_group_inspector', None) is None:
            inspector = grouputils.GroupInspector.from_parent_resource(self)
            self._group_inspector = inspector
        return self._group_inspector

    def _resolve_attribute(self, name):
        """Resolves the resource's attributes.

        Heat extension: "InstanceList" returns comma delimited list of server
        ip addresses.
        """
        if name == self.INSTANCE_LIST:
            def listify(ips):
                return u','.join(ips) or None

            try:
                output = self.get_output(name)
            except (exception.NotFound,
                    exception.TemplateOutputError) as op_err:
                LOG.debug('Falling back to grouputils due to %s', op_err)
            else:
                if isinstance(output, dict):
                    names = self._group_data().member_names(False)
                    return listify(output[n] for n in names if n in output)
                else:
                    LOG.debug('Falling back to grouputils due to '
                              'old (list-style) output format')

            return listify(inst.FnGetAtt('PublicIp') or '0.0.0.0'
                           for inst in grouputils.get_members(self))

    def _nested_output_defns(self, resource_names, get_attr_fn, get_res_fn):
        for attr in self.referenced_attrs():
            if isinstance(attr, six.string_types):
                key = attr
            else:
                key = attr[0]

            if key == self.INSTANCE_LIST:
                value = {r: get_attr_fn([r, 'PublicIp'])
                         for r in resource_names}
                yield output.OutputDefinition(key, value)

        member_ids_value = {r: get_res_fn(r) for r in resource_names}
        yield output.OutputDefinition(self.OUTPUT_MEMBER_IDS,
                                      member_ids_value)

    def child_template(self):
        num_instances = int(self.properties[self.SIZE])
        return self._create_template(num_instances)

    def child_template_files(self, child_env):
        is_rolling_update = (self.action == self.UPDATE and
                             self.update_policy[self.ROLLING_UPDATE])
        return grouputils.get_child_template_files(self.context, self.stack,
                                                   is_rolling_update,
                                                   self.old_template_id)

    def child_params(self):
        """Return the environment for the nested stack."""
        return {
            environment_format.PARAMETERS: {},
            environment_format.RESOURCE_REGISTRY: {
                SCALED_RESOURCE_TYPE: 'AWS::EC2::Instance',
            },
        }

    def get_nested_parameters_stack(self):
        """Return a nested group of size 1 for validation."""
        child_template = self._create_template(1)
        params = self.child_params()
        name = "%s-%s" % (self.stack.name, self.name)
        return self._parse_nested_stack(name, child_template, params)


def resource_mapping():
    return {
        'OS::Heat::InstanceGroup': InstanceGroup,
    }
