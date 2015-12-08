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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.heat import scaling_policy as heat_sp
from heat.scaling import scalingutil as sc_util


class AWSScalingPolicy(heat_sp.AutoScalingPolicy):
    PROPERTIES = (
        AUTO_SCALING_GROUP_NAME, SCALING_ADJUSTMENT, ADJUSTMENT_TYPE,
        COOLDOWN, MIN_ADJUSTMENT_STEP,
    ) = (
        'AutoScalingGroupName', 'ScalingAdjustment', 'AdjustmentType',
        'Cooldown', 'MinAdjustmentStep',
    )

    ATTRIBUTES = (
        ALARM_URL,
    ) = (
        'AlarmUrl',
    )

    properties_schema = {
        AUTO_SCALING_GROUP_NAME: properties.Schema(
            properties.Schema.STRING,
            _('AutoScaling group name to apply policy to.'),
            required=True
        ),
        SCALING_ADJUSTMENT: properties.Schema(
            properties.Schema.INTEGER,
            _('Size of adjustment.'),
            required=True,
            update_allowed=True
        ),
        ADJUSTMENT_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of adjustment (absolute or percentage).'),
            required=True,
            constraints=[
                constraints.AllowedValues(
                    [sc_util.CFN_CHANGE_IN_CAPACITY,
                     sc_util.CFN_EXACT_CAPACITY,
                     sc_util.CFN_PERCENT_CHANGE_IN_CAPACITY]),
            ],
            update_allowed=True
        ),
        COOLDOWN: properties.Schema(
            properties.Schema.INTEGER,
            _('Cooldown period, in seconds.'),
            update_allowed=True
        ),
        MIN_ADJUSTMENT_STEP: properties.Schema(
            properties.Schema.INTEGER,
            _('Minimum number of resources that are added or removed '
              'when the AutoScaling group scales up or down. This can '
              'be used only when specifying PercentChangeInCapacity '
              'for the AdjustmentType property.'),
            constraints=[
                constraints.Range(
                    min=0,
                ),
            ],
            update_allowed=True
        ),

    }

    attributes_schema = {
        ALARM_URL: attributes.Schema(
            _("A signed url to handle the alarm. (Heat extension)."),
            type=attributes.Schema.STRING
        ),
    }

    def _validate_min_adjustment_step(self):
        adjustment_type = self.properties.get(self.ADJUSTMENT_TYPE)
        adjustment_step = self.properties.get(self.MIN_ADJUSTMENT_STEP)
        if (adjustment_type != sc_util.CFN_PERCENT_CHANGE_IN_CAPACITY
                and adjustment_step is not None):
            raise exception.ResourcePropertyValueDependency(
                prop1=self.MIN_ADJUSTMENT_STEP,
                prop2=self.ADJUSTMENT_TYPE,
                value=sc_util.CFN_PERCENT_CHANGE_IN_CAPACITY)

    def get_reference_id(self):
        if self.resource_id is not None:
            return six.text_type(self._get_ec2_signed_url())
        else:
            return six.text_type(self.name)


def resource_mapping():
    return {
        'AWS::AutoScaling::ScalingPolicy': AWSScalingPolicy,
    }
