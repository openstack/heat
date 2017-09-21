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
from heat.common.i18n import _
from heat.engine import constraints as constr
from heat.engine import parameters


PARAM_CONSTRAINTS = (
    DESCRIPTION, LENGTH, RANGE, MODULO, ALLOWED_VALUES, ALLOWED_PATTERN,
    CUSTOM_CONSTRAINT,
) = (
    'description', 'length', 'range', 'modulo', 'allowed_values',
    'allowed_pattern', 'custom_constraint',
)

RANGE_KEYS = (MIN, MAX) = ('min', 'max')

MODULO_KEYS = (STEP, OFFSET) = ('step', 'offset')


class HOTParamSchema(parameters.Schema):
    """HOT parameter schema."""

    KEYS = (
        TYPE, DESCRIPTION, DEFAULT, SCHEMA, CONSTRAINTS,
        HIDDEN, LABEL, IMMUTABLE
    ) = (
        'type', 'description', 'default', 'schema', 'constraints',
        'hidden', 'label', 'immutable'
    )

    # For Parameters the type name for Schema.LIST is comma_delimited_list
    # and the type name for Schema.MAP is json
    TYPES = (
        STRING, NUMBER, LIST, MAP, BOOLEAN,
    ) = (
        'string', 'number', 'comma_delimited_list', 'json', 'boolean',
    )

    PARAMETER_KEYS = KEYS

    @classmethod
    def _constraint_from_def(cls, constraint):
        desc = constraint.get(DESCRIPTION)
        if RANGE in constraint:
            cdef = constraint.get(RANGE)
            cls._check_dict(cdef, RANGE_KEYS, 'range constraint')
            return constr.Range(parameters.Schema.get_num(MIN, cdef),
                                parameters.Schema.get_num(MAX, cdef),
                                desc)
        elif LENGTH in constraint:
            cdef = constraint.get(LENGTH)
            cls._check_dict(cdef, RANGE_KEYS, 'length constraint')
            return constr.Length(parameters.Schema.get_num(MIN, cdef),
                                 parameters.Schema.get_num(MAX, cdef),
                                 desc)
        elif ALLOWED_VALUES in constraint:
            cdef = constraint.get(ALLOWED_VALUES)
            return constr.AllowedValues(cdef, desc)
        elif ALLOWED_PATTERN in constraint:
            cdef = constraint.get(ALLOWED_PATTERN)
            return constr.AllowedPattern(cdef, desc)
        elif CUSTOM_CONSTRAINT in constraint:
            cdef = constraint.get(CUSTOM_CONSTRAINT)
            return constr.CustomConstraint(cdef, desc)
        else:
            raise exception.InvalidSchemaError(
                message=_("No constraint expressed"))

    @classmethod
    def _constraints(cls, param_name, schema_dict):
        constraints = schema_dict.get(cls.CONSTRAINTS)
        if constraints is None:
            return

        if not isinstance(constraints, list):
            raise exception.InvalidSchemaError(
                message=_("Invalid parameter constraints for parameter "
                          "%s, expected a list") % param_name)

        for constraint in constraints:
            cls._check_dict(constraint, PARAM_CONSTRAINTS,
                            'parameter constraints')
            yield cls._constraint_from_def(constraint)

    @classmethod
    def from_dict(cls, param_name, schema_dict):
        """Return a Parameter Schema object from a legacy schema dictionary.

        :param param_name: name of the parameter owning the schema; used
               for more verbose logging
        :type  param_name: str
        """
        cls._validate_dict(param_name, schema_dict)

        # make update_allowed true by default on TemplateResources
        # as the template should deal with this.
        return cls(schema_dict[cls.TYPE],
                   description=schema_dict.get(HOTParamSchema.DESCRIPTION),
                   default=schema_dict.get(HOTParamSchema.DEFAULT),
                   constraints=list(cls._constraints(param_name, schema_dict)),
                   hidden=schema_dict.get(HOTParamSchema.HIDDEN, False),
                   label=schema_dict.get(HOTParamSchema.LABEL),
                   immutable=schema_dict.get(HOTParamSchema.IMMUTABLE, False))


class HOTParamSchema20170224(HOTParamSchema):
    @classmethod
    def _constraint_from_def(cls, constraint):
        desc = constraint.get(DESCRIPTION)

        if MODULO in constraint:
            cdef = constraint.get(MODULO)
            cls._check_dict(cdef, MODULO_KEYS, 'modulo constraint')
            return constr.Modulo(parameters.Schema.get_num(STEP, cdef),
                                 parameters.Schema.get_num(OFFSET, cdef),
                                 desc)
        else:
            return super(HOTParamSchema20170224, cls)._constraint_from_def(
                constraint)


class HOTParamSchema20180302(HOTParamSchema20170224):

    KEYS_20180302 = (TAGS,) = ('tags',)
    KEYS = HOTParamSchema20170224.KEYS + KEYS_20180302

    PARAMETER_KEYS = KEYS

    @classmethod
    def from_dict(cls, param_name, schema_dict):
        """Return a Parameter Schema object from a legacy schema dictionary.

        :param param_name: name of the parameter owning the schema; used
               for more verbose logging
        :type  param_name: str
        """
        cls._validate_dict(param_name, schema_dict)

        # make update_allowed true by default on TemplateResources
        # as the template should deal with this.
        return cls(schema_dict[cls.TYPE],
                   description=schema_dict.get(HOTParamSchema.DESCRIPTION),
                   default=schema_dict.get(HOTParamSchema.DEFAULT),
                   constraints=list(cls._constraints(param_name, schema_dict)),
                   hidden=schema_dict.get(HOTParamSchema.HIDDEN, False),
                   label=schema_dict.get(HOTParamSchema.LABEL),
                   immutable=schema_dict.get(HOTParamSchema.IMMUTABLE, False),
                   tags=schema_dict.get(HOTParamSchema20180302.TAGS))


class HOTParameters(parameters.Parameters):
    PSEUDO_PARAMETERS = (
        PARAM_STACK_ID, PARAM_STACK_NAME, PARAM_REGION, PARAM_PROJECT_ID
    ) = (
        'OS::stack_id', 'OS::stack_name', 'OS::region', 'OS::project_id'
    )

    def set_stack_id(self, stack_identifier):
        """Set the StackId pseudo parameter value."""
        if stack_identifier is not None:
            self.params[self.PARAM_STACK_ID].schema.set_default(
                stack_identifier.stack_id)
            return True
        return False

    def _pseudo_parameters(self, stack_identifier):
        stack_id = getattr(stack_identifier, 'stack_id', '')
        stack_name = getattr(stack_identifier, 'stack_name', '')
        tenant = getattr(stack_identifier, 'tenant', '')

        yield parameters.Parameter(
            self.PARAM_STACK_ID,
            parameters.Schema(parameters.Schema.STRING, _('Stack ID'),
                              default=str(stack_id)))
        yield parameters.Parameter(
            self.PARAM_PROJECT_ID,
            parameters.Schema(parameters.Schema.STRING, _('Project ID'),
                              default=str(tenant)))
        if stack_name:
            yield parameters.Parameter(
                self.PARAM_STACK_NAME,
                parameters.Schema(parameters.Schema.STRING, _('Stack Name'),
                                  default=stack_name))
