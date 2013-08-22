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

import itertools
from webob import exc

from heat.api.openstack.v1 import util
from heat.common import identifier
from heat.common import wsgi
from heat.common import template_format
from heat.common import environment_format
from heat.rpc import api as engine_api
from heat.rpc import client as rpc_client
from heat.common import urlfetch

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class InstantiationData(object):
    """
    The data accompanying a PUT or POST request to create or update a stack.
    """

    PARAMS = (
        PARAM_STACK_NAME,
        PARAM_TEMPLATE,
        PARAM_TEMPLATE_URL,
        PARAM_USER_PARAMS,
        PARAM_ENVIRONMENT,
        PARAM_FILES,
    ) = (
        'stack_name',
        'template',
        'template_url',
        'parameters',
        'environment',
        'files',
    )

    def __init__(self, data):
        """Initialise from the request object."""
        self.data = data

    @staticmethod
    def format_parse(data, data_type):
        """
        Parse the supplied data as JSON or YAML, raising the appropriate
        exception if it is in the wrong format.
        """

        try:
            if data_type == 'Environment':
                return environment_format.parse(data)
            else:
                return template_format.parse(data)
        except ValueError:
            err_reason = _("%s not in valid format") % data_type
            raise exc.HTTPBadRequest(err_reason)

    def stack_name(self):
        """
        Return the stack name.
        """
        if self.PARAM_STACK_NAME not in self.data:
            raise exc.HTTPBadRequest(_("No stack name specified"))
        return self.data[self.PARAM_STACK_NAME]

    def template(self):
        """
        Get template file contents, either inline or from a URL, in JSON
        or YAML format.
        """
        if self.PARAM_TEMPLATE in self.data:
            template_data = self.data[self.PARAM_TEMPLATE]
            if isinstance(template_data, dict):
                return template_data
        elif self.PARAM_TEMPLATE_URL in self.data:
            url = self.data[self.PARAM_TEMPLATE_URL]
            logger.debug('TemplateUrl %s' % url)
            try:
                template_data = urlfetch.get(url)
            except IOError as ex:
                err_reason = _('Could not retrieve template: %s') % str(ex)
                raise exc.HTTPBadRequest(err_reason)
        else:
            raise exc.HTTPBadRequest(_("No template specified"))

        return self.format_parse(template_data, 'Template')

    def environment(self):
        """
        Get the user-supplied environment for the stack in YAML format.
        If the user supplied Parameters then merge these into the
        environment global options.
        """
        env = {}
        if self.PARAM_ENVIRONMENT in self.data:
            env_data = self.data[self.PARAM_ENVIRONMENT]
            if isinstance(env_data, dict):
                env = env_data
            else:
                env = self.format_parse(env_data,
                                        'Environment')

        environment_format.default_for_missing(env)
        parameters = self.data.get(self.PARAM_USER_PARAMS, {})
        env[self.PARAM_USER_PARAMS].update(parameters)
        return env

    def files(self):
        return self.data.get(self.PARAM_FILES, {})

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
        elif key == engine_api.STACK_ACTION:
            return
        elif (key == engine_api.STACK_STATUS and
              engine_api.STACK_ACTION in stack):
            # To avoid breaking API compatibility, we join RES_ACTION
            # and RES_STATUS, so the API format doesn't expose the
            # internal split of state into action/status
            yield (key, '_'.join((stack[engine_api.STACK_ACTION], value)))
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
        self.engine = rpc_client.EngineClient()

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    @util.tenant_local
    def index(self, req):
        """
        Lists summary information for all stacks
        """

        stacks = self.engine.list_stacks(req.context)

        summary_keys = (engine_api.STACK_ID,
                        engine_api.STACK_NAME,
                        engine_api.STACK_DESCRIPTION,
                        engine_api.STACK_STATUS,
                        engine_api.STACK_STATUS_DATA,
                        engine_api.STACK_CREATION_TIME,
                        engine_api.STACK_DELETION_TIME,
                        engine_api.STACK_UPDATED_TIME)

        return {'stacks': [format_stack(req, s, summary_keys) for s in stacks]}

    @util.tenant_local
    def detail(self, req):
        """
        Lists detailed information for all stacks
        """
        stacks = self.engine.list_stacks(req.context)

        return {'stacks': [format_stack(req, s) for s in stacks]}

    @util.tenant_local
    def create(self, req, body):
        """
        Create a new stack
        """

        data = InstantiationData(body)

        result = self.engine.create_stack(req.context,
                                          data.stack_name(),
                                          data.template(),
                                          data.environment(),
                                          data.files(),
                                          data.args())

        return {'stack': format_stack(req, {engine_api.STACK_ID: result})}

    @util.tenant_local
    def lookup(self, req, stack_name, path='', body=None):
        """
        Redirect to the canonical URL for a stack
        """
        try:
            identity = dict(identifier.HeatIdentifier.from_arn(stack_name))
        except ValueError:
            identity = self.engine.identify_stack(req.context,
                                                  stack_name)

        location = util.make_url(req, identity)
        if path:
            location = '/'.join([location, path])

        raise exc.HTTPFound(location=location)

    @util.identified_stack
    def show(self, req, identity):
        """
        Gets detailed information for a stack
        """

        stack_list = self.engine.show_stack(req.context,
                                            identity)

        if not stack_list:
            raise exc.HTTPInternalServerError()

        stack = stack_list[0]

        return {'stack': format_stack(req, stack)}

    @util.identified_stack
    def template(self, req, identity):
        """
        Get the template body for an existing stack
        """

        templ = self.engine.get_template(req.context,
                                         identity)

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

        res = self.engine.update_stack(req.context,
                                       identity,
                                       data.template(),
                                       data.environment(),
                                       data.files(),
                                       data.args())

        raise exc.HTTPAccepted()

    @util.identified_stack
    def delete(self, req, identity):
        """
        Delete the specified stack
        """

        res = self.engine.delete_stack(req.context,
                                       identity,
                                       cast=False)

        if res is not None:
            raise exc.HTTPBadRequest(res['Error'])

        raise exc.HTTPNoContent()

    @util.tenant_local
    def validate_template(self, req, body):
        """
        Implements the ValidateTemplate API action
        Validates the specified template
        """

        data = InstantiationData(body)

        result = self.engine.validate_template(req.context,
                                               data.template())

        if 'Error' in result:
            raise exc.HTTPBadRequest(result['Error'])

        return result

    @util.tenant_local
    def list_resource_types(self, req):
        """
        Returns a list of valid resource types that may be used in a template.
        """
        return {'resource_types': self.engine.list_resource_types(req.context)}

    @util.tenant_local
    def resource_schema(self, req, type_name):
        """
        Returns the schema of the given resource type.
        """
        return self.engine.resource_schema(req.context, type_name)

    @util.tenant_local
    def generate_template(self, req, type_name):
        """
        Generates a template based on the specified type.
        """
        return self.engine.generate_template(req.context, type_name)


class StackSerializer(wsgi.JSONResponseSerializer):
    """Handles serialization of specific controller method responses."""

    def _populate_response_header(self, response, location, status):
        response.status = status
        response.headers['Location'] = location.encode('utf-8')
        response.headers['Content-Type'] = 'application/json'
        return response

    def create(self, response, result):
        self._populate_response_header(response,
                                       result['stack']['links'][0]['href'],
                                       201)
        response.body = self.to_json(result)
        return response


def create_resource(options):
    """
    Stacks resource factory method.
    """
    # TODO(zaneb) handle XML based on Content-type/Accepts
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = StackSerializer()
    return wsgi.Resource(StackController(options), deserializer, serializer)
