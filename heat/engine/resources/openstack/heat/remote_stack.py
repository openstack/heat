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

from oslo_serialization import jsonutils
import six

from heat.common import auth_plugin
from heat.common import context
from heat.common import exception
from heat.common.i18n import _
from heat.common import template_format
from heat.engine import attributes
from heat.engine import environment
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import template


class RemoteStack(resource.Resource):
    """A Resource representing a stack.

    A resource that allowing for the creating stack, where should be defined
    stack template in HOT format, parameters (if template has any parameters
    with no default value), and timeout of creating. After creating current
    stack will have remote stack.
    """
    default_client_name = 'heat'

    PROPERTIES = (
        CONTEXT, TEMPLATE, TIMEOUT, PARAMETERS,
    ) = (
        'context', 'template', 'timeout', 'parameters',
    )

    ATTRIBUTES = (
        NAME_ATTR, OUTPUTS,
    ) = (
        'stack_name', 'outputs',
    )

    _CONTEXT_KEYS = (
        REGION_NAME, CREDENTIAL_SECRET_ID
    ) = (
        'region_name', 'credential_secret_id'
    )

    properties_schema = {
        CONTEXT: properties.Schema(
            properties.Schema.MAP,
            _('Context for this stack.'),
            update_allowed=True,
            schema={
                REGION_NAME: properties.Schema(
                    properties.Schema.STRING,
                    _('Region name in which this stack will be created.'),
                    required=False,
                ),
                CREDENTIAL_SECRET_ID: properties.Schema(
                    properties.Schema.STRING,
                    _('A Barbican secret ID. The Barbican secret should '
                      'contain an OpenStack credential that can be used to '
                      'access a remote cloud.'),
                    required=False,
                    update_allowed=True,
                    support_status=support.SupportStatus(version='12.0.0'),
                ),
            }
        ),
        TEMPLATE: properties.Schema(
            properties.Schema.STRING,
            _('Template that specifies the stack to be created as '
              'a resource.'),
            required=True,
            update_allowed=True
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            _('Number of minutes to wait for this stack creation.'),
            update_allowed=True
        ),
        PARAMETERS: properties.Schema(
            properties.Schema.MAP,
            _('Set of parameters passed to this stack.'),
            default={},
            update_allowed=True
        ),
    }

    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _('Name of the stack.'),
            type=attributes.Schema.STRING
        ),
        OUTPUTS: attributes.Schema(
            _('A dict of key-value pairs output from the stack.'),
            type=attributes.Schema.MAP
        ),
    }

    def __init__(self, name, definition, stack):
        super(RemoteStack, self).__init__(name, definition, stack)
        self._region_name = None
        self._local_context = None

    def _context(self):
        if self._local_context:
            return self._local_context

        ctx_props = self.properties.get(self.CONTEXT)
        if ctx_props:
            self._credential = ctx_props[self.CREDENTIAL_SECRET_ID]
            self._region_name = ctx_props[self.REGION_NAME] if ctx_props[
                self.REGION_NAME] else self.context.region_name
        else:
            self._credential = None
            self._region_name = self.context.region_name

        if ctx_props and self._credential:
            return self._prepare_cloud_context()
        else:
            return self._prepare_region_context()

    def _fetch_barbican_credential(self):
        """Fetch credential information and return context dict."""

        auth = super(RemoteStack, self).client_plugin(
            'barbican').get_secret_payload_by_ref(
            secret_ref='secrets/%s' % (self._credential))
        return auth

    def _prepare_cloud_context(self):
        """Prepare context for remote cloud."""

        auth = self._fetch_barbican_credential()
        dict_ctxt = self.context.to_dict()
        dict_ctxt.update({
            'request_id': dict_ctxt['request_id'],
            'global_request_id': dict_ctxt['global_request_id'],
            'show_deleted': dict_ctxt['show_deleted']
        })
        self._local_context = context.RequestContext.from_dict(dict_ctxt)
        self._local_context._auth_plugin = (
            auth_plugin.get_keystone_plugin_loader(
                auth, self._local_context.keystone_session))

        return self._local_context

    def _prepare_region_context(self):

        # Build RequestContext from existing one
        dict_ctxt = self.context.to_dict()
        dict_ctxt.update({'region_name': self._region_name,
                          'overwrite': False})
        self._local_context = context.RequestContext.from_dict(dict_ctxt)
        return self._local_context

    def heat(self):
        # A convenience method overriding Resource.heat()
        return self._context().clients.client(self.default_client_name)

    def client_plugin(self):
        # A convenience method overriding Resource.client_plugin()
        return self._context().clients.client_plugin(self.default_client_name)

    def validate(self):
        super(RemoteStack, self).validate()

        try:
            self.heat()
        except Exception as ex:
            if self._credential:
                location = "remote cloud"
            else:
                location = 'region "%s"' % self._region_name
            exc_info = dict(location=location, exc=six.text_type(ex))
            msg = _('Cannot establish connection to Heat endpoint at '
                    '%(location)s due to "%(exc)s"') % exc_info
            raise exception.StackValidationFailed(message=msg)

        try:
            params = self.properties[self.PARAMETERS]
            env = environment.get_child_environment(self.stack.env, params)
            tmpl = template_format.parse(self.properties[self.TEMPLATE])
            args = {
                'template': tmpl,
                'files': self.stack.t.files,
                'environment': env.user_env_as_dict(),
            }
            self.heat().stacks.validate(**args)
        except Exception as ex:
            if self._credential:
                location = "remote cloud"
            else:
                location = 'region "%s"' % self._region_name
            exc_info = dict(location=location, exc=six.text_type(ex))
            msg = _('Failed validating stack template using Heat endpoint at '
                    '%(location)s due to "%(exc)s"') % exc_info
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        params = self.properties[self.PARAMETERS]
        env = environment.get_child_environment(self.stack.env, params)
        tmpl = template_format.parse(self.properties[self.TEMPLATE])
        args = {
            'stack_name': self.physical_resource_name_or_FnGetRefId(),
            'template': tmpl,
            'timeout_mins': self.properties[self.TIMEOUT],
            'disable_rollback': True,
            'parameters': params,
            'files': self.stack.t.files,
            'environment': env.user_env_as_dict(),
        }
        remote_stack_id = self.heat().stacks.create(**args)['stack']['id']
        self.resource_id_set(remote_stack_id)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.heat().stacks.delete(stack_id=self.resource_id)

    def handle_resume(self):
        if self.resource_id is None:
            raise exception.Error(_('Cannot resume %s, resource not found')
                                  % self.name)
        self.heat().actions.resume(stack_id=self.resource_id)

    def handle_suspend(self):
        if self.resource_id is None:
            raise exception.Error(_('Cannot suspend %s, resource not found')
                                  % self.name)
        self.heat().actions.suspend(stack_id=self.resource_id)

    def handle_snapshot(self):
        snapshot = self.heat().stacks.snapshot(stack_id=self.resource_id)
        self.data_set('snapshot_id', snapshot['id'])

    def handle_restore(self, defn, restore_data):
        snapshot_id = restore_data['resource_data']['snapshot_id']
        snapshot = self.heat().stacks.snapshot_show(self.resource_id,
                                                    snapshot_id)
        s_data = snapshot['snapshot']['data']
        env = environment.Environment(s_data['environment'])
        files = s_data['files']
        tmpl = template.Template(s_data['template'], env=env, files=files)
        props = dict((k, v) for k, v in self.properties.items()
                     if k in self.properties.data)
        props[self.TEMPLATE] = jsonutils.dumps(tmpl.t)
        props[self.PARAMETERS] = env.params

        return defn.freeze(properties=props)

    def handle_check(self):
        self.heat().actions.check(stack_id=self.resource_id)

    def _needs_update(self, after, before, after_props, before_props,
                      prev_resource, check_init_complete=True):
        # If resource is in CHECK_FAILED state, raise UpdateReplace
        # to replace the failed stack.
        if self.state == (self.CHECK, self.FAILED):
            raise resource.UpdateReplace(self)

        # Always issue an update to the remote stack and let the individual
        # resources in it decide if they need updating.
        return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        # Always issue an update to the remote stack and let the individual
        # resources in it decide if they need updating.
        if self.resource_id:
            self.properties = json_snippet.properties(self.properties_schema,
                                                      self.context)

            params = self.properties[self.PARAMETERS]
            env = environment.get_child_environment(self.stack.env, params)
            tmpl = template_format.parse(self.properties[self.TEMPLATE])
            fields = {
                'stack_id': self.resource_id,
                'parameters': params,
                'template': tmpl,
                'timeout_mins': self.properties[self.TIMEOUT],
                'disable_rollback': self.stack.disable_rollback,
                'files': self.stack.t.files,
                'environment': env.user_env_as_dict(),
            }
            self.heat().stacks.update(**fields)

    def _check_action_complete(self, action):
        stack = self.heat().stacks.get(stack_id=self.resource_id)
        if stack.action != action:
            return False

        if stack.status == self.IN_PROGRESS:
            return False
        elif stack.status == self.COMPLETE:
            return True
        elif stack.status == self.FAILED:
            raise exception.ResourceInError(
                resource_status=stack.stack_status,
                status_reason=stack.stack_status_reason)
        else:
            # Note: this should never happen, so it really means that
            # the resource/engine is in serious problem if it happens.
            raise exception.ResourceUnknownStatus(
                resource_status=stack.stack_status,
                status_reason=stack.stack_status_reason)

    def check_create_complete(self, *args):
        return self._check_action_complete(action=self.CREATE)

    def check_delete_complete(self, *args):
        if self.resource_id is None:
            return True

        try:
            return self._check_action_complete(action=self.DELETE)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return True

    def check_resume_complete(self, *args):
        return self._check_action_complete(action=self.RESUME)

    def check_suspend_complete(self, *args):
        return self._check_action_complete(action=self.SUSPEND)

    def check_update_complete(self, *args):
        return self._check_action_complete(action=self.UPDATE)

    def check_snapshot_complete(self, *args):
        return self._check_action_complete(action=self.SNAPSHOT)

    def check_check_complete(self, *args):
        return self._check_action_complete(action=self.CHECK)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        stack = self.heat().stacks.get(stack_id=self.resource_id)
        if name == self.NAME_ATTR:
            value = getattr(stack, name, None)
            return value or self.physical_resource_name_or_FnGetRefId()

        if name == self.OUTPUTS:
            outputs = stack.outputs
            return dict((output['output_key'], output['output_value'])
                        for output in outputs)

    def get_reference_id(self):
        return self.resource_id

    def needs_replace_with_prop_diff(self, changed_properties_set,
                                     after_props, before_props):
        """Needs replace based on prop_diff."""

        # If region_name changed, trigger UpdateReplace.
        # `context` now set update_allowed=True, but `region_name` is not.
        if self.CONTEXT in changed_properties_set and (
            after_props.get(self.CONTEXT).get(
                'region_name') != before_props.get(self.CONTEXT).get(
                    'region_name')):
                return True
        return False


def resource_mapping():
    return {
        'OS::Heat::Stack': RemoteStack,
    }
