
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


def generate_class(name, template_name):
    try:
        data = urlfetch.get(template_name, allowed_schemes=('file',))
    except IOError:
        return TemplateResource
    tmpl = template.Template(template_format.parse(data))
    properties_schema = properties.Properties.schema_from_params(
        tmpl.param_schemata())
    attributes_schema = attributes.Attributes.schema_from_outputs(
        tmpl[tmpl.OUTPUTS])
    cls = type(name, (TemplateResource,),
               {"properties_schema": properties_schema,
                "attributes_schema": attributes_schema})
    return cls


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
        self.validation_exception = None
        self.update_allowed_keys = ('Properties', 'Metadata')

        tri = stack.env.get_resource_info(
            json_snippet['Type'],
            registry_type=environment.TemplateResourceInfo)
        if tri is None:
            self.validation_exception = ValueError(_(
                'Only Templates with an extension of .yaml or '
                '.template are supported'))
        else:
            self.template_name = tri.template_name
            if tri.user_resource:
                self.allowed_schemes = ('http', 'https')
            else:
                self.allowed_schemes = ('http', 'https', 'file')

        # run Resource.__init__() so we can call self.nested()
        self.properties_schema = {}
        self.attributes_schema = {}
        super(TemplateResource, self).__init__(name, json_snippet, stack)
        if self.validation_exception is None:
            self._generate_schema(self.t.get('Properties', {}))

    def _generate_schema(self, props):
        self._parsed_nested = None
        try:
            tmpl = template.Template(self.child_template())
        except ValueError as download_error:
            self.validation_exception = download_error
            tmpl = template.Template({})

        # re-generate the properties and attributes from the template.
        self.properties_schema = (properties.Properties
                                  .schema_from_params(tmpl.param_schemata()))
        self.attributes_schema = (attributes.Attributes
                                  .schema_from_outputs(tmpl[tmpl.OUTPUTS]))

        self.properties = properties.Properties(self.properties_schema,
                                                props,
                                                self._resolve_runtime_data,
                                                self.name,
                                                self.context)
        self.attributes = attributes.Attributes(self.name,
                                                self.attributes_schema,
                                                self._resolve_attribute)

    def child_params(self):
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
                if pval.type() == properties.Schema.LIST:
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

    def child_template(self):
        if not self._parsed_nested:
            self._parsed_nested = template_format.parse(self.template_data())
        return self._parsed_nested

    def implementation_signature(self):
        self._generate_schema(self.t.get('Properties', {}))
        schema_names = ([prop for prop in self.properties_schema] +
                        [at for at in self.attributes_schema])
        schema_hash = hashlib.sha1(';'.join(schema_names))
        templ_hash = hashlib.sha1(self.template_data())
        return (schema_hash.hexdigest(), templ_hash.hexdigest())

    def template_data(self):
        # we want to have the latest possible template.
        # 1. look in files
        # 2. try download
        # 3. look in the db
        reported_excp = None
        t_data = self.stack.t.files.get(self.template_name)
        if not t_data and self.template_name.endswith((".yaml", ".template")):
            try:
                t_data = urlfetch.get(self.template_name,
                                      allowed_schemes=self.allowed_schemes)
            except (exceptions.RequestException, IOError) as r_exc:
                reported_excp = ValueError(_("Could not fetch remote template "
                                             "'%(name)s': %(exc)s") % {
                                                 'name': self.template_name,
                                                 'exc': str(r_exc)})

        if t_data is None:
            if self.nested() is not None:
                t_data = json.dumps(self.nested().t.t)

        if t_data is not None:
            self.stack.t.files[self.template_name] = t_data
            return t_data
        if reported_excp is None:
            reported_excp = ValueError(_('Unknown error retrieving %s') %
                                       self.template_name)
        raise reported_excp

    def _validate_against_facade(self, facade_cls):
        facade_schemata = properties.schemata(facade_cls.properties_schema)

        for n, fs in facade_schemata.items():
            if fs.required and n not in self.properties_schema:
                msg = (_("Required property %(n)s for facade %(type)s "
                       "missing in provider") % {'n': n, 'type': self.type()})
                raise exception.StackValidationFailed(message=msg)

            ps = self.properties_schema.get(n)
            if (n in self.properties_schema and
                    (fs.type != ps.type)):
                # Type mismatch
                msg = (_("Property %(n)s type mismatch between facade %(type)s"
                       " (%(fs_type)s) and provider (%(ps_type)s)") % {
                           'n': n, 'type': self.type(),
                           'fs_type': fs.type, 'ps_type': ps.type})
                raise exception.StackValidationFailed(message=msg)

        for n, ps in self.properties_schema.items():
            if ps.required and n not in facade_schemata:
                # Required property for template not present in facade
                msg = (_("Provider requires property %(n)s "
                       "unknown in facade %(type)s") % {
                           'n': n, 'type': self.type()})
                raise exception.StackValidationFailed(message=msg)

        for attr in facade_cls.attributes_schema:
            if attr not in self.attributes_schema:
                msg = (_("Attribute %(attr)s for facade %(type)s "
                       "missing in provider") % {
                           'attr': attr, 'type': self.type()})
                raise exception.StackValidationFailed(message=msg)

    def validate(self):
        if self.validation_exception is not None:
            msg = str(self.validation_exception)
            raise exception.StackValidationFailed(message=msg)

        try:
            self.template_data()
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

    def handle_adopt(self, resource_data=None):
        return self.create_with_template(self.parsed_nested(),
                                         self._to_parameters(),
                                         adopt_data=resource_data)

    def handle_create(self):
        return self.create_with_template(self.child_template(),
                                         self.child_params())

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self._generate_schema(json_snippet.get('Properties', {}))
        return self.update_with_template(self.child_template(),
                                         self.child_params())

    def handle_delete(self):
        return self.delete_nested()

    def FnGetRefId(self):
        if not self.nested():
            return unicode(self.name)
        return self.nested().identifier().arn()
