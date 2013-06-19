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

from heat.rpc.api import *
from heat.openstack.common import timeutils
from heat.engine import template

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


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

    if PARAM_DISABLE_ROLLBACK in params:
        disable_rollback = params.get(PARAM_DISABLE_ROLLBACK)
        if str(disable_rollback).lower() == 'true':
            kwargs[PARAM_DISABLE_ROLLBACK] = True
        elif str(disable_rollback).lower() == 'false':
            kwargs[PARAM_DISABLE_ROLLBACK] = False
        else:
            raise ValueError("Unexpected value for parameter %s : %s" %
                             (PARAM_DISABLE_ROLLBACK, disable_rollback))
    return kwargs


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
        STACK_ACTION: stack.action or '',
        STACK_STATUS: stack.status or '',
        STACK_STATUS_DATA: stack.status_reason,
        STACK_CAPABILITIES: [],   # TODO Not implemented yet
        STACK_DISABLE_ROLLBACK: stack.disable_rollback,
        STACK_TIMEOUT: stack.timeout_mins,
    }

    # only show the outputs on a completely created or updated stack
    if (stack.action != stack.DELETE and stack.status == stack.COMPLETE):
        info[STACK_OUTPUTS] = format_stack_outputs(stack, stack.outputs)

    return info


def format_stack_resource(resource, detail=True):
    '''
    Return a representation of the given resource that matches the API output
    expectations.
    '''
    last_updated_time = resource.updated_time or resource.created_time
    res = {
        RES_UPDATED_TIME: timeutils.isotime(last_updated_time),
        RES_NAME: resource.name,
        RES_PHYSICAL_ID: resource.resource_id or '',
        RES_METADATA: resource.metadata,
        RES_ACTION: resource.action or '',
        RES_STATUS: resource.status or '',
        RES_STATUS_DATA: resource.status_reason,
        RES_TYPE: resource.t['Type'],
        RES_ID: dict(resource.identifier()),
        RES_STACK_ID: dict(resource.stack.identifier()),
        RES_STACK_NAME: resource.stack.name,
    }

    if detail:
        res[RES_DESCRIPTION] = resource.parsed_template('Description', '')
        res[RES_METADATA] = resource.metadata

    return res


def format_event(event):
    stack_identifier = event.stack.identifier()

    result = {
        EVENT_ID: dict(event.identifier()),
        EVENT_STACK_ID: dict(stack_identifier),
        EVENT_STACK_NAME: stack_identifier.stack_name,
        EVENT_TIMESTAMP: timeutils.isotime(event.timestamp),
        EVENT_RES_NAME: event.resource.name,
        EVENT_RES_PHYSICAL_ID: event.physical_resource_id,
        EVENT_RES_ACTION: event.action,
        EVENT_RES_STATUS: event.status,
        EVENT_RES_STATUS_DATA: event.reason,
        EVENT_RES_TYPE: event.resource.type(),
        EVENT_RES_PROPERTIES: event.resource_properties,
    }

    return result


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
        WATCH_STACK_ID: watch.stack_id
    }

    return result


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
