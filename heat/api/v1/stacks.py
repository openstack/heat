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
/stack endpoint for heat v1 API
"""

import httplib
import json
import logging
import sys
import urlparse

import webob
from webob.exc import (HTTPNotFound,
                       HTTPConflict,
                       HTTPBadRequest)

from heat.common import exception
from heat.common import wsgi

logger = logging.getLogger('heat.api.v1.stacks')

stack_db = {}

class StackController(object):

    """
    WSGI controller for stacks resource in heat v1 API

    """

    def __init__(self, options):
        self.options = options
        self.stack_id = 1

    def list(self, req):
        """
        Returns the following information for all stacks:
        """
        res = {'ListStacksResponse': {'ListStacksResult': {'StackSummaries': [] } } }
        summaries = res['ListStacksResponse']['ListStacksResult']['StackSummaries']
        for s in stack_db:
            mem = {}
            mem['StackId'] = stack_db[s]['StackId']
            mem['StackStatus'] = 'happy'
            mem['StackName'] = s
            mem['CreationTime'] = 'now'
            try:
                mem['TemplateDescription'] = stack_db[s]['Description']
            except:
                mem['TemplateDescription'] = 'No description'
            summaries.append(mem)

        return res

    def describe(self, req):

        stack_name = None
        if req.params.has_key('StackName'):
            stack_name = req.params['StackName']
            if not stack_db.has_key(stack_name):
                msg = _("Stack does not exist with that name.")
                return webob.exc.HTTPNotFound(msg)

        res = {'DescribeStacksResult': {'Stacks': [] } }
        summaries = res['DescribeStacksResult']['Stacks']
        for s in stack_db:
            if stack_name is None or s == stack_name:
                mem = {}
                mem['StackId'] = stack_db[s]['StackId']
                mem['StackStatus'] = stack_db[s]['StackStatus']
                mem['StackName'] = s
                mem['CreationTime'] = 'now'
                mem['DisableRollback'] = 'false'
                mem['Outputs'] = '[]'
                summaries.append(mem)

        return res

    def _get_template(self, req):
        if req.params.has_key('TemplateBody'):
            logger.info('TemplateBody ...')
            return req.params['TemplateBody']
        elif req.params.has_key('TemplateUrl'):
            logger.info('TemplateUrl %s' % req.params['TemplateUrl'])
            url = urlparse.urlparse(req.params['TemplateUrl'])
            if url.scheme == 'https':
                conn = httplib.HTTPSConnection(url.netloc)
            else:
                conn = httplib.HTTPConnection(url.netloc)
            conn.request("GET", url.path)
            r1 = conn.getresponse()
            logger.info('status %d' % r1.status)
            if r1.status == 200:
                data = r1.read()
                conn.close()
            else:
                data = None
            return data

        return None

    def _apply_user_parameters(self, req, stack):
        # TODO
        pass

    def create(self, req):
        """
        :param req: The WSGI/Webob Request object

        :raises HttpBadRequest if not template is given
        :raises HttpConflict if object already exists
        """
        if stack_db.has_key(req.params['StackName']):
            msg = _("Stack already exists with that name.")
            return webob.exc.HTTPConflict(msg)

        templ = self._get_template(req)
        if templ is None:
            msg = _("TemplateBody or TemplateUrl were not given.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        stack = json.loads(templ)
        my_id = '%s-%d' % (req.params['StackName'], self.stack_id)
        self.stack_id = self.stack_id + 1
        stack['StackId'] = my_id
        stack['StackStatus'] = 'CREATE_COMPLETE'
        self._apply_user_parameters(req, stack)
        stack_db[req.params['StackName']] = stack

        return {'CreateStackResult': {'StackId': my_id}}

    def update(self, req):
        """
        :param req: The WSGI/Webob Request object

        :raises HttpNotFound if object is not available
        """
        if not stack_db.has_key(req.params['StackName']):
            msg = _("Stack does not exist with that name.")
            return webob.exc.HTTPNotFound(msg)

        stack = stack_db[req.params['StackName']]
        my_id = stack['StackId']
        templ = self._get_template(req)
        if templ:
            stack = json.loads(templ)
            stack['StackId'] = my_id
            stack_db[req.params['StackName']] = stack

        self._apply_user_parameters(req, stack)
        stack['StackStatus'] = 'UPDATE_COMPLETE'

        return {'UpdateStackResult': {'StackId': my_id}}


    def delete(self, req):
        """
        Deletes the object and all its resources

        :param req: The WSGI/Webob Request object

        :raises HttpBadRequest if the request is invalid
        :raises HttpNotFound if object is not available
        :raises HttpNotAuthorized if object is not
                deleteable by the requesting user
        """

def create_resource(options):
    """Stacks resource factory method"""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(StackController(options), deserializer, serializer)
