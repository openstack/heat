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

from heat.common.i18n import _
from heat.common.i18n import _LI
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources import signal_responder
from heat.engine import support

LOG = logging.getLogger(__name__)


class Restarter(signal_responder.SignalResponder):

    support_status = support.SupportStatus(
        support.DEPRECATED,
        _('The HARestarter resource type is deprecated and will be removed '
          'in a future release of Heat, once it has support for auto-healing '
          'any type of resource. Note that HARestarter does *not* actually '
          'restart servers - it deletes and then recreates them. It also does '
          'the same to all dependent resources, and may therefore exhibit '
          'unexpected and undesirable behaviour. Avoid.'),
        version='2015.1'
    )

    PROPERTIES = (
        INSTANCE_ID,
    ) = (
        'InstanceId',
    )

    ATTRIBUTES = (
        ALARM_URL,
    ) = (
        'AlarmUrl',
    )

    properties_schema = {
        INSTANCE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Instance ID to be restarted.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('nova.server')
            ]
        ),
    }

    attributes_schema = {
        ALARM_URL: attributes.Schema(
            _("A signed url to handle the alarm (Heat extension)."),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        super(Restarter, self).handle_create()
        self.resource_id_set(self._get_user_id())

    def handle_signal(self, details=None):
        if details is None:
            alarm_state = 'alarm'
        else:
            alarm_state = details.get('state', 'alarm').lower()

        LOG.info(_LI('%(name)s Alarm, new state %(state)s'),
                 {'name': self.name, 'state': alarm_state})

        if alarm_state != 'alarm':
            return

        target_id = self.properties[self.INSTANCE_ID]
        victim = self.stack.resource_by_refid(target_id)
        if victim is None:
            LOG.info(_LI('%(name)s Alarm, can not find instance '
                         '%(instance)s'),
                     {'name': self.name,
                      'instance': target_id})
            return

        LOG.info(_LI('%(name)s Alarm, restarting resource: %(victim)s'),
                 {'name': self.name, 'victim': victim.name})
        self.stack.restart_resource(victim.name)

    def _resolve_attribute(self, name):
        """Resolves the resource's attributes.

        Heat extension: "AlarmUrl" returns the url to post to the policy
        when there is an alarm.
        """
        if name == self.ALARM_URL and self.resource_id is not None:
            return six.text_type(self._get_ec2_signed_url())


def resource_mapping():
    return {
        'OS::Heat::HARestarter': Restarter,
    }
