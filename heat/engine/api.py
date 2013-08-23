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

from heat.rpc import api
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
        timeout_mins = int(params.get(api.PARAM_TIMEOUT, 0))
    except (ValueError, TypeError):
        logger.exception('create timeout conversion')
    else:
        if timeout_mins > 0:
            kwargs[api.PARAM_TIMEOUT] = timeout_mins

    if api.PARAM_DISABLE_ROLLBACK in params:
        disable_rollback = params.get(api.PARAM_DISABLE_ROLLBACK)
        if str(disable_rollback).lower() == 'true':
            kwargs[api.PARAM_DISABLE_ROLLBACK] = True
        elif str(disable_rollback).lower() == 'false':
            kwargs[api.PARAM_DISABLE_ROLLBACK] = False
        else:
            raise ValueError("Unexpected value for parameter %s : %s" %
                             (api.PARAM_DISABLE_ROLLBACK, disable_rollback))
    return kwargs


def format_stack_outputs(stack, outputs):
    '''
    Return a representation of the given output template for the given stack
    that matches the API output expectations.
    '''
    def format_stack_output(k):
        return {api.OUTPUT_DESCRIPTION: outputs[k].get('Description',
                                                       'No description given'),
                api.OUTPUT_KEY: k,
                api.OUTPUT_VALUE: stack.output(k)}

    return [format_stack_output(key) for key in outputs]


def format_stack(stack):
    '''
    Return a representation of the given stack that matches the API output
    expectations.
    '''
    info = {
        api.STACK_NAME: stack.name,
        api.STACK_ID: dict(stack.identifier()),
        api.STACK_CREATION_TIME: timeutils.isotime(stack.created_time),
        api.STACK_UPDATED_TIME: timeutils.isotime(stack.updated_time),
        api.STACK_NOTIFICATION_TOPICS: [],  # TODO Not implemented yet
        api.STACK_PARAMETERS: stack.parameters.map(str),
        api.STACK_DESCRIPTION: stack.t[template.DESCRIPTION],
        api.STACK_TMPL_DESCRIPTION: stack.t[template.DESCRIPTION],
        api.STACK_ACTION: stack.action or '',
        api.STACK_STATUS: stack.status or '',
        api.STACK_STATUS_DATA: stack.status_reason,
        api.STACK_CAPABILITIES: [],   # TODO Not implemented yet
        api.STACK_DISABLE_ROLLBACK: stack.disable_rollback,
        api.STACK_TIMEOUT: stack.timeout_mins,
    }

    # only show the outputs on a completely created or updated stack
    if (stack.action != stack.DELETE and stack.status == stack.COMPLETE):
        info[api.STACK_OUTPUTS] = format_stack_outputs(stack, stack.outputs)

    return info


def format_stack_resource(resource, detail=True):
    '''
    Return a representation of the given resource that matches the API output
    expectations.
    '''
    last_updated_time = resource.updated_time or resource.created_time
    res = {
        api.RES_UPDATED_TIME: timeutils.isotime(last_updated_time),
        api.RES_NAME: resource.name,
        api.RES_PHYSICAL_ID: resource.resource_id or '',
        api.RES_METADATA: resource.metadata,
        api.RES_ACTION: resource.action,
        api.RES_STATUS: resource.status,
        api.RES_STATUS_DATA: resource.status_reason,
        api.RES_TYPE: resource.t['Type'],
        api.RES_ID: dict(resource.identifier()),
        api.RES_STACK_ID: dict(resource.stack.identifier()),
        api.RES_STACK_NAME: resource.stack.name,
        api.RES_REQUIRED_BY: resource.required_by(),
    }

    if detail:
        res[api.RES_DESCRIPTION] = resource.parsed_template('Description', '')
        res[api.RES_METADATA] = resource.metadata

    return res


def format_event(event):
    stack_identifier = event.stack.identifier()

    result = {
        api.EVENT_ID: dict(event.identifier()),
        api.EVENT_STACK_ID: dict(stack_identifier),
        api.EVENT_STACK_NAME: stack_identifier.stack_name,
        api.EVENT_TIMESTAMP: timeutils.isotime(event.timestamp),
        api.EVENT_RES_NAME: event.resource_name,
        api.EVENT_RES_PHYSICAL_ID: event.physical_resource_id,
        api.EVENT_RES_ACTION: event.action,
        api.EVENT_RES_STATUS: event.status,
        api.EVENT_RES_STATUS_DATA: event.reason,
        api.EVENT_RES_TYPE: event.resource_type,
        api.EVENT_RES_PROPERTIES: event.resource_properties,
    }

    return result


def format_watch(watch):

    result = {
        api.WATCH_ACTIONS_ENABLED: watch.rule.get(api.RULE_ACTIONS_ENABLED),
        api.WATCH_ALARM_ACTIONS: watch.rule.get(api.RULE_ALARM_ACTIONS),
        api.WATCH_TOPIC: watch.rule.get(api.RULE_TOPIC),
        api.WATCH_UPDATED_TIME: timeutils.isotime(watch.updated_at),
        api.WATCH_DESCRIPTION: watch.rule.get(api.RULE_DESCRIPTION),
        api.WATCH_NAME: watch.name,
        api.WATCH_COMPARISON: watch.rule.get(api.RULE_COMPARISON),
        api.WATCH_DIMENSIONS: watch.rule.get(api.RULE_DIMENSIONS) or [],
        api.WATCH_PERIODS: watch.rule.get(api.RULE_PERIODS),
        api.WATCH_INSUFFICIENT_ACTIONS:
        watch.rule.get(api.RULE_INSUFFICIENT_ACTIONS),
        api.WATCH_METRIC_NAME: watch.rule.get(api.RULE_METRIC_NAME),
        api.WATCH_NAMESPACE: watch.rule.get(api.RULE_NAMESPACE),
        api.WATCH_OK_ACTIONS: watch.rule.get(api.RULE_OK_ACTIONS),
        api.WATCH_PERIOD: watch.rule.get(api.RULE_PERIOD),
        api.WATCH_STATE_REASON: watch.rule.get(api.RULE_STATE_REASON),
        api.WATCH_STATE_REASON_DATA:
        watch.rule.get(api.RULE_STATE_REASON_DATA),
        api.WATCH_STATE_UPDATED_TIME: timeutils.isotime(
            watch.rule.get(api.RULE_STATE_UPDATED_TIME)),
        api.WATCH_STATE_VALUE: watch.state,
        api.WATCH_STATISTIC: watch.rule.get(api.RULE_STATISTIC),
        api.WATCH_THRESHOLD: watch.rule.get(api.RULE_THRESHOLD),
        api.WATCH_UNIT: watch.rule.get(api.RULE_UNIT),
        api.WATCH_STACK_ID: watch.stack_id
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
        api.WATCH_DATA_ALARM: wd.watch_rule.name,
        api.WATCH_DATA_METRIC: metric_name,
        api.WATCH_DATA_TIME: timeutils.isotime(wd.created_at),
        api.WATCH_DATA_NAMESPACE: namespace,
        api.WATCH_DATA: metric_data
    }

    return result
