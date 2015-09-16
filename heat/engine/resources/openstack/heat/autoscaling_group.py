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
from heat.common import grouputils
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.aws.autoscaling import autoscaling_group as aws_asg
from heat.engine import support
from heat.engine import template


class AutoScalingResourceGroup(aws_asg.AutoScalingGroup):
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
        OUTPUTS, OUTPUTS_LIST, CURRENT_SIZE,
    ) = (
        'outputs', 'outputs_list', 'current_size',
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
              "individual resource. "
              "Requires heat_template_version: 2014-10-16 or higher."),
            support_status=support.SupportStatus(version='2014.2'),
            type=attributes.Schema.MAP
        ),
        OUTPUTS_LIST: attributes.Schema(
            _("A list of the specified attribute of each individual resource. "
              "Requires heat_template_version: 2014-10-16 or higher."),
            support_status=support.SupportStatus(version='2014.2'),
            type=attributes.Schema.LIST
        ),
        CURRENT_SIZE: attributes.Schema(
            _("The current size of AutoscalingResourceGroup."),
            support_status=support.SupportStatus(version='2015.1'),
            type=attributes.Schema.INTEGER
        ),
    }
    update_policy_schema = {}

    def _get_resource_definition(self,
                                 template_version=('heat_template_version',
                                                   '2015-04-30')):
        tmpl = template.Template(dict([template_version]))
        return tmpl.rsrc_defn_from_snippet(None,
                                           self.properties[self.RESOURCE])

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

    def FnGetAtt(self, key, *path):
        if key == self.CURRENT_SIZE:
            return grouputils.get_size(self)
        if path:
            members = grouputils.get_members(self)
            attrs = ((rsrc.name, rsrc.FnGetAtt(*path)) for rsrc in members)
            if key == self.OUTPUTS:
                return dict(attrs)
            if key == self.OUTPUTS_LIST:
                return [value for name, value in attrs]

        if key.startswith("resource."):
            return grouputils.get_nested_attrs(self, key, True, *path)

        raise exception.InvalidTemplateAttribute(resource=self.name,
                                                 key=key)


def resource_mapping():
    return {
        'OS::Heat::AutoScalingGroup': AutoScalingResourceGroup,
    }
