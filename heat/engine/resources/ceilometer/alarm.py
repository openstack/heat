# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import watchrule


class CeilometerAlarm(resource.Resource):

    PROPERTIES = (
        COMPARISON_OPERATOR, EVALUATION_PERIODS, METER_NAME, PERIOD,
        STATISTIC, THRESHOLD, ALARM_ACTIONS, OK_ACTIONS,
        INSUFFICIENT_DATA_ACTIONS, DESCRIPTION, ENABLED,
        REPEAT_ACTIONS, MATCHING_METADATA,
    ) = (
        'comparison_operator', 'evaluation_periods', 'meter_name', 'period',
        'statistic', 'threshold', 'alarm_actions', 'ok_actions',
        'insufficient_data_actions', 'description', 'enabled',
        'repeat_actions', 'matching_metadata',
    )

    properties_schema = {
        COMPARISON_OPERATOR: properties.Schema(
            properties.Schema.STRING,
            _('Operator used to compare specified statistic with threshold.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['ge', 'gt', 'eq', 'ne', 'lt',
                                           'le']),
            ],
            update_allowed=True
        ),
        EVALUATION_PERIODS: properties.Schema(
            properties.Schema.STRING,
            _('Number of periods to evaluate over.'),
            required=True,
            update_allowed=True
        ),
        METER_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Meter name watched by the alarm.'),
            required=True
        ),
        PERIOD: properties.Schema(
            properties.Schema.STRING,
            _('Period (seconds) to evaluate over.'),
            required=True,
            update_allowed=True
        ),
        STATISTIC: properties.Schema(
            properties.Schema.STRING,
            _('Meter statistic to evaluate.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['count', 'avg', 'sum', 'min',
                                           'max']),
            ],
            update_allowed=True
        ),
        THRESHOLD: properties.Schema(
            properties.Schema.STRING,
            _('Threshold to evaluate against.'),
            required=True,
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
        REPEAT_ACTIONS: properties.Schema(
            properties.Schema.BOOLEAN,
            _('False to trigger actions when the threshold is reached AND '
              "the alarm's state has changed. By default, actions are called "
              'each time the threshold is reached.'),
            default='true',
            update_allowed=True
        ),
        MATCHING_METADATA: properties.Schema(
            properties.Schema.MAP,
            _('Meter should match this resource metadata (key=value) '
              'additionally to the meter_name.')
        ),
    }

    update_allowed_keys = ('Properties',)

    def _actions_to_urls(self, props):
        kwargs = {}
        for k, v in iter(props.items()):
            if k in ['alarm_actions', 'ok_actions',
                     'insufficient_data_actions'] and v is not None:
                kwargs[k] = []
                for act in v:
                    # if the action is a resource name
                    # we ask the destination resource for an alarm url.
                    # the template writer should really do this in the
                    # template if possible with:
                    # {Fn::GetAtt: ['MyAction', 'AlarmUrl']}
                    if act in self.stack:
                        url = self.stack[act].FnGetAtt('AlarmUrl')
                        kwargs[k].append(url)
                    else:
                        kwargs[k].append(act)
            else:
                kwargs[k] = v
        return kwargs

    def handle_create(self):
        props = self._actions_to_urls(self.parsed_template('Properties'))
        props['name'] = self.physical_resource_name()

        alarm = self.ceilometer().alarms.create(**props)
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
            kwargs.update(prop_diff)
            self.ceilometer().alarms.update(**self._actions_to_urls(kwargs))

    def handle_suspend(self):
        if self.resource_id is not None:
            self.ceilometer().alarms.update(alarm_id=self.resource_id,
                                            enabled=False)

    def handle_resume(self):
        if self.resource_id is not None:
            self.ceilometer().alarms.update(alarm_id=self.resource_id,
                                            enabled=True)

    def handle_delete(self):
        try:
            wr = watchrule.WatchRule.load(
                self.context, watch_name=self.physical_resource_name())
            wr.destroy()
        except exception.WatchRuleNotFound:
            pass

        if self.resource_id is not None:
            self.ceilometer().alarms.delete(self.resource_id)


def resource_mapping():
    return {
        'OS::Ceilometer::Alarm': CeilometerAlarm,
    }
