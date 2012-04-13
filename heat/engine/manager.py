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
    """Manages the running instances from creation to destruction."""

    def __init__(self, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        pass

    def list_stacks(self, context, params):
        logger.info('context is %s' % context)
        res = {'stacks': [] }
        stacks = db_api.stack_get_all(None)
        if stacks == None:
            return res
        for s in stacks:
            ps = parser.Stack(s.name, s.raw_template.template, params)
            mem = {}
            mem['stack_id'] = s.id
            mem['stack_name'] = s.name
            mem['created_at'] = str(s.created_at)
            mem['template_description'] = ps.t.get('Description', 'No description')
            mem['stack_status'] = ps.t.get('StackStatus', 'unknown')
            res['stacks'].append(mem)

        return res

    def show_stack(self, context, stack_name, params):
        res = {'stacks': [] }
        s = db_api.stack_get(None, id)
        if s:
            ps = parser.Stack(s.name, s.raw_template.template, params)
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
            mem['TemplateDescription'] = ps.t.get('Description', 'No description')
            mem['StackStatus'] = ps.t.get('StackStatus', 'unknown')
            res['stacks'].append(mem)

        return res

    def create_stack(self, context, stack_name, template, params):
        logger.info('template is %s' % template)
        if db_api.stack_get(None, stack_name):
            return {'Error': 'Stack already exists with that name.'}

        stack = parser.Stack(stack_name, template, params)
        rt = {}
        rt['template'] = template
        rt['stack_name'] = stack_name
        new_rt = db_api.raw_template_create(None, rt)
        s = {}
        s['name'] = stack_name
        s['raw_template_id'] = new_rt.id
        new_s = db_api.stack_create(None, s)
        stack.id = new_s.id
        stack.create()
        return {'stack': {'id': new_s.id, 'name': new_s.name,\
                'created_at': str(new_s.created_at)}}

    def validate_template(self, req, body=None):

        logger.info('validate_template')
        if body is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        s = parser.Stack('validate', body, req.params)
        res = s.validate()

        return res

    def delete_stack(self, context, stack_name, params):
        st = db_api.stack_get(None, stack_name)
        if not st:
            return {'Error': 'No stack by that name'}

        logger.info('deleting stack %s' % stack_name)

        rt = db_api.raw_template_get(None, st.raw_template_id)
        ps = parser.Stack(st.name, rt.template, params)
        ps.delete()
        return None

    def list_events(self, context, stack_name):
        if stack_name is not None:
            st = db_api.stack_get(None, stack_name)
            events = db_api.event_get_all_by_stack(None, st.id)
        else:
            events = db_api.event_get_all(None)

        def parse_event(e):
            s = e.stack
            # TODO Missing LogicalResourceId, PhysicalResourceId, ResourceType,
            # ResourceStatusReason
            return {'EventId': e.id,
                     'StackId': e.stack_id,
                     'StackName': s.name,
                     'Timestamp': str(e.created_at),
                     'ResourceStatus': str(e.name)}

        return {'events': [parse_event(e) for e in events]}
