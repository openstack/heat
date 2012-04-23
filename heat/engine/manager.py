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


import contextlib
import functools
import os
import socket
import sys
import tempfile
import time
import traceback
import logging
import webob
from heat import manager
from heat.engine import parser
from heat.db import api as db_api
logger = logging.getLogger('heat.engine.manager')


class EngineManager(manager.Manager):
    """
    Manages the running instances from creation to destruction.
    All the methods in here are called from the RPC backend.  This is
    all done dynamically so if a call is made via RPC that does not
    have a corresponding method here, an exception will be thrown when
    it attempts to call into this class.  Arguments to these methods
    are also dynamically added and will be named as keyword arguments
    by the RPC caller.
    """

    def __init__(self, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        pass

    def list_stacks(self, context, params):
        """
        The list_stacks method is the end point that actually implements
        the 'list' command of the heat API.
        arg1 -> RPC context.
        arg2 -> Dict of http request parameters passed in from API side.
        """
        logger.info('context is %s' % context)
        res = {'stacks': []}
        stacks = db_api.stack_get_all(None)
        if stacks == None:
            return res
        for s in stacks:
            ps = parser.Stack(s.name, s.raw_template.parsed_template.template,
                              s.id, params)
            mem = {}
            mem['stack_id'] = s.id
            mem['stack_name'] = s.name
            mem['created_at'] = str(s.created_at)
            mem['template_description'] = ps.t.get('Description',
                                                   'No description')
            mem['StackStatus'] = ps.t.get('stack_status', 'unknown')
            res['stacks'].append(mem)

        return res

    def show_stack(self, context, stack_name, params):
        """
        The show_stack method returns the attributes of one stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to see.
        arg3 -> Dict of http request parameters passed in from API side.
        """
        res = {'stacks': []}
        s = db_api.stack_get(None, stack_name)
        if s:
            ps = parser.Stack(s.name, s.raw_template.parsed_template.template,
                              s.id, params)
            mem = {}
            mem['stack_id'] = s.id
            mem['stack_name'] = s.name
            mem['creation_at'] = str(s.created_at)
            mem['updated_at'] = str(s.updated_at)
            mem['NotificationARNs'] = 'TODO'
            mem['Outputs'] = ps.get_outputs()
            mem['Parameters'] = ps.t['Parameters']
            mem['StackStatusReason'] = 'TODO'
            mem['TimeoutInMinutes'] = 'TODO'
            mem['TemplateDescription'] = ps.t.get('Description',
                                                  'No description')
            mem['StackStatus'] = ps.t.get('stack_status', 'unknown')
            res['stacks'].append(mem)

        return res

    def create_stack(self, context, stack_name, template, params):
        """
        The create_stack method creates a new stack using the template
        provided.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to create.
        arg3 -> Template of stack you want to create.
        arg4 -> Params passed from API.
        """
        logger.info('template is %s' % template)
        if db_api.stack_get(None, stack_name):
            return {'Error': 'Stack already exists with that name.'}

        stack = parser.Stack(stack_name, template, 0, params)
        rt = {}
        rt['template'] = template
        rt['stack_name'] = stack_name
        new_rt = db_api.raw_template_create(None, rt)

        s = {}
        s['name'] = stack_name
        s['raw_template_id'] = new_rt.id
        new_s = db_api.stack_create(None, s)
        stack.id = new_s.id

        pt = {}
        pt['template'] = stack.t
        pt['raw_template_id'] = new_rt.id
        new_pt = db_api.parsed_template_create(None, pt)

        stack.parsed_template_id = new_pt.id
        stack.create()

        return {'stack': {'id': new_s.id, 'name': new_s.name,\
                'created_at': str(new_s.created_at)}}

    def validate_template(self, req, body=None):
        """
        The validate_template method uses the stack parser to check
        the validity of a template.

        arg1 -> http request params.
        arg2 -> Template body.
        """

        logger.info('validate_template')
        if body is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        s = parser.Stack('validate', body, 0, req.params)
        res = s.validate()

        return res

    def delete_stack(self, context, stack_name, params):
        """
        The delete_stack method deletes a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to delete.
        arg3 -> Params passed from API.
        """
        st = db_api.stack_get(None, stack_name)
        if not st:
            return {'Error': 'No stack by that name'}

        logger.info('deleting stack %s' % stack_name)

        ps = parser.Stack(st.name, st.raw_template.parsed_template.template,
                          st.id, params)
        ps.delete()
        return None

    def list_events(self, context, stack_name):
        """
        The list_events method lists all events associated with a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to get events for.
        """
        if stack_name is not None:
            st = db_api.stack_get(None, stack_name)
            if not st:
                return {'Error': 'No stack by that name'}

            events = db_api.event_get_all_by_stack(None, st.id)
        else:
            events = db_api.event_get_all(None)

        def parse_event(e):
            s = e.stack
            return {'EventId': e.id,
                    'StackId': e.stack_id,
                    'StackName': s.name,
                    'Timestamp': str(e.created_at),
                    'LogicalResourceId': e.logical_resource_id,
                    'PhysicalResourceId': e.physical_resource_id,
                    'ResourceType': e.resource_type,
                    'ResourceStatusReason': e.resource_status_reason,
                    'ResourceProperties': e.resource_properties,
                    'ResourceStatus': e.name}

        return {'events': [parse_event(e) for e in events]}
