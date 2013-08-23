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

from requests import exceptions

from heat.common import template_format
from heat.common import urlfetch
from heat.engine import attributes
from heat.engine import environment
from heat.engine import properties
from heat.engine import stack_resource
from heat.engine import template

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class TemplateResource(stack_resource.StackResource):
    '''
    A resource implemented by a nested stack.

    This implementation passes resource properties as parameters to the nested
    stack. Outputs of the nested stack are exposed as attributes of this
    resource.
    '''

    def __init__(self, name, json_snippet, stack):
        self._parsed_nested = None
        self.stack = stack
        tri = stack.env.get_resource_info(
            json_snippet['Type'],
            registry_type=environment.TemplateResourceInfo)
        self.template_name = tri.template_name

        cri = stack.env.get_resource_info(
            json_snippet['Type'],
            registry_type=environment.ClassResourceInfo)

        # if we're not overriding via the environment, mirror the template as
        # a new resource
        if cri is None or cri.get_class() == self.__class__:
            tmpl = template.Template(self.parsed_nested)
            self.properties_schema = (properties.Properties
                .schema_from_params(tmpl.param_schemata()))
            self.attributes_schema = (attributes.Attributes
                .schema_from_outputs(tmpl[template.OUTPUTS]))
        # otherwise we are overriding a resource type via the environment
        # and should mimic that type
        else:
            cls_facade = cri.get_class()
            self.properties_schema = cls_facade.properties_schema
            self.attributes_schema = cls_facade.attributes_schema

        super(TemplateResource, self).__init__(name, json_snippet, stack)

    def _to_parameters(self):
        '''
        :return: parameter values for our nested stack based on our properties
        '''
        params = {}
        for n, v in iter(self.properties.props.items()):
            if not v.implemented():
                continue

            val = self.properties[n]

            if val is not None:
                # take a list and create a CommaDelimitedList
                if v.type() == properties.LIST:
                    if isinstance(val[0], dict):
                        flattened = []
                        for (i, item) in enumerate(val):
                            for (k, v) in iter(item.items()):
                                mem_str = '.member.%d.%s=%s' % (i, k, v)
                                flattened.append(mem_str)
                        params[n] = ','.join(flattened)
                    else:
                        val = ','.join(val)

                # for MAP, the JSON param takes either a collection or string,
                # so just pass it on and let the param validate as appropriate

                params[n] = val

        return params

    @property
    def parsed_nested(self):
        if not self._parsed_nested:
            self._parsed_nested = template_format.parse(self.template_data)
        return self._parsed_nested

    @property
    def template_data(self):
        t_data = self.stack.t.files.get(self.template_name)
        if not t_data and self.template_name.endswith((".yaml", ".template")):
            try:
                t_data = urlfetch.get(self.template_name)
            except (exceptions.RequestException, IOError) as r_exc:
                raise ValueError("Could not fetch remote template '%s': %s" %
                                 (self.template_name, str(r_exc)))
            else:
                # TODO(Randall) Whoops, misunderstanding on my part; this
                # doesn't actually persist to the db like I thought.
                # Find a better way
                self.stack.t.files[self.template_name] = t_data
        return t_data

    def handle_create(self):
        return self.create_with_template(self.parsed_nested,
                                         self._to_parameters())

    def handle_delete(self):
        self.delete_nested()

    def FnGetRefId(self):
        if not self.nested():
            return unicode(self.name)
        return self.nested().identifier().arn()
