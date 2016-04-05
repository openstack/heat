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
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LI
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources import signal_responder
from heat.engine import support
from heat.scaling import cooldown
from heat.scaling import scalingutil as sc_util

LOG = logging.getLogger(__name__)


class AutoScalingPolicy(signal_responder.SignalResponder,
                        cooldown.CooldownMixin):
    """A resource to manage scaling of `OS::Heat::AutoScalingGroup`.

    **Note** while it may incidentally support
    `AWS::AutoScaling::AutoScalingGroup` for now, please don't use it for that
    purpose and use `AWS::AutoScaling::ScalingPolicy` instead.
    """
    PROPERTIES = (
        AUTO_SCALING_GROUP_NAME, SCALING_ADJUSTMENT, ADJUSTMENT_TYPE,
        COOLDOWN, MIN_ADJUSTMENT_STEP
    ) = (
        'auto_scaling_group_id', 'scaling_adjustment', 'adjustment_type',
        'cooldown', 'min_adjustment_step',
    )

    ATTRIBUTES = (
        ALARM_URL, SIGNAL_URL
    ) = (
        'alarm_url', 'signal_url'
    )

    properties_schema = {
        # TODO(Qiming): property name should be AUTO_SCALING_GROUP_ID
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
                constraints.AllowedValues(
                    [sc_util.CHANGE_IN_CAPACITY,
                     sc_util.EXACT_CAPACITY,
                     sc_util.PERCENT_CHANGE_IN_CAPACITY]),
            ],
            update_allowed=True
        ),
        COOLDOWN: properties.Schema(
            properties.Schema.NUMBER,
            _('Cooldown period, in seconds.'),
            update_allowed=True
        ),
        MIN_ADJUSTMENT_STEP: properties.Schema(
            properties.Schema.INTEGER,
            _('Minimum number of resources that are added or removed '
              'when the AutoScaling group scales up or down. This can '
              'be used only when specifying percent_change_in_capacity '
              'for the adjustment_type property.'),
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
            _("A signed url to handle the alarm."),
            type=attributes.Schema.STRING
        ),
        SIGNAL_URL: attributes.Schema(
            _("A url to handle the alarm using native API."),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.STRING
        ),
    }

    def validate(self):
        """
        Add validation for min_adjustment_step
        """
        super(AutoScalingPolicy, self).validate()
        self._validate_min_adjustment_step()

    def _validate_min_adjustment_step(self):
        adjustment_type = self.properties.get(self.ADJUSTMENT_TYPE)
        adjustment_step = self.properties.get(self.MIN_ADJUSTMENT_STEP)
        if (adjustment_type != sc_util.PERCENT_CHANGE_IN_CAPACITY
                and adjustment_step is not None):
            raise exception.ResourcePropertyValueDependency(
                prop1=self.MIN_ADJUSTMENT_STEP,
                prop2=self.ADJUSTMENT_TYPE,
                value=sc_util.PERCENT_CHANGE_IN_CAPACITY)

    def handle_create(self):
        super(AutoScalingPolicy, self).handle_create()
        self.resource_id_set(self._get_user_id())

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """
        If Properties has changed, update self.properties, so we get the new
        values during any subsequent adjustment.
        """
        if prop_diff:
            self.properties = json_snippet.properties(self.properties_schema,
                                                      self.context)

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

        LOG.info(_LI('Alarm %(name)s, new state %(state)s'),
                 {'name': self.name, 'state': alarm_state})

        if alarm_state != 'alarm':
            raise exception.NoActionRequired()
        if not self._is_scaling_allowed():
            LOG.info(_LI("%(name)s NOT performing scaling action, "
                         "cooldown %(cooldown)s"),
                     {'name': self.name,
                      'cooldown': self.properties[self.COOLDOWN]})
            raise exception.NoActionRequired()

        asgn_id = self.properties[self.AUTO_SCALING_GROUP_NAME]
        group = self.stack.resource_by_refid(asgn_id)
        changed_size = False
        try:
            if group is None:
                raise exception.NotFound(_('Alarm %(alarm)s could not find '
                                           'scaling group named "%(group)s"'
                                           ) % {'alarm': self.name,
                                                'group': asgn_id})

            LOG.info(_LI('%(name)s Alarm, adjusting Group %(group)s with id '
                         '%(asgn_id)s by %(filter)s'),
                     {'name': self.name, 'group': group.name,
                      'asgn_id': asgn_id,
                      'filter': self.properties[self.SCALING_ADJUSTMENT]})
            changed_size = group.adjust(
                self.properties[self.SCALING_ADJUSTMENT],
                self.properties[self.ADJUSTMENT_TYPE],
                self.properties[self.MIN_ADJUSTMENT_STEP],
                signal=True)
        finally:
            self._finished_scaling("%s : %s" % (
                self.properties[self.ADJUSTMENT_TYPE],
                self.properties[self.SCALING_ADJUSTMENT]),
                changed_size=changed_size)

    def _resolve_attribute(self, name):
        if name == self.ALARM_URL:
            return six.text_type(self._get_ec2_signed_url())
        elif name == self.SIGNAL_URL:
            return six.text_type(self._get_heat_signal_url())

    def FnGetRefId(self):
        return resource.Resource.FnGetRefId(self)


def resource_mapping():
    return {
        'OS::Heat::ScalingPolicy': AutoScalingPolicy,
    }
