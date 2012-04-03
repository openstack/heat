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

"""
Reference implementation stacks server WSGI controller
"""
import json
import logging

import webob
from webob.exc import (HTTPNotFound,
                       HTTPConflict,
                       HTTPBadRequest)

from heat.common import exception
from heat.common import wsgi

from heat.engine import parser
from heat.db import api as db_api


logger = logging.getLogger('heat.engine.api.v1.stacks')

stack_db = {}

class StacksController(object):
    '''
    bla
    '''

    def __init__(self, conf):
        self.conf = conf
        db_api.configure(conf)

    def index(self, req, format='json'):
        logger.info('format is %s' % format)
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

    def show(self, req, id):
        res = {'stacks': [] }
        if stack_db.has_key(id):
            mem = {}
            mem['stack_id'] = id
            mem['stack_name'] = id
            mem['creation_at'] = 'TODO'
            mem['updated_at'] = 'TODO'
            mem['NotificationARNs'] = 'TODO'
            mem['Outputs'] = stack_db[id].get_outputs()
            mem['Parameters'] = stack_db[id].t['Parameters']
            mem['StackStatusReason'] = 'TODO'
            mem['TimeoutInMinutes'] = 'TODO'
            try:
                mem['TemplateDescription'] = stack_db[id].t['Description']
                mem['StackStatus'] = stack_db[id].t['StackStatus']
            except:
                mem['TemplateDescription'] = 'No description'
                mem['StackStatus'] = 'unknown'
            res['stacks'].append(mem)
        else:
            return webob.exc.HTTPNotFound('No stack by that name')

        return res

    def create(self, req, body=None):

        if body is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        if stack_db.has_key(body['StackName']):
            msg = _("Stack already exists with that name.")
            return webob.exc.HTTPConflict(msg)

        stack_db[body['StackName']] = parser.Stack(body['StackName'], body, req.params)
        stack_db[body['StackName']].start()

        return {'stack': {'id': body['StackName']}}

    def validate_template(self, req, body=None):

        logger.info('validate_template')
        if body is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        s = parser.Stack('validate', body, req.params)
        res = s.validate()

        return res

    def delete(self, req, id):
        if not stack_db.has_key(id):
            return webob.exc.HTTPNotFound('No stack by that name')

        logger.info('deleting stack %s' % id)
        stack_db[id].stop()
        del stack_db[id]
        return None

def create_resource(conf):
    """Stacks resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(StacksController(conf), deserializer, serializer)
