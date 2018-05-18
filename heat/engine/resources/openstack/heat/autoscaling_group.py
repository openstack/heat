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

import six

from oslo_log import log as logging

from heat.common import exception
from heat.common import grouputils
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine.hot import template
from heat.engine import output
from heat.engine import properties
from heat.engine.resources.aws.autoscaling import autoscaling_group as aws_asg
from heat.engine import rsrc_defn
from heat.engine import support

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


class AutoScalingResourceGroup(aws_asg.AutoScalingGroup):
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
        return ', '.join(six.text_type(a) for a in attr_path)

    def get_attribute(self, key, *path):
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
            if isinstance(attr, six.string_types):
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
