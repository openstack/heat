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

import urllib2
import json

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine import parser

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


(PROP_TEMPLATE_URL,
 PROP_TIMEOUT_MINS,
 PROP_PARAMETERS) = ('TemplateURL', 'TimeoutInMinutes', 'Parameters')


class Stack(resource.Resource):
    properties_schema = {PROP_TEMPLATE_URL: {'Type': 'String',
                                             'Required': True},
                         PROP_TIMEOUT_MINS: {'Type': 'Number'},
                         PROP_PARAMETERS: {'Type': 'Map'}}

    def __init__(self, name, json_snippet, stack):
        super(Stack, self).__init__(name, json_snippet, stack)
        self._nested = None

    def _params(self):
        p = self.stack.resolve_runtime_data(self.properties[PROP_PARAMETERS])
        return p

    def nested(self):
        if self._nested is None and self.resource_id is not None:
            self._nested = parser.Stack.load(self.context,
                                             self.resource_id)

            if self._nested is None:
                raise exception.NotFound('Nested stack not found in DB')

        return self._nested

    def create_with_template(self, child_template):
        '''
        Handle the creation of the nested stack from a given JSON template.
        '''
        template = parser.Template(child_template)
        params = parser.Parameters(self.physical_resource_name(), template,
                                   self._params())

        self._nested = parser.Stack(self.context,
                                    self.physical_resource_name(),
                                    template,
                                    params)

        nested_id = self._nested.store(self.stack)
        self.resource_id_set(nested_id)
        self._nested.create()
        if self._nested.state != self._nested.CREATE_COMPLETE:
            raise exception.Error(self._nested.state_description)

    def handle_create(self):
        response = urllib2.urlopen(self.properties[PROP_TEMPLATE_URL])
        template = template_format.parse(response)

        self.create_with_template(template)

    def handle_update(self):
        return self.UPDATE_REPLACE

    def handle_delete(self):
        try:
            stack = self.nested()
        except exception.NotFound:
            logger.info("Stack not found to delete")
        else:
            if stack is not None:
                stack.delete()

    def FnGetAtt(self, key):
        if not key.startswith('Outputs.'):
            raise exception.InvalidTemplateAttribute(
                        resource=self.physical_resource_name(), key=key)

        prefix, dot, op = key.partition('.')
        stack = self.nested()
        if stack is None:
            # This seems like a hack, to get past validation
            return ''
        if op not in stack.outputs:
            raise exception.InvalidTemplateAttribute(
                        resource=self.physical_resource_name(), key=key)

        return stack.output(op)


def resource_mapping():
    return {
        'AWS::CloudFormation::Stack': Stack,
    }
