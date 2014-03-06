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
from heat.engine.cfn import template as cfn_template
from heat.engine import parameters
from heat.engine import constraints as constr
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging


logger = logging.getLogger(__name__)

PARAM_CONSTRAINTS = (
    CONSTRAINTS, DESCRIPTION, LENGTH, RANGE, MIN, MAX,
    ALLOWED_VALUES, ALLOWED_PATTERN, CUSTOM_CONSTRAINT,
) = (
    'constraints', 'description', 'length', 'range', 'min', 'max',
    'allowed_values', 'allowed_pattern', 'custom_constraint',
)


def snake_to_camel(name):
    return ''.join([t.capitalize() for t in name.split('_')])


class HOTemplate(template.Template):
    """
    A Heat Orchestration Template format stack template.
    """

    SECTIONS = (VERSION, DESCRIPTION, PARAMETER_GROUPS, PARAMETERS,
                RESOURCES, OUTPUTS, MAPPINGS) = \
               ('heat_template_version', 'description', 'parameter_groups',
                'parameters', 'resources', 'outputs', '__undefined__')

    SECTIONS_NO_DIRECT_ACCESS = set([PARAMETERS, VERSION])

    VERSIONS = ('2013-05-23',)

    _CFN_TO_HOT_SECTIONS = {cfn_template.CfnTemplate.VERSION: VERSION,
                            cfn_template.CfnTemplate.DESCRIPTION: DESCRIPTION,
                            cfn_template.CfnTemplate.PARAMETERS: PARAMETERS,
                            cfn_template.CfnTemplate.MAPPINGS: MAPPINGS,
                            cfn_template.CfnTemplate.RESOURCES: RESOURCES,
                            cfn_template.CfnTemplate.OUTPUTS: OUTPUTS}

    def __init__(self, template, *args, **kwargs):
        # All user templates are forced to include a version string. This is
        # just a convenient default for unit tests.
        version = template.get(self.VERSION, '2013-05-23')

        if version not in self.VERSIONS:
            msg = _('"%(version)s" is not a valid '
                    'heat_template_version. Should be one of: '
                    '%(valid)s')
            raise ValueError(msg % {'version': version,
                                    'valid': str(self.VERSIONS)})

        super(HOTemplate, self).__init__(template, *args, **kwargs)
        self.version = self.VERSION, version

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

        if section == self.MAPPINGS:
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

    def param_schemata(self):
        params = self.t.get(self.PARAMETERS, {}).iteritems()
        return dict((name, HOTParamSchema.from_dict(schema))
                    for name, schema in params)

    def parameters(self, stack_identifier, user_params, validate_value=True,
                   context=None):
        return HOTParameters(stack_identifier, self, user_params=user_params,
                             validate_value=validate_value, context=context)


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

    PARAMETER_KEYS = KEYS

    @classmethod
    def from_dict(cls, schema_dict):
        """
        Return a Parameter Schema object from a legacy schema dictionary.
        """
        cls._validate_dict(schema_dict)

        def constraints():
            constraints = schema_dict.get(CONSTRAINTS)
            if constraints is None:
                return

            if not isinstance(constraints, list):
                raise constr.InvalidSchemaError(
                    _("Invalid parameter constraints, expected a list"))

            valid_keys = (DESCRIPTION, LENGTH, RANGE, ALLOWED_VALUES,
                          ALLOWED_PATTERN, CUSTOM_CONSTRAINT)

            for constraint in constraints:
                cls._check_dict(constraint, valid_keys,
                                'parameter constraints')
                desc = constraint.get(DESCRIPTION)
                if RANGE in constraint:
                    cdef = constraint.get(RANGE)
                    cls._check_dict(cdef, (MIN, MAX), 'range constraint')
                    yield constr.Range(parameters.Schema.get_num(MIN, cdef),
                                       parameters.Schema.get_num(MAX, cdef),
                                       desc)
                elif LENGTH in constraint:
                    cdef = constraint.get(LENGTH)
                    cls._check_dict(cdef, (MIN, MAX), 'length constraint')
                    yield constr.Length(parameters.Schema.get_num(MIN, cdef),
                                        parameters.Schema.get_num(MAX, cdef),
                                        desc)
                elif ALLOWED_VALUES in constraint:
                    cdef = constraint.get(ALLOWED_VALUES)
                    yield constr.AllowedValues(cdef, desc)
                elif ALLOWED_PATTERN in constraint:
                    cdef = constraint.get(ALLOWED_PATTERN)
                    yield constr.AllowedPattern(cdef, desc)
                elif CUSTOM_CONSTRAINT in constraint:
                    cdef = constraint.get(CUSTOM_CONSTRAINT)
                    yield constr.CustomConstraint(cdef, desc)
                else:
                    raise constr.InvalidSchemaError(
                        _("No constraint expressed"))

        # make update_allowed true by default on TemplateResources
        # as the template should deal with this.
        return cls(schema_dict[cls.TYPE],
                   description=schema_dict.get(HOTParamSchema.DESCRIPTION),
                   default=schema_dict.get(HOTParamSchema.DEFAULT),
                   constraints=list(constraints()),
                   hidden=schema_dict.get(HOTParamSchema.HIDDEN, False),
                   label=schema_dict.get(HOTParamSchema.LABEL))


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
