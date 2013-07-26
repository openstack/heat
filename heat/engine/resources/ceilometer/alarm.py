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

from heat.engine import resource


class CeilometerAlarm(resource.Resource):

    properties_schema = {'comparison_operator': {'Type': 'String',
                                                 'Required': True,
                                                 'AllowedValues': ['ge',
                                                                   'gt',
                                                                   'eq',
                                                                   'ne',
                                                                   'lt',
                                                                   'le']},
                         'evaluation_periods': {'Type': 'String',
                                                'Required': True},
                         'counter_name': {'Type': 'String',
                                          'Required': True},
                         'period': {'Type': 'String',
                                    'Required': True},
                         'statistic': {'Type': 'String',
                                       'Required': True,
                                       'AllowedValues': ['count',
                                                         'avg',
                                                         'sum',
                                                         'min',
                                                         'max']},
                         'threshold': {'Type': 'String',
                                       'Required': True},
                         'alarm_actions': {'Type': 'List'},
                         'ok_actions': {'Type': 'List'},
                         'insufficient_data_actions': {'Type': 'List'},
                         'description': {'Type': 'String'},
                         'source': {'Type': 'String'},
                         'matching_metadata': {'Type': 'Map'}}

    update_allowed_keys = ('Properties',)
    # allow the properties that affect the watch calculation.
    # note: when using in-instance monitoring you can only change the
    # metric name if you re-configure the instance too.
    update_allowed_properties = ('comparison_operator', 'description',
                                 'evaluation_periods', 'period', 'statistic',
                                 'alarm_actions', 'ok_actions',
                                 'insufficient_data_actions', 'threshold')

    def _actions_to_urls(self, props):
        kwargs = {}
        for k, v in iter(props.items()):
            if k.endswith('_actions') and v is not None:
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
        props['enabled'] = True

        alarm = self.ceilometer().alarms.create(**props)
        self.resource_id_set(alarm.alarm_id)

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
        if self.resource_id is not None:
            self.ceilometer().alarms.delete(self.resource_id)


def resource_mapping():
    return {
        'OS::Metering::Alarm': CeilometerAlarm,
    }
