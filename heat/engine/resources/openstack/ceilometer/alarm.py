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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import watchrule


COMMON_PROPERTIES = (
    ALARM_ACTIONS, OK_ACTIONS, REPEAT_ACTIONS,
    INSUFFICIENT_DATA_ACTIONS, DESCRIPTION, ENABLED, TIME_CONSTRAINTS,
    SEVERITY,
) = (
    'alarm_actions', 'ok_actions', 'repeat_actions',
    'insufficient_data_actions', 'description', 'enabled', 'time_constraints',
    'severity',
)

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
                      "(eg. 'Taiwan/Taipei', 'Europe/Amsterdam')."),
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


NOVA_METERS = ['instance', 'memory', 'memory.usage',
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


def actions_to_urls(stack, properties):
    kwargs = {}
    for k, v in iter(properties.items()):
        if k in [ALARM_ACTIONS, OK_ACTIONS,
                 INSUFFICIENT_DATA_ACTIONS] and v is not None:
            kwargs[k] = []
            for act in v:
                # if the action is a resource name
                # we ask the destination resource for an alarm url.
                # the template writer should really do this in the
                # template if possible with:
                # {Fn::GetAtt: ['MyAction', 'AlarmUrl']}
                if act in stack:
                    url = stack[act].FnGetAtt('AlarmUrl')
                    kwargs[k].append(url)
                else:
                    if act:
                        kwargs[k].append(act)
        else:
            kwargs[k] = v
    return kwargs


class CeilometerAlarm(resource.Resource):
    """A resource that implements alarming service of Ceilometer.

    A resource that allows for the setting alarms based on threshold evaluation
    for a collection of samples. Also, you can define actions to take if state
    of watched resource will be satisfied specified conditions. For example, it
    can watch for the memory consumption and when it reaches 70% on a given
    instance if the instance has been up for more than 10 min, some action will
    be called.
    """

    PROPERTIES = (
        COMPARISON_OPERATOR, EVALUATION_PERIODS, METER_NAME, PERIOD,
        STATISTIC, THRESHOLD, MATCHING_METADATA, QUERY,
    ) = (
        'comparison_operator', 'evaluation_periods', 'meter_name', 'period',
        'statistic', 'threshold', 'matching_metadata', 'query',
    )

    QUERY_FACTOR_FIELDS = (
        QF_FIELD, QF_OP, QF_VALUE,
    ) = (
        'field', 'op', 'value',
    )

    QF_OP_VALS = constraints.AllowedValues(['le', 'ge', 'eq',
                                            'lt', 'gt', 'ne'])

    properties_schema = {
        COMPARISON_OPERATOR: properties.Schema(
            properties.Schema.STRING,
            _('Operator used to compare specified statistic with threshold.'),
            constraints=[
                constraints.AllowedValues(['ge', 'gt', 'eq', 'ne', 'lt',
                                           'le']),
            ],
            update_allowed=True
        ),
        EVALUATION_PERIODS: properties.Schema(
            properties.Schema.INTEGER,
            _('Number of periods to evaluate over.'),
            update_allowed=True
        ),
        METER_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Meter name watched by the alarm.'),
            required=True
        ),
        PERIOD: properties.Schema(
            properties.Schema.INTEGER,
            _('Period (seconds) to evaluate over.'),
            update_allowed=True
        ),
        STATISTIC: properties.Schema(
            properties.Schema.STRING,
            _('Meter statistic to evaluate.'),
            constraints=[
                constraints.AllowedValues(['count', 'avg', 'sum', 'min',
                                           'max']),
            ],
            update_allowed=True
        ),
        THRESHOLD: properties.Schema(
            properties.Schema.NUMBER,
            _('Threshold to evaluate against.'),
            required=True,
            update_allowed=True
        ),
        MATCHING_METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Meter should match this resource metadata (key=value) '
              'additionally to the meter_name.'),
            default={},
            update_allowed=True
        ),
        QUERY: properties.Schema(
            properties.Schema.LIST,
            _('A list of query factors, each comparing '
              'a Sample attribute with a value. '
              'Implicitly combined with matching_metadata, if any.'),
            update_allowed=True,
            support_status=support.SupportStatus(version='2015.1'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    QF_FIELD: properties.Schema(
                        properties.Schema.STRING,
                        _('Name of attribute to compare. '
                          'Names of the form metadata.user_metadata.X '
                          'or metadata.metering.X are equivalent to what '
                          'you can address through matching_metadata; '
                          'the former for Nova meters, '
                          'the latter for all others. '
                          'To see the attributes of your Samples, '
                          'use `ceilometer --debug sample-list`.')
                    ),
                    QF_OP: properties.Schema(
                        properties.Schema.STRING,
                        _('Comparison operator.'),
                        constraints=[QF_OP_VALS]
                    ),
                    QF_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        _('String value with which to compare.')
                    )
                }
            )
        )
    }
    properties_schema.update(common_properties_schema)

    default_client_name = 'ceilometer'

    entity = 'alarms'

    def cfn_to_ceilometer(self, stack, properties):
        """Apply all relevant compatibility xforms."""

        kwargs = actions_to_urls(stack, properties)
        kwargs['type'] = 'threshold'
        if kwargs.get(self.METER_NAME) in NOVA_METERS:
            prefix = 'user_metadata.'
        else:
            prefix = 'metering.'

        rule = {}
        for field in ['period', 'evaluation_periods', 'threshold',
                      'statistic', 'comparison_operator', 'meter_name']:
            if field in kwargs:
                rule[field] = kwargs[field]
                del kwargs[field]
        mmd = properties.get(self.MATCHING_METADATA) or {}
        query = properties.get(self.QUERY) or []

        # make sure the matching_metadata appears in the query like this:
        # {field: metadata.$prefix.x, ...}
        for m_k, m_v in six.iteritems(mmd):
            key = 'metadata.%s' % prefix
            if m_k.startswith('metadata.'):
                m_k = m_k[len('metadata.'):]
            if m_k.startswith('metering.') or m_k.startswith('user_metadata.'):
                # check prefix
                m_k = m_k.split('.', 1)[-1]
            key = '%s%s' % (key, m_k)
            # NOTE(prazumovsky): type of query value must be a string, but
            # matching_metadata value type can not be a string, so we
            # must convert value to a string type.
            query.append(dict(field=key, op='eq', value=six.text_type(m_v)))
        if self.MATCHING_METADATA in kwargs:
            del kwargs[self.MATCHING_METADATA]
        if self.QUERY in kwargs:
            del kwargs[self.QUERY]
        if query:
            rule['query'] = query
        kwargs['threshold_rule'] = rule
        return kwargs

    def handle_create(self):
        props = self.cfn_to_ceilometer(self.stack,
                                       self.properties)
        props['name'] = self.physical_resource_name()
        alarm = self.client().alarms.create(**props)
        self.resource_id_set(alarm.alarm_id)

        # the watchrule below is for backwards compatibility.
        # 1) so we don't create watch tasks unneccessarly
        # 2) to support CW stats post, we will redirect the request
        #    to ceilometer.
        wr = watchrule.WatchRule(context=self.context,
                                 watch_name=self.physical_resource_name(),
                                 rule=self.parsed_template('Properties'),
                                 stack_id=self.stack.id)
        wr.state = wr.CEILOMETER_CONTROLLED
        wr.store()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            kwargs = {'alarm_id': self.resource_id}
            kwargs.update(self.properties)
            kwargs.update(prop_diff)
            alarms_client = self.client().alarms
            alarms_client.update(**self.cfn_to_ceilometer(self.stack, kwargs))

    def handle_suspend(self):
        if self.resource_id is not None:
            self.client().alarms.update(alarm_id=self.resource_id,
                                        enabled=False)

    def handle_resume(self):
        if self.resource_id is not None:
            self.client().alarms.update(alarm_id=self.resource_id,
                                        enabled=True)

    def handle_delete(self):
        try:
            wr = watchrule.WatchRule.load(
                self.context, watch_name=self.physical_resource_name())
            wr.destroy()
        except exception.EntityNotFound:
            pass

        return super(CeilometerAlarm, self).handle_delete()

    def handle_check(self):
        watch_name = self.physical_resource_name()
        watchrule.WatchRule.load(self.context, watch_name=watch_name)
        self.client().alarms.get(self.resource_id)


class BaseCeilometerAlarm(resource.Resource):
    default_client_name = 'ceilometer'

    entity = 'alarms'

    def handle_create(self):
        properties = actions_to_urls(self.stack,
                                     self.properties)
        properties['name'] = self.physical_resource_name()
        properties['type'] = self.ceilometer_alarm_type
        alarm = self.client().alarms.create(
            **self._reformat_properties(properties))
        self.resource_id_set(alarm.alarm_id)

    def _reformat_properties(self, properties):
        rule = {}
        for name in self.PROPERTIES:
            value = properties.pop(name, None)
            if value:
                rule[name] = value
        if rule:
            properties['%s_rule' % self.ceilometer_alarm_type] = rule
        return properties

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            kwargs = {'alarm_id': self.resource_id}
            kwargs.update(prop_diff)
            alarms_client = self.client().alarms
            alarms_client.update(**self._reformat_properties(
                actions_to_urls(self.stack, kwargs)))

    def handle_suspend(self):
        self.client().alarms.update(
            alarm_id=self.resource_id, enabled=False)

    def handle_resume(self):
        self.client().alarms.update(
            alarm_id=self.resource_id, enabled=True)

    def handle_check(self):
        self.client().alarms.get(self.resource_id)


class CombinationAlarm(BaseCeilometerAlarm):
    """A resource that implements combination of Ceilometer alarms.

    Allows to use alarm as a combination of other alarms with some operator:
    activate this alarm if any alarm in combination has been activated or
    if all alarms in combination have been activated.
    """

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        ALARM_IDS, OPERATOR,
    ) = (
        'alarm_ids', 'operator',
    )

    properties_schema = {
        ALARM_IDS: properties.Schema(
            properties.Schema.LIST,
            _('List of alarm identifiers to combine.'),
            required=True,
            constraints=[constraints.Length(min=1)],
            update_allowed=True),
        OPERATOR: properties.Schema(
            properties.Schema.STRING,
            _('Operator used to combine the alarms.'),
            constraints=[constraints.AllowedValues(['and', 'or'])],
            update_allowed=True)
    }
    properties_schema.update(common_properties_schema)

    ceilometer_alarm_type = 'combination'


def resource_mapping():
    return {
        'OS::Ceilometer::Alarm': CeilometerAlarm,
        'OS::Ceilometer::CombinationAlarm': CombinationAlarm,
    }
