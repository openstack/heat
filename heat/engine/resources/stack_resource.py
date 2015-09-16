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

import hashlib
import json

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LE
from heat.common.i18n import _LW
from heat.common import identifier
from heat.common import template_format
from heat.engine import attributes
from heat.engine import environment
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
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
        self.resource_info = None

    def validate(self):
        super(StackResource, self).validate()
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
            raise exception.StackValidationFailed(
                error=_("Failed to validate"),
                path=[self.stack.t.get_section_name('resources'), self.name],
                message=six.text_type(ex))

    def _outputs_to_attribs(self, json_snippet):
        outputs = json_snippet.get('Outputs')
        if not self.attributes and outputs:
            self.attributes_schema = (
                attributes.Attributes.schema_from_outputs(outputs))
            # Note: it can be updated too and for show return dictionary
            #       with all available outputs
            self.attributes = attributes.Attributes(
                self.name, self.attributes_schema,
                self._resolve_all_attributes)

    def _needs_update(self, after, before, after_props, before_props,
                      prev_resource, check_init_complete=True):
        # Issue an update to the nested stack if the stack resource
        # is able to update. If return true, let the individual
        # resources in it decide if they need updating.

        # FIXME (ricolin): seems currently can not call super here
        if self.nested() is None and self.status == self.FAILED:
            raise exception.UpdateReplace(self)

        if (check_init_complete and
                self.nested() is None and
                self.action == self.INIT and self.status == self.COMPLETE):
            raise exception.UpdateReplace(self)

        return True

    @scheduler.wrappertask
    def update(self, after, before=None, prev_resource=None):
        try:
            yield super(StackResource, self).update(after, before,
                                                    prev_resource)
        except StopIteration:
            with excutils.save_and_reraise_exception():
                stack_identity = identifier.HeatIdentifier(
                    self.context.tenant_id,
                    self.physical_resource_name(),
                    self.resource_id)
                self.rpc_client().stack_cancel_update(
                    self.context,
                    dict(stack_identity),
                    cancel_with_rollback=False)

    def has_nested(self):
        if self.nested() is not None:
            return True

        return False

    def nested(self, force_reload=False, show_deleted=False):
        """Return a Stack object representing the nested (child) stack.

        If we catch NotFound exception when loading, return None.

        :param force_reload: Forces reloading from the DB instead of returning
                             the locally cached Stack object
        :param show_deleted: Returns the stack even if it's been deleted
        """
        if force_reload:
            self._nested = None

        if self._nested is None and self.resource_id is not None:
            try:
                self._nested = parser.Stack.load(self.context,
                                                 self.resource_id,
                                                 show_deleted=show_deleted,
                                                 force_reload=force_reload)
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
            LOG.warn(_LW("Preview of '%s' not yet implemented"),
                     self.__class__.__name__)
            return self

        name = "%s-%s" % (self.stack.name, self.name)
        self._nested = self._parse_nested_stack(name, child_template, params)

        return self.nested().preview_resources()

    def _parse_child_template(self, child_template, child_env):
        parsed_child_template = child_template
        if isinstance(parsed_child_template, template.Template):
            parsed_child_template = parsed_child_template.t
        return template.Template(parsed_child_template,
                                 files=self.stack.t.files, env=child_env)

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
        return nested

    def _child_nested_depth(self):
        if self.stack.nested_depth >= cfg.CONF.max_nested_stack_depth:
            msg = _("Recursion depth exceeds %d."
                    ) % cfg.CONF.max_nested_stack_depth
            raise exception.RequestLimitExceeded(message=msg)
        return self.stack.nested_depth + 1

    def _child_parsed_template(self, child_template, child_env):
        parsed_template = self._parse_child_template(child_template, child_env)
        self._validate_nested_resources(parsed_template)

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

        if self.nested():
            # It's an update and these resources will be deleted
            total_resources -= len(self.nested().resources)

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

        if user_params is None:
            user_params = self.child_params()
        child_env = environment.get_child_environment(
            self.stack.env,
            user_params,
            child_resource_name=self.name,
            item_to_remove=self.resource_info)

        new_nested_depth = self._child_nested_depth()
        parsed_template = self._child_parsed_template(child_template,
                                                      child_env)

        adopt_data_str = None
        if adopt_data is not None:
            if 'environment' not in adopt_data:
                adopt_data['environment'] = child_env.user_env_as_dict()
            if 'template' not in adopt_data:
                if isinstance(child_template, template.Template):
                    adopt_data['template'] = child_template.t
                else:
                    adopt_data['template'] = child_template
            adopt_data_str = json.dumps(adopt_data)

        args = {rpc_api.PARAM_TIMEOUT: timeout_mins,
                rpc_api.PARAM_DISABLE_ROLLBACK: True,
                rpc_api.PARAM_ADOPT_STACK_DATA: adopt_data_str}
        try:
            result = self.rpc_client()._create_stack(
                self.context,
                name,
                parsed_template.t,
                child_env.user_env_as_dict(),
                parsed_template.files,
                args,
                owner_id=self.stack.id,
                user_creds_id=self.stack.user_creds_id,
                stack_user_project_id=stack_user_project_id,
                nested_depth=new_nested_depth,
                parent_resource_name=self.name)
        except Exception as ex:
            self.raise_local_exception(ex)

        self.resource_id_set(result['stack_id'])

    def raise_local_exception(self, ex):
        if (isinstance(ex, exception.ActionInProgress) and
                self.stack.action == self.stack.ROLLBACK):
            # The update was interrupted and the rollback is already in
            # progress, so just ignore the error and wait for the rollback to
            # finish
            return

        if not ex.__class__.__name__.endswith('_Remote'):
            raise ex

        full_message = six.text_type(ex)
        if full_message.find('\n') > -1:
            message, msg_trace = full_message.split('\n', 1)
        else:
            message = full_message

        raise exception.ResourceFailure(message, self, action=self.action)

    def check_create_complete(self, cookie=None):
        return self._check_status_complete(resource.Resource.CREATE)

    def _check_status_complete(self, action, show_deleted=False,
                               cookie=None):
        nested = self.nested(force_reload=True, show_deleted=show_deleted)
        if nested is None:
            if action == resource.Resource.DELETE:
                return True
            # It's possible the engine handling the create hasn't persisted
            # the stack to the DB when we first start polling for state
            return False

        if nested.action != action:
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
            if (prev_updated_at == nested.updated_time and
                    prev_state == nested.state):
                return False

        if nested.status == resource.Resource.IN_PROGRESS:
            return False
        elif nested.status == resource.Resource.COMPLETE:
            return True
        elif nested.status == resource.Resource.FAILED:
            raise exception.ResourceFailure(nested.status_reason, self,
                                            action=action)
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=nested.status,
                status_reason=nested.status_reason,
                result=_('Stack unknown status'))

    def check_adopt_complete(self, cookie=None):
        return self._check_status_complete(resource.Resource.ADOPT)

    def update_with_template(self, child_template, user_params=None,
                             timeout_mins=None):
        """Update the nested stack with the new template."""
        if self.id is None:
            self._store()

        nested_stack = self.nested()
        if nested_stack is None:
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
            nested_stack = self.nested()

        if timeout_mins is None:
            timeout_mins = self.stack.timeout_mins

        if user_params is None:
            user_params = self.child_params()

        child_env = environment.get_child_environment(
            self.stack.env,
            user_params,
            child_resource_name=self.name,
            item_to_remove=self.resource_info)
        parsed_template = self._child_parsed_template(child_template,
                                                      child_env)

        cookie = {'previous': {
            'updated_at': nested_stack.updated_time,
            'state': nested_stack.state}}

        args = {rpc_api.PARAM_TIMEOUT: timeout_mins}
        try:
            self.rpc_client().update_stack(
                self.context,
                dict(nested_stack.identifier()),
                parsed_template.t,
                child_env.user_env_as_dict(),
                parsed_template.files,
                args)
        except Exception as ex:
            LOG.exception(_LE('update_stack'))
            self.raise_local_exception(ex)
        return cookie

    def check_update_complete(self, cookie=None):
        return self._check_status_complete(resource.Resource.UPDATE,
                                           cookie=cookie)

    def delete_nested(self):
        """Delete the nested stack."""
        stack = self.nested()
        if stack is None:
            return

        stack_identity = dict(stack.identifier())

        try:
            self.rpc_client().delete_stack(self.context, stack_identity)
        except Exception as ex:
            self.rpc_client().ignore_error_named(ex, 'NotFound')

    def handle_delete(self):
        return self.delete_nested()

    def check_delete_complete(self, cookie=None):
        return self._check_status_complete(resource.Resource.DELETE,
                                           show_deleted=True)

    def handle_suspend(self):
        stack = self.nested()
        if stack is None:
            raise exception.Error(_('Cannot suspend %s, stack not created')
                                  % self.name)
        stack_identity = identifier.HeatIdentifier(
            self.context.tenant_id,
            self.physical_resource_name(),
            self.resource_id)
        self.rpc_client().stack_suspend(self.context, dict(stack_identity))

    def check_suspend_complete(self, cookie=None):
        return self._check_status_complete(resource.Resource.SUSPEND)

    def handle_resume(self):
        stack = self.nested()
        if stack is None:
            raise exception.Error(_('Cannot resume %s, stack not created')
                                  % self.name)
        stack_identity = identifier.HeatIdentifier(
            self.context.tenant_id,
            self.physical_resource_name(),
            self.resource_id)
        self.rpc_client().stack_resume(self.context, dict(stack_identity))

    def check_resume_complete(self, cookie=None):
        return self._check_status_complete(resource.Resource.RESUME)

    def handle_check(self):
        stack = self.nested()
        if stack is None:
            raise exception.Error(_('Cannot check %s, stack not created')
                                  % self.name)

        stack_identity = identifier.HeatIdentifier(
            self.context.tenant_id,
            self.physical_resource_name(),
            self.resource_id)
        self.rpc_client().stack_check(self.context, dict(stack_identity))

    def check_check_complete(self, cookie=None):
        return self._check_status_complete(resource.Resource.CHECK)

    def prepare_abandon(self):
        nested_stack = self.nested()
        if nested_stack:
            return self.nested().prepare_abandon()

        return {}

    def get_output(self, op):
        """Return the specified Output value from the nested stack.

        If the output key does not exist, raise an InvalidTemplateAttribute
        exception.
        """
        stack = self.nested()
        if stack is None:
            return None
        if op not in stack.outputs:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=op)
        result = stack.output(op)
        if result is None and stack.outputs[op].get('error_msg') is not None:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=op)
        return result

    def _resolve_attribute(self, name):
        return self.get_output(name)

    def implementation_signature(self):
        schema_names = ([prop for prop in self.properties_schema] +
                        [at for at in self.attributes_schema])
        schema_hash = hashlib.sha256(';'.join(schema_names))
        definition = {'template': self.child_template(),
                      'files': self.stack.t.files}
        definition_hash = hashlib.sha256(jsonutils.dumps(definition))
        return (schema_hash.hexdigest(), definition_hash.hexdigest())
