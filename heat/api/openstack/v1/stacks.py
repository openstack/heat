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
Stack endpoint for Heat v1 ReST API.
"""

import httplib
import json
import os
import socket
import sys
import re
import urlparse
import webob
from webob import exc
from functools import wraps

from heat.common import wsgi
from heat.common import config
from heat.common import context
from heat.common import exception
from heat import utils
from heat.engine import api as engine_api
from heat.engine import identifier
from heat.engine import rpcapi as engine_rpcapi

from heat.openstack.common import rpc
import heat.openstack.common.rpc.common as rpc_common
from heat.openstack.common import log as logging

logger = logging.getLogger('heat.api.openstack.v1.stacks')

CREATE_PARAMS = (
    PARAM_STACK_NAME,
    PARAM_TEMPLATE,
    PARAM_TEMPLATE_URL,
    PARAM_USER_PARAMS,
) = (
    'stack_name',
    'template',
    'template_url',
    'parameters',
)


def json_parse(data, data_type):
    try:
        return json.loads(data)
    except ValueError:
        err_reason = "%s not in valid JSON format" % data_type
        raise exc.HTTPBadRequest(explanation=err_reason)


def get_template(req):
    """
    Get template file contents, either from local file or URL, in JSON format
    """
    if PARAM_TEMPLATE in req.params:
        return json_parse(req.params[PARAM_TEMPLATE], 'Template')
    elif PARAM_TEMPLATE_URL in req.params:
        logger.debug('Template URL %s' % req.params[PARAM_TEMPLATE_URL])
        url = urlparse.urlparse(req.params[PARAM_TEMPLATE_URL])
        err_reason = _("Could not retrieve template")

        try:
            ConnType = (url.scheme == 'https' and httplib.HTTPSConnection
                                               or httplib.HTTPConnection)
            conn = ConnType(url.netloc)

            try:
                conn.request("GET", url.path)
                resp = conn.getresponse()
                logger.info('status %d' % r1.status)

                if resp.status != 200:
                    raise exc.HTTPBadRequest(explanation=err_reason)

                return json_parse(resp.read(), 'Template')
            finally:
                conn.close()
        except socket.gaierror:
            raise exc.HTTPBadRequest(explanation=err_reason)

    raise exc.HTTPBadRequest(explanation=_("No template specified"))


def get_user_params(req):
    """
    Get the user-supplied parameters for the stack in JSON format
    """
    if PARAM_USER_PARAMS not in req.params:
        return {}

    return json_parse(req.params[PARAM_USER_PARAMS], 'User Parameters')


def get_args(req):
    params = req.params.items()
    return dict((k, v) for k, v in params if k not in CREATE_PARAMS)


def tenant_local(handler):
    @wraps(handler)
    def handle_stack_method(controller, req, tenant_id, **kwargs):
        req.context.tenant = tenant_id
        return handler(controller, req, **kwargs)

    return handle_stack_method


def identified_stack(handler):
    @tenant_local
    @wraps(handler)
    def handle_stack_method(controller, req, stack_name, stack_id, **kwargs):
        stack_identity = identifier.HeatIdentifier(req.context.tenant,
                                                   stack_name,
                                                   stack_id)
        return handler(controller, req, dict(stack_identity), **kwargs)

    return handle_stack_method


def stack_url(req, identity):
    try:
        stack_identity = identifier.HeatIdentifier(**identity)
    except ValueError:
        err_reason = _("Invalid Stack address")
        raise exc.HTTPInternalServerError(explanation=err_reason)

    return req.relative_url(stack_identity.url_path(), True)


def format_stack(req, stack, keys=[]):
    include_key = lambda k: k in keys if keys else True

    def transform(key, value):
        if key == engine_api.STACK_ID:
            return 'URL', stack_url(req, value)
        elif key == engine_api.STACK_PARAMETERS:
            return key, json.dumps(value)

        return key, value

    return dict(transform(k, v) for k, v in stack.items() if include_key(k))


class StackController(object):
    """
    WSGI controller for stacks resource in Heat v1 API
    Implements the API actions
    """

    def __init__(self, options):
        self.options = options
        self.engine_rpcapi = engine_rpcapi.EngineAPI()

    def _remote_error(self, ex):
        """
        Map rpc_common.RemoteError exceptions returned by the engine
        to webob exceptions which can be used to return
        properly formatted error responses.
        """
        raise exc.HTTPBadRequest(explanation=str(ex))

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    @tenant_local
    def index(self, req):
        """
        Lists summary information for all stacks
        """

        try:
            # Note show_stack returns details for all stacks when called with
            # no stack_name, we only use a subset of the result here though
            stack_list = self.engine_rpcapi.show_stack(req.context, None)
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        summary_keys = (engine_api.STACK_ID,
                        engine_api.STACK_NAME,
                        engine_api.STACK_DESCRIPTION,
                        engine_api.STACK_STATUS,
                        engine_api.STACK_STATUS_DATA,
                        engine_api.STACK_CREATION_TIME,
                        engine_api.STACK_DELETION_TIME,
                        engine_api.STACK_UPDATED_TIME)

        stacks = stack_list['stacks']

        return {'stacks': [format_stack(req, s, summary_keys) for s in stacks]}

    @tenant_local
    def create(self, req):
        """
        Create a new stack
        """
        if PARAM_STACK_NAME not in req.params:
            raise exc.HTTPBadRequest(explanation=_("No stack name specified"))
        stack_name = req.params[PARAM_STACK_NAME]

        stack_params = get_user_params(req)
        template = get_template(req)
        args = get_args(req)

        try:
            result = self.engine_rpcapi.create_stack(req.context,
                                                     stack_name,
                                                     template,
                                                     stack_params,
                                                     args)
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        if 'Description' in result:
            raise exc.HTTPBadRequest(explanation=result['Description'])

        raise exc.HTTPCreated(location=stack_url(req, result))

    @tenant_local
    def lookup(self, req, stack_name):
        """
        Redirect to the canonical URL for a stack
        """

        try:
            identity = self.engine_rpcapi.identify_stack(req.context,
                                                         stack_name)
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        raise exc.HTTPFound(location=stack_url(req, identity))

    @identified_stack
    def show(self, req, identity):
        """
        Gets detailed information for a stack
        """

        try:
            stack_list = self.engine_rpcapi.show_stack(req.context,
                                                       identity)
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        if not stack_list['stacks']:
            raise exc.HTTPNotFound()

        stack = stack_list['stacks'][0]

        return {'stack': format_stack(req, stack)}

    @identified_stack
    def template(self, req, identity):
        """
        Get the template body for an existing stack
        """

        try:
            templ = self.engine_rpcapi.get_template(req.context,
                                                    identity)
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        if templ is None:
            raise exc.HTTPNotFound()

        # TODO(zaneb): always set Content-type to application/json
        return json.dumps(templ)

    @identified_stack
    def update(self, req, identity):
        """
        Update an existing stack with a new template and/or parameters
        """
        stack_params = get_user_params(req)
        template = get_template(req)
        args = get_args(req)

        try:
            res = self.engine_rpcapi.update_stack(req.context,
                                                  identity,
                                                  template,
                                                  stack_params, args)
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        if 'Description' in res:
            raise exc.HTTPBadRequest(explanation=res['Description'])

        raise exc.HTTPAccepted()

    @identified_stack
    def delete(self, req, identity):
        """
        Delete the specified stack
        """

        try:
            res = self.engine_rpcapi.delete_stack(req.context,
                                                  identity,
                                                  cast=False)

        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        if res is not None:
            raise exc.HTTPBadRequest(explanation=res['Error'])

        raise exc.HTTPNoContent()

    @tenant_local
    def validate_template(self, req):
        """
        Implements the ValidateTemplate API action
        Validates the specified template
        """

        template = get_template(req)
        stack_params = get_user_params(req)

        try:
            return self.engine_rpcapi.validate_template(req.context,
                                                        template, stack_params)
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)


def create_resource(options):
    """
    Stacks resource factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    return wsgi.Resource(StackController(options), deserializer)
