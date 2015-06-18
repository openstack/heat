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
from heat.engine.resources.openstack.ceilometer import alarm
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
    AGGREGATION_METHOD: properties.Schema(
        properties.Schema.STRING,
        _('The aggregation method to compare to the threshold'),
        constraints=[
            constraints.AllowedValues(['mean', 'sum', 'last', 'max', 'min',
                                       'std', 'median', 'first', 'count']),
        ],
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


class CeilometerGnocchiResourcesAlarm(alarm.BaseCeilometerAlarm):

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
            _('Id of a resource'),
            required=True,
            update_allowed=True
        ),
        RESOURCE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Resource type'),
            required=True,
            update_allowed=True
        ),
    }
    properties_schema.update(common_gnocchi_properties_schema)
    properties_schema.update(alarm.common_properties_schema)

    ceilometer_alarm_type = 'gnocchi_resources_threshold'


class CeilometerGnocchiAggregationByMetricsAlarm(
        CeilometerGnocchiResourcesAlarm):

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
    properties_schema.update(alarm.common_properties_schema)

    ceilometer_alarm_type = 'gnocchi_aggregation_by_metrics_threshold'


class CeilometerGnocchiAggregationByResourcesAlarm(
        CeilometerGnocchiResourcesAlarm):

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
            _('The query to filter the metrics'),
            required=True,
            update_allowed=True
        ),
        RESOURCE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Resource type'),
            required=True,
            update_allowed=True
        ),
    }

    properties_schema.update(common_gnocchi_properties_schema)
    properties_schema.update(alarm.common_properties_schema)

    ceilometer_alarm_type = 'gnocchi_aggregation_by_resources_threshold'


def resource_mapping():
    return {
        'OS::Ceilometer::GnocchiResourcesAlarm':
            CeilometerGnocchiResourcesAlarm,
        'OS::Ceilometer::GnocchiAggregationByMetricsAlarm':
            CeilometerGnocchiAggregationByMetricsAlarm,
        'OS::Ceilometer::GnocchiAggregationByResourcesAlarm':
            CeilometerGnocchiAggregationByResourcesAlarm,
    }
