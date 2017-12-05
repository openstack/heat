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

import abc
import collections
import itertools

from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import strutils
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common import param_utils
from heat.engine import constraints as constr


PARAMETER_KEYS = (
    TYPE, DEFAULT, NO_ECHO, ALLOWED_VALUES, ALLOWED_PATTERN,
    MAX_LENGTH, MIN_LENGTH, MAX_VALUE, MIN_VALUE,
    DESCRIPTION, CONSTRAINT_DESCRIPTION, LABEL
) = (
    'Type', 'Default', 'NoEcho', 'AllowedValues', 'AllowedPattern',
    'MaxLength', 'MinLength', 'MaxValue', 'MinValue',
    'Description', 'ConstraintDescription', 'Label'
)


class Schema(constr.Schema):
    """Parameter schema."""

    KEYS = (
        TYPE, DESCRIPTION, DEFAULT, SCHEMA, CONSTRAINTS, HIDDEN,
        LABEL, IMMUTABLE, TAGS,
    ) = (
        'Type', 'Description', 'Default', 'Schema', 'Constraints', 'NoEcho',
        'Label', 'Immutable', 'Tags',
    )

    PARAMETER_KEYS = PARAMETER_KEYS

    # For Parameters the type name for Schema.LIST is CommaDelimitedList
    # and the type name for Schema.MAP is Json
    TYPES = (
        STRING, NUMBER, LIST, MAP, BOOLEAN,
    ) = (
        'String', 'Number', 'CommaDelimitedList', 'Json', 'Boolean',
    )

    def __init__(self, data_type, description=None, default=None, schema=None,
                 constraints=None, hidden=False, label=None, immutable=False,
                 tags=None):
        super(Schema, self).__init__(data_type=data_type,
                                     description=description,
                                     default=default,
                                     schema=schema,
                                     required=default is None,
                                     constraints=constraints,
                                     label=label,
                                     immutable=immutable)
        self.hidden = hidden
        self.tags = tags

    # Schema class validates default value for lists assuming list type. For
    # comma delimited list string supported in parameters Schema class, the
    # default value has to be parsed into a list if necessary so that
    # validation works.
    def _validate_default(self, context):
        if self.default is not None:
            default_value = self.default
            if self.type == self.LIST and not isinstance(self.default, list):
                try:
                    default_value = self.default.split(',')
                except (KeyError, AttributeError) as err:
                    raise exception.InvalidSchemaError(
                        message=_('Default must be a comma-delimited list '
                                  'string: %s') % err)
            elif self.type == self.LIST and isinstance(self.default, list):
                default_value = [(six.text_type(x))
                                 for x in self.default]
            try:
                self.validate_constraints(default_value, context,
                                          [constr.CustomConstraint])
            except (ValueError, TypeError,
                    exception.StackValidationFailed) as exc:
                raise exception.InvalidSchemaError(
                    message=_('Invalid default %(default)s (%(exc)s)') %
                    dict(default=self.default, exc=exc))

    def set_default(self, default=None):
        super(Schema, self).set_default(default)
        self.required = default is None

    @staticmethod
    def get_num(key, context):
        val = context.get(key)
        if val is not None:
            val = Schema.str_to_num(val)
        return val

    @staticmethod
    def _check_dict(schema_dict, allowed_keys, entity):
        if not isinstance(schema_dict, dict):
            raise exception.InvalidSchemaError(
                message=_("Invalid %s, expected a mapping") % entity)
        for key in schema_dict:
            if key not in allowed_keys:
                raise exception.InvalidSchemaError(
                    message=_("Invalid key '%(key)s' for %(entity)s") % {
                        "key": key, "entity": entity})

    @classmethod
    def _validate_dict(cls, param_name, schema_dict):
        cls._check_dict(schema_dict,
                        cls.PARAMETER_KEYS,
                        "parameter (%s)" % param_name)

        if cls.TYPE not in schema_dict:
            raise exception.InvalidSchemaError(
                message=_("Missing parameter type for parameter: %s") %
                param_name)

        if not isinstance(schema_dict.get(cls.TAGS, []), list):
            raise exception.InvalidSchemaError(
                message=_("Tags property should be a list for parameter: %s") %
                param_name)

    @classmethod
    def from_dict(cls, param_name, schema_dict):
        """Return a Parameter Schema object from a legacy schema dictionary.

        :param param_name: name of the parameter owning the schema; used
               for more verbose logging
        :type  param_name: str
        """
        cls._validate_dict(param_name, schema_dict)

        def constraints():
            desc = schema_dict.get(CONSTRAINT_DESCRIPTION)

            if MIN_VALUE in schema_dict or MAX_VALUE in schema_dict:
                yield constr.Range(Schema.get_num(MIN_VALUE, schema_dict),
                                   Schema.get_num(MAX_VALUE, schema_dict),
                                   desc)
            if MIN_LENGTH in schema_dict or MAX_LENGTH in schema_dict:
                yield constr.Length(Schema.get_num(MIN_LENGTH, schema_dict),
                                    Schema.get_num(MAX_LENGTH, schema_dict),
                                    desc)
            if ALLOWED_VALUES in schema_dict:
                yield constr.AllowedValues(schema_dict[ALLOWED_VALUES], desc)
            if ALLOWED_PATTERN in schema_dict:
                yield constr.AllowedPattern(schema_dict[ALLOWED_PATTERN], desc)

        # make update_allowed true by default on TemplateResources
        # as the template should deal with this.
        return cls(schema_dict[TYPE],
                   description=schema_dict.get(DESCRIPTION),
                   default=schema_dict.get(DEFAULT),
                   constraints=list(constraints()),
                   hidden=str(schema_dict.get(NO_ECHO,
                                              'false')).lower() == 'true',
                   label=schema_dict.get(LABEL))

    def validate_value(self, value, context=None):
        super(Schema, self).validate_constraints(value, context)

    def __getitem__(self, key):
        if key == self.TYPE:
            return self.type
        if key == self.HIDDEN:
            return self.hidden
        else:
            return super(Schema, self).__getitem__(key)


@six.python_2_unicode_compatible
class Parameter(object):
    """A template parameter."""

    def __new__(cls, name, schema, value=None):
        """Create a new Parameter of the appropriate type."""
        if cls is not Parameter:
            return super(Parameter, cls).__new__(cls)

        # Check for fully-fledged Schema objects
        if not isinstance(schema, Schema):
            schema = Schema.from_dict(name, schema)

        if schema.type == schema.STRING:
            ParamClass = StringParam
        elif schema.type == schema.NUMBER:
            ParamClass = NumberParam
        elif schema.type == schema.LIST:
            ParamClass = CommaDelimitedListParam
        elif schema.type == schema.MAP:
            ParamClass = JsonParam
        elif schema.type == schema.BOOLEAN:
            ParamClass = BooleanParam
        else:
            raise ValueError(_('Invalid Parameter type "%s"') % schema.type)

        return super(Parameter, cls).__new__(ParamClass)

    __slots__ = ('name', 'schema', 'user_value', 'user_default')

    def __init__(self, name, schema, value=None):
        """Initialise the parameter.

        Initialise the Parameter with a name, schema and optional user-supplied
        value.
        """
        self.name = name
        self.schema = schema
        self.user_value = value
        self.user_default = None

    def validate(self, validate_value=True, context=None):
        """Validates the parameter.

        This method validates if the parameter's schema is valid,
        and if the default value - if present - or the user-provided
        value for the parameter comply with the schema.
        """
        err_msg = _("Parameter '%(name)s' is invalid: %(exp)s")

        try:
            self.schema.validate(context)

            if not validate_value:
                return

            if self.user_value is not None:
                self._validate(self.user_value, context)
            elif self.has_default():
                self._validate(self.default(), context)
            else:
                raise exception.UserParameterMissing(key=self.name)
        except exception.StackValidationFailed as ex:
            msg = err_msg % dict(name=self.name, exp=six.text_type(ex))
            raise exception.StackValidationFailed(message=msg)
        except exception.InvalidSchemaError as ex:
            msg = err_msg % dict(name=self.name, exp=six.text_type(ex))
            raise exception.InvalidSchemaError(message=msg)

    def value(self):
        """Get the parameter value, optionally sanitising it for output."""
        if self.user_value is not None:
            return self.user_value

        if self.has_default():
            return self.default()

        raise exception.UserParameterMissing(key=self.name)

    def has_value(self):
        """Parameter has a user or default value."""
        return self.user_value is not None or self.has_default()

    def hidden(self):
        """Return whether the parameter is hidden.

        Hidden parameters should be sanitised in any output to the user.
        """
        return self.schema.hidden

    def description(self):
        """Return the description of the parameter."""
        return self.schema.description or ''

    def label(self):
        """Return the label or param name."""
        return self.schema.label or self.name

    def tags(self):
        """Return the tags associated with the parameter"""
        return self.schema.tags or []

    def has_default(self):
        """Return whether the parameter has a default value."""
        return (self.schema.default is not None or
                self.user_default is not None)

    def default(self):
        """Return the default value of the parameter."""
        if self.user_default is not None:
            return self.user_default
        return self.schema.default

    def set_default(self, value):
        self.user_default = value

    @classmethod
    def _value_as_text(cls, value):
        return six.text_type(value)

    def __str__(self):
        """Return a string representation of the parameter."""
        value = self.value()
        if self.hidden():
            return six.text_type('******')
        else:
            return self._value_as_text(value)


class NumberParam(Parameter):
    """A template parameter of type "Number"."""

    __slots__ = tuple()

    def __int__(self):
        """Return an integer representation of the parameter."""
        return int(super(NumberParam, self).value())

    def __float__(self):
        """Return a float representation of the parameter."""
        return float(super(NumberParam, self).value())

    def _validate(self, val, context):
        try:
            Schema.str_to_num(val)
        except (ValueError, TypeError) as ex:
            raise exception.StackValidationFailed(message=six.text_type(ex))
        self.schema.validate_value(val, context)

    def value(self):
        return Schema.str_to_num(super(NumberParam, self).value())


class BooleanParam(Parameter):
    """A template parameter of type "Boolean"."""

    __slots__ = tuple()

    def _validate(self, val, context):
        try:
            strutils.bool_from_string(val, strict=True)
        except ValueError as ex:
            raise exception.StackValidationFailed(message=six.text_type(ex))
        self.schema.validate_value(val, context)

    def value(self):
        if self.user_value is not None:
            raw_value = self.user_value
        else:
            raw_value = self.default()
        return strutils.bool_from_string(str(raw_value), strict=True)


class StringParam(Parameter):
    """A template parameter of type "String"."""

    __slots__ = tuple()

    def _validate(self, val, context):
        self.schema.validate_value(val, context=context)

    def value(self):
        return self.schema.to_schema_type(super(StringParam, self).value())


class ParsedParameter(Parameter):
    """A template parameter with cached parsed value."""

    __slots__ = ('parsed',)

    def __init__(self, name, schema, value=None):
        super(ParsedParameter, self).__init__(name, schema, value)
        self._update_parsed()

    def set_default(self, value):
        super(ParsedParameter, self).set_default(value)
        self._update_parsed()

    def _update_parsed(self):
        if self.has_value():
            if self.user_value is not None:
                self.parsed = self.parse(self.user_value)
            else:
                self.parsed = self.parse(self.default())


class CommaDelimitedListParam(ParsedParameter, collections.Sequence):
    """A template parameter of type "CommaDelimitedList"."""

    __slots__ = ('parsed',)

    def __init__(self, name, schema, value=None):
        self.parsed = []
        super(CommaDelimitedListParam, self).__init__(name, schema, value)

    def parse(self, value):
        # only parse when value is not already a list
        if isinstance(value, list):
            return [(six.text_type(x)) for x in value]
        try:
            return param_utils.delim_string_to_list(value)
        except (KeyError, AttributeError) as err:
            message = _('Value must be a comma-delimited list string: %s')
            raise ValueError(message % six.text_type(err))
        return value

    def value(self):
        if self.has_value():
            return self.parsed

        raise exception.UserParameterMissing(key=self.name)

    def __len__(self):
        """Return the length of the list."""
        return len(self.parsed)

    def __getitem__(self, index):
        """Return an item from the list."""
        return self.parsed[index]

    @classmethod
    def _value_as_text(cls, value):
        return ",".join(value)

    def _validate(self, val, context):
        try:
            parsed = self.parse(val)
        except ValueError as ex:
            raise exception.StackValidationFailed(message=six.text_type(ex))
        self.schema.validate_value(parsed, context)


class JsonParam(ParsedParameter):
    """A template parameter who's value is map or list."""

    __slots__ = ('parsed',)

    def __init__(self, name, schema, value=None):
        self.parsed = {}
        super(JsonParam, self).__init__(name, schema, value)

    def parse(self, value):
        try:
            val = value
            if not isinstance(val, six.string_types):
                # turn off oslo_serialization's clever to_primitive()
                val = jsonutils.dumps(val, default=None)
            if val:
                return jsonutils.loads(val)
        except (ValueError, TypeError) as err:
            message = _('Value must be valid JSON: %s') % err
            raise ValueError(message)
        return value

    def value(self):
        if self.has_value():
            return self.parsed

        raise exception.UserParameterMissing(key=self.name)

    def __getitem__(self, key):
        return self.parsed[key]

    def __iter__(self):
        return iter(self.parsed)

    def __len__(self):
        return len(self.parsed)

    @classmethod
    def _value_as_text(cls, value):
        return encodeutils.safe_decode(jsonutils.dumps(value))

    def _validate(self, val, context):
        try:
            parsed = self.parse(val)
        except ValueError as ex:
            raise exception.StackValidationFailed(message=six.text_type(ex))
        self.schema.validate_value(parsed, context)


@six.add_metaclass(abc.ABCMeta)
class Parameters(collections.Mapping):
    """Parameters of a stack.

    The parameters of a stack, with type checking, defaults, etc. specified by
    the stack's template.
    """

    def __init__(self, stack_identifier, tmpl, user_params=None,
                 param_defaults=None):
        """Initialisation of the parameter.

        Create the parameter container for a stack from the stack name and
        template, optionally setting the user-supplied parameter values.
        """
        user_params = user_params or {}
        param_defaults = param_defaults or {}

        def user_parameter(schema_item):
            name, schema = schema_item
            return Parameter(name, schema,
                             user_params.get(name))

        self.tmpl = tmpl
        self.user_params = user_params

        schemata = self.tmpl.param_schemata()
        user_parameters = (user_parameter(si) for si in
                           six.iteritems(schemata))
        pseudo_parameters = self._pseudo_parameters(stack_identifier)

        self.params = dict((p.name,
                            p) for p in itertools.chain(pseudo_parameters,
                                                        user_parameters))
        self.non_pseudo_param_keys = [p for p in self.params if p not in
                                      self.PSEUDO_PARAMETERS]

        for pd_name, param_default in param_defaults.items():
            if pd_name in self.params:
                self.params[pd_name].set_default(param_default)

    def validate(self, validate_value=True, context=None):
        """Validates all parameters.

        This method validates if all user-provided parameters are actually
        defined in the template, and if all parameters are valid.
        """
        self._validate_user_parameters()

        for param in six.itervalues(self.params):
            param.validate(validate_value, context)

    def __contains__(self, key):
        """Return whether the specified parameter exists."""
        return key in self.params

    def __iter__(self):
        """Return an iterator over the parameter names."""
        return iter(self.params)

    def __len__(self):
        """Return the number of parameters defined."""
        return len(self.params)

    def __getitem__(self, key):
        """Get a parameter value."""
        return self.params[key].value()

    def map(self, func, filter_func=lambda p: True):
        """Map the supplied function onto each Parameter.

        Map the supplied function onto each Parameter (with an optional filter
        function) and return the resulting dictionary.
        """
        return dict((n, func(p))
                    for n, p in six.iteritems(self.params) if filter_func(p))

    def set_stack_id(self, stack_identifier):
        """Set the StackId pseudo parameter value."""
        if stack_identifier is not None:
            self.params[self.PARAM_STACK_ID].schema.set_default(
                stack_identifier.arn())
            return True
        return False

    def _validate_user_parameters(self):
        schemata = self.tmpl.param_schemata()
        for param in self.user_params:
            if param not in schemata:
                raise exception.UnknownUserParameter(key=param)

    @abc.abstractmethod
    def _pseudo_parameters(self, stack_identifier):
        pass

    def immutable_params_modified(self, new_parameters, input_params):
        # A parameter must have been present in the old stack for its
        # immutability to be enforced
        common_params = list(set(new_parameters.non_pseudo_param_keys)
                             & set(self.non_pseudo_param_keys))
        invalid_params = []
        for param in common_params:
            old_value = self.params[param]
            if param in input_params:
                new_value = input_params[param]
            else:
                new_value = new_parameters[param]
            immutable = new_parameters.params[param].schema.immutable
            if immutable and old_value.value() != new_value:
                invalid_params.append(param)
        if invalid_params:
            return invalid_params
