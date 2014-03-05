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
from heat.engine import constraints as constr
from heat.engine import parameters

from heat.openstack.common import log as logging


logger = logging.getLogger(__name__)


PARAM_CONSTRAINTS = (
    CONSTRAINTS, DESCRIPTION, LENGTH, RANGE, MIN, MAX,
    ALLOWED_VALUES, ALLOWED_PATTERN, CUSTOM_CONSTRAINT,
) = (
    'constraints', 'description', 'length', 'range', 'min', 'max',
    'allowed_values', 'allowed_pattern', 'custom_constraint',
)


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
