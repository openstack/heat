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

import collections

from oslo_log import log as logging
from oslo_utils import timeutils
import six

from heat.common.i18n import _
from heat.common.i18n import _LE
from heat.common import param_utils
from heat.common import template_format
from heat.engine import constraints as constr
from heat.rpc import api as rpc_api

LOG = logging.getLogger(__name__)


def extract_args(params):
    '''
    Extract any arguments passed as parameters through the API and return them
    as a dictionary. This allows us to filter the passed args and do type
    conversion where appropriate
    '''
    kwargs = {}
    timeout_mins = params.get(rpc_api.PARAM_TIMEOUT)
    if timeout_mins not in ('0', 0, None):
        try:
            timeout = int(timeout_mins)
        except (ValueError, TypeError):
            LOG.exception(_LE('Timeout conversion failed'))
        else:
            if timeout > 0:
                kwargs[rpc_api.PARAM_TIMEOUT] = timeout
            else:
                raise ValueError(_('Invalid timeout value %s') % timeout)

    if rpc_api.PARAM_DISABLE_ROLLBACK in params:
        disable_rollback = param_utils.extract_bool(
            params[rpc_api.PARAM_DISABLE_ROLLBACK])
        kwargs[rpc_api.PARAM_DISABLE_ROLLBACK] = disable_rollback

    if rpc_api.PARAM_SHOW_DELETED in params:
        params[rpc_api.PARAM_SHOW_DELETED] = param_utils.extract_bool(
            params[rpc_api.PARAM_SHOW_DELETED])

    adopt_data = params.get(rpc_api.PARAM_ADOPT_STACK_DATA)
    if adopt_data:
        try:
            adopt_data = template_format.simple_parse(adopt_data)
        except ValueError as exc:
            raise ValueError(_('Invalid adopt data: %s') % exc)
        kwargs[rpc_api.PARAM_ADOPT_STACK_DATA] = adopt_data

    tags = params.get(rpc_api.PARAM_TAGS)
    if tags:
        if not isinstance(tags, list):
            raise ValueError(_('Invalid tags, not a list: %s') % tags)

        for tag in tags:
            if not isinstance(tag, six.string_types):
                raise ValueError(_('Invalid tag, "%s" is not a string') % tag)

            if len(tag) > 80:
                raise ValueError(_('Invalid tag, "%s" is longer than 80 '
                                   'characters') % tag)

            # Comma is not allowed as per the API WG tagging guidelines
            if ',' in tag:
                raise ValueError(_('Invalid tag, "%s" contains a comma') % tag)

        kwargs[rpc_api.PARAM_TAGS] = tags

    return kwargs


def format_stack_outputs(stack, outputs):
    '''
    Return a representation of the given output template for the given stack
    that matches the API output expectations.
    '''
    def format_stack_output(k):
        output = {
            rpc_api.OUTPUT_DESCRIPTION: outputs[k].get('Description',
                                                       'No description given'),
            rpc_api.OUTPUT_KEY: k,
            rpc_api.OUTPUT_VALUE: stack.output(k)
        }
        if outputs[k].get('error_msg'):
            output.update({rpc_api.OUTPUT_ERROR: outputs[k].get('error_msg')})
        return output

    return [format_stack_output(key) for key in outputs]


def format_stack(stack, preview=False):
    '''
    Return a representation of the given stack that matches the API output
    expectations.
    '''
    updated_time = stack.updated_time and timeutils.isotime(stack.updated_time)
    info = {
        rpc_api.STACK_NAME: stack.name,
        rpc_api.STACK_ID: dict(stack.identifier()),
        rpc_api.STACK_CREATION_TIME: timeutils.isotime(stack.created_time),
        rpc_api.STACK_UPDATED_TIME: updated_time,
        rpc_api.STACK_NOTIFICATION_TOPICS: [],  # TODO(?) Not implemented yet
        rpc_api.STACK_PARAMETERS: stack.parameters.map(str),
        rpc_api.STACK_DESCRIPTION: stack.t[stack.t.DESCRIPTION],
        rpc_api.STACK_TMPL_DESCRIPTION: stack.t[stack.t.DESCRIPTION],
        rpc_api.STACK_CAPABILITIES: [],   # TODO(?) Not implemented yet
        rpc_api.STACK_DISABLE_ROLLBACK: stack.disable_rollback,
        rpc_api.STACK_TIMEOUT: stack.timeout_mins,
        rpc_api.STACK_OWNER: stack.username,
        rpc_api.STACK_PARENT: stack.owner_id,
        rpc_api.STACK_USER_PROJECT_ID: stack.stack_user_project_id,
        rpc_api.STACK_TAGS: stack.tags,
    }

    if not preview:
        update_info = {
            rpc_api.STACK_ACTION: stack.action or '',
            rpc_api.STACK_STATUS: stack.status or '',
            rpc_api.STACK_STATUS_DATA: stack.status_reason,
        }
        info.update(update_info)

    # allow users to view the outputs of stacks
    if (stack.action != stack.DELETE and stack.status != stack.IN_PROGRESS):
        info[rpc_api.STACK_OUTPUTS] = format_stack_outputs(stack,
                                                           stack.outputs)

    return info


def format_resource_attributes(resource, with_attr=None):
    def resolve(attr, resolver):
        try:
            return resolver[attr]
        except Exception:
            return None

    resolver = resource.attributes
    if 'show' in resolver.keys():
        show_attr = resolver['show']
        if isinstance(show_attr, collections.Mapping):
            resolver = show_attr

    if not with_attr:
        with_attr = []

    attributes = set(resolver.keys() + with_attr)
    return dict((attr, resolve(attr, resolver))
                for attr in attributes)


def format_resource_properties(resource):
    def get_property(prop):
        try:
            return resource.properties[prop]
        except (KeyError, ValueError):
            return None

    return dict((prop, get_property(prop))
                for prop in resource.properties_schema.keys())


def format_stack_resource(resource, detail=True, with_props=False,
                          with_attr=None):
    '''
    Return a representation of the given resource that matches the API output
    expectations.
    '''
    last_updated_time = resource.updated_time or resource.created_time
    res = {
        rpc_api.RES_UPDATED_TIME: timeutils.isotime(last_updated_time),
        rpc_api.RES_NAME: resource.name,
        rpc_api.RES_PHYSICAL_ID: resource.resource_id or '',
        rpc_api.RES_ACTION: resource.action,
        rpc_api.RES_STATUS: resource.status,
        rpc_api.RES_STATUS_DATA: resource.status_reason,
        rpc_api.RES_TYPE: resource.type(),
        rpc_api.RES_ID: dict(resource.identifier()),
        rpc_api.RES_STACK_ID: dict(resource.stack.identifier()),
        rpc_api.RES_STACK_NAME: resource.stack.name,
        rpc_api.RES_REQUIRED_BY: resource.required_by(),
    }

    if (hasattr(resource, 'nested') and callable(resource.nested) and
            resource.nested() is not None):
        res[rpc_api.RES_NESTED_STACK_ID] = dict(resource.nested().identifier())

    if resource.stack.parent_resource_name:
        res[rpc_api.RES_PARENT_RESOURCE] = resource.stack.parent_resource_name

    if detail:
        res[rpc_api.RES_DESCRIPTION] = resource.t.description
        res[rpc_api.RES_METADATA] = resource.metadata_get()
        res[rpc_api.RES_SCHEMA_ATTRIBUTES] = format_resource_attributes(
            resource, with_attr)

    if with_props:
        res[rpc_api.RES_SCHEMA_PROPERTIES] = format_resource_properties(
            resource)

    return res


def format_stack_preview(stack):
    def format_resource(res):
        if isinstance(res, list):
            return map(format_resource, res)
        return format_stack_resource(res, with_props=True)

    fmt_stack = format_stack(stack, preview=True)
    fmt_resources = map(format_resource, stack.preview_resources())
    fmt_stack['resources'] = fmt_resources

    return fmt_stack


def format_event(event):
    stack_identifier = event.stack.identifier()

    result = {
        rpc_api.EVENT_ID: dict(event.identifier()),
        rpc_api.EVENT_STACK_ID: dict(stack_identifier),
        rpc_api.EVENT_STACK_NAME: stack_identifier.stack_name,
        rpc_api.EVENT_TIMESTAMP: timeutils.isotime(event.timestamp),
        rpc_api.EVENT_RES_NAME: event.resource_name,
        rpc_api.EVENT_RES_PHYSICAL_ID: event.physical_resource_id,
        rpc_api.EVENT_RES_ACTION: event.action,
        rpc_api.EVENT_RES_STATUS: event.status,
        rpc_api.EVENT_RES_STATUS_DATA: event.reason,
        rpc_api.EVENT_RES_TYPE: event.resource_type,
        rpc_api.EVENT_RES_PROPERTIES: event.resource_properties,
    }

    return result


def format_notification_body(stack):
    # some other possibilities here are:
    # - template name
    # - template size
    # - resource count
    if stack.status is not None and stack.action is not None:
        state = '_'.join(stack.state)
    else:
        state = 'Unknown'
    result = {
        rpc_api.NOTIFY_TENANT_ID: stack.context.tenant_id,
        rpc_api.NOTIFY_USER_ID: stack.context.user,
        rpc_api.NOTIFY_STACK_ID: stack.identifier().arn(),
        rpc_api.NOTIFY_STACK_NAME: stack.name,
        rpc_api.NOTIFY_STATE: state,
        rpc_api.NOTIFY_STATE_REASON: stack.status_reason,
        rpc_api.NOTIFY_CREATE_AT: timeutils.isotime(stack.created_time),
    }
    return result


def format_watch(watch):

    result = {
        rpc_api.WATCH_ACTIONS_ENABLED: watch.rule.get(
            rpc_api.RULE_ACTIONS_ENABLED),
        rpc_api.WATCH_ALARM_ACTIONS: watch.rule.get(
            rpc_api.RULE_ALARM_ACTIONS),
        rpc_api.WATCH_TOPIC: watch.rule.get(rpc_api.RULE_TOPIC),
        rpc_api.WATCH_UPDATED_TIME: timeutils.isotime(watch.updated_at),
        rpc_api.WATCH_DESCRIPTION: watch.rule.get(rpc_api.RULE_DESCRIPTION),
        rpc_api.WATCH_NAME: watch.name,
        rpc_api.WATCH_COMPARISON: watch.rule.get(rpc_api.RULE_COMPARISON),
        rpc_api.WATCH_DIMENSIONS: watch.rule.get(
            rpc_api.RULE_DIMENSIONS) or [],
        rpc_api.WATCH_PERIODS: watch.rule.get(rpc_api.RULE_PERIODS),
        rpc_api.WATCH_INSUFFICIENT_ACTIONS:
        watch.rule.get(rpc_api.RULE_INSUFFICIENT_ACTIONS),
        rpc_api.WATCH_METRIC_NAME: watch.rule.get(rpc_api.RULE_METRIC_NAME),
        rpc_api.WATCH_NAMESPACE: watch.rule.get(rpc_api.RULE_NAMESPACE),
        rpc_api.WATCH_OK_ACTIONS: watch.rule.get(rpc_api.RULE_OK_ACTIONS),
        rpc_api.WATCH_PERIOD: watch.rule.get(rpc_api.RULE_PERIOD),
        rpc_api.WATCH_STATE_REASON: watch.rule.get(rpc_api.RULE_STATE_REASON),
        rpc_api.WATCH_STATE_REASON_DATA:
        watch.rule.get(rpc_api.RULE_STATE_REASON_DATA),
        rpc_api.WATCH_STATE_UPDATED_TIME: timeutils.isotime(
            watch.rule.get(rpc_api.RULE_STATE_UPDATED_TIME)),
        rpc_api.WATCH_STATE_VALUE: watch.state,
        rpc_api.WATCH_STATISTIC: watch.rule.get(rpc_api.RULE_STATISTIC),
        rpc_api.WATCH_THRESHOLD: watch.rule.get(rpc_api.RULE_THRESHOLD),
        rpc_api.WATCH_UNIT: watch.rule.get(rpc_api.RULE_UNIT),
        rpc_api.WATCH_STACK_ID: watch.stack_id
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
        LOG.error(_LE("Unexpected number of keys in watch_data.data!"))
        return

    result = {
        rpc_api.WATCH_DATA_ALARM: wd.watch_rule.name,
        rpc_api.WATCH_DATA_METRIC: metric_name,
        rpc_api.WATCH_DATA_TIME: timeutils.isotime(wd.created_at),
        rpc_api.WATCH_DATA_NAMESPACE: namespace,
        rpc_api.WATCH_DATA: metric_data
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
        param.schema.STRING: rpc_api.PARAM_TYPE_STRING,
        param.schema.NUMBER: rpc_api.PARAM_TYPE_NUMBER,
        param.schema.LIST: rpc_api.PARAM_TYPE_COMMA_DELIMITED_LIST,
        param.schema.MAP: rpc_api.PARAM_TYPE_JSON,
        param.schema.BOOLEAN: rpc_api.PARAM_TYPE_BOOLEAN
    }

    res = {
        rpc_api.PARAM_TYPE: schema_to_api_types.get(param.schema.type,
                                                    param.schema.type),
        rpc_api.PARAM_DESCRIPTION: param.description(),
        rpc_api.PARAM_NO_ECHO: 'true' if param.hidden() else 'false',
        rpc_api.PARAM_LABEL: param.label()
    }

    if param.has_value():
        res[rpc_api.PARAM_DEFAULT] = param.value()

    constraint_description = []

    # build constraints
    for c in param.schema.constraints:
        if isinstance(c, constr.Length):
            if c.min is not None:
                res[rpc_api.PARAM_MIN_LENGTH] = c.min

            if c.max is not None:
                res[rpc_api.PARAM_MAX_LENGTH] = c.max

        elif isinstance(c, constr.Range):
            if c.min is not None:
                res[rpc_api.PARAM_MIN_VALUE] = c.min

            if c.max is not None:
                res[rpc_api.PARAM_MAX_VALUE] = c.max

        elif isinstance(c, constr.AllowedValues):
            res[rpc_api.PARAM_ALLOWED_VALUES] = list(c.allowed)

        elif isinstance(c, constr.AllowedPattern):
            res[rpc_api.PARAM_ALLOWED_PATTERN] = c.pattern

        elif isinstance(c, constr.CustomConstraint):
            res[rpc_api.PARAM_CUSTOM_CONSTRAINT] = c.name

        if c.description:
            constraint_description.append(c.description)

    if constraint_description:
        res[rpc_api.PARAM_CONSTRAINT_DESCRIPTION] = " ".join(
            constraint_description)

    return res


def format_software_config(sc):
    if sc is None:
        return
    result = {
        rpc_api.SOFTWARE_CONFIG_ID: sc.id,
        rpc_api.SOFTWARE_CONFIG_NAME: sc.name,
        rpc_api.SOFTWARE_CONFIG_GROUP: sc.group,
        rpc_api.SOFTWARE_CONFIG_CONFIG: sc.config['config'],
        rpc_api.SOFTWARE_CONFIG_INPUTS: sc.config['inputs'],
        rpc_api.SOFTWARE_CONFIG_OUTPUTS: sc.config['outputs'],
        rpc_api.SOFTWARE_CONFIG_OPTIONS: sc.config['options'],
        rpc_api.SOFTWARE_CONFIG_CREATION_TIME: timeutils.isotime(
            sc.created_at),
    }
    return result


def format_software_deployment(sd):
    if sd is None:
        return
    result = {
        rpc_api.SOFTWARE_DEPLOYMENT_ID: sd.id,
        rpc_api.SOFTWARE_DEPLOYMENT_SERVER_ID: sd.server_id,
        rpc_api.SOFTWARE_DEPLOYMENT_INPUT_VALUES: sd.input_values,
        rpc_api.SOFTWARE_DEPLOYMENT_OUTPUT_VALUES: sd.output_values,
        rpc_api.SOFTWARE_DEPLOYMENT_ACTION: sd.action,
        rpc_api.SOFTWARE_DEPLOYMENT_STATUS: sd.status,
        rpc_api.SOFTWARE_DEPLOYMENT_STATUS_REASON: sd.status_reason,
        rpc_api.SOFTWARE_DEPLOYMENT_CONFIG_ID: sd.config.id,
        rpc_api.SOFTWARE_DEPLOYMENT_CREATION_TIME: timeutils.isotime(
            sd.created_at)
    }
    if sd.updated_at:
        result[rpc_api.SOFTWARE_DEPLOYMENT_UPDATED_TIME] = timeutils.isotime(
            sd.updated_at)
    return result


def format_snapshot(snapshot):
    if snapshot is None:
        return
    result = {
        rpc_api.SNAPSHOT_ID: snapshot.id,
        rpc_api.SNAPSHOT_NAME: snapshot.name,
        rpc_api.SNAPSHOT_STATUS: snapshot.status,
        rpc_api.SNAPSHOT_STATUS_REASON: snapshot.status_reason,
        rpc_api.SNAPSHOT_DATA: snapshot.data,
        rpc_api.SNAPSHOT_CREATION_TIME: timeutils.isotime(
            snapshot.created_at),
    }
    return result
