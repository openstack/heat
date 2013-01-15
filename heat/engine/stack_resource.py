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
from heat.engine import resource
from heat.engine import parser

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class StackResource(resource.Resource):
    '''
    An abstract Resource subclass that allows the management of an entire Stack
    as a resource in a parent stack.
    '''

    def __init__(self, name, json_snippet, stack):
        super(StackResource, self).__init__(name, json_snippet, stack)
        self._nested = None

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

    def create_with_template(self, child_template, user_params):
        '''
        Handle the creation of the nested stack from a given JSON template.
        '''
        template = parser.Template(child_template)
        params = parser.Parameters(self.physical_resource_name(), template,
                                   user_params)

        self._nested = parser.Stack(self.context,
                                    self.physical_resource_name(),
                                    template,
                                    params)

        nested_id = self._nested.store(self.stack)
        self.resource_id_set(nested_id)
        self._nested.create()
        if self._nested.state != self._nested.CREATE_COMPLETE:
            raise exception.Error(self._nested.state_description)

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

    def get_output(self, op):
        '''
        Return the specified Output value from the nested stack.

        If the output key does not exist, raise an InvalidTemplateAttribute
        exception.
        '''
        stack = self.nested()
        if not stack:
            return None
        if op not in stack.outputs:
            raise exception.InvalidTemplateAttribute(
                resource=self.physical_resource_name(), key=key)

        return stack.output(op)
