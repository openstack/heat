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

from heat.common import template_format
from heat.rpc import api
from heat.openstack.common import timeutils
from heat.engine import constraints as constr

from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

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
        logger.exception(_('create timeout conversion'))
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
            raise ValueError(_('Unexpected value for parameter'
                               ' %(name)s : %(value)s') %
                             dict(name=api.PARAM_DISABLE_ROLLBACK,
                                  value=disable_rollback))

    adopt_data = params.get(api.PARAM_ADOPT_STACK_DATA)
    if adopt_data:
        adopt_data = template_format.simple_parse(adopt_data)
        if not isinstance(adopt_data, dict):
            raise ValueError(
                _('Unexpected adopt data "%s". Adopt data must be a dict.')
                % adopt_data)
        kwargs[api.PARAM_ADOPT_STACK_DATA] = adopt_data

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
    updated_time = stack.updated_time and timeutils.isotime(stack.updated_time)
    info = {
        api.STACK_NAME: stack.name,
        api.STACK_ID: dict(stack.identifier()),
        api.STACK_CREATION_TIME: timeutils.isotime(stack.created_time),
        api.STACK_UPDATED_TIME: updated_time,
        api.STACK_NOTIFICATION_TOPICS: [],  # TODO Not implemented yet
        api.STACK_PARAMETERS: stack.parameters.map(str),
        api.STACK_DESCRIPTION: stack.t[stack.t.DESCRIPTION],
        api.STACK_TMPL_DESCRIPTION: stack.t[stack.t.DESCRIPTION],
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

    if getattr(resource, 'nested', None) is not None:
        res[api.RES_MEMBERS] = [r.resource_id for r in
                                resource.nested().resources.itervalues()]

    return res


def format_stack_preview(stack):
    def format_resource(res):
        if isinstance(res, list):
            return map(format_resource, res)
        return format_stack_resource(res)

    fmt_stack = format_stack(stack)
    fmt_resources = map(format_resource, stack.preview_resources())
    fmt_stack['resources'] = fmt_resources

    return fmt_stack


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


def format_notification_body(stack):
    # some other posibilities here are:
    # - template name
    # - template size
    # - resource count
    if stack.status is not None and stack.action is not None:
        state = '_'.join(stack.state)
    else:
        state = 'Unknown'
    result = {
        api.NOTIFY_TENANT_ID: stack.context.tenant_id,
        api.NOTIFY_USER_ID: stack.context.user,
        api.NOTIFY_STACK_ID: stack.identifier().arn(),
        api.NOTIFY_STACK_NAME: stack.name,
        api.NOTIFY_STATE: state,
        api.NOTIFY_STATE_REASON: stack.status_reason,
        api.NOTIFY_CREATE_AT: timeutils.isotime(stack.created_time),
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
        logger.error(_("Unexpected number of keys in watch_data.data!"))
        return

    result = {
        api.WATCH_DATA_ALARM: wd.watch_rule.name,
        api.WATCH_DATA_METRIC: metric_name,
        api.WATCH_DATA_TIME: timeutils.isotime(wd.created_at),
        api.WATCH_DATA_NAMESPACE: namespace,
        api.WATCH_DATA: metric_data
    }

    return result


def format_validate_parameter(param):
    """
    Format a template parameter for validate template API call

    Formats a template parameter and its schema information from the engine's
    internal representation (i.e. a Parameter object and its associated
    Schema object) to a representation expected by the current API (for example
    to be compatible to CFN syntax).
    """

    # map of Schema object types to API expected types
    schema_to_api_types = {
        param.schema.STRING: api.PARAM_TYPE_STRING,
        param.schema.NUMBER: api.PARAM_TYPE_NUMBER,
        param.schema.LIST: api.PARAM_TYPE_COMMA_DELIMITED_LIST,
        param.schema.MAP: api.PARAM_TYPE_JSON
    }

    res = {
        api.PARAM_TYPE: schema_to_api_types.get(param.schema.type,
                                                param.schema.type),
        api.PARAM_DESCRIPTION: param.description(),
        api.PARAM_NO_ECHO: 'true' if param.hidden() else 'false',
        api.PARAM_LABEL: param.label()
    }

    if param.has_default():
        res[api.PARAM_DEFAULT] = param.default()

    constraint_description = []

    # build constraints
    for c in param.schema.constraints:
        if isinstance(c, constr.Length):
            if c.min is not None:
                res[api.PARAM_MIN_LENGTH] = c.min

            if c.max is not None:
                res[api.PARAM_MAX_LENGTH] = c.max

        elif isinstance(c, constr.Range):
            if c.min is not None:
                res[api.PARAM_MIN_VALUE] = c.min

            if c.max is not None:
                res[api.PARAM_MAX_VALUE] = c.max

        elif isinstance(c, constr.AllowedValues):
            res[api.PARAM_ALLOWED_VALUES] = list(c.allowed)

        elif isinstance(c, constr.AllowedPattern):
            res[api.PARAM_ALLOWED_PATTERN] = c.pattern

        if c.description:
            constraint_description.append(c.description)

    if constraint_description:
        res[api.PARAM_CONSTRAINT_DESCRIPTION] = " ".join(
            constraint_description)

    return res


def format_software_config(sc):
    if sc is None:
        return
    result = {
        api.SOFTWARE_CONFIG_ID: sc.id,
        api.SOFTWARE_CONFIG_NAME: sc.name,
        api.SOFTWARE_CONFIG_GROUP: sc.group,
        api.SOFTWARE_CONFIG_CONFIG: sc.config['config'],
        api.SOFTWARE_CONFIG_INPUTS: sc.config['inputs'],
        api.SOFTWARE_CONFIG_OUTPUTS: sc.config['outputs'],
        api.SOFTWARE_CONFIG_OPTIONS: sc.config['options']
    }
    return result


def format_software_deployment(sd):
    if sd is None:
        return
    result = {
        api.SOFTWARE_DEPLOYMENT_ID: sd.id,
        api.SOFTWARE_DEPLOYMENT_SERVER_ID: sd.server_id,
        api.SOFTWARE_DEPLOYMENT_INPUT_VALUES: sd.input_values,
        api.SOFTWARE_DEPLOYMENT_OUTPUT_VALUES: sd.output_values,
        api.SOFTWARE_DEPLOYMENT_ACTION: sd.action,
        api.SOFTWARE_DEPLOYMENT_STATUS: sd.status,
        api.SOFTWARE_DEPLOYMENT_STATUS_REASON: sd.status_reason,
        api.SOFTWARE_DEPLOYMENT_SIGNAL_ID: sd.signal_id,
        api.SOFTWARE_DEPLOYMENT_CONFIG_ID: sd.config.id,
    }
    return result
