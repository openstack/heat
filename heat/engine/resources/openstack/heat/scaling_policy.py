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
from heat.scaling import cooldown

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
        COOLDOWN,
    ) = (
        'auto_scaling_group_id', 'scaling_adjustment', 'adjustment_type',
        'cooldown',
    )

    EXACT_CAPACITY, CHANGE_IN_CAPACITY, PERCENT_CHANGE_IN_CAPACITY = (
        'exact_capacity', 'change_in_capacity', 'percent_change_in_capacity')

    ATTRIBUTES = (
        ALARM_URL,
    ) = (
        'alarm_url',
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
                constraints.AllowedValues([CHANGE_IN_CAPACITY,
                                           EXACT_CAPACITY,
                                           PERCENT_CHANGE_IN_CAPACITY]),
            ],
            update_allowed=True
        ),
        COOLDOWN: properties.Schema(
            properties.Schema.NUMBER,
            _('Cooldown period, in seconds.'),
            update_allowed=True
        ),
    }

    attributes_schema = {
        ALARM_URL: attributes.Schema(
            _("A signed url to handle the alarm.")
        ),
    }

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

    def _get_adjustement_type(self):
        adjustment_type = self.properties[self.ADJUSTMENT_TYPE]
        return ''.join([t.capitalize() for t in adjustment_type.split('_')])

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
            raise resource.NoActionRequired()
        if self._cooldown_inprogress():
            LOG.info(_LI("%(name)s NOT performing scaling action, "
                         "cooldown %(cooldown)s"),
                     {'name': self.name,
                      'cooldown': self.properties[self.COOLDOWN]})
            raise resource.NoActionRequired()

        asgn_id = self.properties[self.AUTO_SCALING_GROUP_NAME]
        group = self.stack.resource_by_refid(asgn_id)
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
            adjustment_type = self._get_adjustement_type()
            group.adjust(self.properties[self.SCALING_ADJUSTMENT],
                         adjustment_type)

        finally:
            self._cooldown_timestamp("%s : %s" % (
                self.properties[self.ADJUSTMENT_TYPE],
                self.properties[self.SCALING_ADJUSTMENT]))

    def _resolve_attribute(self, name):
        if name == self.ALARM_URL and self.resource_id is not None:
            return six.text_type(self._get_signed_url())

    def FnGetRefId(self):
        return resource.Resource.FnGetRefId(self)


def resource_mapping():
    return {
        'OS::Heat::ScalingPolicy': AutoScalingPolicy,
    }
