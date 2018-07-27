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

"""Stack endpoint for Heat v1 REST API."""

import contextlib
from oslo_log import log as logging
import six
from six.moves.urllib import parse
from webob import exc

from heat.api.openstack.v1 import util
from heat.api.openstack.v1.views import stacks_view
from heat.common import context
from heat.common import environment_format
from heat.common.i18n import _
from heat.common import identifier
from heat.common import param_utils
from heat.common import serializers
from heat.common import template_format
from heat.common import urlfetch
from heat.common import wsgi
from heat.rpc import api as rpc_api
from heat.rpc import client as rpc_client

LOG = logging.getLogger(__name__)


class InstantiationData(object):
    """The data to create or update a stack.

    The data accompanying a PUT or POST request.
    """

    PARAMS = (
        PARAM_STACK_NAME,
        PARAM_TEMPLATE,
        PARAM_TEMPLATE_URL,
        PARAM_USER_PARAMS,
        PARAM_ENVIRONMENT,
        PARAM_FILES,
        PARAM_ENVIRONMENT_FILES,
        PARAM_FILES_CONTAINER
    ) = (
        'stack_name',
        'template',
        'template_url',
        'parameters',
        'environment',
        'files',
        'environment_files',
        'files_container'
    )

    def __init__(self, data, patch=False):
        """Initialise from the request object.

        If called from the PATCH api, insert a flag for the engine code
        to distinguish.
        """
        self.data = data
        self.patch = patch
        if patch:
            self.data[rpc_api.PARAM_EXISTING] = True

    @staticmethod
    @contextlib.contextmanager
    def parse_error_check(data_type):
        try:
            yield
        except ValueError as parse_ex:
            mdict = {'type': data_type, 'error': six.text_type(parse_ex)}
            msg = _("%(type)s not in valid format: %(error)s") % mdict
            raise exc.HTTPBadRequest(msg)

    def stack_name(self):
        """Return the stack name."""
        if self.PARAM_STACK_NAME not in self.data:
            raise exc.HTTPBadRequest(_("No stack name specified"))
        return self.data[self.PARAM_STACK_NAME]

    def template(self):
        """Get template file contents.

        Get template file contents, either inline, from stack adopt data or
        from a URL, in JSON or YAML format.
        """
        template_data = None
        if rpc_api.PARAM_ADOPT_STACK_DATA in self.data:
            adopt_data = self.data[rpc_api.PARAM_ADOPT_STACK_DATA]
            try:
                adopt_data = template_format.simple_parse(adopt_data)
                template_format.validate_template_limit(
                    six.text_type(adopt_data['template']))
                return adopt_data['template']
            except (ValueError, KeyError) as ex:
                err_reason = _('Invalid adopt data: %s') % ex
                raise exc.HTTPBadRequest(err_reason)
        elif self.PARAM_TEMPLATE in self.data:
            template_data = self.data[self.PARAM_TEMPLATE]
            if isinstance(template_data, dict):
                template_format.validate_template_limit(six.text_type(
                    template_data))
                return template_data

        elif self.PARAM_TEMPLATE_URL in self.data:
            url = self.data[self.PARAM_TEMPLATE_URL]
            LOG.debug('TemplateUrl %s' % url)
            try:
                template_data = urlfetch.get(url)
            except IOError as ex:
                err_reason = _('Could not retrieve template: %s') % ex
                raise exc.HTTPBadRequest(err_reason)

        if template_data is None:
            if self.patch:
                return None
            else:
                raise exc.HTTPBadRequest(_("No template specified"))

        with self.parse_error_check('Template'):
            return template_format.parse(template_data)

    def environment(self):
        """Get the user-supplied environment for the stack in YAML format.

        If the user supplied Parameters then merge these into the
        environment global options.
        """
        env = {}
        # Don't use merged environment, if environment_files are supplied.
        if (self.PARAM_ENVIRONMENT in self.data and
                not self.data.get(self.PARAM_ENVIRONMENT_FILES)):
            env_data = self.data[self.PARAM_ENVIRONMENT]
            with self.parse_error_check('Environment'):
                if isinstance(env_data, dict):
                    env = environment_format.validate(env_data)
                else:
                    env = environment_format.parse(env_data)

        environment_format.default_for_missing(env)
        parameters = self.data.get(self.PARAM_USER_PARAMS, {})
        env[self.PARAM_USER_PARAMS].update(parameters)
        return env

    def files(self):
        return self.data.get(self.PARAM_FILES, {})

    def environment_files(self):
        return self.data.get(self.PARAM_ENVIRONMENT_FILES, None)

    def files_container(self):
        return self.data.get(self.PARAM_FILES_CONTAINER, None)

    def args(self):
        """Get any additional arguments supplied by the user."""
        params = self.data.items()
        return dict((k, v) for k, v in params if k not in self.PARAMS)


class StackController(object):
    """WSGI controller for stacks resource in Heat v1 API.

    Implements the API actions.
    """
    # Define request scope (must match what is in policy.json or policies in
    # code)
    REQUEST_SCOPE = 'stacks'

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    def _extract_bool_param(self, name, value):
        try:
            return param_utils.extract_bool(name, value)
        except ValueError as e:
            raise exc.HTTPBadRequest(six.text_type(e))

    def _extract_int_param(self, name, value,
                           allow_zero=True, allow_negative=False):
        try:
            return param_utils.extract_int(name, value,
                                           allow_zero, allow_negative)
        except ValueError as e:
            raise exc.HTTPBadRequest(six.text_type(e))

    def _extract_tags_param(self, tags):
        try:
            return param_utils.extract_tags(tags)
        except ValueError as e:
            raise exc.HTTPBadRequest(six.text_type(e))

    def _index(self, req, use_admin_cnxt=False):
        filter_whitelist = {
            # usage of keys in this list are not encouraged, please use
            # rpc_api.STACK_KEYS instead
            'id': util.PARAM_TYPE_MIXED,
            'status': util.PARAM_TYPE_MIXED,
            'name': util.PARAM_TYPE_MIXED,
            'action': util.PARAM_TYPE_MIXED,
            'tenant': util.PARAM_TYPE_MIXED,
            'username': util.PARAM_TYPE_MIXED,
            'owner_id': util.PARAM_TYPE_MIXED,
        }
        whitelist = {
            'limit': util.PARAM_TYPE_SINGLE,
            'marker': util.PARAM_TYPE_SINGLE,
            'sort_dir': util.PARAM_TYPE_SINGLE,
            'sort_keys': util.PARAM_TYPE_MULTI,
            'show_deleted': util.PARAM_TYPE_SINGLE,
            'show_nested': util.PARAM_TYPE_SINGLE,
            'show_hidden': util.PARAM_TYPE_SINGLE,
            'tags': util.PARAM_TYPE_SINGLE,
            'tags_any': util.PARAM_TYPE_SINGLE,
            'not_tags': util.PARAM_TYPE_SINGLE,
            'not_tags_any': util.PARAM_TYPE_SINGLE,
        }
        params = util.get_allowed_params(req.params, whitelist)
        stack_keys = dict.fromkeys(rpc_api.STACK_KEYS, util.PARAM_TYPE_MIXED)
        unsupported = (
            rpc_api.STACK_ID,  # not user visible
            rpc_api.STACK_CAPABILITIES,  # not supported
            rpc_api.STACK_CREATION_TIME,  # don't support timestamp
            rpc_api.STACK_DELETION_TIME,  # don't support timestamp
            rpc_api.STACK_DESCRIPTION,  # not supported
            rpc_api.STACK_NOTIFICATION_TOPICS,  # not supported
            rpc_api.STACK_OUTPUTS,  # not in database
            rpc_api.STACK_PARAMETERS,  # not in this table
            rpc_api.STACK_TAGS,  # tags query following a specific guideline
            rpc_api.STACK_TMPL_DESCRIPTION,  # not supported
            rpc_api.STACK_UPDATED_TIME,  # don't support timestamp
        )
        for key in unsupported:
            stack_keys.pop(key)
        # downward compatibility
        stack_keys.update(filter_whitelist)
        filter_params = util.get_allowed_params(req.params, stack_keys)

        show_deleted = False
        p_name = rpc_api.PARAM_SHOW_DELETED
        if p_name in params:
            params[p_name] = self._extract_bool_param(p_name, params[p_name])
            show_deleted = params[p_name]

        show_nested = False
        p_name = rpc_api.PARAM_SHOW_NESTED
        if p_name in params:
            params[p_name] = self._extract_bool_param(p_name, params[p_name])
            show_nested = params[p_name]

        key = rpc_api.PARAM_LIMIT
        if key in params:
            params[key] = self._extract_int_param(key, params[key])

        show_hidden = False
        p_name = rpc_api.PARAM_SHOW_HIDDEN
        if p_name in params:
            params[p_name] = self._extract_bool_param(p_name, params[p_name])
            show_hidden = params[p_name]

        tags = None
        if rpc_api.PARAM_TAGS in params:
            params[rpc_api.PARAM_TAGS] = self._extract_tags_param(
                params[rpc_api.PARAM_TAGS])
            tags = params[rpc_api.PARAM_TAGS]

        tags_any = None
        if rpc_api.PARAM_TAGS_ANY in params:
            params[rpc_api.PARAM_TAGS_ANY] = self._extract_tags_param(
                params[rpc_api.PARAM_TAGS_ANY])
            tags_any = params[rpc_api.PARAM_TAGS_ANY]

        not_tags = None
        if rpc_api.PARAM_NOT_TAGS in params:
            params[rpc_api.PARAM_NOT_TAGS] = self._extract_tags_param(
                params[rpc_api.PARAM_NOT_TAGS])
            not_tags = params[rpc_api.PARAM_NOT_TAGS]

        not_tags_any = None
        if rpc_api.PARAM_NOT_TAGS_ANY in params:
            params[rpc_api.PARAM_NOT_TAGS_ANY] = self._extract_tags_param(
                params[rpc_api.PARAM_NOT_TAGS_ANY])
            not_tags_any = params[rpc_api.PARAM_NOT_TAGS_ANY]

        # get the with_count value, if invalid, raise ValueError
        with_count = False
        if req.params.get('with_count'):
            with_count = self._extract_bool_param(
                'with_count',
                req.params.get('with_count'))

        if not filter_params:
            filter_params = None

        if use_admin_cnxt:
            cnxt = context.get_admin_context()
        else:
            cnxt = req.context

        stacks = self.rpc_client.list_stacks(cnxt,
                                             filters=filter_params,
                                             **params)
        count = None
        if with_count:
            try:
                # Check if engine has been updated to a version with
                # support to count_stacks before trying to use it.
                count = self.rpc_client.count_stacks(cnxt,
                                                     filters=filter_params,
                                                     show_deleted=show_deleted,
                                                     show_nested=show_nested,
                                                     show_hidden=show_hidden,
                                                     tags=tags,
                                                     tags_any=tags_any,
                                                     not_tags=not_tags,
                                                     not_tags_any=not_tags_any)
            except AttributeError as ex:
                LOG.warning("Old Engine Version: %s", ex)

        return stacks_view.collection(req, stacks=stacks,
                                      count=count,
                                      include_project=cnxt.is_admin)

    @util.registered_policy_enforce
    def global_index(self, req):
        return self._index(req, use_admin_cnxt=True)

    @util.registered_policy_enforce
    def index(self, req):
        """Lists summary information for all stacks."""
        global_tenant = False
        name = rpc_api.PARAM_GLOBAL_TENANT
        if name in req.params:
            global_tenant = self._extract_bool_param(
                name,
                req.params.get(name))

        if global_tenant:
            return self.global_index(req, req.context.tenant_id)

        return self._index(req)

    @util.registered_policy_enforce
    def detail(self, req):
        """Lists detailed information for all stacks."""
        stacks = self.rpc_client.list_stacks(req.context)

        return {'stacks': [stacks_view.format_stack(req, s) for s in stacks]}

    @util.registered_policy_enforce
    def preview(self, req, body):
        """Preview the outcome of a template and its params."""

        data = InstantiationData(body)
        args = self.prepare_args(data)
        result = self.rpc_client.preview_stack(
            req.context,
            data.stack_name(),
            data.template(),
            data.environment(),
            data.files(),
            args,
            environment_files=data.environment_files(),
            files_container=data.files_container())

        formatted_stack = stacks_view.format_stack(req, result)
        return {'stack': formatted_stack}

    def prepare_args(self, data, is_update=False):
        args = data.args()
        key = rpc_api.PARAM_TIMEOUT
        if key in args:
            args[key] = self._extract_int_param(key, args[key])
        key = rpc_api.PARAM_TAGS
        if args.get(key) is not None:
            args[key] = self._extract_tags_param(args[key])
        key = rpc_api.PARAM_CONVERGE
        if not is_update and key in args:
            msg = _("%s flag only supported in stack update (or update "
                    "preview) request.") % key
            raise exc.HTTPBadRequest(six.text_type(msg))
        return args

    @util.registered_policy_enforce
    def create(self, req, body):
        """Create a new stack."""
        data = InstantiationData(body)

        args = self.prepare_args(data)
        result = self.rpc_client.create_stack(
            req.context,
            data.stack_name(),
            data.template(),
            data.environment(),
            data.files(),
            args,
            environment_files=data.environment_files(),
            files_container=data.files_container())

        formatted_stack = stacks_view.format_stack(
            req,
            {rpc_api.STACK_ID: result}
        )
        return {'stack': formatted_stack}

    @util.registered_policy_enforce
    def lookup(self, req, stack_name, path='', body=None):
        """Redirect to the canonical URL for a stack."""
        try:
            identity = dict(identifier.HeatIdentifier.from_arn(stack_name))
        except ValueError:
            identity = self.rpc_client.identify_stack(req.context,
                                                      stack_name)

        location = util.make_url(req, identity)
        if path:
            location = '/'.join([location, path])

        params = req.params
        if params:
            location += '?%s' % parse.urlencode(params, True)

        raise exc.HTTPFound(location=location)

    @util.registered_identified_stack
    def show(self, req, identity):
        """Gets detailed information for a stack."""
        params = req.params

        p_name = rpc_api.RESOLVE_OUTPUTS
        if rpc_api.RESOLVE_OUTPUTS in params:
            resolve_outputs = self._extract_bool_param(
                p_name, params[p_name])
        else:
            resolve_outputs = True
        stack_list = self.rpc_client.show_stack(req.context,
                                                identity, resolve_outputs)

        if not stack_list:
            raise exc.HTTPInternalServerError()

        stack = stack_list[0]

        return {'stack': stacks_view.format_stack(req, stack)}

    @util.registered_identified_stack
    def template(self, req, identity):
        """Get the template body for an existing stack."""

        templ = self.rpc_client.get_template(req.context,
                                             identity)

        # TODO(zaneb): always set Content-type to application/json
        return templ

    @util.registered_identified_stack
    def environment(self, req, identity):
        """Get the environment for an existing stack."""
        env = self.rpc_client.get_environment(req.context, identity)

        return env

    @util.registered_identified_stack
    def files(self, req, identity):
        """Get the files for an existing stack."""
        return self.rpc_client.get_files(req.context, identity)

    @util.registered_identified_stack
    def update(self, req, identity, body):
        """Update an existing stack with a new template and/or parameters."""
        data = InstantiationData(body)

        args = self.prepare_args(data, is_update=True)
        self.rpc_client.update_stack(
            req.context,
            identity,
            data.template(),
            data.environment(),
            data.files(),
            args,
            environment_files=data.environment_files(),
            files_container=data.files_container())

        raise exc.HTTPAccepted()

    @util.registered_identified_stack
    def update_patch(self, req, identity, body):
        """Update an existing stack with a new template.

        Update an existing stack with a new template by patching the parameters
        Add the flag patch to the args so the engine code can distinguish
        """
        data = InstantiationData(body, patch=True)

        args = self.prepare_args(data, is_update=True)
        self.rpc_client.update_stack(
            req.context,
            identity,
            data.template(),
            data.environment(),
            data.files(),
            args,
            environment_files=data.environment_files(),
            files_container=data.files_container())

        raise exc.HTTPAccepted()

    def _param_show_nested(self, req):
        whitelist = {'show_nested': 'single'}
        params = util.get_allowed_params(req.params, whitelist)

        p_name = 'show_nested'
        if p_name in params:
            return self._extract_bool_param(p_name, params[p_name])

    @util.registered_identified_stack
    def preview_update(self, req, identity, body):
        """Preview update for existing stack with a new template/parameters."""
        data = InstantiationData(body)

        args = self.prepare_args(data, is_update=True)
        show_nested = self._param_show_nested(req)
        if show_nested is not None:
            args[rpc_api.PARAM_SHOW_NESTED] = show_nested
        changes = self.rpc_client.preview_update_stack(
            req.context,
            identity,
            data.template(),
            data.environment(),
            data.files(),
            args,
            environment_files=data.environment_files(),
            files_container=data.files_container())

        return {'resource_changes': changes}

    @util.registered_identified_stack
    def preview_update_patch(self, req, identity, body):
        """Preview PATCH update for existing stack."""
        data = InstantiationData(body, patch=True)

        args = self.prepare_args(data, is_update=True)
        show_nested = self._param_show_nested(req)
        if show_nested is not None:
            args['show_nested'] = show_nested
        changes = self.rpc_client.preview_update_stack(
            req.context,
            identity,
            data.template(),
            data.environment(),
            data.files(),
            args,
            environment_files=data.environment_files(),
            files_container=data.files_container())

        return {'resource_changes': changes}

    @util.registered_identified_stack
    def delete(self, req, identity):
        """Delete the specified stack."""

        self.rpc_client.delete_stack(req.context,
                                     identity,
                                     cast=False)
        raise exc.HTTPNoContent()

    @util.registered_identified_stack
    def abandon(self, req, identity):
        """Abandons specified stack.

        Abandons specified stack by deleting the stack and it's resources
        from the database, but underlying resources will not be deleted.
        """
        return self.rpc_client.abandon_stack(req.context,
                                             identity)

    @util.registered_identified_stack
    def export(self, req, identity):
        """Export specified stack.

        Return stack data in JSON format.
        """
        return self.rpc_client.export_stack(req.context, identity)

    @util.registered_policy_enforce
    def validate_template(self, req, body):
        """Implements the ValidateTemplate API action.

        Validates the specified template.
        """

        data = InstantiationData(body)

        whitelist = {'show_nested': util.PARAM_TYPE_SINGLE,
                     'ignore_errors': util.PARAM_TYPE_SINGLE}
        params = util.get_allowed_params(req.params, whitelist)

        show_nested = False
        p_name = rpc_api.PARAM_SHOW_NESTED
        if p_name in params:
            params[p_name] = self._extract_bool_param(p_name, params[p_name])
            show_nested = params[p_name]

        if rpc_api.PARAM_IGNORE_ERRORS in params:
            ignorable_errors = params[rpc_api.PARAM_IGNORE_ERRORS].split(',')
        else:
            ignorable_errors = None

        result = self.rpc_client.validate_template(
            req.context,
            data.template(),
            data.environment(),
            files=data.files(),
            environment_files=data.environment_files(),
            files_container=data.files_container(),
            show_nested=show_nested,
            ignorable_errors=ignorable_errors)

        if 'Error' in result:
            raise exc.HTTPBadRequest(result['Error'])

        return result

    @util.registered_policy_enforce
    def list_resource_types(self, req):
        """Returns a resource types list which may be used in template."""
        support_status = req.params.get('support_status')
        type_name = req.params.get('name')
        version = req.params.get('version')
        if req.params.get('with_description') is not None:
            with_description = self._extract_bool_param(
                'with_description',
                req.params.get('with_description'))
        else:
            # Add backward compatibility support for case when heatclient
            # version is lower than version with this parameter.
            with_description = False
        return {
            'resource_types':
            self.rpc_client.list_resource_types(
                req.context,
                support_status=support_status,
                type_name=type_name,
                heat_version=version,
                with_description=with_description)}

    @util.registered_policy_enforce
    def list_template_versions(self, req):
        """Returns a list of available template versions."""
        return {
            'template_versions':
            self.rpc_client.list_template_versions(req.context)
        }

    @util.registered_policy_enforce
    def list_template_functions(self, req, template_version):
        """Returns a list of available functions in a given template."""
        if req.params.get('with_condition_func') is not None:
            with_condition = self._extract_bool_param(
                'with_condition_func',
                req.params.get('with_condition_func'))
        else:
            with_condition = False

        return {
            'template_functions':
            self.rpc_client.list_template_functions(req.context,
                                                    template_version,
                                                    with_condition)
        }

    @util.registered_policy_enforce
    def resource_schema(self, req, type_name, with_description=False):
        """Returns the schema of the given resource type."""
        return self.rpc_client.resource_schema(
            req.context, type_name,
            self._extract_bool_param('with_description', with_description))

    @util.registered_policy_enforce
    def generate_template(self, req, type_name):
        """Generates a template based on the specified type."""
        template_type = 'cfn'
        if rpc_api.TEMPLATE_TYPE in req.params:
            try:
                template_type = param_utils.extract_template_type(
                    req.params.get(rpc_api.TEMPLATE_TYPE))
            except ValueError as ex:
                msg = _("Template type is not supported: %s") % ex
                raise exc.HTTPBadRequest(six.text_type(msg))

        return self.rpc_client.generate_template(req.context,
                                                 type_name,
                                                 template_type)

    @util.registered_identified_stack
    def snapshot(self, req, identity, body):
        name = body.get('name')
        return self.rpc_client.stack_snapshot(req.context, identity, name)

    @util.registered_identified_stack
    def show_snapshot(self, req, identity, snapshot_id):
        snapshot = self.rpc_client.show_snapshot(
            req.context, identity, snapshot_id)
        return {'snapshot': snapshot}

    @util.registered_identified_stack
    def delete_snapshot(self, req, identity, snapshot_id):
        self.rpc_client.delete_snapshot(req.context, identity, snapshot_id)
        raise exc.HTTPNoContent()

    @util.registered_identified_stack
    def list_snapshots(self, req, identity):
        return {
            'snapshots': self.rpc_client.stack_list_snapshots(
                req.context, identity)
        }

    @util.registered_identified_stack
    def restore_snapshot(self, req, identity, snapshot_id):
        self.rpc_client.stack_restore(req.context, identity, snapshot_id)
        raise exc.HTTPAccepted()

    @util.registered_identified_stack
    def list_outputs(self, req, identity):
        return {
            'outputs': self.rpc_client.list_outputs(
                req.context, identity)
        }

    @util.registered_identified_stack
    def show_output(self, req, identity, output_key):
        return {'output': self.rpc_client.show_output(req.context,
                                                      identity,
                                                      output_key)}


class StackSerializer(serializers.JSONResponseSerializer):
    """Handles serialization of specific controller method responses."""

    def _populate_response_header(self, response, location, status):
        response.status = status
        if six.PY2:
            response.headers['Location'] = location.encode('utf-8')
        else:
            response.headers['Location'] = location
        response.headers['Content-Type'] = 'application/json'
        return response

    def create(self, response, result):
        self._populate_response_header(response,
                                       result['stack']['links'][0]['href'],
                                       201)
        response.body = six.b(self.to_json(result))
        return response


def create_resource(options):
    """Stacks resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = StackSerializer()
    return wsgi.Resource(StackController(options), deserializer, serializer)
