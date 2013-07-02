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

from heat.common import exception
from heat.engine import attributes
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class StackResource(resource.Resource):
    '''
    An abstract Resource subclass that allows the management of an entire Stack
    as a resource in a parent stack.
    '''

    def __init__(self, name, json_snippet, stack):
        super(StackResource, self).__init__(name, json_snippet, stack)
        self._outputs_to_attribs(json_snippet)
        self._nested = None

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
                                             self.resource_id)

            if self._nested is None:
                raise exception.NotFound('Nested stack not found in DB')

        return self._nested

    def create_with_template(self, child_template, user_params,
                             timeout_mins=None):
        '''
        Handle the creation of the nested stack from a given JSON template.
        '''
        template = parser.Template(child_template)
        self._outputs_to_attribs(child_template)

        # Note we disable rollback for nested stacks, since they
        # should be rolled back by the parent stack on failure
        self._nested = parser.Stack(self.context,
                                    self.physical_resource_name(),
                                    template,
                                    environment.Environment(user_params),
                                    timeout_mins=timeout_mins,
                                    disable_rollback=True)

        nested_id = self._nested.store(self.stack)
        self.resource_id_set(nested_id)

        stack_creator = scheduler.TaskRunner(self._nested.stack_task,
                                             action=self.CREATE)
        stack_creator.start(timeout=self._nested.timeout_secs())
        return stack_creator

    def check_create_complete(self, stack_creator):
        done = stack_creator.step()
        if done:
            if self._nested.state != (self._nested.CREATE,
                                      self._nested.COMPLETE):
                raise exception.Error(self._nested.status_reason)

        return done

    def delete_nested(self):
        '''
        Delete the nested stack.
        '''
        try:
            stack = self.nested()
        except exception.NotFound:
            logger.info("Stack not found to delete")
        else:
            if stack is not None:
                stack.delete()

    def handle_suspend(self):
        stack = self.nested()
        if stack is None:
            raise exception.Error(_('Cannot suspend %s, stack not created')
                                  % self.name)

        suspend_task = scheduler.TaskRunner(self._nested.stack_task,
                                            action=self.SUSPEND,
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
                                           action=self.RESUME,
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
            raise exception.InvalidTemplateAttribute(
                resource=self.name, key=op)

        return stack.output(op)

    def _resolve_attribute(self, name):
        if name.startswith('Outputs.'):
            name = name.partition('.')[-1]
        return unicode(self.get_output(name))
