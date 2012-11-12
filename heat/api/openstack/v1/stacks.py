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
import itertools
import json
import socket
import urlparse
from webob import exc

from heat.api.openstack.v1 import util
from heat.common import wsgi
from heat.engine import api as engine_api
from heat.engine import rpcapi as engine_rpcapi

import heat.openstack.common.rpc.common as rpc_common
from heat.openstack.common import log as logging

logger = logging.getLogger('heat.api.openstack.v1.stacks')


class InstantiationData(object):
    """
    The data accompanying a PUT or POST request to create or update a stack.
    """

    PARAMS = (
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

    def __init__(self, data):
        """Initialise from the request object."""
        self.data = data

    @staticmethod
    def json_parse(data, data_type):
        """
        Parse the supplied data as JSON, raising the appropriate exception
        if it is in the wrong format.
        """

        try:
            return json.loads(data)
        except ValueError:
            err_reason = "%s not in valid JSON format" % data_type
            raise exc.HTTPBadRequest(explanation=err_reason)

    def stack_name(self):
        """
        Return the stack name.
        """
        if self.PARAM_STACK_NAME not in self.data:
            raise exc.HTTPBadRequest(explanation=_("No stack name specified"))
        return self.data[self.PARAM_STACK_NAME]

    def _load_template(self, template_url):
        """
        Retrieve a template from a URL, in JSON format.
        """
        logger.debug('Template URL %s' % template_url)
        url = urlparse.urlparse(template_url)
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

                return self.json_parse(resp.read(), 'Template')
            finally:
                conn.close()
        except socket.gaierror:
            raise exc.HTTPBadRequest(explanation=err_reason)

    def template(self):
        """
        Get template file contents, either inline or from a URL, in JSON
        format.
        """
        if self.PARAM_TEMPLATE in self.data:
            return self.data[self.PARAM_TEMPLATE]
        elif self.PARAM_TEMPLATE_URL in self.data:
            return self._load_template(self.data[self.PARAM_TEMPLATE_URL])

        raise exc.HTTPBadRequest(explanation=_("No template specified"))

    def user_params(self):
        """
        Get the user-supplied parameters for the stack in JSON format.
        """
        return self.data.get(self.PARAM_USER_PARAMS, {})

    def args(self):
        """
        Get any additional arguments supplied by the user.
        """
        params = self.data.items()
        return dict((k, v) for k, v in params if k not in self.PARAMS)


def format_stack(req, stack, keys=[]):
    include_key = lambda k: k in keys if keys else True

    def transform(key, value):
        if not include_key(key):
            return

        if key == engine_api.STACK_ID:
            yield ('id', value['stack_id'])
            yield ('links', [util.make_link(req, value)])
        else:
            # TODO(zaneb): ensure parameters can be formatted for XML
            #elif key == engine_api.STACK_PARAMETERS:
            #    return key, json.dumps(value)
            yield (key, value)

    return dict(itertools.chain.from_iterable(
        transform(k, v) for k, v in stack.items()))


class StackController(object):
    """
    WSGI controller for stacks resource in Heat v1 API
    Implements the API actions
    """

    def __init__(self, options):
        self.options = options
        self.engine_rpcapi = engine_rpcapi.EngineAPI()

    def _remote_error(self, ex, force_exists=False):
        """
        Map rpc_common.RemoteError exceptions returned by the engine
        to webob exceptions which can be used to return
        properly formatted error responses.
        """
        if ex.exc_type in ('AttributeError', 'ValueError'):
            if force_exists:
                raise exc.HTTPBadRequest(explanation=str(ex))
            else:
                raise exc.HTTPNotFound(explanation=str(ex))

        raise exc.HTTPInternalServerError(explanation=str(ex))

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    @util.tenant_local
    def index(self, req):
        """
        Lists summary information for all stacks
        """

        try:
            stack_list = self.engine_rpcapi.list_stacks(req.context)
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex, True)

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

    @util.tenant_local
    def create(self, req, body):
        """
        Create a new stack
        """

        data = InstantiationData(body)

        try:
            result = self.engine_rpcapi.create_stack(req.context,
                                                     data.stack_name(),
                                                     data.template(),
                                                     data.user_params(),
                                                     data.args())
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex, True)

        if 'Description' in result:
            raise exc.HTTPBadRequest(explanation=result['Description'])

        raise exc.HTTPCreated(location=util.make_url(req, result))

    @util.tenant_local
    def lookup(self, req, stack_name, body=None):
        """
        Redirect to the canonical URL for a stack
        """

        try:
            identity = self.engine_rpcapi.identify_stack(req.context,
                                                         stack_name)
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        raise exc.HTTPFound(location=util.make_url(req, identity))

    @util.identified_stack
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
            raise exc.HTTPInternalServerError()

        stack = stack_list['stacks'][0]

        return {'stack': format_stack(req, stack)}

    @util.identified_stack
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
        return templ

    @util.identified_stack
    def update(self, req, identity, body):
        """
        Update an existing stack with a new template and/or parameters
        """
        data = InstantiationData(body)

        try:
            res = self.engine_rpcapi.update_stack(req.context,
                                                  identity,
                                                  data.template(),
                                                  data.user_params(),
                                                  data.args())
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        if 'Description' in res:
            raise exc.HTTPBadRequest(explanation=res['Description'])

        raise exc.HTTPAccepted()

    @util.identified_stack
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

    @util.tenant_local
    def validate_template(self, req, body):
        """
        Implements the ValidateTemplate API action
        Validates the specified template
        """

        data = InstantiationData(body)

        try:
            result = self.engine_rpcapi.validate_template(req.context,
                                                          data.template())
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex, True)

        if 'Error' in result:
            raise exc.HTTPBadRequest(explanation=result['Error'])

        return result


def create_resource(options):
    """
    Stacks resource factory method.
    """
    # TODO(zaneb) handle XML based on Content-type/Accepts
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(StackController(options), deserializer, serializer)
