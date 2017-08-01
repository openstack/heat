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

import collections
import numbers
import re

from oslo_cache import core
from oslo_config import cfg
from oslo_log import log
from oslo_utils import reflection
from oslo_utils import strutils
import six

from heat.common import cache
from heat.common import exception
from heat.common.i18n import _
from heat.engine import resources

# decorator that allows to cache the value
# of the function based on input arguments
MEMOIZE = core.get_memoization_decorator(conf=cfg.CONF,
                                         region=cache.get_cache_region(),
                                         group="constraint_validation_cache")

LOG = log.getLogger(__name__)


class Schema(collections.Mapping):
    """Schema base class for validating properties or parameters.

    Schema objects are serializable to dictionaries following a superset of
    the HOT input Parameter schema using dict().

    Serialises to JSON in the form::

        {
            'type': 'list',
            'required': False
            'constraints': [
                {
                    'length': {'min': 1},
                    'description': 'List must not be empty'
                }
            ],
            'schema': {
                '*': {
                    'type': 'string'
                }
            },
            'description': 'An example list property.'
        }
    """

    KEYS = (
        TYPE, DESCRIPTION, DEFAULT, SCHEMA, REQUIRED, CONSTRAINTS,
        IMMUTABLE,
    ) = (
        'type', 'description', 'default', 'schema', 'required', 'constraints',
        'immutable',
    )

    # Keywords for data types; each Schema subclass can define its respective
    # type name used in templates
    TYPE_KEYS = (
        INTEGER_TYPE, STRING_TYPE, NUMBER_TYPE, BOOLEAN_TYPE, MAP_TYPE,
        LIST_TYPE,
    ) = (
        'INTEGER', 'STRING', 'NUMBER', 'BOOLEAN', 'MAP',
        'LIST',
    )

    # Default type names for data types used in templates; can be overridden by
    # subclasses
    TYPES = (
        INTEGER, STRING, NUMBER, BOOLEAN, MAP, LIST, ANY,
    ) = (
        'Integer', 'String', 'Number', 'Boolean', 'Map', 'List', 'Any',
    )

    def __init__(self, data_type, description=None,
                 default=None, schema=None,
                 required=False, constraints=None, label=None,
                 immutable=False):
        self._len = None
        self.label = label
        self.type = data_type
        if self.type not in self.TYPES:
            raise exception.InvalidSchemaError(
                message=_('Invalid type (%s)') % self.type)

        if required and default is not None:
            LOG.warning("Option 'required=True' should not be used with "
                        "any 'default' value (%s)", default)

        self.description = description
        self.required = required
        self.immutable = immutable

        if isinstance(schema, type(self)):
            if self.type != self.LIST:
                msg = _('Single schema valid only for '
                        '%(ltype)s, not %(utype)s') % dict(ltype=self.LIST,
                                                           utype=self.type)
                raise exception.InvalidSchemaError(message=msg)

            self.schema = AnyIndexDict(schema)
        else:
            self.schema = schema
        if self.schema is not None and self.type not in (self.LIST,
                                                         self.MAP):
            msg = _('Schema valid only for %(ltype)s or '
                    '%(mtype)s, not %(utype)s') % dict(ltype=self.LIST,
                                                       mtype=self.MAP,
                                                       utype=self.type)
            raise exception.InvalidSchemaError(message=msg)

        self.constraints = constraints or []
        self.default = default

    def validate(self, context=None):
        """Validates the schema.

        This method checks if the schema itself is valid, and if the
        default value - if present - complies to the schema's constraints.
        """
        for c in self.constraints:
            if not self._is_valid_constraint(c):
                err_msg = _('%(name)s constraint '
                            'invalid for %(utype)s') % dict(
                                name=type(c).__name__,
                                utype=self.type)
                raise exception.InvalidSchemaError(message=err_msg)

        self._validate_default(context)
        # validated nested schema(ta)
        if self.schema:
            if isinstance(self.schema, AnyIndexDict):
                self.schema.value.validate(context)
            else:
                for nested_schema in six.itervalues(self.schema):
                    nested_schema.validate(context)

    def _validate_default(self, context):
        if self.default is not None:
            try:
                self.validate_constraints(self.default, context,
                                          [CustomConstraint])
            except (ValueError, TypeError) as exc:
                raise exception.InvalidSchemaError(
                    message=_('Invalid default %(default)s (%(exc)s)') %
                    dict(default=self.default, exc=exc))

    def set_default(self, default=None):
        """Set the default value for this Schema object."""
        self.default = default

    def _is_valid_constraint(self, constraint):
        valid_types = getattr(constraint, 'valid_types', [])
        return any(self.type == getattr(self, t, None) for t in valid_types)

    @staticmethod
    def str_to_num(value):
        """Convert a string representation of a number into a numeric type."""
        if isinstance(value, numbers.Number):
            return value
        try:
            return int(value)
        except ValueError:
            return float(value)

    def to_schema_type(self, value):
        """Returns the value in the schema's data type."""
        try:
            # We have to be backwards-compatible for Integer and Number
            # Schema types and try to convert string representations of
            # number into "real" number types, therefore calling
            # str_to_num below.
            if self.type == self.INTEGER:
                num = Schema.str_to_num(value)
                if isinstance(num, float):
                    raise ValueError(_('%s is not an integer.') % num)
                return num
            elif self.type == self.NUMBER:
                return Schema.str_to_num(value)
            elif self.type == self.STRING:
                return six.text_type(value)
            elif self.type == self.BOOLEAN:
                return strutils.bool_from_string(str(value), strict=True)
        except ValueError:
            raise ValueError(_('Value "%(val)s" is invalid for data type '
                               '"%(type)s".')
                             % {'val': value, 'type': self.type})

        return value

    def validate_constraints(self, value, context=None, skipped=None):
        if not skipped:
            skipped = []

        try:
            for constraint in self.constraints:
                if type(constraint) not in skipped:
                    constraint.validate(value, self, context)
        except ValueError as ex:
            raise exception.StackValidationFailed(message=six.text_type(ex))

    def __getitem__(self, key):
        if key == self.TYPE:
            return self.type.lower()
        elif key == self.DESCRIPTION:
            if self.description is not None:
                return self.description
        elif key == self.DEFAULT:
            if self.default is not None:
                return self.default
        elif key == self.SCHEMA:
            if self.schema is not None:
                return dict((n, dict(s)) for n, s in self.schema.items())
        elif key == self.REQUIRED:
            return self.required
        elif key == self.CONSTRAINTS:
            if self.constraints:
                return [dict(c) for c in self.constraints]

        raise KeyError(key)

    def __iter__(self):
        for k in self.KEYS:
            try:
                self[k]
            except KeyError:
                pass
            else:
                yield k

    def __len__(self):
        if self._len is None:
            self._len = len(list(iter(self)))
        return self._len


class AnyIndexDict(collections.Mapping):
    """A Mapping that returns the same value for any integer index.

    Used for storing the schema for a list. When converted to a dictionary,
    it contains a single item with the key '*'.
    """

    ANYTHING = '*'

    def __init__(self, value):
        self.value = value

    def __getitem__(self, key):
        if key != self.ANYTHING and not isinstance(key, six.integer_types):
            raise KeyError(_('Invalid key %s') % str(key))

        return self.value

    def __iter__(self):
        yield self.ANYTHING

    def __len__(self):
        return 1


class Constraint(collections.Mapping):
    """Parent class for constraints on allowable values for a Property.

    Constraints are serializable to dictionaries following the HOT input
    Parameter constraints schema using dict().
    """

    (DESCRIPTION,) = ('description',)

    def __init__(self, description=None):
        self.description = description

    def __str__(self):
        def desc():
            if self.description:
                yield self.description
            yield self._str()

        return '\n'.join(desc())

    def validate(self, value, schema=None, context=None):
        if not self._is_valid(value, schema, context):
            if self.description:
                err_msg = self.description
            else:
                err_msg = self._err_msg(value)
            raise ValueError(err_msg)

    @classmethod
    def _name(cls):
        return '_'.join(w.lower() for w in re.findall('[A-Z]?[a-z]+',
                                                      cls.__name__))

    def __getitem__(self, key):
        if key == self.DESCRIPTION:
            if self.description is None:
                raise KeyError(key)
            return self.description

        if key == self._name():
            return self._constraint()

        raise KeyError(key)

    def __iter__(self):
        if self.description is not None:
            yield self.DESCRIPTION

        yield self._name()

    def __len__(self):
        return 2 if self.description is not None else 1


class Range(Constraint):
    """Constrain values within a range.

    Serializes to JSON as::

        {
            'range': {'min': <min>, 'max': <max>},
            'description': <description>
        }
    """

    (MIN, MAX) = ('min', 'max')

    valid_types = (Schema.INTEGER_TYPE, Schema.NUMBER_TYPE,)

    def __init__(self, min=None, max=None, description=None):
        super(Range, self).__init__(description)
        self.min = min
        self.max = max

        for param in (min, max):
            if not isinstance(param, (float, six.integer_types, type(None))):
                raise exception.InvalidSchemaError(
                    message=_('min/max must be numeric'))

        if min is max is None:
            raise exception.InvalidSchemaError(
                message=_('A range constraint must have a min value and/or '
                          'a max value specified.'))

    def _str(self):
        if self.max is None:
            fmt = _('The value must be at least %(min)s.')
        elif self.min is None:
            fmt = _('The value must be no greater than %(max)s.')
        else:
            fmt = _('The value must be in the range %(min)s to %(max)s.')
        return fmt % self._constraint()

    def _err_msg(self, value):
        return '%s is out of range (min: %s, max: %s)' % (value,
                                                          self.min,
                                                          self.max)

    def _is_valid(self, value, schema, context):
        value = Schema.str_to_num(value)

        if self.min is not None:
            if value < self.min:
                return False

        if self.max is not None:
            if value > self.max:
                return False

        return True

    def _constraint(self):
        def constraints():
            if self.min is not None:
                yield self.MIN, self.min
            if self.max is not None:
                yield self.MAX, self.max

        return dict(constraints())


class Length(Range):
    """Constrain the length of values within a range.

    Serializes to JSON as::

        {
            'length': {'min': <min>, 'max': <max>},
            'description': <description>
        }
    """

    valid_types = (Schema.STRING_TYPE, Schema.LIST_TYPE, Schema.MAP_TYPE,)

    def __init__(self, min=None, max=None, description=None):
        if min is max is None:
            raise exception.InvalidSchemaError(
                message=_('A length constraint must have a min value and/or '
                          'a max value specified.'))

        super(Length, self).__init__(min, max, description)

        for param in (min, max):
            if not isinstance(param, (six.integer_types, type(None))):
                msg = _('min/max length must be integral')
                raise exception.InvalidSchemaError(message=msg)

    def _str(self):
        if self.max is None:
            fmt = _('The length must be at least %(min)s.')
        elif self.min is None:
            fmt = _('The length must be no greater than %(max)s.')
        else:
            fmt = _('The length must be in the range %(min)s to %(max)s.')
        return fmt % self._constraint()

    def _err_msg(self, value):
        return 'length (%d) is out of range (min: %s, max: %s)' % (len(value),
                                                                   self.min,
                                                                   self.max)

    def _is_valid(self, value, schema, context):
        return super(Length, self)._is_valid(len(value), schema, context)


class Modulo(Constraint):
    """Constrain values to modulo.

    Serializes to JSON as::

        {
            'modulo': {'step': <step>, 'offset': <offset>},
            'description': <description>
        }
    """

    (STEP, OFFSET) = ('step', 'offset')

    valid_types = (Schema.INTEGER_TYPE, Schema.NUMBER_TYPE,)

    def __init__(self, step=None, offset=None, description=None):
        super(Modulo, self).__init__(description)
        self.step = step
        self.offset = offset

        if step is None or offset is None:
            raise exception.InvalidSchemaError(
                message=_('A modulo constraint must have a step value and '
                          'an offset value specified.'))

        for param in (step, offset):
            if not isinstance(param, (float, six.integer_types, type(None))):
                raise exception.InvalidSchemaError(
                    message=_('step/offset must be numeric'))

            if not int(param) == param:
                raise exception.InvalidSchemaError(
                    message=_('step/offset must be integer'))

        step, offset = int(step), int(offset)

        if step == 0:
            raise exception.InvalidSchemaError(message=_('step cannot be 0.'))

        if abs(offset) >= abs(step):
            raise exception.InvalidSchemaError(
                message=_('offset must be smaller (by absolute value) '
                          'than step.'))

        if step * offset < 0:
            raise exception.InvalidSchemaError(
                message=_('step and offset must be both positive or both '
                          'negative.'))

    def _str(self):
        if self.step is None or self.offset is None:
            fmt = _('The values must be specified.')
        else:
            fmt = _('The value must be a multiple of %(step)s '
                    'with an offset of %(offset)s.')
        return fmt % self._constraint()

    def _err_msg(self, value):
        return '%s is not a multiple of %s with an offset of %s)' % (
            value, self.step, self.offset)

    def _is_valid(self, value, schema, context):
        value = Schema.str_to_num(value)

        if value % self.step != self.offset:
            return False

        return True

    def _constraint(self):
        def constraints():
            if self.step is not None:
                yield self.STEP, self.step
            if self.offset is not None:
                yield self.OFFSET, self.offset

        return dict(constraints())


class AllowedValues(Constraint):
    """Constrain values to a predefined set.

    Serializes to JSON as::

        {
            'allowed_values': [<allowed1>, <allowed2>, ...],
            'description': <description>
        }
    """

    valid_types = (Schema.STRING_TYPE, Schema.INTEGER_TYPE, Schema.NUMBER_TYPE,
                   Schema.BOOLEAN_TYPE, Schema.LIST_TYPE,)

    def __init__(self, allowed, description=None):
        super(AllowedValues, self).__init__(description)
        if (not isinstance(allowed, collections.Sequence) or
                isinstance(allowed, six.string_types)):
            raise exception.InvalidSchemaError(
                message=_('AllowedValues must be a list'))
        self.allowed = tuple(allowed)

    def _str(self):
        allowed = ', '.join(str(a) for a in self.allowed)
        return _('Allowed values: %s') % allowed

    def _err_msg(self, value):
        allowed = '[%s]' % ', '.join(str(a) for a in self.allowed)
        return '"%s" is not an allowed value %s' % (value, allowed)

    def _is_valid(self, value, schema, context):
        # For list values, check if all elements of the list are contained
        # in allowed list.
        if isinstance(value, list):
            return all(v in self.allowed for v in value)

        if schema is not None:
            _allowed = tuple(schema.to_schema_type(v) for v in self.allowed)
            return schema.to_schema_type(value) in _allowed

        return value in self.allowed

    def _constraint(self):
        return list(self.allowed)


class AllowedPattern(Constraint):
    """Constrain values to a predefined regular expression pattern.

    Serializes to JSON as::

        {
            'allowed_pattern': <pattern>,
            'description': <description>
        }
    """

    valid_types = (Schema.STRING_TYPE,)

    def __init__(self, pattern, description=None):
        super(AllowedPattern, self).__init__(description)
        if not isinstance(pattern, six.string_types):
            raise exception.InvalidSchemaError(
                message=_('AllowedPattern must be a string'))
        self.pattern = pattern
        self.match = re.compile(pattern).match

    def _str(self):
        return _('Value must match pattern: %s') % self.pattern

    def _err_msg(self, value):
        return '"%s" does not match pattern "%s"' % (value, self.pattern)

    def _is_valid(self, value, schema, context):
        match = self.match(value)
        return match is not None and match.end() == len(value)

    def _constraint(self):
        return self.pattern


class CustomConstraint(Constraint):
    """A constraint delegating validation to an external class."""
    valid_types = (Schema.STRING_TYPE, Schema.INTEGER_TYPE, Schema.NUMBER_TYPE,
                   Schema.BOOLEAN_TYPE, Schema.LIST_TYPE)

    def __init__(self, name, description=None, environment=None):
        super(CustomConstraint, self).__init__(description)
        self.name = name
        self._environment = environment
        self._custom_constraint = None

    def _constraint(self):
        return self.name

    @property
    def custom_constraint(self):
        if self._custom_constraint is None:
            if self._environment is None:
                self._environment = resources.global_env()
            constraint_class = self._environment.get_constraint(self.name)
            if constraint_class:
                self._custom_constraint = constraint_class()
        return self._custom_constraint

    def _str(self):
        message = getattr(self.custom_constraint, "message", None)
        if not message:
            message = _('Value must be of type %s') % self.name
        return message

    def _err_msg(self, value):
        constraint = self.custom_constraint
        if constraint is None:
            return _('"%(value)s" does not validate %(name)s '
                     '(constraint not found)') % {
                         "value": value, "name": self.name}

        error = getattr(constraint, "error", None)
        if error:
            return error(value)
        return _('"%(value)s" does not validate %(name)s') % {
            "value": value, "name": self.name}

    def _is_valid(self, value, schema, context):
        constraint = self.custom_constraint
        if not constraint:
            return False
        return constraint.validate(value, context)


class BaseCustomConstraint(object):
    """A base class for validation using API clients.

    It will provide a better error message, and reduce a bit of duplication.
    Subclass must provide `expected_exceptions` and implement
    `validate_with_client`.
    """
    expected_exceptions = (exception.EntityNotFound,)
    resource_client_name = None
    resource_getter_name = None

    _error_message = None

    def error(self, value):
        if self._error_message is None:
            return _("Error validating value '%(value)s'") % {"value": value}
        return _("Error validating value '%(value)s': %(message)s") % {
            "value": value, "message": self._error_message}

    def validate(self, value, context):

        @MEMOIZE
        def check_cache_or_validate_value(cache_value_prefix,
                                          value_to_validate):
            """Check if validation result stored in cache or validate value.

            The function checks that value was validated and validation
            result stored in cache. If not then it executes validation and
            stores the result of validation in cache.
            If caching is disabled it requests for validation each time.

            :param cache_value_prefix: cache prefix that used to distinguish
                                       value in heat cache. So the cache key
                                       would be the following:
                                       cache_value_prefix + value_to_validate.
            :param value_to_validate: value that need to be validated
            :return: True if value is valid otherwise False
            """
            try:
                self.validate_with_client(context.clients, value_to_validate)
            except self.expected_exceptions as e:
                self._error_message = str(e)
                return False
            else:
                return True
        class_name = reflection.get_class_name(self, fully_qualified=False)
        cache_value_prefix = "{0}:{1}".format(class_name,
                                              six.text_type(context.tenant_id))
        validation_result = check_cache_or_validate_value(
            cache_value_prefix, value)
        # if validation failed we should not store it in cache
        # cause validation will be fixed soon (by admin or other guy)
        # and we don't need to require user wait for expiration time
        if not validation_result:
            check_cache_or_validate_value.invalidate(cache_value_prefix,
                                                     value)
        return validation_result

    def validate_with_client(self, client, resource_id):
        if self.resource_client_name and self.resource_getter_name:
            getattr(client.client_plugin(self.resource_client_name),
                    self.resource_getter_name)(resource_id)
        else:
            raise exception.InvalidSchemaError(
                message=_('Client name and resource getter name must be '
                          'specified.'))
