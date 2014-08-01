
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

from oslo.config import cfg

from heat.common import exception
from heat.engine import attributes
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler

from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

logger = logging.getLogger(__name__)


class StackResource(resource.Resource):
    '''
    An abstract Resource subclass that allows the management of an entire Stack
    as a resource in a parent stack.
    '''

    # Assume True as this is evaluated before the stack is created
    # so there is no way to know for sure without subclass-specific
    # template parsing.
    requires_deferred_auth = True

    def __init__(self, name, json_snippet, stack):
        super(StackResource, self).__init__(name, json_snippet, stack)
        self._nested = None
        if self.stack.parent_resource:
            self.recursion_depth = (
                self.stack.parent_resource.recursion_depth + 1)
        else:
            self.recursion_depth = 0

    def _outputs_to_attribs(self, json_snippet):
        if not self.attributes and 'Outputs' in json_snippet:
            self.attributes_schema = (
                attributes.Attributes
                .schema_from_outputs(json_snippet.get('Outputs')))
            self.attributes = attributes.Attributes(self.name,
                                                    self.attributes_schema,
                                                    self._resolve_attribute)

    def nested(self):
        '''
        Return a Stack object representing the nested (child) stack.
        '''
        if self._nested is None and self.resource_id is not None:
            self._nested = parser.Stack.load(self.context,
                                             self.resource_id,
                                             parent_resource=self,
                                             show_deleted=False)

            if self._nested is None:
                raise exception.NotFound(_("Nested stack not found in DB"))

        return self._nested

    def child_template(self):
        '''
        Default implementation to get the child template.

        Resources that inherit from StackResource should override this method
        with specific details about the template used by them.
        '''
        raise NotImplementedError()

    def child_params(self):
        '''
        Default implementation to get the child params.

        Resources that inherit from StackResource should override this method
        with specific details about the parameters used by them.
        '''
        raise NotImplementedError()

    def preview(self):
        '''
        Preview a StackResource as resources within a Stack.

        This method overrides the original Resource.preview to return a preview
        of all the resources contained in this Stack.  For this to be possible,
        the specific resources need to override both ``child_template`` and
        ``child_params`` with specific information to allow the stack to be
        parsed correctly. If any of these methods is missing, the entire
        StackResource will be returned as if it were a regular Resource.
        '''
        try:
            template = parser.Template(self.child_template())
            params = self.child_params()
        except NotImplementedError:
            not_implemented_msg = _("Preview of '%s' not yet implemented")
            logger.warning(not_implemented_msg % self.__class__.__name__)
            return self

        self._validate_nested_resources(template)
        name = "%s-%s" % (self.stack.name, self.name)
        nested = parser.Stack(self.context,
                              name,
                              template,
                              self._nested_environment(params),
                              disable_rollback=True,
                              parent_resource=self,
                              owner_id=self.stack.id)

        return nested.preview_resources()

    def _validate_nested_resources(self, template):
        total_resources = (len(template[template.RESOURCES]) +
                           self.stack.root_stack.total_resources())
        if (total_resources > cfg.CONF.max_resources_per_stack):
            message = exception.StackResourceLimitExceeded.msg_fmt
            raise exception.RequestLimitExceeded(message=message)

    def _nested_environment(self, user_params):
        """Build a sensible environment for the nested stack.

        This is built from the user_params and the parent stack's registry
        so we can use user-defined resources within nested stacks.
        """
        nested_env = environment.Environment()
        nested_env.registry = self.stack.env.registry
        user_env = {environment.PARAMETERS: {}}
        if user_params is not None:
            if environment.PARAMETERS not in user_params:
                user_env[environment.PARAMETERS] = user_params
            else:
                user_env.update(user_params)
        nested_env.load(user_env)
        return nested_env

    def create_with_template(self, child_template, user_params,
                             timeout_mins=None, adopt_data=None):
        '''
        Handle the creation of the nested stack from a given JSON template.
        '''
        if self.recursion_depth >= cfg.CONF.max_nested_stack_depth:
            msg = _("Recursion depth exceeds %d.") % \
                cfg.CONF.max_nested_stack_depth
            raise exception.RequestLimitExceeded(message=msg)
        template = parser.Template(child_template, files=self.stack.t.files)
        self._validate_nested_resources(template)
        self._outputs_to_attribs(child_template)

        if timeout_mins is None:
            timeout_mins = self.stack.timeout_mins

        # Note we disable rollback for nested stacks, since they
        # should be rolled back by the parent stack on failure
        nested = parser.Stack(self.context,
                              self.physical_resource_name(),
                              template,
                              self._nested_environment(user_params),
                              timeout_mins=timeout_mins,
                              disable_rollback=True,
                              parent_resource=self,
                              owner_id=self.stack.id,
                              adopt_stack_data=adopt_data)
        nested.validate()
        self._nested = nested
        nested_id = self._nested.store()
        self.resource_id_set(nested_id)

        action = self._nested.CREATE
        if adopt_data:
            action = self._nested.ADOPT

        stack_creator = scheduler.TaskRunner(self._nested.stack_task,
                                             action=action)
        stack_creator.start(timeout=self._nested.timeout_secs())
        return stack_creator

    def check_create_complete(self, stack_creator):
        done = stack_creator.step()
        if done:
            if self._nested.state != (self._nested.CREATE,
                                      self._nested.COMPLETE):
                raise exception.Error(self._nested.status_reason)

        return done

    def update_with_template(self, child_template, user_params,
                             timeout_mins=None):
        """Update the nested stack with the new template."""
        template = parser.Template(child_template, files=self.stack.t.files)
        # Note that there is no call to self._outputs_to_attribs here.
        # If we have a use case for updating attributes of the resource based
        # on updated templates we should make sure it's optional because not
        # all subclasses want that behavior, since they may offer custom
        # attributes.
        nested_stack = self.nested()
        if nested_stack is None:
            raise exception.Error(_('Cannot update %s, stack not created')
                                  % self.name)
        res_diff = (
            len(template[template.RESOURCES]) - len(nested_stack.resources))
        new_size = nested_stack.root_stack.total_resources() + res_diff
        if new_size > cfg.CONF.max_resources_per_stack:
            raise exception.RequestLimitExceeded(
                message=exception.StackResourceLimitExceeded.msg_fmt)

        if timeout_mins is None:
            timeout_mins = self.stack.timeout_mins

        # Note we disable rollback for nested stacks, since they
        # should be rolled back by the parent stack on failure
        stack = parser.Stack(self.context,
                             self.physical_resource_name(),
                             template,
                             self._nested_environment(user_params),
                             timeout_mins=timeout_mins,
                             disable_rollback=True,
                             parent_resource=self,
                             owner_id=self.stack.id)
        stack.parameters.set_stack_id(nested_stack.identifier())
        stack.validate()

        if not hasattr(type(self), 'attributes_schema'):
            self.attributes = None
            self._outputs_to_attribs(child_template)

        updater = scheduler.TaskRunner(nested_stack.update_task, stack)
        updater.start()
        return updater

    def check_update_complete(self, updater):
        if updater is None:
            return True

        if not updater.step():
            return False

        nested_stack = self.nested()
        if nested_stack.state != (nested_stack.UPDATE,
                                  nested_stack.COMPLETE):
            raise exception.Error(_("Nested stack UPDATE failed: %s") %
                                  nested_stack.status_reason)
        return True

    def delete_nested(self):
        '''
        Delete the nested stack.
        '''
        try:
            stack = self.nested()
        except exception.NotFound:
            logger.info(_("Stack not found to delete"))
        else:
            if stack is not None:
                delete_task = scheduler.TaskRunner(stack.delete)
                delete_task.start()
                return delete_task

    def check_delete_complete(self, delete_task):
        if delete_task is None:
            return True

        done = delete_task.step()
        if done:
            nested_stack = self.nested()
            if nested_stack.state != (nested_stack.DELETE,
                                      nested_stack.COMPLETE):
                raise exception.Error(nested_stack.status_reason)

        return done

    def handle_suspend(self):
        stack = self.nested()
        if stack is None:
            raise exception.Error(_('Cannot suspend %s, stack not created')
                                  % self.name)

        suspend_task = scheduler.TaskRunner(self._nested.stack_task,
                                            action=self._nested.SUSPEND,
                                            reverse=True)

        suspend_task.start(timeout=self._nested.timeout_secs())
        return suspend_task

    def check_suspend_complete(self, suspend_task):
        done = suspend_task.step()
        if done:
            if self._nested.state != (self._nested.SUSPEND,
                                      self._nested.COMPLETE):
                raise exception.Error(self._nested.status_reason)

        return done

    def handle_resume(self):
        stack = self.nested()
        if stack is None:
            raise exception.Error(_('Cannot resume %s, stack not created')
                                  % self.name)

        resume_task = scheduler.TaskRunner(self._nested.stack_task,
                                           action=self._nested.RESUME,
                                           reverse=False)

        resume_task.start(timeout=self._nested.timeout_secs())
        return resume_task

    def check_resume_complete(self, resume_task):
        done = resume_task.step()
        if done:
            if self._nested.state != (self._nested.RESUME,
                                      self._nested.COMPLETE):
                raise exception.Error(self._nested.status_reason)

        return done

    def set_deletion_policy(self, policy):
        self.nested().set_deletion_policy(policy)

    def get_abandon_data(self):
        return self.nested().get_abandon_data()

    def get_output(self, op):
        '''
        Return the specified Output value from the nested stack.

        If the output key does not exist, raise an InvalidTemplateAttribute
        exception.
        '''
        stack = self.nested()
        if stack is None:
            return None
        if op not in stack.outputs:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=op)
        return stack.output(op)

    def _resolve_attribute(self, name):
        return unicode(self.get_output(name))
