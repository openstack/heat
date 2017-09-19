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

from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support

from six.moves.urllib import parse as urlparse


COMMON_PROPERTIES = (
    ALARM_ACTIONS, OK_ACTIONS, INSUFFICIENT_DATA_ACTIONS,
    ALARM_QUEUES, OK_QUEUES, INSUFFICIENT_DATA_QUEUES,
    REPEAT_ACTIONS, DESCRIPTION, ENABLED, TIME_CONSTRAINTS, SEVERITY,
) = (
    'alarm_actions', 'ok_actions', 'insufficient_data_actions',
    'alarm_queues', 'ok_queues', 'insufficient_data_queues',
    'repeat_actions', 'description', 'enabled', 'time_constraints', 'severity',
)

INTERNAL_PROPERTIES = (ALARM_QUEUES, OK_QUEUES, INSUFFICIENT_DATA_QUEUES)

_TIME_CONSTRAINT_KEYS = (
    NAME, START, DURATION, TIMEZONE, TIME_CONSTRAINT_DESCRIPTION,
) = (
    'name', 'start', 'duration', 'timezone', 'description',
)

common_properties_schema = {
    DESCRIPTION: properties.Schema(
        properties.Schema.STRING,
        _('Description for the alarm.'),
        update_allowed=True
    ),
    ENABLED: properties.Schema(
        properties.Schema.BOOLEAN,
        _('True if alarm evaluation/actioning is enabled.'),
        default='true',
        update_allowed=True
    ),
    ALARM_ACTIONS: properties.Schema(
        properties.Schema.LIST,
        _('A list of URLs (webhooks) to invoke when state transitions to '
          'alarm.'),
        update_allowed=True
    ),
    OK_ACTIONS: properties.Schema(
        properties.Schema.LIST,
        _('A list of URLs (webhooks) to invoke when state transitions to '
          'ok.'),
        update_allowed=True
    ),
    INSUFFICIENT_DATA_ACTIONS: properties.Schema(
        properties.Schema.LIST,
        _('A list of URLs (webhooks) to invoke when state transitions to '
          'insufficient-data.'),
        update_allowed=True
    ),
    ALARM_QUEUES: properties.Schema(
        properties.Schema.LIST,
        _('A list of Zaqar queues to post to when state transitions to '
          'alarm.'),
        support_status=support.SupportStatus(version='8.0.0'),
        schema=properties.Schema(
            properties.Schema.STRING,
            constraints=[constraints.CustomConstraint('zaqar.queue')]
        ),
        default=[],
        update_allowed=True
    ),
    OK_QUEUES: properties.Schema(
        properties.Schema.LIST,
        _('A list of Zaqar queues to post to when state transitions to '
          'ok.'),
        support_status=support.SupportStatus(version='8.0.0'),
        schema=properties.Schema(
            properties.Schema.STRING,
            constraints=[constraints.CustomConstraint('zaqar.queue')]
        ),
        default=[],
        update_allowed=True
    ),
    INSUFFICIENT_DATA_QUEUES: properties.Schema(
        properties.Schema.LIST,
        _('A list of Zaqar queues to post to when state transitions to '
          'insufficient-data.'),
        support_status=support.SupportStatus(version='8.0.0'),
        schema=properties.Schema(
            properties.Schema.STRING,
            constraints=[constraints.CustomConstraint('zaqar.queue')]
        ),
        default=[],
        update_allowed=True
    ),
    REPEAT_ACTIONS: properties.Schema(
        properties.Schema.BOOLEAN,
        _("False to trigger actions when the threshold is reached AND "
          "the alarm's state has changed. By default, actions are called "
          "each time the threshold is reached."),
        default='true',
        update_allowed=True
    ),
    SEVERITY: properties.Schema(
        properties.Schema.STRING,
        _('Severity of the alarm.'),
        default='low',
        constraints=[
            constraints.AllowedValues(['low', 'moderate', 'critical'])
        ],
        update_allowed=True,
        support_status=support.SupportStatus(version='5.0.0'),
    ),
    TIME_CONSTRAINTS: properties.Schema(
        properties.Schema.LIST,
        _('Describe time constraints for the alarm. '
          'Only evaluate the alarm if the time at evaluation '
          'is within this time constraint. Start point(s) of '
          'the constraint are specified with a cron expression, '
          'whereas its duration is given in seconds.'
          ),
        schema=properties.Schema(
            properties.Schema.MAP,
            schema={
                NAME: properties.Schema(
                    properties.Schema.STRING,
                    _("Name for the time constraint."),
                    required=True
                ),
                START: properties.Schema(
                    properties.Schema.STRING,
                    _("Start time for the time constraint. "
                      "A CRON expression property."),
                    constraints=[
                        constraints.CustomConstraint(
                            'cron_expression')
                    ],
                    required=True
                ),
                TIME_CONSTRAINT_DESCRIPTION: properties.Schema(
                    properties.Schema.STRING,
                    _("Description for the time constraint."),
                ),
                DURATION: properties.Schema(
                    properties.Schema.INTEGER,
                    _("Duration for the time constraint."),
                    constraints=[
                        constraints.Range(min=0)
                    ],
                    required=True
                ),
                TIMEZONE: properties.Schema(
                    properties.Schema.STRING,
                    _("Timezone for the time constraint "
                      "(eg. 'Asia/Taipei', 'Europe/Amsterdam')."),
                    constraints=[
                        constraints.CustomConstraint('timezone')
                    ],
                )
            }

        ),
        support_status=support.SupportStatus(version='5.0.0'),
        default=[],
    )
}


NOVA_METERS = ['instance', 'memory', 'memory.usage', 'memory.resident',
               'cpu', 'cpu_util', 'vcpus',
               'disk.read.requests', 'disk.read.requests.rate',
               'disk.write.requests', 'disk.write.requests.rate',
               'disk.read.bytes', 'disk.read.bytes.rate',
               'disk.write.bytes', 'disk.write.bytes.rate',
               'disk.device.read.requests', 'disk.device.read.requests.rate',
               'disk.device.write.requests', 'disk.device.write.requests.rate',
               'disk.device.read.bytes', 'disk.device.read.bytes.rate',
               'disk.device.write.bytes', 'disk.device.write.bytes.rate',
               'disk.root.size', 'disk.ephemeral.size',
               'network.incoming.bytes', 'network.incoming.bytes.rate',
               'network.outgoing.bytes', 'network.outgoing.bytes.rate',
               'network.incoming.packets', 'network.incoming.packets.rate',
               'network.outgoing.packets', 'network.outgoing.packets.rate']


class BaseAlarm(resource.Resource):
    """Base Alarm Manager."""

    default_client_name = 'aodh'

    entity = 'alarm'

    alarm_type = 'threshold'

    QUERY_FACTOR_FIELDS = (
        QF_FIELD, QF_OP, QF_VALUE, QF_TYPE,
    ) = (
        'field', 'op', 'value', 'type',
    )

    QF_OP_VALS = constraints.AllowedValues(['le', 'ge', 'eq',
                                            'lt', 'gt', 'ne'])
    QF_TYPE_VALS = constraints.AllowedValues(['integer', 'float', 'string',
                                              'boolean', 'datetime'])

    def actions_to_urls(self, props):
        kwargs = dict(props)

        def get_urls(action_type, queue_type):
            for act in kwargs.get(action_type) or []:
                # if the action is a resource name
                # we ask the destination resource for an alarm url.
                # the template writer should really do this in the
                # template if possible with:
                # {Fn::GetAtt: ['MyAction', 'AlarmUrl']}
                if act in self.stack:
                    yield self.stack[act].FnGetAtt('AlarmUrl')
                elif act:
                    yield act

            for queue in kwargs.pop(queue_type, []):
                query = {'queue_name': queue}
                yield 'trust+zaqar://?%s' % urlparse.urlencode(query)

        action_props = {arg_types[0]: list(get_urls(*arg_types))
                        for arg_types in ((ALARM_ACTIONS, ALARM_QUEUES),
                                          (OK_ACTIONS, OK_QUEUES),
                                          (INSUFFICIENT_DATA_ACTIONS,
                                           INSUFFICIENT_DATA_QUEUES))}
        kwargs.update(action_props)
        return kwargs

    def _reformat_properties(self, props):
        rule = {}
        # Note that self.PROPERTIES includes only properties specific to the
        # child class; BaseAlarm properties are not included.
        for name in self.PROPERTIES:
            if name in props:
                rule[name] = props.pop(name)
        if rule:
            props['%s_rule' % self.alarm_type] = rule
        return props

    def handle_suspend(self):
        if self.resource_id is not None:
            alarm_update = {'enabled': False}
            self.client().alarm.update(self.resource_id,
                                       alarm_update)

    def handle_resume(self):
        if self.resource_id is not None:
            alarm_update = {'enabled': True}
            self.client().alarm.update(self.resource_id,
                                       alarm_update)

    def handle_check(self):
        self.client().alarm.get(self.resource_id)
