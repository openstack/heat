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
from heat.common import utils as heat_utils
from heat.engine import parser

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
    'stack_name', 'stack_id',
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
        STACK_ID: stack.id,
        STACK_CREATION_TIME: heat_utils.strtime(stack.created_time),
        STACK_UPDATED_TIME: heat_utils.strtime(stack.updated_time),
        STACK_NOTIFICATION_TOPICS: [],  # TODO Not implemented yet
        STACK_PARAMETERS: stack.t[parser.PARAMETERS],
        STACK_DESCRIPTION: stack.t[parser.DESCRIPTION],
        STACK_TMPL_DESCRIPTION: stack.t[parser.DESCRIPTION],
        STACK_STATUS: stack.state,
        STACK_STATUS_DATA: stack.state_description,
        STACK_CAPABILITIES: [],   # TODO Not implemented yet
        STACK_DISABLE_ROLLBACK: True,   # TODO Not implemented yet
        STACK_TIMEOUT: stack.timeout_mins,
    }

    # only show the outputs on a completely created stack
    if stack.state == stack.CREATE_COMPLETE:
        info[STACK_OUTPUTS] = format_stack_outputs(stack, stack.outputs)

    return info


RES_KEYS = (
    RES_DESCRIPTION, RES_UPDATED_TIME,
    RES_NAME, RES_PHYSICAL_ID, RES_METADATA,
    RES_STATUS, RES_STATUS_DATA, RES_TYPE,
    RES_STACK_ID, RES_STACK_NAME,
) = (
    'description', 'updated_time',
    'logical_resource_id', 'physical_resource_id', 'metadata',
    'resource_status', 'resource_status_reason', 'resource_type',
    STACK_ID, STACK_NAME,
)


def format_stack_resource(resource):
    '''
    Return a representation of the given resource that matches the API output
    expectations.
    '''
    last_updated_time = resource.updated_time or resource.created_time
    res = {
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


def format_event(event):
    s = event.stack
    event = {
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

    return event
