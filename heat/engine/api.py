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
import logging
from heat.common import utils as heat_utils
from heat.engine import parser


logger = logging.getLogger('heat.engine.manager')

PARAM_KEYS = (
    PARAM_TIMEOUT,
    PARAM_USER_KEY_re,
    PARAM_USER_VALUE_fmt,
) = (
    'TimeoutInMinutes',
    re.compile(r'Parameters\.member\.(.*?)\.ParameterKey$'),
    'Parameters.member.%s.ParameterValue',
)


def extract_user_params(params):
    '''
    Extract a dictionary of user parameters (to e.g. a stack create command)
    from the parameter dictionary passed through the API.

    In the API parameters, each user parameter appears as two key-value pairs
    with keys of the form:

        Parameters.member.1.ParameterKey
        Parameters.member.1.ParameterValue
    '''
    def get_param_pairs():
        for k in params:
            keymatch = PARAM_USER_KEY_re.match(k)
            if keymatch:
                key = params[k]
                v = PARAM_USER_VALUE_fmt % keymatch.group(1)
                try:
                    value = params[v]
                except KeyError:
                    logger.error('Could not apply parameter %s' % key)

                yield (key, value)

    return dict(get_param_pairs())


def extract_args(params):
    '''
    Extract any arguments passed as parameters through the API and return them
    as a dictionary.
    '''
    kwargs = {}
    try:
        timeout_mins = int(params.get(PARAM_TIMEOUT, 0))
    except (ValueError, TypeError):
        logger.exception('create timeout conversion')
    else:
        if timeout_mins > 0:
            kwargs['timeout_mins'] = timeout_mins
    return kwargs


def _filter_keys(data, keys):
    '''
    Filter the provided data so that only the dictionary keys specified are
    present. If keys is None, return all of the data.
    '''
    if keys is not None:
        data = dict((k, v) for (k, v) in data.iteritems() if k in keys)

    return data


STACK_KEYS = (
    STACK_NAME, STACK_ID,
    STACK_CREATION_TIME, STACK_UPDATED_TIME, STACK_DELETION_TIME,
    STACK_NOTIFICATION_TOPICS,
    STACK_DESCRIPTION, STACK_TMPL_DESCRIPTION,
    STACK_PARAMETERS, STACK_OUTPUTS,
    STACK_STATUS, STACK_STATUS_DATA,
    STACK_TIMEOUT,
) = (
    'StackName', 'StackId',
    'CreationTime', 'LastUpdatedTime', 'DeletionTime',
    'NotificationARNs',
    'Description', 'TemplateDescription',
    'Parameters', 'Outputs',
    'StackStatus', 'StackStatusReason',
    PARAM_TIMEOUT,
)

KEYS_STACK = (
    STACK_NAME, STACK_ID,
    STACK_CREATION_TIME, STACK_UPDATED_TIME,
    STACK_NOTIFICATION_TOPICS,
    STACK_DESCRIPTION,
    STACK_PARAMETERS, STACK_DESCRIPTION, STACK_OUTPUTS,
    STACK_STATUS, STACK_STATUS_DATA,
    STACK_TIMEOUT,
)
KEYS_STACK_SUMMARY = (
    STACK_CREATION_TIME, STACK_DELETION_TIME,
    STACK_UPDATED_TIME,
    STACK_ID, STACK_NAME,
    STACK_TMPL_DESCRIPTION,
    STACK_STATUS, STACK_STATUS_DATA,
)


STACK_OUTPUT_KEYS = (
    OUTPUT_DESCRIPTION,
    OUTPUT_KEY, OUTPUT_VALUE,
) = (
    'Description',
    'OutputKey', 'OutputValue',
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


def format_stack(stack, keys=None):
    '''
    Return a representation of the given stack that matches the API output
    expectations.
    '''
    info = {
        STACK_NAME: stack.name,
        STACK_ID: stack.id,
        STACK_CREATION_TIME: heat_utils.strtime(stack.created_time),
        STACK_UPDATED_TIME: heat_utils.strtime(stack.updated_time),
        STACK_NOTIFICATION_TOPICS: [],  # TODO Not implemented yet
        STACK_PARAMETERS: stack.t[parser.PARAMETERS],
        STACK_DESCRIPTION: stack.t[parser.DESCRIPTION],
        STACK_TMPL_DESCRIPTION: stack.t[parser.DESCRIPTION],
        STACK_STATUS: stack.state,
        STACK_STATUS_DATA: stack.state_description,
        STACK_TIMEOUT: stack.timeout_mins,
    }

    # only show the outputs on a completely created stack
    if stack.state == stack.CREATE_COMPLETE:
        info[STACK_OUTPUTS] = format_stack_outputs(stack, stack.outputs)

    return _filter_keys(info, keys)


RES_KEYS = (
    RES_DESCRIPTION, RES_UPDATED_TIME,
    RES_NAME, RES_PHYSICAL_ID, RES_METADATA,
    RES_STATUS, RES_STATUS_DATA, RES_TYPE,
    RES_STACK_ID, RES_STACK_NAME,
    RES_TIMESTAMP,
) = (
    'Description', 'LastUpdatedTimestamp',
    'LogicalResourceId', 'PhysicalResourceId', 'Metadata',
    'ResourceStatus', 'ResourceStatusReason', 'ResourceType',
    STACK_ID, STACK_NAME,
    'Timestamp',
)

KEYS_RESOURCE_DETAIL = (
    RES_DESCRIPTION, RES_UPDATED_TIME,
    RES_NAME, RES_PHYSICAL_ID, RES_METADATA,
    RES_STATUS, RES_STATUS_DATA, RES_TYPE,
    RES_STACK_ID, RES_STACK_NAME,
)
KEYS_RESOURCE = (
    RES_DESCRIPTION,
    RES_NAME, RES_PHYSICAL_ID,
    RES_STATUS, RES_STATUS_DATA, RES_TYPE,
    RES_STACK_ID, RES_STACK_NAME,
    RES_TIMESTAMP,
)
KEYS_RESOURCE_SUMMARY = (
    RES_UPDATED_TIME,
    RES_NAME, RES_PHYSICAL_ID,
    RES_STATUS, RES_STATUS_DATA, RES_TYPE,
)


def format_stack_resource(resource, keys=None):
    '''
    Return a representation of the given resource that matches the API output
    expectations.
    '''
    last_updated_time = resource.updated_time or resource.created_time
    attrs = {
        RES_DESCRIPTION: resource.parsed_template().get('Description', ''),
        RES_UPDATED_TIME: heat_utils.strtime(last_updated_time),
        RES_NAME: resource.name,
        RES_PHYSICAL_ID: resource.instance_id or '',
        RES_METADATA: resource.metadata,
        RES_STATUS: resource.state,
        RES_STATUS_DATA: resource.state_description,
        RES_TYPE: resource.t['Type'],
        RES_STACK_ID: resource.stack.id,
        RES_STACK_NAME: resource.stack.name,
        RES_TIMESTAMP: heat_utils.strtime(last_updated_time),
    }

    return _filter_keys(attrs, keys)


EVENT_KEYS = (
    EVENT_ID,
    EVENT_STACK_ID, EVENT_STACK_NAME,
    EVENT_TIMESTAMP,
    EVENT_RES_NAME, EVENT_RES_PHYSICAL_ID,
    EVENT_RES_STATUS, EVENT_RES_STATUS_DATA, EVENT_RES_TYPE,
    EVENT_RES_PROPERTIES,
) = (
    'EventId',
    STACK_ID, STACK_NAME,
    RES_TIMESTAMP,
    RES_NAME, RES_PHYSICAL_ID,
    RES_STATUS, RES_STATUS_DATA, RES_TYPE,
    'ResourceProperties',
)


def format_event(event, keys=None):
    s = event.stack
    attrs = {
        EVENT_ID: event.id,
        EVENT_STACK_ID: s.id,
        EVENT_STACK_NAME: s.name,
        EVENT_TIMESTAMP: heat_utils.strtime(event.created_at),
        EVENT_RES_NAME: event.logical_resource_id,
        EVENT_RES_PHYSICAL_ID: event.physical_resource_id,
        EVENT_RES_STATUS: event.name,
        EVENT_RES_STATUS_DATA: event.resource_status_reason,
        EVENT_RES_TYPE: event.resource_type,
        EVENT_RES_PROPERTIES: event.resource_properties,
    }

    return _filter_keys(attrs, keys)
