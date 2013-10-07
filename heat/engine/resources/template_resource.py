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

from heat.common import exception
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
        if tri.user_resource:
            self.allowed_schemes = ('http', 'https')
        else:
            self.allowed_schemes = ('http', 'https', 'file')

        # parse_nested can fail if the URL in the environment is bad
        # or otherwise inaccessible.  Suppress the error here so the
        # stack can be deleted, and detect it at validate/create time
        try:
            tmpl = template.Template(self.parsed_nested)
        except ValueError:
            tmpl = template.Template({})

        self.properties_schema = (properties.Properties
            .schema_from_params(tmpl.param_schemata()))
        self.attributes_schema = (attributes.Attributes
            .schema_from_outputs(tmpl[template.OUTPUTS]))

        super(TemplateResource, self).__init__(name, json_snippet, stack)

    def _to_parameters(self):
        '''
        :return: parameter values for our nested stack based on our properties
        '''
        params = {}
        for pname, pval in iter(self.properties.props.items()):
            if not pval.implemented():
                continue

            val = self.properties[pname]
            if val is not None:
                # take a list and create a CommaDelimitedList
                if pval.type() == properties.LIST:
                    if len(val) == 0:
                        params[pname] = ''
                    elif isinstance(val[0], dict):
                        flattened = []
                        for (count, item) in enumerate(val):
                            for (ik, iv) in iter(item.items()):
                                mem_str = '.member.%d.%s=%s' % (count, ik, iv)
                                flattened.append(mem_str)
                        params[pname] = ','.join(flattened)
                    else:
                        params[pname] = ','.join(val)
                else:
                    # for MAP, the JSON param takes either a collection or
                    # string, so just pass it on and let the param validate
                    # as appropriate
                    params[pname] = val

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
                t_data = urlfetch.get(self.template_name,
                                      allowed_schemes=self.allowed_schemes)
            except (exceptions.RequestException, IOError) as r_exc:
                raise ValueError("Could not fetch remote template '%s': %s" %
                                 (self.template_name, str(r_exc)))
            else:
                # TODO(Randall) Whoops, misunderstanding on my part; this
                # doesn't actually persist to the db like I thought.
                # Find a better way
                self.stack.t.files[self.template_name] = t_data
        return t_data

    def _validate_against_facade(self, facade_cls):
        facade_schemata = properties.schemata(facade_cls.properties_schema)

        for n, fs in facade_schemata.items():
            if fs.required and n not in self.properties_schema:
                msg = ("Required property %s for facade %s "
                       "missing in provider") % (n, self.type())
                raise exception.StackValidationFailed(message=msg)

            ps = self.properties_schema.get(n)
            if (n in self.properties_schema and
                    (fs.type != ps.type)):
                # Type mismatch
                msg = ("Property %s type mismatch between facade %s (%s) "
                       "and provider (%s)") % (n, self.type(),
                                               fs.type, ps.type)
                raise exception.StackValidationFailed(message=msg)

        for n, ps in self.properties_schema.items():
            if ps.required and n not in facade_schemata:
                # Required property for template not present in facade
                msg = ("Provider requires property %s "
                       "unknown in facade %s") % (n, self.type())
                raise exception.StackValidationFailed(message=msg)

        for attr in facade_cls.attributes_schema:
            if attr not in self.attributes_schema:
                msg = ("Attribute %s for facade %s "
                       "missing in provider") % (attr, self.type())
                raise exception.StackValidationFailed(message=msg)

    def validate(self):
        try:
            td = self.template_data
        except ValueError as ex:
            msg = _("Failed to retrieve template data: %s") % str(ex)
            raise exception.StackValidationFailed(message=msg)
        cri = self.stack.env.get_resource_info(
            self.type(),
            registry_type=environment.ClassResourceInfo)

        # If we're using an existing resource type as a facade for this
        # template, check for compatibility between the interfaces.
        if cri is not None and not isinstance(self, cri.get_class()):
            facade_cls = cri.get_class()
            self._validate_against_facade(facade_cls)

        return super(TemplateResource, self).validate()

    def handle_create(self):
        return self.create_with_template(self.parsed_nested,
                                         self._to_parameters())

    def handle_delete(self):
        return self.delete_nested()

    def FnGetRefId(self):
        if not self.nested():
            return unicode(self.name)
        return self.nested().identifier().arn()
