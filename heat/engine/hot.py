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
from heat.engine import constraints as constr
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging


logger = logging.getLogger(__name__)

PARAM_CONSTRAINTS = (CONSTRAINTS, DESCRIPTION, LENGTH, RANGE,
                     MIN, MAX, ALLOWED_VALUES, ALLOWED_PATTERN) = \
                    ('constraints', 'description', 'length', 'range',
                     'min', 'max', 'allowed_values', 'allowed_pattern')


def snake_to_camel(name):
    return ''.join([t.capitalize() for t in name.split('_')])


class HOTemplate(template.Template):
    """
    A Heat Orchestration Template format stack template.
    """

    SECTIONS = (VERSION, DESCRIPTION, PARAMETER_GROUPS, PARAMETERS,
                RESOURCES, OUTPUTS, UNDEFINED) = \
               ('heat_template_version', 'description', 'parameter_groups',
                'parameters', 'resources', 'outputs', '__undefined__')

    SECTIONS_NO_DIRECT_ACCESS = set([PARAMETERS])

    _CFN_TO_HOT_SECTIONS = {template.Template.VERSION: VERSION,
                            template.Template.DESCRIPTION: DESCRIPTION,
                            template.Template.PARAMETERS: PARAMETERS,
                            template.Template.MAPPINGS: UNDEFINED,
                            template.Template.RESOURCES: RESOURCES,
                            template.Template.OUTPUTS: OUTPUTS}

    def __getitem__(self, section):
        """"Get the relevant section in the template."""
        #first translate from CFN into HOT terminology if necessary
        section = HOTemplate._translate(section,
                                        self._CFN_TO_HOT_SECTIONS, section)

        if section not in self.SECTIONS:
            raise KeyError(_('"%s" is not a valid template section') % section)
        if section in self.SECTIONS_NO_DIRECT_ACCESS:
            raise KeyError(
                _('Section %s can not be accessed directly.') % section)

        if section == self.VERSION:
            return self.t[section]

        if section == self.UNDEFINED:
            return {}

        if section == self.DESCRIPTION:
            default = 'No description'
        else:
            default = {}

        the_section = self.t.get(section, default)

        # In some cases (e.g. parameters), also translate each entry of
        # a section into CFN format (case, naming, etc) so the rest of the
        # engine can cope with it.
        # This is a shortcut for now and might be changed in the future.

        if section == self.RESOURCES:
            return self._translate_resources(the_section)

        if section == self.OUTPUTS:
            return self._translate_outputs(the_section)

        return the_section

    @staticmethod
    def _translate(value, mapping, default=None):
        if value in mapping:
            return mapping[value]

        return default

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
    def _resolve_ref(s, params, transform=None):
        """
        Resolve constructs of the form { Ref: my_param }
        """
        def match_param_ref(key, value):
            return (key == 'Ref' and
                    value is not None and
                    value in params)

        def handle_param_ref(ref):
            try:
                return params[ref]
            except (KeyError, ValueError):
                raise exception.UserParameterMissing(key=ref)

        return template._resolve(match_param_ref, handle_param_ref, s,
                                 transform)

    @staticmethod
    def _resolve_get_param(s, params, transform=None):
        """
        Resolve constructs of the form { get_param: my_param }
        """
        def match_param_ref(key, value):
            return (key == 'get_param' and
                    value is not None)

        def handle_param_ref(args):
            try:
                if not isinstance(args, list):
                    args = [args]

                parameter = params[args[0]]
                try:
                    for inner_param in args[1:]:
                        if hasattr(parameter, str(inner_param)):
                            parameter = getattr(parameter, inner_param)
                        else:
                            parameter = parameter[inner_param]
                    return parameter
                except (KeyError, IndexError, TypeError):
                    return ''
            except (KeyError, ValueError):
                raise exception.UserParameterMissing(key=args[0])

        return template._resolve(match_param_ref, handle_param_ref, s,
                                 transform)

    @staticmethod
    def resolve_param_refs(s, params, transform=None):
        resolved = HOTemplate._resolve_ref(s, params, transform)
        return HOTemplate._resolve_get_param(resolved, params, transform)

    @staticmethod
    def resolve_resource_refs(s, resources, transform=None):
        '''
        Resolve constructs of the form { "get_resource" : "resource" }
        '''
        def match_resource_ref(key, value):
            return key in ['get_resource', 'Ref'] and value in resources

        def handle_resource_ref(arg):
            return resources[arg].FnGetRefId()

        return template._resolve(match_resource_ref, handle_resource_ref, s,
                                 transform)

    @staticmethod
    def resolve_attributes(s, resources, transform=None):
        """
        Resolve constructs of the form { get_attr: [my_resource, my_attr] }
        """
        def match_get_attr(key, value):
            return (key in ['get_attr'] and
                    isinstance(value, list) and
                    len(value) >= 2 and
                    None not in value and
                    value[0] in resources)

        def handle_get_attr(args):
            resource = args[0]
            try:
                r = resources[resource]
                if r.state in (
                        (r.CREATE, r.IN_PROGRESS),
                        (r.CREATE, r.COMPLETE),
                        (r.RESUME, r.IN_PROGRESS),
                        (r.RESUME, r.COMPLETE),
                        (r.UPDATE, r.IN_PROGRESS),
                        (r.UPDATE, r.COMPLETE)):
                    rsrc_attr = args[1]
                    attr = r.FnGetAtt(rsrc_attr)
                    try:
                        for inner_attr in args[2:]:
                            if hasattr(attr, str(inner_attr)):
                                attr = getattr(attr, inner_attr)
                            else:
                                attr = attr[inner_attr]
                        return attr
                    except (KeyError, IndexError, TypeError):
                        return ''
            except (KeyError, IndexError):
                raise exception.InvalidTemplateAttribute(resource=resource,
                                                         key=rsrc_attr)

        return template._resolve(match_get_attr, handle_get_attr, s,
                                 transform)

    @staticmethod
    def resolve_replace(s, transform=None):
        """
        Resolve template string substitution via function str_replace

        Resolves the str_replace function of the form::

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
                text = text.replace(key, str(value))
            return text

        match_str_replace = lambda k, v: k in ['str_replace', 'Fn::Replace']
        return template._resolve(match_str_replace,
                                 handle_str_replace, s, transform)

    def resolve_get_file(self, s, transform=None):
        """
        Resolve file inclusion via function get_file. For any key provided
        the contents of the value in the template files dictionary
        will be substituted.

        Resolves the get_file function of the form::

          get_file:
            <string key>
        """

        def handle_get_file(args):
            if not (isinstance(args, basestring)):
                raise TypeError(
                    _('Argument to "get_file" must be a string'))
            f = self.files.get(args)
            if f is None:
                raise ValueError(_('No content found in the "files" section '
                                   'for get_file path: %s') % args)
            return f

        match_get_file = lambda k, v: k == 'get_file'
        return template._resolve(match_get_file,
                                 handle_get_file, s, transform)

    def param_schemata(self):
        params = self.t.get(self.PARAMETERS, {}).iteritems()
        return dict((name, HOTParamSchema.from_dict(schema))
                    for name, schema in params)

    def parameters(self, stack_identifier, user_params, validate_value=True):
        return HOTParameters(stack_identifier, self, user_params=user_params,
                             validate_value=validate_value)


class HOTParamSchema(parameters.Schema):
    """HOT parameter schema."""

    KEYS = (
        TYPE, DESCRIPTION, DEFAULT, SCHEMA, CONSTRAINTS,
        HIDDEN, LABEL
    ) = (
        'type', 'description', 'default', 'schema', 'constraints',
        'hidden', 'label'
    )

    # For Parameters the type name for Schema.LIST is comma_delimited_list
    # and the type name for Schema.MAP is json
    TYPES = (
        STRING, NUMBER, LIST, MAP,
    ) = (
        'string', 'number', 'comma_delimited_list', 'json',
    )

    @classmethod
    def from_dict(cls, schema_dict):
        """
        Return a Parameter Schema object from a legacy schema dictionary.
        """

        def constraints():
            constraints = schema_dict.get(CONSTRAINTS)
            if constraints is None:
                return

            for constraint in constraints:
                desc = constraint.get(DESCRIPTION)
                if RANGE in constraint:
                    cdef = constraint.get(RANGE)
                    yield constr.Range(parameters.Schema.get_num(MIN, cdef),
                                       parameters.Schema.get_num(MAX, cdef),
                                       desc)
                if LENGTH in constraint:
                    cdef = constraint.get(LENGTH)
                    yield constr.Length(parameters.Schema.get_num(MIN, cdef),
                                        parameters.Schema.get_num(MAX, cdef),
                                        desc)
                if ALLOWED_VALUES in constraint:
                    cdef = constraint.get(ALLOWED_VALUES)
                    yield constr.AllowedValues(cdef, desc)
                if ALLOWED_PATTERN in constraint:
                    cdef = constraint.get(ALLOWED_PATTERN)
                    yield constr.AllowedPattern(cdef, desc)

        # make update_allowed true by default on TemplateResources
        # as the template should deal with this.
        return cls(schema_dict[cls.TYPE],
                   description=schema_dict.get(HOTParamSchema.DESCRIPTION),
                   default=schema_dict.get(HOTParamSchema.DEFAULT),
                   constraints=list(constraints()),
                   hidden=schema_dict.get(HOTParamSchema.HIDDEN, False))


class HOTParameters(parameters.Parameters):
    PSEUDO_PARAMETERS = (
        PARAM_STACK_ID, PARAM_STACK_NAME, PARAM_REGION
    ) = (
        'OS::stack_id', 'OS::stack_name', 'OS::region'
    )

    def set_stack_id(self, stack_identifier):
        '''
        Set the StackId pseudo parameter value
        '''
        if stack_identifier is not None:
            self.params[self.PARAM_STACK_ID].schema.set_default(
                stack_identifier.stack_id)
        else:
            raise exception.InvalidStackIdentifier()

    def _pseudo_parameters(self, stack_identifier):
        stack_id = getattr(stack_identifier, 'stack_id', '')
        stack_name = getattr(stack_identifier, 'stack_name', '')

        yield parameters.Parameter(
            self.PARAM_STACK_ID,
            parameters.Schema(parameters.Schema.STRING, _('Stack ID'),
                              default=str(stack_id)))
        if stack_name:
            yield parameters.Parameter(
                self.PARAM_STACK_NAME,
                parameters.Schema(parameters.Schema.STRING, _('Stack Name'),
                                  default=stack_name))
