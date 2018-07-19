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
from heat.engine import properties
from heat.engine.resources import alarm_base
from heat.engine import support


COMMON_GNOCCHI_PROPERTIES = (
    COMPARISON_OPERATOR, EVALUATION_PERIODS, GRANULARITY,
    AGGREGATION_METHOD, THRESHOLD,
) = (
    'comparison_operator', 'evaluation_periods', 'granularity',
    'aggregation_method', 'threshold',
)

common_gnocchi_properties_schema = {
    COMPARISON_OPERATOR: properties.Schema(
        properties.Schema.STRING,
        _('Operator used to compare specified statistic with threshold.'),
        constraints=[alarm_base.BaseAlarm.QF_OP_VALS],
        update_allowed=True
    ),
    EVALUATION_PERIODS: properties.Schema(
        properties.Schema.INTEGER,
        _('Number of periods to evaluate over.'),
        update_allowed=True
    ),
    AGGREGATION_METHOD: properties.Schema(
        properties.Schema.STRING,
        _('The aggregation method to compare to the threshold.'),
        update_allowed=True
    ),
    GRANULARITY: properties.Schema(
        properties.Schema.INTEGER,
        _('The time range in seconds.'),
        update_allowed=True
    ),
    THRESHOLD: properties.Schema(
        properties.Schema.NUMBER,
        _('Threshold to evaluate against.'),
        required=True,
        update_allowed=True
    ),
}


class AodhGnocchiResourcesAlarm(alarm_base.BaseAlarm):
    """A resource allowing for the watch of some specified resource.

    An alarm that evaluates threshold based on some metric for the
    specified resource.
    """

    support_status = support.SupportStatus(version='2015.1')

    PROPERTIES = (
        METRIC, RESOURCE_ID, RESOURCE_TYPE
    ) = (
        'metric', 'resource_id', 'resource_type'
    )
    PROPERTIES += COMMON_GNOCCHI_PROPERTIES

    properties_schema = {
        METRIC: properties.Schema(
            properties.Schema.STRING,
            _('Metric name watched by the alarm.'),
            required=True,
            update_allowed=True
        ),
        RESOURCE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Id of a resource.'),
            required=True,
            update_allowed=True
        ),
        RESOURCE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Resource type.'),
            required=True,
            update_allowed=True
        ),
    }
    properties_schema.update(common_gnocchi_properties_schema)
    properties_schema.update(alarm_base.common_properties_schema)

    alarm_type = 'gnocchi_resources_threshold'

    def get_alarm_props(self, props):
        kwargs = self.actions_to_urls(props)
        kwargs = self._reformat_properties(kwargs)

        return kwargs

    def handle_create(self):
        props = self.get_alarm_props(self.properties)
        props['name'] = self.physical_resource_name()
        props['type'] = self.alarm_type
        alarm = self.client().alarm.create(props)
        self.resource_id_set(alarm['alarm_id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            new_props = json_snippet.properties(self.properties_schema,
                                                self.context)
            props = self.get_alarm_props(new_props)
            self.client().alarm.update(self.resource_id, props)

    def parse_live_resource_data(self, resource_properties,
                                 resource_data):
        record_reality = {}
        rule = self.alarm_type + '_rule'
        threshold_data = resource_data.get(rule).copy()
        threshold_data.update(resource_data)
        for key in self.properties_schema.keys():
            if key in alarm_base.INTERNAL_PROPERTIES:
                continue
            if self.properties_schema[key].update_allowed:
                record_reality.update({key: threshold_data.get(key)})
        return record_reality


class AodhGnocchiAggregationByMetricsAlarm(
        AodhGnocchiResourcesAlarm):
    """A resource that implements alarm with specified metrics.

    A resource that implements alarm which allows to use specified by user
    metrics in metrics list.
    """

    support_status = support.SupportStatus(version='2015.1')

    PROPERTIES = (METRICS,) = ('metrics',)
    PROPERTIES += COMMON_GNOCCHI_PROPERTIES

    properties_schema = {
        METRICS: properties.Schema(
            properties.Schema.LIST,
            _('A list of metric ids.'),
            required=True,
            update_allowed=True,
        ),
    }
    properties_schema.update(common_gnocchi_properties_schema)
    properties_schema.update(alarm_base.common_properties_schema)

    alarm_type = 'gnocchi_aggregation_by_metrics_threshold'


class AodhGnocchiAggregationByResourcesAlarm(
        AodhGnocchiResourcesAlarm):
    """A resource that implements alarm as an aggregation of resources alarms.

    A resource that implements alarm which uses aggregation of resources alarms
    with some condition. If state of a system is satisfied alarm condition,
    alarm is activated.
    """

    support_status = support.SupportStatus(version='2015.1')

    PROPERTIES = (
        METRIC, QUERY, RESOURCE_TYPE
    ) = (
        'metric', 'query', 'resource_type'
    )
    PROPERTIES += COMMON_GNOCCHI_PROPERTIES

    properties_schema = {
        METRIC: properties.Schema(
            properties.Schema.STRING,
            _('Metric name watched by the alarm.'),
            required=True,
            update_allowed=True
        ),
        QUERY: properties.Schema(
            properties.Schema.STRING,
            _('The query to filter the metrics.'),
            required=True,
            update_allowed=True
        ),
        RESOURCE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Resource type.'),
            required=True,
            update_allowed=True
        ),
    }

    properties_schema.update(common_gnocchi_properties_schema)
    properties_schema.update(alarm_base.common_properties_schema)

    alarm_type = 'gnocchi_aggregation_by_resources_threshold'


def resource_mapping():
    return {
        'OS::Aodh::GnocchiResourcesAlarm':
            AodhGnocchiResourcesAlarm,
        'OS::Aodh::GnocchiAggregationByMetricsAlarm':
            AodhGnocchiAggregationByMetricsAlarm,
        'OS::Aodh::GnocchiAggregationByResourcesAlarm':
            AodhGnocchiAggregationByResourcesAlarm,
    }
