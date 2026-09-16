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

from oslo_log import log as logging
from oslo_utils import excutils

from heat.common import exception
from heat.common import grouputils
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine.hot import template
from heat.engine.notification import autoscaling as notification
from heat.engine import output
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.heat import instance_group as instgrp
from heat.engine import rsrc_defn
from heat.engine import support
from heat.scaling import cooldown
from heat.scaling import scalingutil as sc_util

LOG = logging.getLogger(__name__)


class HOTInterpreter(template.HOTemplate20150430):
    def __new__(cls):
        return object.__new__(cls)

    def __init__(self):
        version = {'heat_template_version': '2015-04-30'}
        super(HOTInterpreter, self).__init__(version)

    def parse(self, stack, snippet, path=''):
        return snippet

    def parse_conditions(self, stack, snippet, path=''):
        return snippet


class AutoScalingResourceGroup(cooldown.CooldownMixin,
                               instgrp.InstanceGroup):
    """An autoscaling group that can scale arbitrary resources.

    An autoscaling group allows the creation of a desired count of similar
    resources, which are defined with the resource property in HOT format.
    If there is a need to create many of the same resources (e.g. one
    hundred sets of Server, WaitCondition and WaitConditionHandle or even
    Neutron Nets), AutoScalingGroup is a convenient and easy way to do that.
    """

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
        OUTPUTS, OUTPUTS_LIST, CURRENT_SIZE, REFS, REFS_MAP,
    ) = (
        'outputs', 'outputs_list', 'current_size', 'refs', 'refs_map',
    )

    (OUTPUT_MEMBER_IDS,) = (REFS_MAP,)

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
            update_allowed=True,
            schema={
                MIN_IN_SERVICE: properties.Schema(
                    properties.Schema.INTEGER,
                    _('The minimum number of resources in service while '
                      'rolling updates are being executed.'),
                    constraints=[constraints.Range(min=0)],
                    default=0),
                MAX_BATCH_SIZE: properties.Schema(
                    properties.Schema.INTEGER,
                    _('The maximum number of resources to replace at once.'),
                    constraints=[constraints.Range(min=1)],
                    default=1),
                PAUSE_TIME: properties.Schema(
                    properties.Schema.NUMBER,
                    _('The number of seconds to wait between batches of '
                      'updates.'),
                    constraints=[constraints.Range(min=0)],
                    default=0),
            },
            # A default policy has all fields with their own default values.
            default={
                MIN_IN_SERVICE: 0,
                MAX_BATCH_SIZE: 1,
                PAUSE_TIME: 0,
            },
        ),
    }

    attributes_schema = {
        OUTPUTS: attributes.Schema(
            _("A map of resource names to the specified attribute of each "
              "individual resource that is part of the AutoScalingGroup. "
              "This map specifies output parameters that are available "
              "once the AutoScalingGroup has been instantiated."),
            support_status=support.SupportStatus(version='2014.2'),
            type=attributes.Schema.MAP
        ),
        OUTPUTS_LIST: attributes.Schema(
            _("A list of the specified attribute of each individual resource "
              "that is part of the AutoScalingGroup. This list of attributes "
              "is available as an output once the AutoScalingGroup has been "
              "instantiated."),
            support_status=support.SupportStatus(version='2014.2'),
            type=attributes.Schema.LIST
        ),
        CURRENT_SIZE: attributes.Schema(
            _("The current size of AutoscalingResourceGroup."),
            support_status=support.SupportStatus(version='2015.1'),
            type=attributes.Schema.INTEGER
        ),
        REFS: attributes.Schema(
            _("A list of resource IDs for the resources in the group."),
            type=attributes.Schema.LIST,
            support_status=support.SupportStatus(version='7.0.0'),
        ),
        REFS_MAP: attributes.Schema(
            _("A map of resource names to IDs for the resources in "
              "the group."),
            type=attributes.Schema.MAP,
            support_status=support.SupportStatus(version='7.0.0'),
        ),

    }
    update_policy_schema = {}

    def get_size(self):
        """Get desired capacity."""
        return self.properties[self.DESIRED_CAPACITY]

    def handle_create(self):
        return self.create_with_template(self.child_template())

    def _tags(self):
        # The group name must match what is returned from FnGetRefId.
        autoscaling_tag = [{self.TAG_KEY: 'metering.AutoScalingGroupName',
                            self.TAG_VALUE: self.FnGetRefId()}]
        return super(AutoScalingResourceGroup, self)._tags() + autoscaling_tag

    def check_create_complete(self, task):
        """Update cooldown timestamp after create succeeds."""
        done = super(AutoScalingResourceGroup, self).check_create_complete(
            task)
        cooldown = self.properties[self.COOLDOWN]
        if done:
            self._finished_scaling(cooldown,
                                   "%s : %s" % (sc_util.EXACT_CAPACITY,
                                                grouputils.get_size(self)))
        return done

    def check_update_complete(self, cookie):
        """Update the cooldown timestamp after update succeeds."""
        done = super(AutoScalingResourceGroup, self).check_update_complete(
            cookie)
        cooldown = self.properties[self.COOLDOWN]
        if done:
            self._finished_scaling(cooldown,
                                   "%s : %s" % (sc_util.EXACT_CAPACITY,
                                                grouputils.get_size(self)))
        return done

    def _get_new_capacity(self, capacity,
                          adjustment,
                          adjustment_type=sc_util.EXACT_CAPACITY,
                          min_adjustment_step=None):
        lower = self.properties[self.MIN_SIZE]
        upper = self.properties[self.MAX_SIZE]
        return sc_util.calculate_new_capacity(capacity, adjustment,
                                              adjustment_type,
                                              min_adjustment_step,
                                              lower, upper)

    def resize(self, capacity):
        try:
            super(AutoScalingResourceGroup, self).resize(capacity)
        finally:
            # allow outputs to be re-resolved
            self.clear_stored_attributes()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Updates self.properties, if Properties has changed.

        If Properties has changed, update self.properties, so we get the new
        values during any subsequent adjustment.
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
            # Replace resources first if the definition has changed
            self._try_rolling_update(prop_diff)

        # Update will happen irrespective of whether auto-scaling
        # is in progress or not.
        capacity = grouputils.get_size(self)
        desired_capacity = self.properties[self.DESIRED_CAPACITY] or capacity
        new_capacity = self._get_new_capacity(capacity, desired_capacity)
        self.resize(new_capacity)

    def adjust(self, adjustment,
               adjustment_type=sc_util.CHANGE_IN_CAPACITY,
               min_adjustment_step=None, cooldown=None):
        """Adjust the size of the scaling group if the cooldown permits."""
        if self.status != self.COMPLETE:
            LOG.info("%s NOT performing scaling adjustment, "
                     "when status is not COMPLETE", self.name)
            raise resource.NoActionRequired

        capacity = grouputils.get_size(self)
        new_capacity = self._get_new_capacity(capacity, adjustment,
                                              adjustment_type,
                                              min_adjustment_step)
        if new_capacity == capacity:
            LOG.info("%s NOT performing scaling adjustment, "
                     "as there is no change in capacity.", self.name)
            raise resource.NoActionRequired

        if cooldown is None:
            cooldown = self.properties[self.COOLDOWN]

        self._check_scaling_allowed(cooldown)

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
        size_changed = False
        try:
            notification.send(**notif)
            try:
                self.resize(new_capacity)
            except Exception as resize_ex:
                with excutils.save_and_reraise_exception():
                    try:
                        notif.update({'suffix': 'error',
                                      'message': str(resize_ex),
                                      'capacity': grouputils.get_size(self),
                                      })
                        notification.send(**notif)
                    except Exception:
                        LOG.exception('Failed sending error notification')
            else:
                size_changed = True
                notif.update({
                    'suffix': 'end',
                    'capacity': new_capacity,
                    'message': _("End resizing the group %(group)s") % {
                        'group': notif['groupname']},
                })
                notification.send(**notif)
        except Exception:
            LOG.error("Error in performing scaling adjustment for "
                      "group %s.", self.name)
            raise
        finally:
            self._finished_scaling(cooldown,
                                   "%s : %s" % (adjustment_type, adjustment),
                                   size_changed=size_changed)

    def validate(self):
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

        super(AutoScalingResourceGroup, self).validate()

    def child_template(self):
        if self.properties[self.DESIRED_CAPACITY]:
            num_instances = self.properties[self.DESIRED_CAPACITY]
        else:
            num_instances = self.properties[self.MIN_SIZE]
        return self._create_template(num_instances)

    def _get_resource_definition(self):
        resource_def = self.properties[self.RESOURCE]
        defn_data = dict(HOTInterpreter()._rsrc_defn_args(None, 'member',
                                                          resource_def))
        return rsrc_defn.ResourceDefinition(None, **defn_data)

    def child_template_files(self, child_env):
        is_update = self.action == self.UPDATE
        return grouputils.get_child_template_files(self.context, self.stack,
                                                   is_update,
                                                   self.old_template_id)

    def _try_rolling_update(self, prop_diff):
        if self.RESOURCE in prop_diff:
            policy = self.properties[self.ROLLING_UPDATES]
            self._replace(policy[self.MIN_IN_SERVICE],
                          policy[self.MAX_BATCH_SIZE],
                          policy[self.PAUSE_TIME])

    def _create_template(self, num_instances, num_replace=0,
                         template_version=('heat_template_version',
                                           '2015-04-30')):
        """Create a template in the HOT format for the nested stack."""
        return super(AutoScalingResourceGroup,
                     self)._create_template(num_instances, num_replace,
                                            template_version=template_version)

    def _attribute_output_name(self, *attr_path):
        return ', '.join(str(a) for a in attr_path)

    def get_attribute(self, key, *path):  # noqa: C901
        if key == self.CURRENT_SIZE:
            return grouputils.get_size(self)

        op_key = key
        op_path = path
        keycomponents = None
        if key == self.OUTPUTS_LIST:
            op_key = self.OUTPUTS
        elif key == self.REFS:
            op_key = self.REFS_MAP
        elif key.startswith("resource."):
            keycomponents = key.split('.', 2)
            if len(keycomponents) > 2:
                op_path = (keycomponents[2],) + path
            op_key = self.OUTPUTS if op_path else self.REFS_MAP
        try:
            output = self.get_output(self._attribute_output_name(op_key,
                                                                 *op_path))
        except (exception.NotFound,
                exception.TemplateOutputError) as op_err:
            LOG.debug('Falling back to grouputils due to %s', op_err)

            if key == self.REFS:
                return grouputils.get_member_refids(self)
            if key == self.REFS_MAP:
                members = grouputils.get_members(self)
                return {m.name: m.resource_id for m in members}
            if path and key in {self.OUTPUTS, self.OUTPUTS_LIST}:
                members = grouputils.get_members(self)
                attrs = ((rsrc.name,
                          rsrc.FnGetAtt(*path)) for rsrc in members)
                if key == self.OUTPUTS:
                    return dict(attrs)
                if key == self.OUTPUTS_LIST:
                    return [value for name, value in attrs]
            if keycomponents is not None:
                return grouputils.get_nested_attrs(self, key, True, *path)
        else:
            if key in {self.REFS, self.REFS_MAP}:
                names = self._group_data().member_names(False)
                if key == self.REFS:
                    return [output[n] for n in names if n in output]
                else:
                    return {n: output[n] for n in names if n in output}

            if path and key in {self.OUTPUTS_LIST, self.OUTPUTS}:
                names = self._group_data().member_names(False)
                if key == self.OUTPUTS_LIST:
                    return [output[n] for n in names if n in output]
                else:
                    return {n: output[n] for n in names if n in output}

            if keycomponents is not None:
                names = list(self._group_data().member_names(False))
                index = keycomponents[1]
                try:
                    resource_name = names[int(index)]
                    return output[resource_name]
                except (IndexError, KeyError):
                    raise exception.NotFound(_("Member '%(mem)s' not found "
                                               "in group resource '%(grp)s'.")
                                             % {'mem': index,
                                                'grp': self.name})

        raise exception.InvalidTemplateAttribute(resource=self.name,
                                                 key=key)

    def _nested_output_defns(self, resource_names, get_attr_fn, get_res_fn):
        for attr in self.referenced_attrs():
            if isinstance(attr, str):
                key, path = attr, []
            else:
                key, path = attr[0], list(attr[1:])
            # Always use map types, as list order is not defined at
            # template generation time.
            if key == self.OUTPUTS_LIST:
                key = self.OUTPUTS
            if key.startswith("resource."):
                keycomponents = key.split('.', 2)
                path = keycomponents[2:] + path
                if path:
                    key = self.OUTPUTS
            output_name = self._attribute_output_name(key, *path)

            if key == self.OUTPUTS and path:
                value = {r: get_attr_fn([r] + path) for r in resource_names}
                yield output.OutputDefinition(output_name, value)

        # Always define an output for the member IDs, which also doubles as the
        # output used by the REFS and REFS_MAP attributes.
        member_ids_value = {r: get_res_fn(r) for r in resource_names}
        yield output.OutputDefinition(self.OUTPUT_MEMBER_IDS,
                                      member_ids_value)


def resource_mapping():
    return {
        'OS::Heat::AutoScalingGroup': AutoScalingResourceGroup,
    }
