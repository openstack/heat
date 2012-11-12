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

import re
from heat.openstack.common import timeutils
from heat.engine import parser
from heat.engine import template
from heat.engine import watchrule

from heat.openstack.common import log as logging

logger = logging.getLogger('heat.engine.manager')

PARAM_KEYS = (PARAM_TIMEOUT, ) = ('timeout_mins', )


def extract_args(params):
    '''
    Extract any arguments passed as parameters through the API and return them
    as a dictionary. This allows us to filter the passed args and do type
    conversion where appropriate
    '''
    kwargs = {}
    try:
        timeout_mins = int(params.get(PARAM_TIMEOUT, 0))
    except (ValueError, TypeError):
        logger.exception('create timeout conversion')
    else:
        if timeout_mins > 0:
            kwargs[PARAM_TIMEOUT] = timeout_mins
    return kwargs


STACK_KEYS = (
    STACK_NAME, STACK_ID,
    STACK_CREATION_TIME, STACK_UPDATED_TIME, STACK_DELETION_TIME,
    STACK_NOTIFICATION_TOPICS,
    STACK_DESCRIPTION, STACK_TMPL_DESCRIPTION,
    STACK_PARAMETERS, STACK_OUTPUTS,
    STACK_STATUS, STACK_STATUS_DATA, STACK_CAPABILITIES,
    STACK_DISABLE_ROLLBACK, STACK_TIMEOUT,
) = (
    'stack_name', 'stack_identity',
    'creation_time', 'updated_time', 'deletion_time',
    'notification_topics',
    'description', 'template_description',
    'parameters', 'outputs',
    'stack_status', 'stack_status_reason', 'capabilities',
    'disable_rollback', 'timeout_mins'
)

STACK_OUTPUT_KEYS = (
    OUTPUT_DESCRIPTION,
    OUTPUT_KEY, OUTPUT_VALUE,
) = (
    'description',
    'output_key', 'output_value',
)


def format_stack_outputs(stack, outputs):
    '''
    Return a representation of the given output template for the given stack
    that matches the API output expectations.
    '''
    def format_stack_output(k):
        return {OUTPUT_DESCRIPTION: outputs[k].get('Description',
                                                   'No description given'),
                OUTPUT_KEY: k,
                OUTPUT_VALUE: stack.output(k)}

    return [format_stack_output(key) for key in outputs]


def format_stack(stack):
    '''
    Return a representation of the given stack that matches the API output
    expectations.
    '''
    info = {
        STACK_NAME: stack.name,
        STACK_ID: dict(stack.identifier()),
        STACK_CREATION_TIME: timeutils.isotime(stack.created_time),
        STACK_UPDATED_TIME: timeutils.isotime(stack.updated_time),
        STACK_NOTIFICATION_TOPICS: [],  # TODO Not implemented yet
        STACK_PARAMETERS: stack.parameters.map(str),
        STACK_DESCRIPTION: stack.t[template.DESCRIPTION],
        STACK_TMPL_DESCRIPTION: stack.t[template.DESCRIPTION],
        STACK_STATUS: stack.state,
        STACK_STATUS_DATA: stack.state_description,
        STACK_CAPABILITIES: [],   # TODO Not implemented yet
        STACK_DISABLE_ROLLBACK: True,   # TODO Not implemented yet
        STACK_TIMEOUT: stack.timeout_mins,
    }

    # only show the outputs on a completely created or updated stack
    if stack.state in (stack.CREATE_COMPLETE, stack.UPDATE_COMPLETE):
        info[STACK_OUTPUTS] = format_stack_outputs(stack, stack.outputs)

    return info


RES_KEYS = (
    RES_DESCRIPTION, RES_UPDATED_TIME,
    RES_NAME, RES_PHYSICAL_ID, RES_METADATA,
    RES_STATUS, RES_STATUS_DATA, RES_TYPE,
    RES_ID, RES_STACK_ID, RES_STACK_NAME,
) = (
    'description', 'updated_time',
    'logical_resource_id', 'physical_resource_id', 'metadata',
    'resource_status', 'resource_status_reason', 'resource_type',
    'resource_identity', STACK_ID, STACK_NAME,
)


def format_stack_resource(resource):
    '''
    Return a representation of the given resource that matches the API output
    expectations.
    '''
    last_updated_time = resource.updated_time or resource.created_time
    res = {
        RES_DESCRIPTION: resource.parsed_template().get('Description', ''),
        RES_UPDATED_TIME: timeutils.isotime(last_updated_time),
        RES_NAME: resource.name,
        RES_PHYSICAL_ID: resource.resource_id or '',
        RES_METADATA: resource.metadata,
        RES_STATUS: resource.state,
        RES_STATUS_DATA: resource.state_description,
        RES_TYPE: resource.t['Type'],
        RES_ID: dict(resource.identifier()),
        RES_STACK_ID: dict(resource.stack.identifier()),
        RES_STACK_NAME: resource.stack.name,
    }

    return res


EVENT_KEYS = (
    EVENT_ID,
    EVENT_STACK_ID, EVENT_STACK_NAME,
    EVENT_TIMESTAMP,
    EVENT_RES_NAME, EVENT_RES_PHYSICAL_ID,
    EVENT_RES_STATUS, EVENT_RES_STATUS_DATA, EVENT_RES_TYPE,
    EVENT_RES_PROPERTIES,
) = (
    'event_id',
    STACK_ID, STACK_NAME,
    "event_time",
    RES_NAME, RES_PHYSICAL_ID,
    RES_STATUS, RES_STATUS_DATA, RES_TYPE,
    'resource_properties',
)


def format_event(context, event):
    stack = parser.Stack.load(context, stack=event.stack)
    result = {
        EVENT_ID: event.id,
        EVENT_STACK_ID: dict(stack.identifier()),
        EVENT_STACK_NAME: stack.name,
        EVENT_TIMESTAMP: timeutils.isotime(event.created_at),
        EVENT_RES_NAME: event.logical_resource_id,
        EVENT_RES_PHYSICAL_ID: event.physical_resource_id,
        EVENT_RES_STATUS: event.name,
        EVENT_RES_STATUS_DATA: event.resource_status_reason,
        EVENT_RES_TYPE: event.resource_type,
        EVENT_RES_PROPERTIES: event.resource_properties,
    }

    return result


# This is the representation of a watch we expose to the API via RPC
WATCH_KEYS = (
    WATCH_ACTIONS_ENABLED, WATCH_ALARM_ACTIONS, WATCH_TOPIC,
    WATCH_UPDATED_TIME, WATCH_DESCRIPTION, WATCH_NAME,
    WATCH_COMPARISON, WATCH_DIMENSIONS, WATCH_PERIODS,
    WATCH_INSUFFICIENT_ACTIONS, WATCH_METRIC_NAME, WATCH_NAMESPACE,
    WATCH_OK_ACTIONS, WATCH_PERIOD, WATCH_STATE_REASON,
    WATCH_STATE_REASON_DATA, WATCH_STATE_UPDATED_TIME, WATCH_STATE_VALUE,
    WATCH_STATISTIC, WATCH_THRESHOLD, WATCH_UNIT, WATCH_STACK_NAME
    ) = (
    'actions_enabled', 'actions', 'topic',
    'updated_time', 'description', 'name',
    'comparison', 'dimensions', 'periods',
    'insufficient_actions', 'metric_name', 'namespace',
    'ok_actions', 'period', 'state_reason',
    'state_reason_data', 'state_updated_time', 'state_value',
    'statistic', 'threshold', 'unit', 'stack_name')


# Alternate representation of a watch rule to align with DB format
# FIXME : These align with AWS naming for compatibility with the
# current cfn-push-stats & metadata server, fix when we've ported
# cfn-push-stats to use the Cloudwatch server and/or moved metric
# collection into ceilometer, these should just be WATCH_KEYS
# or each field should be stored separately in the DB watch_data
# table if we stick to storing watch data in the heat DB
WATCH_RULE_KEYS = (
    RULE_ACTIONS_ENABLED, RULE_ALARM_ACTIONS, RULE_TOPIC,
    RULE_UPDATED_TIME, RULE_DESCRIPTION, RULE_NAME,
    RULE_COMPARISON, RULE_DIMENSIONS, RULE_PERIODS,
    RULE_INSUFFICIENT_ACTIONS, RULE_METRIC_NAME, RULE_NAMESPACE,
    RULE_OK_ACTIONS, RULE_PERIOD, RULE_STATE_REASON,
    RULE_STATE_REASON_DATA, RULE_STATE_UPDATED_TIME, RULE_STATE_VALUE,
    RULE_STATISTIC, RULE_THRESHOLD, RULE_UNIT, RULE_STACK_NAME
    ) = (
    'ActionsEnabled', 'AlarmActions', 'AlarmArn',
    'AlarmConfigurationUpdatedTimestamp', 'AlarmDescription', 'AlarmName',
    'ComparisonOperator', 'Dimensions', 'EvaluationPeriods',
    'InsufficientDataActions', 'MetricName', 'Namespace',
    'OKActions', 'Period', 'StateReason',
    'StateReasonData', 'StateUpdatedTimestamp', 'StateValue',
    'Statistic', 'Threshold', 'Unit', 'StackName')


WATCH_STATES = (WATCH_STATE_OK, WATCH_STATE_ALARM, WATCH_STATE_NODATA
    ) = (watchrule.WatchRule.NORMAL,
         watchrule.WatchRule.ALARM,
         watchrule.WatchRule.NODATA)


def format_watch(watch):

    result = {
        WATCH_ACTIONS_ENABLED: watch.rule.get(RULE_ACTIONS_ENABLED),
        WATCH_ALARM_ACTIONS: watch.rule.get(RULE_ALARM_ACTIONS),
        WATCH_TOPIC: watch.rule.get(RULE_TOPIC),
        WATCH_UPDATED_TIME: timeutils.isotime(watch.updated_at),
        WATCH_DESCRIPTION: watch.rule.get(RULE_DESCRIPTION),
        WATCH_NAME: watch.name,
        WATCH_COMPARISON: watch.rule.get(RULE_COMPARISON),
        WATCH_DIMENSIONS: watch.rule.get(RULE_DIMENSIONS) or [],
        WATCH_PERIODS: watch.rule.get(RULE_PERIODS),
        WATCH_INSUFFICIENT_ACTIONS: watch.rule.get(RULE_INSUFFICIENT_ACTIONS),
        WATCH_METRIC_NAME: watch.rule.get(RULE_METRIC_NAME),
        WATCH_NAMESPACE: watch.rule.get(RULE_NAMESPACE),
        WATCH_OK_ACTIONS: watch.rule.get(RULE_OK_ACTIONS),
        WATCH_PERIOD: watch.rule.get(RULE_PERIOD),
        WATCH_STATE_REASON: watch.rule.get(RULE_STATE_REASON),
        WATCH_STATE_REASON_DATA: watch.rule.get(RULE_STATE_REASON_DATA),
        WATCH_STATE_UPDATED_TIME: timeutils.isotime(
                                  watch.rule.get(RULE_STATE_UPDATED_TIME)),
        WATCH_STATE_VALUE: watch.state,
        WATCH_STATISTIC: watch.rule.get(RULE_STATISTIC),
        WATCH_THRESHOLD: watch.rule.get(RULE_THRESHOLD),
        WATCH_UNIT: watch.rule.get(RULE_UNIT),
        WATCH_STACK_NAME: watch.stack_name
    }

    return result


WATCH_DATA_KEYS = (
    WATCH_DATA_ALARM, WATCH_DATA_METRIC, WATCH_DATA_TIME,
    WATCH_DATA_NAMESPACE, WATCH_DATA
    ) = (
    'watch_name', 'metric_name', 'timestamp',
    'namespace', 'data')


def format_watch_data(wd):

    # Demangle DB format data into something more easily used in the API
    # We are expecting a dict with exactly two items, Namespace and
    # a metric key
    namespace = wd.data['Namespace']
    metric = [(k, v) for k, v in wd.data.items() if k != 'Namespace']
    if len(metric) == 1:
        metric_name, metric_data = metric[0]
    else:
        logger.error("Unexpected number of keys in watch_data.data!")
        return

    result = {
        WATCH_DATA_ALARM: wd.watch_rule.name,
        WATCH_DATA_METRIC: metric_name,
        WATCH_DATA_TIME: timeutils.isotime(wd.created_at),
        WATCH_DATA_NAMESPACE: namespace,
        WATCH_DATA: metric_data
    }

    return result
