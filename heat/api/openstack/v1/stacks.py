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

from webob import exc

from heat.api.openstack.v1 import util
from heat.api.openstack.v1.views import stacks_view
from heat.common import environment_format
from heat.common import identifier
from heat.common import serializers
from heat.common import template_format
from heat.common import urlfetch
from heat.common import wsgi
from heat.openstack.common import log as logging
from heat.rpc import api as engine_api
from heat.rpc import client as rpc_client

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
        except ValueError as parse_ex:
            mdict = {'type': data_type, 'error': parse_ex}
            msg = _("%(type)s not in valid format: %(error)s") % mdict
            raise exc.HTTPBadRequest(msg)

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
                err_reason = _('Could not retrieve template: %s') % ex
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


class StackController(object):
    """
    WSGI controller for stacks resource in Heat v1 API
    Implements the API actions
    """
    # Define request scope (must match what is in policy.json)
    REQUEST_SCOPE = 'stacks'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    def _index(self, req, tenant_safe=True):
        filter_whitelist = {
            'status': 'mixed',
            'name': 'mixed',
            'action': 'mixed',
        }
        whitelist = {
            'limit': 'single',
            'marker': 'single',
            'sort_dir': 'single',
            'sort_keys': 'multi',
        }
        params = util.get_allowed_params(req.params, whitelist)
        filter_params = util.get_allowed_params(req.params, filter_whitelist)

        if not filter_params:
            filter_params = None

        stacks = self.rpc_client.list_stacks(req.context,
                                             filters=filter_params,
                                             tenant_safe=tenant_safe,
                                             **params)

        count = None
        if req.params.get('with_count'):
            try:
                # Check if engine has been updated to a version with
                # support to count_stacks before trying to use it.
                count = self.rpc_client.count_stacks(req.context,
                                                     filters=filter_params,
                                                     tenant_safe=tenant_safe)
            except AttributeError as exc:
                logger.warning(_("Old Engine Version: %s") % exc)

        return stacks_view.collection(req, stacks=stacks, count=count,
                                      tenant_safe=tenant_safe)

    @util.policy_enforce
    def global_index(self, req):
        return self._index(req, tenant_safe=False)

    @util.policy_enforce
    def index(self, req):
        """
        Lists summary information for all stacks
        """
        global_tenant = bool(req.params.get('global_tenant', False))
        if global_tenant:
            return self.global_index(req, req.context.tenant_id)

        return self._index(req)

    @util.policy_enforce
    def detail(self, req):
        """
        Lists detailed information for all stacks
        """
        stacks = self.rpc_client.list_stacks(req.context)

        return {'stacks': [stacks_view.format_stack(req, s) for s in stacks]}

    @util.policy_enforce
    def preview(self, req, body):
        """
        Preview the outcome of a template and its params
        """

        data = InstantiationData(body)
        args = util.extract_args(data.args())

        result = self.rpc_client.preview_stack(req.context,
                                               data.stack_name(),
                                               data.template(),
                                               data.environment(),
                                               data.files(),
                                               args)

        formatted_stack = stacks_view.format_stack(req, result)
        return {'stack': formatted_stack}

    @util.policy_enforce
    def create(self, req, body):
        """
        Create a new stack
        """
        data = InstantiationData(body)
        args = util.extract_args(data.args())

        result = self.rpc_client.create_stack(req.context,
                                              data.stack_name(),
                                              data.template(),
                                              data.environment(),
                                              data.files(),
                                              args)

        formatted_stack = stacks_view.format_stack(
            req,
            {engine_api.STACK_ID: result}
        )
        return {'stack': formatted_stack}

    @util.policy_enforce
    def lookup(self, req, stack_name, path='', body=None):
        """
        Redirect to the canonical URL for a stack
        """
        try:
            identity = dict(identifier.HeatIdentifier.from_arn(stack_name))
        except ValueError:
            identity = self.rpc_client.identify_stack(req.context,
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

        stack_list = self.rpc_client.show_stack(req.context,
                                                identity)

        if not stack_list:
            raise exc.HTTPInternalServerError()

        stack = stack_list[0]

        return {'stack': stacks_view.format_stack(req, stack)}

    @util.identified_stack
    def template(self, req, identity):
        """
        Get the template body for an existing stack
        """

        templ = self.rpc_client.get_template(req.context,
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
        args = util.extract_args(data.args())

        self.rpc_client.update_stack(req.context,
                                     identity,
                                     data.template(),
                                     data.environment(),
                                     data.files(),
                                     args)

        raise exc.HTTPAccepted()

    @util.identified_stack
    def delete(self, req, identity):
        """
        Delete the specified stack
        """

        res = self.rpc_client.delete_stack(req.context,
                                           identity,
                                           cast=False)

        if res is not None:
            raise exc.HTTPBadRequest(res['Error'])

        raise exc.HTTPNoContent()

    @util.identified_stack
    def abandon(self, req, identity):
        """
        Abandons specified stack by deleting the stack and it's resources
        from the database, but underlying resources will not be deleted.
        """
        return self.rpc_client.abandon_stack(req.context,
                                             identity)

    @util.policy_enforce
    def validate_template(self, req, body):
        """
        Implements the ValidateTemplate API action
        Validates the specified template
        """

        data = InstantiationData(body)

        result = self.rpc_client.validate_template(req.context,
                                                   data.template(),
                                                   data.environment())

        if 'Error' in result:
            raise exc.HTTPBadRequest(result['Error'])

        return result

    @util.policy_enforce
    def list_resource_types(self, req):
        """
        Returns a list of valid resource types that may be used in a template.
        """
        support_status = req.params.get('support_status')
        return {
            'resource_types':
            self.rpc_client.list_resource_types(req.context, support_status)}

    @util.policy_enforce
    def resource_schema(self, req, type_name):
        """
        Returns the schema of the given resource type.
        """
        return self.rpc_client.resource_schema(req.context, type_name)

    @util.policy_enforce
    def generate_template(self, req, type_name):
        """
        Generates a template based on the specified type.
        """
        return self.rpc_client.generate_template(req.context, type_name)


class StackSerializer(serializers.JSONResponseSerializer):
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
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = StackSerializer()
    return wsgi.Resource(StackController(options), deserializer, serializer)
