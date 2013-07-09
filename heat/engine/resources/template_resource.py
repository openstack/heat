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

from heat.engine import resource
from heat.engine import stack_resource
from heat.engine import properties
from heat.common import template_format

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class TemplateResource(stack_resource.StackResource):
    '''A Nested Stack Resource representing another Resource.'''
    def __init__(self, name, json_snippet, stack):
        self.template_name = stack.env.get_resource_type(json_snippet['Type'],
                                                         name)
        # on purpose don't pass in the environment so we get
        # the official/facade class to copy it's schema.
        cls_facade = resource.get_class(json_snippet['Type'])
        self.properties_schema = cls_facade.properties_schema
        self.attributes_schema = cls_facade.attributes_schema

        super(TemplateResource, self).__init__(name, json_snippet, stack)

    def _to_parameters(self):
        '''Convert CommaDelimitedList to List.'''
        params = {}
        for n, v in iter(self.properties.props.items()):
            if not v.implemented():
                continue
            elif v.type() == properties.LIST:
                # take a list and create a CommaDelimitedList
                val = self.properties[n]
                if val:
                    params[n] = ','.join(val)
            else:
                # for MAP, the JSON param takes either a collection or string,
                # so just pass it on and let the param validate as appropriate
                params[n] = self.properties[n]

        return params

    def handle_create(self):
        template_data = self.stack.t.files.get(self.template_name)
        template = template_format.parse(template_data)

        return self.create_with_template(template,
                                         self._to_parameters())

    def handle_delete(self):
        self.delete_nested()

    def FnGetRefId(self):
        return self.nested().identifier().arn()


resource.register_template_class(TemplateResource)
