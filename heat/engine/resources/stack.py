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
from heat.engine import stack_resource
from heat.common import template_format
from heat.common import urlfetch

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


(PROP_TEMPLATE_URL,
 PROP_TIMEOUT_MINS,
 PROP_PARAMETERS) = ('TemplateURL', 'TimeoutInMinutes', 'Parameters')


class NestedStack(stack_resource.StackResource):
    '''
    A Resource representing a child stack to allow composition of templates.
    '''

    properties_schema = {PROP_TEMPLATE_URL: {'Type': 'String',
                                             'Required': True},
                         PROP_TIMEOUT_MINS: {'Type': 'Number'},
                         PROP_PARAMETERS: {'Type': 'Map'}}

    def handle_create(self):
        template_data = urlfetch.get(self.properties[PROP_TEMPLATE_URL])
        template = template_format.parse(template_data)

        return self.create_with_template(template,
                                         self.properties[PROP_PARAMETERS],
                                         self.properties[PROP_TIMEOUT_MINS])

    def handle_delete(self):
        self.delete_nested()

    def FnGetRefId(self):
        return self.nested().identifier().arn()

    def FnGetAtt(self, key):
        if not key.startswith('Outputs.'):
            raise exception.InvalidTemplateAttribute(
                resource=self.name, key=key)

        prefix, dot, op = key.partition('.')
        return unicode(self.get_output(op))


def resource_mapping():
    return {
        'AWS::CloudFormation::Stack': NestedStack,
    }
