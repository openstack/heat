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
from heat.common import param_utils
from heat.common import template_format
from heat.common import timeutils as heat_timeutils
from heat.engine import constraints as constr
from heat.rpc import api as rpc_api

LOG = logging.getLogger(__name__)


def extract_args(params):
    """Extract arguments passed as parameters and return them as a dictionary.

    Extract any arguments passed as parameters through the API and return them
    as a dictionary. This allows us to filter the passed args and do type
    conversion where appropriate
    """
    kwargs = {}
    timeout_mins = params.get(rpc_api.PARAM_TIMEOUT)
    if timeout_mins not in ('0', 0, None):
        try:
            timeout = int(timeout_mins)
        except (ValueError, TypeError):
            LOG.exception('Timeout conversion failed')
        else:
            if timeout > 0:
                kwargs[rpc_api.PARAM_TIMEOUT] = timeout
            else:
                raise ValueError(_('Invalid timeout value %s') % timeout)
    for name in [rpc_api.PARAM_CONVERGE, rpc_api.PARAM_DISABLE_ROLLBACK]:
        if name in params:
            bool_value = param_utils.extract_bool(name, params[name])
            kwargs[name] = bool_value

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


def _parse_object_status(status):
    """Parse input status into action and status if possible.

    This function parses a given string (or list of strings) and see if it
    contains the action part. The action part is exacted if found.

    :param status: A string or a list of strings where each string contains
                   a status to be checked.
    :returns: (actions, statuses) tuple, where actions is a set of actions
              extracted from the input status and statuses is a set of pure
              object status.
    """

    if not isinstance(status, list):
        status = [status]

    status_set = set()
    action_set = set()
    for val in status:
        # Note: cannot reference Stack.STATUSES due to circular reference issue
        for s in ('COMPLETE', 'FAILED', 'IN_PROGRESS'):
            index = val.rfind(s)
            if index != -1:
                status_set.add(val[index:])
                if index > 1:
                    action_set.add(val[:index - 1])
                break

    return action_set, status_set


def translate_filters(params):
    """Translate filter names to their corresponding DB field names.

    :param params: A dictionary containing keys from engine.api.STACK_KEYS
                    and other keys previously leaked to users.
    :returns: A dict containing only valid DB filed names.
    """
    key_map = {
        rpc_api.STACK_NAME: 'name',
        rpc_api.STACK_ACTION: 'action',
        rpc_api.STACK_STATUS: 'status',
        rpc_api.STACK_STATUS_DATA: 'status_reason',
        rpc_api.STACK_DISABLE_ROLLBACK: 'disable_rollback',
        rpc_api.STACK_TIMEOUT: 'timeout',
        rpc_api.STACK_OWNER: 'username',
        rpc_api.STACK_PARENT: 'owner_id',
        rpc_api.STACK_USER_PROJECT_ID: 'stack_user_project_id'
    }

    for key, field in key_map.items():
        value = params.pop(key, None)
        if not value:
            continue

        fld_value = params.get(field, None)
        if fld_value:
            if not isinstance(fld_value, list):
                fld_value = [fld_value]
            if not isinstance(value, list):
                value = [value]

            value.extend(fld_value)

        params[field] = value

    # Deal with status which might be of form <ACTION>_<STATUS>, e.g.
    # "CREATE_FAILED". Note this logic is still not ideal due to the fact
    # that action and status are stored separately.
    if 'status' in params:
        a_set, s_set = _parse_object_status(params['status'])
        statuses = sorted(s_set)
        params['status'] = statuses[0] if len(statuses) == 1 else statuses

        if a_set:
            a = params.get('action', [])
            action_set = set(a) if isinstance(a, list) else set([a])
            actions = sorted(action_set.union(a_set))

            params['action'] = actions[0] if len(actions) == 1 else actions

    return params


def format_stack_outputs(outputs, resolve_value=False):
    """Return a representation of the given output template.

    Return a representation of the given output template for the given stack
    that matches the API output expectations.
    """
    return [format_stack_output(outputs[key], resolve_value=resolve_value)
            for key in outputs]


def format_stack_output(output_defn, resolve_value=True):
    result = {
        rpc_api.OUTPUT_KEY: output_defn.name,
        rpc_api.OUTPUT_DESCRIPTION: output_defn.description(),
    }

    if resolve_value:
        value = None
        try:
            value = output_defn.get_value()
        except Exception as ex:
            # We don't need error raising, just adding output_error to
            # resulting dict.
            result.update({rpc_api.OUTPUT_ERROR: six.text_type(ex)})
        finally:
            result.update({rpc_api.OUTPUT_VALUE: value})

    return result


def format_stack(stack, preview=False, resolve_outputs=True):
    """Return a representation of the given stack.

    Return a representation of the given stack that matches the API output
    expectations.
    """
    updated_time = heat_timeutils.isotime(stack.updated_time)
    created_time = heat_timeutils.isotime(stack.created_time or
                                          timeutils.utcnow())
    deleted_time = heat_timeutils.isotime(stack.deleted_time)
    info = {
        rpc_api.STACK_NAME: stack.name,
        rpc_api.STACK_ID: dict(stack.identifier()),
        rpc_api.STACK_CREATION_TIME: created_time,
        rpc_api.STACK_UPDATED_TIME: updated_time,
        rpc_api.STACK_DELETION_TIME: deleted_time,
        rpc_api.STACK_NOTIFICATION_TOPICS: [],  # TODO(therve) Not implemented
        rpc_api.STACK_PARAMETERS: stack.parameters.map(six.text_type),
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
    if (not (stack.action == stack.DELETE and stack.status == stack.COMPLETE)
            and resolve_outputs):
        info[rpc_api.STACK_OUTPUTS] = format_stack_outputs(stack.outputs,
                                                           resolve_value=True)

    return info


def format_stack_db_object(stack):
    """Return a summary representation of the given stack.

    Given a stack versioned db object, return a representation of the given
    stack for a stack listing.
    """
    updated_time = heat_timeutils.isotime(stack.updated_at)
    created_time = heat_timeutils.isotime(stack.created_at)
    deleted_time = heat_timeutils.isotime(stack.deleted_at)

    tags = None
    if stack.tags:
        tags = [t.tag for t in stack.tags]
    info = {
        rpc_api.STACK_ID: dict(stack.identifier()),
        rpc_api.STACK_NAME: stack.name,
        rpc_api.STACK_DESCRIPTION: '',
        rpc_api.STACK_ACTION: stack.action,
        rpc_api.STACK_STATUS: stack.status,
        rpc_api.STACK_STATUS_DATA: stack.status_reason,
        rpc_api.STACK_CREATION_TIME: created_time,
        rpc_api.STACK_UPDATED_TIME: updated_time,
        rpc_api.STACK_DELETION_TIME: deleted_time,
        rpc_api.STACK_OWNER: stack.username,
        rpc_api.STACK_PARENT: stack.owner_id,
        rpc_api.STACK_USER_PROJECT_ID: stack.stack_user_project_id,
        rpc_api.STACK_TAGS: tags,
    }

    return info


def format_resource_attributes(resource, with_attr=None):
    resolver = resource.attributes
    if not with_attr:
        with_attr = []

    # Always return live values for consistency
    resolver.reset_resolved_values()

    def resolve(attr, resolver):
        try:
            return resolver._resolver(attr)
        except Exception:
            return None
    # if 'show' in attributes_schema, will resolve all attributes of resource
    # including the ones are not represented in response of show API, such as
    # 'console_urls' for nova server, user can view it by taking with_attr
    # parameter
    if 'show' in resolver:
        show_attr = resolve('show', resolver)
        # check if 'show' resolved to dictionary. so it's not None
        if isinstance(show_attr, collections.Mapping):
            for a in with_attr:
                if a not in show_attr:
                    show_attr[a] = resolve(a, resolver)
            return show_attr
        else:
            # remove 'show' attribute if it's None or not a mapping
            # then resolve all attributes manually
            del resolver._attributes['show']
    attributes = set(resolver) | set(with_attr)
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
    """Return a representation of the given resource.

    Return a representation of the given resource that matches the API output
    expectations.
    """
    created_time = heat_timeutils.isotime(resource.created_time)
    last_updated_time = heat_timeutils.isotime(
        resource.updated_time or resource.created_time)
    res = {
        rpc_api.RES_UPDATED_TIME: last_updated_time,
        rpc_api.RES_CREATION_TIME: created_time,
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

    if resource.has_nested():
        res[rpc_api.RES_NESTED_STACK_ID] = dict(resource.nested_identifier())

    if resource.stack.parent_resource_name:
        res[rpc_api.RES_PARENT_RESOURCE] = resource.stack.parent_resource_name

    if detail:
        res[rpc_api.RES_DESCRIPTION] = resource.t.description
        res[rpc_api.RES_METADATA] = resource.metadata_get()
        if with_attr is not False:
            res[rpc_api.RES_ATTRIBUTES] = format_resource_attributes(
                resource, with_attr)

    if with_props:
        res[rpc_api.RES_PROPERTIES] = format_resource_properties(
            resource)

    return res


def format_stack_preview(stack):
    def format_resource(res):
        if isinstance(res, list):
            return list(map(format_resource, res))
        return format_stack_resource(res, with_props=True)

    fmt_stack = format_stack(stack, preview=True)
    fmt_resources = list(map(format_resource, stack.preview_resources()))
    fmt_stack['resources'] = fmt_resources

    return fmt_stack


def format_event(event, stack_identifier, root_stack_identifier=None,
                 include_rsrc_prop_data=True):
    result = {
        rpc_api.EVENT_ID: dict(event.identifier(stack_identifier)),
        rpc_api.EVENT_STACK_ID: dict(stack_identifier),
        rpc_api.EVENT_STACK_NAME: stack_identifier.stack_name,
        rpc_api.EVENT_TIMESTAMP: heat_timeutils.isotime(event.created_at),
        rpc_api.EVENT_RES_NAME: event.resource_name,
        rpc_api.EVENT_RES_PHYSICAL_ID: event.physical_resource_id,
        rpc_api.EVENT_RES_ACTION: event.resource_action,
        rpc_api.EVENT_RES_STATUS: event.resource_status,
        rpc_api.EVENT_RES_STATUS_DATA: event.resource_status_reason,
        rpc_api.EVENT_RES_TYPE: event.resource_type,
    }
    if root_stack_identifier:
        result[rpc_api.EVENT_ROOT_STACK_ID] = dict(root_stack_identifier)
    if include_rsrc_prop_data:
        result[rpc_api.EVENT_RES_PROPERTIES] = event.resource_properties

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

    updated_at = heat_timeutils.isotime(stack.updated_time)
    result = {
        rpc_api.NOTIFY_TENANT_ID: stack.context.tenant_id,
        rpc_api.NOTIFY_USER_ID: stack.context.username,
        # deprecated: please use rpc_api.NOTIFY_USERID for user id or
        # rpc_api.NOTIFY_USERNAME for user name.
        rpc_api.NOTIFY_USERID: stack.context.user_id,
        rpc_api.NOTIFY_USERNAME: stack.context.username,
        rpc_api.NOTIFY_STACK_ID: stack.id,
        rpc_api.NOTIFY_STACK_NAME: stack.name,
        rpc_api.NOTIFY_STATE: state,
        rpc_api.NOTIFY_STATE_REASON: stack.status_reason,
        rpc_api.NOTIFY_CREATE_AT: heat_timeutils.isotime(stack.created_time),
        rpc_api.NOTIFY_TAGS: stack.tags,
        rpc_api.NOTIFY_UPDATE_AT: updated_at
    }
    if stack.t is not None:
        result[rpc_api.NOTIFY_DESCRIPTION] = stack.t[stack.t.DESCRIPTION]

    return result


def format_watch(watch):

    updated_time = heat_timeutils.isotime(watch.updated_at or
                                          timeutils.utcnow())
    result = {
        rpc_api.WATCH_ACTIONS_ENABLED: watch.rule.get(
            rpc_api.RULE_ACTIONS_ENABLED),
        rpc_api.WATCH_ALARM_ACTIONS: watch.rule.get(
            rpc_api.RULE_ALARM_ACTIONS),
        rpc_api.WATCH_TOPIC: watch.rule.get(rpc_api.RULE_TOPIC),
        rpc_api.WATCH_UPDATED_TIME: updated_time,
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
        rpc_api.WATCH_STATE_UPDATED_TIME: heat_timeutils.isotime(
            watch.rule.get(rpc_api.RULE_STATE_UPDATED_TIME,
                           timeutils.utcnow())),
        rpc_api.WATCH_STATE_VALUE: watch.state,
        rpc_api.WATCH_STATISTIC: watch.rule.get(rpc_api.RULE_STATISTIC),
        rpc_api.WATCH_THRESHOLD: watch.rule.get(rpc_api.RULE_THRESHOLD),
        rpc_api.WATCH_UNIT: watch.rule.get(rpc_api.RULE_UNIT),
        rpc_api.WATCH_STACK_ID: watch.stack_id
    }

    return result


def format_watch_data(wd, rule_names):

    # Demangle DB format data into something more easily used in the API
    # We are expecting a dict with exactly two items, Namespace and
    # a metric key
    namespace = wd.data['Namespace']
    metric = [(k, v) for k, v in wd.data.items() if k != 'Namespace']
    if len(metric) == 1:
        metric_name, metric_data = metric[0]
    else:
        LOG.error("Unexpected number of keys in watch_data.data!")
        return

    result = {
        rpc_api.WATCH_DATA_ALARM: rule_names.get(wd.watch_rule_id),
        rpc_api.WATCH_DATA_METRIC: metric_name,
        rpc_api.WATCH_DATA_TIME: heat_timeutils.isotime(wd.created_at),
        rpc_api.WATCH_DATA_NAMESPACE: namespace,
        rpc_api.WATCH_DATA: metric_data
    }

    return result


def format_validate_parameter(param):
    """Format a template parameter for validate template API call.

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

    if param.has_default():
        res[rpc_api.PARAM_DEFAULT] = param.default()

    if param.user_value:
        res[rpc_api.PARAM_VALUE] = param.user_value

    if param.tags():
        res[rpc_api.PARAM_TAG] = param.tags()

    _build_parameter_constraints(res, param)

    return res


def _build_parameter_constraints(res, param):
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

        elif isinstance(c, constr.Modulo):
            if c.step is not None:
                res[rpc_api.PARAM_STEP] = c.step

            if c.offset is not None:
                res[rpc_api.PARAM_OFFSET] = c.offset

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


def format_software_config(sc, detail=True, include_project=False):
    if sc is None:
        return
    result = {
        rpc_api.SOFTWARE_CONFIG_ID: sc.id,
        rpc_api.SOFTWARE_CONFIG_NAME: sc.name,
        rpc_api.SOFTWARE_CONFIG_GROUP: sc.group,
        rpc_api.SOFTWARE_CONFIG_CREATION_TIME:
            heat_timeutils.isotime(sc.created_at)
    }
    if detail:
        result[rpc_api.SOFTWARE_CONFIG_CONFIG] = sc.config['config']
        result[rpc_api.SOFTWARE_CONFIG_INPUTS] = sc.config['inputs']
        result[rpc_api.SOFTWARE_CONFIG_OUTPUTS] = sc.config['outputs']
        result[rpc_api.SOFTWARE_CONFIG_OPTIONS] = sc.config['options']

    if include_project:
        result[rpc_api.SOFTWARE_CONFIG_PROJECT] = sc.tenant
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
        rpc_api.SOFTWARE_DEPLOYMENT_CREATION_TIME:
            heat_timeutils.isotime(sd.created_at),
    }
    if sd.updated_at:
        result[rpc_api.SOFTWARE_DEPLOYMENT_UPDATED_TIME] = (
            heat_timeutils.isotime(sd.updated_at))
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
        rpc_api.SNAPSHOT_CREATION_TIME:
            heat_timeutils.isotime(snapshot.created_at),
    }
    return result
