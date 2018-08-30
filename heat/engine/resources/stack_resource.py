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

import json
import weakref

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import reflection
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common import identifier
from heat.common import template_format
from heat.engine import attributes
from heat.engine import environment
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import stk_defn
from heat.engine import template
from heat.objects import raw_template
from heat.objects import stack as stack_object
from heat.objects import stack_lock
from heat.rpc import api as rpc_api

LOG = logging.getLogger(__name__)


class StackResource(resource.Resource):
    """Allows entire stack to be managed as a resource in a parent stack.

    An abstract Resource subclass that allows the management of an entire Stack
    as a resource in a parent stack.
    """

    # Assume True as this is evaluated before the stack is created
    # so there is no way to know for sure without subclass-specific
    # template parsing.
    requires_deferred_auth = True

    def __init__(self, name, json_snippet, stack):
        super(StackResource, self).__init__(name, json_snippet, stack)
        self._nested = None
        self._outputs = None
        self.resource_info = None

    def validate(self):
        super(StackResource, self).validate()
        # Don't redo a non-strict validation of a nested stack during the
        # creation of a child stack; only validate a child stack prior to the
        # creation of the root stack.
        if self.stack.nested_depth == 0 or not self.stack.strict_validate:
            self.validate_nested_stack()

    def validate_nested_stack(self):
        try:
            name = "%s-%s" % (self.stack.name, self.name)
            nested_stack = self._parse_nested_stack(
                name,
                self.child_template(),
                self.child_params())
            nested_stack.strict_validate = False
            nested_stack.validate()
        except AssertionError:
            raise
        except Exception as ex:
            path = "%s<%s>" % (self.name, self.template_url)
            raise exception.StackValidationFailed(
                ex, path=[self.stack.t.RESOURCES, path])

    @property
    def template_url(self):
        """Template url for the stack resource.

        When stack resource is a TemplateResource, it's the template
        location. For group resources like ResourceGroup where the
        template is constructed dynamically, it's just a placeholder.
        """

        return "nested_stack"

    def _outputs_to_attribs(self, json_snippet):
        outputs = json_snippet.get('Outputs')
        if not self.attributes and outputs:
            self.attributes_schema = (
                attributes.Attributes.schema_from_outputs(outputs))
            # Note: it can be updated too and for show return dictionary
            #       with all available outputs
            self.attributes = attributes.Attributes(
                self.name, self.attributes_schema,
                self._make_resolver(weakref.ref(self)))

    def _needs_update(self, after, before, after_props, before_props,
                      prev_resource, check_init_complete=True):

        # If the nested stack has not been created, use the default
        # implementation to determine if we need to replace the resource. Note
        # that we do *not* return the result.
        if self.resource_id is None:
            super(StackResource, self)._needs_update(after, before,
                                                     after_props, before_props,
                                                     prev_resource,
                                                     check_init_complete)
        else:
            if self.state == (self.CHECK, self.FAILED):
                nested_stack = self.rpc_client().show_stack(
                    self.context, self.nested_identifier())[0]
                nested_stack_state = (nested_stack[rpc_api.STACK_ACTION],
                                      nested_stack[rpc_api.STACK_STATUS])
                if nested_stack_state == (self.stack.CHECK, self.stack.FAILED):
                    # The stack-check action marked the stack resource
                    # CHECK_FAILED, so return True to allow the individual
                    # CHECK_FAILED resources decide if they need updating.
                    return True
                # The mark-unhealthy action marked the stack resource
                # CHECK_FAILED, so raise UpdateReplace to replace the
                # entire failed stack.
                raise resource.UpdateReplace(self)

        # Always issue an update to the nested stack and let the individual
        # resources in it decide if they need updating.
        return True

    def nested_identifier(self):
        if self.resource_id is None:
            return None
        return identifier.HeatIdentifier(
            self.context.tenant_id,
            self.physical_resource_name(),
            self.resource_id)

    def has_nested(self):
        """Return True if the resource has an existing nested stack."""
        return self.resource_id is not None or self._nested is not None

    def nested(self):
        """Return a Stack object representing the nested (child) stack.

        If we catch NotFound exception when loading, return None.
        """
        if self._nested is None and self.resource_id is not None:
            try:
                self._nested = parser.Stack.load(self.context,
                                                 self.resource_id)
            except exception.NotFound:
                return None

        return self._nested

    def child_template(self):
        """Default implementation to get the child template.

        Resources that inherit from StackResource should override this method
        with specific details about the template used by them.
        """
        raise NotImplementedError()

    def child_params(self):
        """Default implementation to get the child params.

        Resources that inherit from StackResource should override this method
        with specific details about the parameters used by them.
        """
        raise NotImplementedError()

    def preview(self):
        """Preview a StackResource as resources within a Stack.

        This method overrides the original Resource.preview to return a preview
        of all the resources contained in this Stack.  For this to be possible,
        the specific resources need to override both ``child_template`` and
        ``child_params`` with specific information to allow the stack to be
        parsed correctly. If any of these methods is missing, the entire
        StackResource will be returned as if it were a regular Resource.
        """
        try:
            child_template = self.child_template()
            params = self.child_params()
        except NotImplementedError:
            class_name = reflection.get_class_name(self, fully_qualified=False)
            LOG.warning("Preview of '%s' not yet implemented", class_name)
            return self

        name = "%s-%s" % (self.stack.name, self.name)
        self._nested = self._parse_nested_stack(name, child_template, params)

        return self.nested().preview_resources()

    def get_nested_parameters_stack(self):
        """Return a stack for schema validation.

        This returns a stack to be introspected for building parameters schema.
        It can be customized by subclass to return a restricted version of what
        will be running.
        """
        try:
            child_template = self.child_template()
            params = self.child_params()
        except NotImplementedError:
            class_name = reflection.get_class_name(self, fully_qualified=False)
            LOG.warning("Nested parameters of '%s' not yet "
                        "implemented", class_name)
            return
        name = "%s-%s" % (self.stack.name, self.name)
        return self._parse_nested_stack(name, child_template, params)

    def _parse_child_template(self, child_template, child_env):
        parsed_child_template = child_template
        if isinstance(parsed_child_template, template.Template):
            parsed_child_template = parsed_child_template.t
        return template.Template(parsed_child_template,
                                 files=self.child_template_files(child_env),
                                 env=child_env)

    def child_template_files(self, child_env):
        """Default implementation to get the files map for child template."""
        return self.stack.t.files

    def _parse_nested_stack(self, stack_name, child_template,
                            child_params, timeout_mins=None,
                            adopt_data=None):
        if timeout_mins is None:
            timeout_mins = self.stack.timeout_mins

        stack_user_project_id = self.stack.stack_user_project_id
        new_nested_depth = self._child_nested_depth()

        child_env = environment.get_child_environment(
            self.stack.env, child_params,
            child_resource_name=self.name,
            item_to_remove=self.resource_info)

        parsed_template = self._child_parsed_template(child_template,
                                                      child_env)
        self._validate_nested_resources(parsed_template)

        # Note we disable rollback for nested stacks, since they
        # should be rolled back by the parent stack on failure
        nested = parser.Stack(self.context,
                              stack_name,
                              parsed_template,
                              timeout_mins=timeout_mins,
                              disable_rollback=True,
                              parent_resource=self.name,
                              owner_id=self.stack.id,
                              user_creds_id=self.stack.user_creds_id,
                              stack_user_project_id=stack_user_project_id,
                              adopt_stack_data=adopt_data,
                              nested_depth=new_nested_depth)
        nested.set_parent_stack(self.stack)
        return nested

    def _child_nested_depth(self):
        if self.stack.nested_depth >= cfg.CONF.max_nested_stack_depth:
            msg = _("Recursion depth exceeds %d."
                    ) % cfg.CONF.max_nested_stack_depth
            raise exception.RequestLimitExceeded(message=msg)
        return self.stack.nested_depth + 1

    def _child_parsed_template(self, child_template, child_env):
        parsed_template = self._parse_child_template(child_template, child_env)

        # Don't overwrite the attributes_schema for subclasses that
        # define their own attributes_schema.
        if not hasattr(type(self), 'attributes_schema'):
            self.attributes = None
            self._outputs_to_attribs(parsed_template)
        return parsed_template

    def _validate_nested_resources(self, templ):
        if cfg.CONF.max_resources_per_stack == -1:
            return

        total_resources = (len(templ[templ.RESOURCES]) +
                           self.stack.total_resources(self.root_stack_id))

        identity = self.nested_identifier()
        if identity is not None:
            existing = self.rpc_client().list_stack_resources(self.context,
                                                              identity)
            # Don't double-count existing resources during an update
            total_resources -= len(existing)

        if (total_resources > cfg.CONF.max_resources_per_stack):
            message = exception.StackResourceLimitExceeded.msg_fmt
            raise exception.RequestLimitExceeded(message=message)

    def create_with_template(self, child_template, user_params=None,
                             timeout_mins=None, adopt_data=None):
        """Create the nested stack with the given template."""
        name = self.physical_resource_name()
        if timeout_mins is None:
            timeout_mins = self.stack.timeout_mins
        stack_user_project_id = self.stack.stack_user_project_id

        kwargs = self._stack_kwargs(user_params, child_template, adopt_data)

        adopt_data_str = None
        if adopt_data is not None:
            if 'environment' not in adopt_data:
                adopt_data['environment'] = kwargs['params']
            if 'template' not in adopt_data:
                if isinstance(child_template, template.Template):
                    adopt_data['template'] = child_template.t
                else:
                    adopt_data['template'] = child_template
            adopt_data_str = json.dumps(adopt_data)

        args = {rpc_api.PARAM_TIMEOUT: timeout_mins,
                rpc_api.PARAM_DISABLE_ROLLBACK: True,
                rpc_api.PARAM_ADOPT_STACK_DATA: adopt_data_str}
        kwargs.update({
            'stack_name': name,
            'args': args,
            'environment_files': None,
            'owner_id': self.stack.id,
            'user_creds_id': self.stack.user_creds_id,
            'stack_user_project_id': stack_user_project_id,
            'nested_depth': self._child_nested_depth(),
            'parent_resource_name': self.name
        })
        with self.translate_remote_exceptions:
            try:
                result = self.rpc_client()._create_stack(self.context,
                                                         **kwargs)
            except exception.HeatException:
                with excutils.save_and_reraise_exception():
                    if adopt_data is None:
                        raw_template.RawTemplate.delete(self.context,
                                                        kwargs['template_id'])

        self.resource_id_set(result['stack_id'])

    def child_definition(self, child_template=None, user_params=None,
                         nested_identifier=None):
        if user_params is None:
            user_params = self.child_params()
        if child_template is None:
            child_template = self.child_template()
        if nested_identifier is None:
            nested_identifier = self.nested_identifier()

        child_env = environment.get_child_environment(
            self.stack.env,
            user_params,
            child_resource_name=self.name,
            item_to_remove=self.resource_info)

        parsed_template = self._child_parsed_template(child_template,
                                                      child_env)
        return stk_defn.StackDefinition(self.context, parsed_template,
                                        nested_identifier,
                                        None)

    def _stack_kwargs(self, user_params, child_template, adopt_data=None):
        defn = self.child_definition(child_template, user_params)
        parsed_template = defn.t

        if adopt_data is None:
            template_id = parsed_template.store(self.context)
            return {
                'template_id': template_id,
                'template': None,
                'params': None,
                'files': None,
            }
        else:
            return {
                'template': parsed_template.t,
                'params': defn.env.user_env_as_dict(),
                'files': parsed_template.files,
            }

    @excutils.exception_filter
    def translate_remote_exceptions(self, ex):
        if (isinstance(ex, exception.ActionInProgress) and
                self.stack.action == self.stack.ROLLBACK):
            # The update was interrupted and the rollback is already in
            # progress, so just ignore the error and wait for the rollback to
            # finish
            return True

        class_name = reflection.get_class_name(ex, fully_qualified=False)
        if not class_name.endswith('_Remote'):
            return False

        full_message = six.text_type(ex)
        if full_message.find('\n') > -1:
            message, msg_trace = full_message.split('\n', 1)
        else:
            message = full_message

        raise exception.ResourceFailure(message, self, action=self.action)

    def check_create_complete(self, cookie=None):
        return self._check_status_complete(self.CREATE)

    def _check_status_complete(self, expected_action, cookie=None):

        try:
            data = stack_object.Stack.get_status(self.context,
                                                 self.resource_id)
        except exception.NotFound:
            if expected_action == self.DELETE:
                return True
            # It's possible the engine handling the create hasn't persisted
            # the stack to the DB when we first start polling for state
            return False

        action, status, status_reason, updated_time = data

        if action != expected_action:
            return False

        # Has the action really started?
        #
        # The rpc call to update does not guarantee that the stack will be
        # placed into IN_PROGRESS by the time it returns (it runs stack.update
        # in a thread) so you could also have a situation where we get into
        # this method and the update hasn't even started.
        #
        # So we are using a mixture of state (action+status) and updated_at
        # to see if the action has actually progressed.
        # - very fast updates (like something with one RandomString) we will
        #   probably miss the state change, but we should catch the updated_at.
        # - very slow updates we won't see the updated_at for quite a while,
        #   but should see the state change.
        if cookie is not None:
            prev_state = cookie['previous']['state']
            prev_updated_at = cookie['previous']['updated_at']
            if (prev_updated_at == updated_time and
                    prev_state == (action, status)):
                return False

        if status == self.IN_PROGRESS:
            return False
        elif status == self.COMPLETE:
            # For operations where we do not take a resource lock
            # (i.e. legacy-style), check that the stack lock has been
            # released before reporting completeness.
            done = (self._should_lock_on_action(expected_action) or
                    stack_lock.StackLock.get_engine_id(
                self.context, self.resource_id) is None)
            if done:
                # Reset nested, to indicate we changed status
                self._nested = None
            return done
        elif status == self.FAILED:
            raise exception.ResourceFailure(status_reason, self,
                                            action=action)
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=status,
                status_reason=status_reason,
                result=_('Stack unknown status'))

    def check_adopt_complete(self, cookie=None):
        return self._check_status_complete(self.ADOPT)

    def _try_rollback(self):
        stack_identity = self.nested_identifier()
        if stack_identity is None:
            return False

        try:
            self.rpc_client().stack_cancel_update(
                self.context,
                dict(stack_identity),
                cancel_with_rollback=True)
        except exception.NotSupported:
            return False

        try:
            data = stack_object.Stack.get_status(self.context,
                                                 self.resource_id)
        except exception.NotFound:
            return False

        action, status, status_reason, updated_time = data

        # If nested stack is still in progress, it should eventually roll
        # itself back due to stack_cancel_update(), so we just need to wait
        # for that to complete
        return status == self.stack.IN_PROGRESS

    def update_with_template(self, child_template, user_params=None,
                             timeout_mins=None):
        """Update the nested stack with the new template."""
        if self.id is None:
            self.store()

        if self.stack.action == self.stack.ROLLBACK:
            if self._try_rollback():
                LOG.info('Triggered nested stack %s rollback',
                         self.physical_resource_name())
                return {'target_action': self.stack.ROLLBACK}

        if self.resource_id is None:
            # if the create failed for some reason and the nested
            # stack was not created, we need to create an empty stack
            # here so that the update will work.
            def _check_for_completion():
                while not self.check_create_complete():
                    yield

            empty_temp = template_format.parse(
                "heat_template_version: '2013-05-23'")
            self.create_with_template(empty_temp, {})
            checker = scheduler.TaskRunner(_check_for_completion)
            checker(timeout=self.stack.timeout_secs())

        if timeout_mins is None:
            timeout_mins = self.stack.timeout_mins

        try:
            status_data = stack_object.Stack.get_status(self.context,
                                                        self.resource_id)
        except exception.NotFound:
            raise resource.UpdateReplace(self)

        action, status, status_reason, updated_time = status_data

        kwargs = self._stack_kwargs(user_params, child_template)
        cookie = {'previous': {
            'updated_at': updated_time,
            'state': (action, status)}}

        kwargs.update({
            'stack_identity': dict(self.nested_identifier()),
            'args': {rpc_api.PARAM_TIMEOUT: timeout_mins,
                     rpc_api.PARAM_CONVERGE: self.converge}
        })
        with self.translate_remote_exceptions:
            try:
                self.rpc_client()._update_stack(self.context, **kwargs)
            except exception.HeatException:
                with excutils.save_and_reraise_exception():
                    raw_template.RawTemplate.delete(self.context,
                                                    kwargs['template_id'])
        return cookie

    def check_update_complete(self, cookie=None):
        if cookie is not None and 'target_action' in cookie:
            target_action = cookie['target_action']
            cookie = None
        else:
            target_action = self.stack.UPDATE
        return self._check_status_complete(target_action,
                                           cookie=cookie)

    def handle_update_cancel(self, cookie):
        stack_identity = self.nested_identifier()
        if stack_identity is not None:
            try:
                self.rpc_client().stack_cancel_update(
                    self.context,
                    dict(stack_identity),
                    cancel_with_rollback=False)
            except exception.NotSupported:
                LOG.debug('Nested stack %s not in cancellable state',
                          stack_identity.stack_name)

    def handle_create_cancel(self, cookie):
        return self.handle_update_cancel(cookie)

    def delete_nested(self):
        """Delete the nested stack."""
        stack_identity = self.nested_identifier()
        if stack_identity is None:
            return

        with self.rpc_client().ignore_error_by_name('EntityNotFound'):
            if self.abandon_in_progress:
                self.rpc_client().abandon_stack(self.context, stack_identity)
            else:
                self.rpc_client().delete_stack(self.context, stack_identity,
                                               cast=False)

    def handle_delete(self):
        return self.delete_nested()

    def check_delete_complete(self, cookie=None):
        return self._check_status_complete(self.DELETE)

    def handle_suspend(self):
        stack_identity = self.nested_identifier()
        if stack_identity is None:
            raise exception.Error(_('Cannot suspend %s, stack not created')
                                  % self.name)
        self.rpc_client().stack_suspend(self.context, dict(stack_identity))

    def check_suspend_complete(self, cookie=None):
        return self._check_status_complete(self.SUSPEND)

    def handle_resume(self):
        stack_identity = self.nested_identifier()
        if stack_identity is None:
            raise exception.Error(_('Cannot resume %s, stack not created')
                                  % self.name)
        self.rpc_client().stack_resume(self.context, dict(stack_identity))

    def check_resume_complete(self, cookie=None):
        return self._check_status_complete(self.RESUME)

    def handle_check(self):
        stack_identity = self.nested_identifier()
        if stack_identity is None:
            raise exception.Error(_('Cannot check %s, stack not created')
                                  % self.name)

        self.rpc_client().stack_check(self.context, dict(stack_identity))

    def check_check_complete(self, cookie=None):
        return self._check_status_complete(self.CHECK)

    def prepare_abandon(self):
        self.abandon_in_progress = True
        nested_stack = self.nested()
        if nested_stack:
            return nested_stack.prepare_abandon()

        return {}

    def get_output(self, op):
        """Return the specified Output value from the nested stack.

        If the output key does not exist, raise a NotFound exception.
        """
        if (self._outputs is None or
                (op in self._outputs and
                 rpc_api.OUTPUT_ERROR not in self._outputs[op] and
                 self._outputs[op].get(rpc_api.OUTPUT_VALUE) is None)):
            stack_identity = self.nested_identifier()
            if stack_identity is None:
                return
            stack = self.rpc_client().show_stack(self.context,
                                                 dict(stack_identity))
            if not stack:
                return
            outputs = stack[0].get(rpc_api.STACK_OUTPUTS) or {}
            self._outputs = {o[rpc_api.OUTPUT_KEY]: o for o in outputs}

        if op not in self._outputs:
            raise exception.NotFound(_('Specified output key %s not '
                                       'found.') % op)

        output_data = self._outputs[op]
        if rpc_api.OUTPUT_ERROR in output_data:
            raise exception.TemplateOutputError(
                resource=self.name,
                attribute=op,
                message=output_data[rpc_api.OUTPUT_ERROR])

        return output_data[rpc_api.OUTPUT_VALUE]

    def _resolve_attribute(self, name):
        try:
            return self.get_output(name)
        except exception.NotFound:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=name)
