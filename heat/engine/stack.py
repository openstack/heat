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
import logging

from heat.common import exception
from heat.engine.resources import Resource
from heat.db import api as db_api
from heat.engine import parser

logger = logging.getLogger(__file__)


(PROP_TEMPLATE_URL,
 PROP_TIMEOUT_MINS,
 PROP_PARAMETERS) = ('TemplateURL', 'TimeoutInMinutes', 'Parameters')


class Stack(Resource):
    properties_schema = {PROP_TEMPLATE_URL: {'Type': 'String',
                                             'Required': True},
                         PROP_TIMEOUT_MINS: {'Type': 'Number'},
                         PROP_PARAMETERS: {'Type': 'Map'}}

    def __init__(self, name, json_snippet, stack):
        Resource.__init__(self, name, json_snippet, stack)
        self._nested = None

    def _params(self):
        p = self.stack.resolve_runtime_data(self.properties[PROP_PARAMETERS])
        return p

    def nested(self):
        if self._nested is None:
            if self.instance_id is None:
                return None

            st = db_api.stack_get(self.stack.context, self.instance_id)
            if not st:
                raise exception.NotFound('Nested stack not found in DB')

            n = parser.Stack(self.stack.context, st.name,
                             st.raw_template.template,
                             self.instance_id, self._params())
            self._nested = n

        return self._nested

    def create_with_template(self, child_template):
        '''
        Handle the creation of the nested stack from a given JSON template.
        '''
        self._nested = parser.Stack(self.stack.context,
                                    self.name,
                                    child_template,
                                    parms=self._params(),
                                    metadata_server=self.stack.metadata_server)

        rt = {'template': child_template, 'stack_name': self.name}
        new_rt = db_api.raw_template_create(None, rt)

        parent_stack = db_api.stack_get(self.stack.context, self.stack.id)

        s = {'name': self.name,
             'owner_id': self.stack.id,
             'raw_template_id': new_rt.id,
             'user_creds_id': parent_stack.user_creds_id,
             'username': self.stack.context.username}
        new_s = db_api.stack_create(None, s)
        self._nested.id = new_s.id

        self._nested.create()
        self.instance_id_set(self._nested.id)

    def handle_create(self):
        response = urllib2.urlopen(self.properties[PROP_TEMPLATE_URL])
        template = json.load(response)

        self.create_with_template(template)

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
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        prefix, dot, op = key.partition('.')
        stack = self.nested()
        if stack is None:
            # This seems like a hack, to get past validation
            return ''
        if op not in self.nested().outputs:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        return stack.output(op)
