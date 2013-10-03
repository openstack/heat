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
from heat.engine import template
from heat.engine import parameters
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging


logger = logging.getLogger(__name__)

SECTIONS = (VERSION, DESCRIPTION, PARAMETERS,
            RESOURCES, OUTPUTS, UNDEFINED) = \
           ('heat_template_version', 'description', 'parameters',
            'resources', 'outputs', '__undefined__')

PARAM_CONSTRAINTS = (CONSTRAINTS, DESCRIPTION, LENGTH, RANGE,
                     MIN, MAX, ALLOWED_VALUES, ALLOWED_PATTERN) = \
                    ('constraints', 'description', 'length', 'range',
                     'min', 'max', 'allowed_values', 'allowed_pattern')

_CFN_TO_HOT_SECTIONS = {template.VERSION: VERSION,
                        template.DESCRIPTION: DESCRIPTION,
                        template.PARAMETERS: PARAMETERS,
                        template.MAPPINGS: UNDEFINED,
                        template.RESOURCES: RESOURCES,
                        template.OUTPUTS: OUTPUTS}


def snake_to_camel(name):
    return ''.join([t.capitalize() for t in name.split('_')])


class HOTemplate(template.Template):
    """
    A Heat Orchestration Template format stack template.
    """

    def __getitem__(self, section):
        """"Get the relevant section in the template."""
        #first translate from CFN into HOT terminology if necessary
        section = HOTemplate._translate(section, _CFN_TO_HOT_SECTIONS, section)

        if section not in SECTIONS:
            raise KeyError(_('"%s" is not a valid template section') % section)

        if section == VERSION:
            return self.t[section]

        if section == UNDEFINED:
            return {}

        if section == DESCRIPTION:
            default = 'No description'
        else:
            default = {}

        the_section = self.t.get(section, default)

        # In some cases (e.g. parameters), also translate each entry of
        # a section into CFN format (case, naming, etc) so the rest of the
        # engine can cope with it.
        # This is a shortcut for now and might be changed in the future.

        if section == PARAMETERS:
            return self._translate_parameters(the_section)

        if section == RESOURCES:
            return self._translate_resources(the_section)

        if section == OUTPUTS:
            return self._translate_outputs(the_section)

        return the_section

    @staticmethod
    def _translate(value, mapping, default=None):
        if value in mapping:
            return mapping[value]

        return default

    def _translate_parameters(self, parameters):
        """Get the parameters of the template translated into CFN format."""
        params = {}
        for name, attrs in parameters.iteritems():
            param = {}
            for key, val in attrs.iteritems():
                # Do not translate 'constraints' since we want to handle this
                # specifically in HOT and not in common code.
                if key != CONSTRAINTS:
                    key = snake_to_camel(key)
                if key == 'Type':
                    val = snake_to_camel(val)
                elif key == 'Hidden':
                    key = 'NoEcho'
                param[key] = val
            if len(param) > 0:
                params[name] = param
        return params

    def _translate_resources(self, resources):
        """Get the resources of the template translated into CFN format."""
        HOT_TO_CFN_ATTRS = {'type': 'Type',
                            'properties': 'Properties'}

        cfn_resources = {}

        for resource_name, attrs in resources.iteritems():
            cfn_resource = {}

            for attr, attr_value in attrs.iteritems():
                cfn_attr = self._translate(attr, HOT_TO_CFN_ATTRS, attr)
                cfn_resource[cfn_attr] = attr_value

            cfn_resources[resource_name] = cfn_resource

        return cfn_resources

    def _translate_outputs(self, outputs):
        """Get the outputs of the template translated into CFN format."""
        HOT_TO_CFN_ATTRS = {'description': 'Description',
                            'value': 'Value'}

        cfn_outputs = {}

        for output_name, attrs in outputs.iteritems():
            cfn_output = {}

            for attr, attr_value in attrs.iteritems():
                cfn_attr = self._translate(attr, HOT_TO_CFN_ATTRS, attr)
                cfn_output[cfn_attr] = attr_value

            cfn_outputs[output_name] = cfn_output

        return cfn_outputs

    @staticmethod
    def resolve_param_refs(s, parameters):
        """
        Resolve constructs of the form { get_param: my_param }
        """
        def match_param_ref(key, value):
            return (key in ['get_param', 'Ref'] and
                    value is not None and
                    value in parameters)

        def handle_param_ref(ref):
            try:
                return parameters[ref]
            except (KeyError, ValueError):
                raise exception.UserParameterMissing(key=ref)

        return template._resolve(match_param_ref, handle_param_ref, s)

    @staticmethod
    def resolve_resource_refs(s, resources):
        '''
        Resolve constructs of the form { "get_resource" : "resource" }
        '''
        def match_resource_ref(key, value):
            return key in ['get_resource', 'Ref'] and value in resources

        def handle_resource_ref(arg):
            return resources[arg].FnGetRefId()

        return template._resolve(match_resource_ref, handle_resource_ref, s)

    @staticmethod
    def resolve_attributes(s, resources):
        """
        Resolve constructs of the form { get_attr: [my_resource, my_attr] }
        """
        def match_get_attr(key, value):
            return (key in ['get_attr', 'Fn::GetAtt'] and
                    isinstance(value, list) and
                    len(value) == 2 and
                    None not in value and
                    value[0] in resources)

        def handle_get_attr(args):
            resource, att = args
            try:
                r = resources[resource]
                if r.state in (
                        (r.CREATE, r.IN_PROGRESS),
                        (r.CREATE, r.COMPLETE),
                        (r.RESUME, r.IN_PROGRESS),
                        (r.RESUME, r.COMPLETE),
                        (r.UPDATE, r.IN_PROGRESS),
                        (r.UPDATE, r.COMPLETE)):
                    return r.FnGetAtt(att)
            except KeyError:
                raise exception.InvalidTemplateAttribute(resource=resource,
                                                         key=att)

        return template._resolve(match_get_attr, handle_get_attr, s)

    @staticmethod
    def resolve_replace(s):
        """
        Resolve template string substitution via function str_replace

        Resolves the str_replace function of the form

          str_replace:
            template: <string template>
            params:
              <param dictionary>
        """
        def handle_str_replace(args):
            if not (isinstance(args, dict) or isinstance(args, list)):
                raise TypeError(_('Arguments to "str_replace" must be a'
                                'dictionary or a list'))

            try:
                if isinstance(args, dict):
                    text = args.get('template')
                    params = args.get('params', {})
                elif isinstance(args, list):
                    params, text = args
                if text is None:
                    raise KeyError()
            except KeyError:
                example = ('''str_replace:
                  template: This is var1 template var2
                  params:
                    var1: a
                    var2: string''')
                raise KeyError(_('"str_replace" syntax should be %s') %
                               example)
            if not hasattr(text, 'replace'):
                raise TypeError(_('"template" parameter must be a string'))
            if not isinstance(params, dict):
                raise TypeError(
                    _('"params" parameter must be a dictionary'))
            for key in params.iterkeys():
                value = params.get(key, '') or ""
                text = text.replace(key, value)
            return text

        match_str_replace = lambda k, v: k in ['str_replace', 'Fn::Replace']
        return template._resolve(match_str_replace,
                                 handle_str_replace, s)

    def param_schemata(self):
        params = self[PARAMETERS].iteritems()
        return dict((name, HOTParamSchema(schema)) for name, schema in params)


class HOTParamSchema(parameters.ParamSchema):
    """HOT parameter schema."""

    def do_check(self, name, value, keys):
        # map ParamSchema constraint type to keys used in HOT constraints
        constraint_map = {
            parameters.ALLOWED_PATTERN: [ALLOWED_PATTERN],
            parameters.ALLOWED_VALUES: [ALLOWED_VALUES],
            parameters.MIN_LENGTH: [LENGTH, MIN],
            parameters.MAX_LENGTH: [LENGTH, MAX],
            parameters.MIN_VALUE: [RANGE, MIN],
            parameters.MAX_VALUE: [RANGE, MAX]
        }

        for const_type in keys:
            # get constraint type specific check function
            check = self.check(const_type)
            # get constraint type specific keys in HOT
            const_keys = constraint_map[const_type]

            for constraint in self.get(CONSTRAINTS, []):
                const_descr = constraint.get(DESCRIPTION)

                for const_key in const_keys:
                    if const_key not in constraint:
                        break
                    constraint = constraint[const_key]
                else:
                    check(name, value, constraint, const_descr)
