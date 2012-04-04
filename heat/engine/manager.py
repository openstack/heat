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

from eventlet import greenthread

import heat.context
from heat.common import exception
from heat import manager
from heat.openstack.common import cfg
from heat import rpc
from heat.engine import parser
from heat.db import api as db_api

logger = logging.getLogger('heat.engine.manager')

stack_db = {}

class EngineManager(manager.Manager):
    """Manages the running instances from creation to destruction."""

    def __init__(self, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        pass

    def list_stacks(self, context):
        logger.info('context is %s' % context)
        res = {'stacks': [] }
        for s in stack_db:
            mem = {}
            mem['stack_id'] = s
            mem['stack_name'] = s
            mem['created_at'] = 'now'
            try:
                mem['template_description'] = stack_db[s].t['Description']
                mem['stack_status'] = stack_db[s].t['StackStatus']
            except:
                mem['template_description'] = 'No description'
                mem['stack_status'] = 'unknown'
            res['stacks'].append(mem)

        return res

    def show_stack(self, context, stack_name):

        res = {'stacks': [] }
        if stack_db.has_key(stack_name):
            mem = {}
            mem['stack_id'] = stack_name
            mem['stack_name'] = stack_name
            mem['creation_at'] = 'TODO'
            mem['updated_at'] = 'TODO'
            mem['NotificationARNs'] = 'TODO'
            mem['Outputs'] = stack_db[stack_name].get_outputs()
            mem['Parameters'] = stack_db[stack_name].t['Parameters']
            mem['StackStatusReason'] = 'TODO'
            mem['TimeoutInMinutes'] = 'TODO'
            try:
                mem['TemplateDescription'] = stack_db[stack_name].t['Description']
                mem['StackStatus'] = stack_db[stack_name].t['StackStatus']
            except:
                mem['TemplateDescription'] = 'No description'
                mem['StackStatus'] = 'unknown'
            res['stacks'].append(mem)
        else:
            #return webob.exc.HTTPNotFound('No stack by that name')
			#TODO
			pass

        return res

    def create_stack(self, context, stack_name, template):
        if stack_db.has_key(stack_name):
            return {'Error': 'Stack already exists with that name.'}

        logger.info('template is %s' % template)
        stack_db[stack_name] = parser.Stack(stack_name, template)
        stack_db[stack_name].start()

        return {'stack': {'id': stack_name}}

    def validate_template(self, req, body=None):

        logger.info('validate_template')
        if body is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        s = parser.Stack('validate', body, req.params)
        res = s.validate()

        return res

    def delete_stack(self, context, stack_name):
        if not stack_db.has_key(stack_name):
            return {'Error': 'No stack by that name'}

        logger.info('deleting stack %s' % stack_name)
        stack_db[stack_name].stop()
        del stack_db[stack_name]
        return None

    def list_events(self, context, stack_name):
        return db_api.event_get_all_by_stack(None, stack_name)
