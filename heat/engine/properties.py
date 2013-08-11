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

import collections
import re

from heat.common import exception
from heat.engine import parameters

SCHEMA_KEYS = (
    REQUIRED, IMPLEMENTED, DEFAULT, TYPE, SCHEMA,
    ALLOWED_PATTERN, MIN_VALUE, MAX_VALUE, ALLOWED_VALUES,
    MIN_LENGTH, MAX_LENGTH,
) = (
    'Required', 'Implemented', 'Default', 'Type', 'Schema',
    'AllowedPattern', 'MinValue', 'MaxValue', 'AllowedValues',
    'MinLength', 'MaxLength',
)

SCHEMA_TYPES = (
    INTEGER,
    STRING, NUMBER, BOOLEAN,
    MAP, LIST
) = (
    'Integer',
    'String', 'Number', 'Boolean',
    'Map', 'List'
)


class InvalidPropertySchemaError(Exception):
    pass


class Schema(collections.Mapping):
    """
    A Schema for a resource Property.

    Schema objects are serialisable to dictionaries following a superset of
    the HOT input Parameter schema using dict().

    Serialises to JSON in the form:
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
    ) = (
        'type', 'description', 'default', 'schema', 'required', 'constraints',
    )

    def __init__(self, data_type, description=None,
                 default=None, schema=None,
                 required=False, constraints=[],
                 implemented=True):
        self._len = None
        self.type = data_type
        if self.type not in SCHEMA_TYPES:
            raise InvalidPropertySchemaError('Invalid type (%s)' % self.type)

        self.description = description
        self.required = required
        self.implemented = implemented

        if isinstance(schema, type(self)):
            if self.type != LIST:
                msg = 'Single schema valid only for %s, not %s' % (LIST,
                                                                   self.type)
                raise InvalidPropertySchemaError(msg)

            self.schema = AnyIndexDict(schema)
        else:
            self.schema = schema
        if self.schema is not None and self.type not in (LIST, MAP):
            msg = 'Schema valid only for %s or %s, not %s' % (LIST, MAP,
                                                              self.type)
            raise InvalidPropertySchemaError(msg)

        self.constraints = constraints
        for c in constraints:
            if self.type not in c.valid_types:
                err_msg = '%s constraint invalid for %s' % (type(c).__name__,
                                                            self.type)
                raise InvalidPropertySchemaError(err_msg)

        self.default = default

    @classmethod
    def from_legacy(cls, schema_dict):
        """
        Return a new Schema object from a legacy schema dictionary.
        """

        # Check for fully-fledged Schema objects
        if isinstance(schema_dict, cls):
            return schema_dict

        unknown = [k for k in schema_dict if k not in SCHEMA_KEYS]
        if unknown:
            raise InvalidPropertySchemaError('Unknown key(s) %s' % unknown)

        def constraints():
            def get_num(key):
                val = schema_dict.get(key)
                if val is not None:
                    val = Property.str_to_num(val)
                return val

            if MIN_VALUE in schema_dict or MAX_VALUE in schema_dict:
                yield Range(get_num(MIN_VALUE),
                            get_num(MAX_VALUE))
            if MIN_LENGTH in schema_dict or MAX_LENGTH in schema_dict:
                yield Length(get_num(MIN_LENGTH),
                             get_num(MAX_LENGTH))
            if ALLOWED_VALUES in schema_dict:
                yield AllowedValues(schema_dict[ALLOWED_VALUES])
            if ALLOWED_PATTERN in schema_dict:
                yield AllowedPattern(schema_dict[ALLOWED_PATTERN])

        try:
            data_type = schema_dict[TYPE]
        except KeyError:
            raise InvalidPropertySchemaError('No %s specified' % TYPE)

        if SCHEMA in schema_dict:
            if data_type == LIST:
                ss = cls.from_legacy(schema_dict[SCHEMA])
            elif data_type == MAP:
                schema_dicts = schema_dict[SCHEMA].items()
                ss = dict((n, cls.from_legacy(sd)) for n, sd in schema_dicts)
            else:
                raise InvalidPropertySchemaError('%s supplied for %s %s' %
                                                 (SCHEMA, TYPE, data_type))
        else:
            ss = None

        return cls(data_type,
                   default=schema_dict.get(DEFAULT),
                   schema=ss,
                   required=schema_dict.get(REQUIRED, False),
                   constraints=list(constraints()),
                   implemented=schema_dict.get(IMPLEMENTED, True))

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
    """
    A Mapping that returns the same value for any integer index.

    Used for storing the schema for a list. When converted to a dictionary,
    it contains a single item with the key '*'.
    """

    ANYTHING = '*'

    def __init__(self, value):
        self.value = value

    def __getitem__(self, key):
        if key != self.ANYTHING and not isinstance(key, (int, long)):
            raise KeyError('Invalid key %s' % str(key))

        return self.value

    def __iter__(self):
        yield self.ANYTHING

    def __len__(self):
        return 1


class Constraint(collections.Mapping):
    """
    Parent class for constraints on allowable values for a Property.

    Constraints are serialisable to dictionaries following the HOT input
    Parameter constraints schema using dict().
    """

    (DESCRIPTION,) = ('description',)

    def __init__(self, description=None):
        self.description = description

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
    """
    Constrain values within a range.

    Serialises to JSON as:

        {
            'range': {'min': <min>, 'max': <max>},
            'description': <description>
        }
    """

    (MIN, MAX) = ('min', 'max')

    valid_types = (INTEGER, NUMBER)

    def __init__(self, min=None, max=None, description=None):
        super(Range, self).__init__(description)
        self.min = min
        self.max = max

        for param in (min, max):
            if not isinstance(param, (float, int, long, type(None))):
                raise InvalidPropertySchemaError('min/max must be numeric')

    def _constraint(self):
        def constraints():
            if self.min is not None:
                yield self.MIN, self.min
            if self.max is not None:
                yield self.MAX, self.max

        return dict(constraints())


class Length(Range):
    """
    Constrain the length of values within a range.

    Serialises to JSON as:

        {
            'length': {'min': <min>, 'max': <max>},
            'description': <description>
        }
    """

    valid_types = (STRING, LIST)

    def __init__(self, min=None, max=None, description=None):
        super(Length, self).__init__(min, max, description)

        for param in (min, max):
            if not isinstance(param, (int, long, type(None))):
                msg = 'min/max length must be integral'
                raise InvalidPropertySchemaError(msg)


class AllowedValues(Constraint):
    """
    Constrain values to a predefined set.

    Serialises to JSON as:

        {
            'allowed_values': [<allowed1>, <allowed2>, ...],
            'description': <description>
        }
    """

    valid_types = (STRING, INTEGER, NUMBER, BOOLEAN)

    def __init__(self, allowed, description=None):
        super(AllowedValues, self).__init__(description)
        if (not isinstance(allowed, collections.Sequence) or
                isinstance(allowed, basestring)):
            raise InvalidPropertySchemaError('AllowedValues must be a list')
        self.allowed = tuple(allowed)

    def _constraint(self):
        return list(self.allowed)


class AllowedPattern(Constraint):
    """
    Constrain values to a predefined regular expression pattern.

    Serialises to JSON as:

        {
            'allowed_pattern': <pattern>,
            'description': <description>
        }
    """

    valid_types = (STRING,)

    def __init__(self, pattern, description=None):
        super(AllowedPattern, self).__init__(description)
        self.pattern = pattern

    def _constraint(self):
        return self.pattern


class Property(object):

    __param_type_map = {
        parameters.STRING: STRING,
        parameters.NUMBER: NUMBER,
        parameters.COMMA_DELIMITED_LIST: LIST,
        parameters.JSON: MAP
    }

    def __init__(self, schema, name=None):
        self.schema = schema
        self.name = name

        for key in self.schema:
            assert key in SCHEMA_KEYS, 'Unknown schema key "%s"' % key

        assert self.type() in SCHEMA_TYPES,\
            'Unknown property type "%s"' % self.type()

    def required(self):
        return self.schema.get(REQUIRED, False)

    def implemented(self):
        return self.schema.get(IMPLEMENTED, True)

    def has_default(self):
        return DEFAULT in self.schema

    def default(self):
        return self.schema[DEFAULT]

    def type(self):
        return self.schema[TYPE]

    def _check_allowed(self, value):
        if ALLOWED_VALUES in self.schema:
            allowed = list(self.schema[ALLOWED_VALUES])
            if value not in allowed:
                raise ValueError('"%s" is not an allowed value %s' %
                                 (value, str(allowed)))

    @staticmethod
    def str_to_num(value):
        try:
            return int(value)
        except ValueError:
            return float(value)

    @staticmethod
    def schema_from_param(param):
        """
        Convert the param specification to a property schema definition

        :param param: parameter definition
        :return: a property schema definition for param
        """
        if parameters.TYPE not in param:
            raise ValueError("Parameter does not define a type for conversion")
        ret = {
            TYPE: Property.__param_type_map.get(param.get(parameters.TYPE))
        }
        if parameters.DEFAULT in param:
            ret.update({DEFAULT: param[parameters.DEFAULT]})
        else:
            ret.update({REQUIRED: "true"})
        if parameters.ALLOWED_VALUES in param:
            ret.update({ALLOWED_VALUES: param[parameters.ALLOWED_VALUES]})
        if parameters.ALLOWED_PATTERN in param:
            ret.update({ALLOWED_PATTERN: param[parameters.ALLOWED_PATTERN]})
        if parameters.MAX_LENGTH in param:
            ret.update({MAX_LENGTH: param[parameters.MAX_LENGTH]})
        if parameters.MIN_LENGTH in param:
            ret.update({MIN_LENGTH: param[parameters.MIN_LENGTH]})
        if parameters.MAX_VALUE in param:
            ret.update({MAX_VALUE: param[parameters.MAX_VALUE]})
        if parameters.MIN_VALUE in param:
            ret.update({MIN_VALUE: param[parameters.MIN_VALUE]})
        return ret

    def _validate_integer(self, value):
        if value is None:
            value = self.has_default() and self.default() or 0
        if not isinstance(value, int):
            raise TypeError('value is not an integer')
        return self._validate_number(value)

    def _validate_number(self, value):
        if value is None:
            value = self.has_default() and self.default() or 0
        self._check_allowed(value)

        num = self.str_to_num(value)

        minn = self.str_to_num(self.schema.get(MIN_VALUE, value))
        maxn = self.str_to_num(self.schema.get(MAX_VALUE, value))

        if num > maxn or num < minn:
            format = '%d' if isinstance(num, int) else '%f'
            raise ValueError('%s is out of range' % (format % num))
        return value

    def _validate_string(self, value):
        if value is None:
            value = self.has_default() and self.default() or ''
        if not isinstance(value, basestring):
            raise ValueError('Value must be a string')

        self._check_allowed(value)

        if ALLOWED_PATTERN in self.schema:
            pattern = self.schema[ALLOWED_PATTERN]
            match = re.match(pattern, value)
            if match is None or match.end() != len(value):
                raise ValueError('"%s" does not match pattern "%s"' %
                                 (value, pattern))

        self._validate_min_max_length(value, STRING)
        return value

    def _validate_min_max_length(self, value, value_type):
        if MIN_LENGTH in self.schema:
            min_length = int(self.schema[MIN_LENGTH])
            if len(value) < min_length:
                raise ValueError('Minimum %s length is %d' %
                                 (value_type, min_length))

        if MAX_LENGTH in self.schema:
            max_length = int(self.schema[MAX_LENGTH])
            if len(value) > max_length:
                raise ValueError('Maximum %s length is %d' %
                                 (value_type, max_length))

    def _validate_map(self, value):
        if value is None:
            value = self.has_default() and self.default() or {}
        if not isinstance(value, collections.Mapping):
            raise TypeError('"%s" is not a map' % value)

        if SCHEMA in self.schema:
            children = dict(Properties(self.schema[SCHEMA], value,
                                       parent_name=self.name))
        else:
            children = value

        self._validate_min_max_length(value, MAP)
        return children

    def _validate_list(self, value):
        if value is None:
            value = self.has_default() and self.default() or []
        if (not isinstance(value, collections.Sequence) or
                isinstance(value, basestring)):
            raise TypeError('"%s" is not a list' % repr(value))

        for v in value:
            self._check_allowed(v)

        if SCHEMA in self.schema:
            prop = Property(self.schema[SCHEMA])
            children = [prop.validate_data(d) for d in value]
        else:
            children = value

        self._validate_min_max_length(value, LIST)
        return children

    def _validate_bool(self, value):
        if value is None:
            value = self.has_default() and self.default() or False
        if isinstance(value, bool):
            return value
        normalised = value.lower()
        if normalised not in ['true', 'false']:
            raise ValueError('"%s" is not a valid boolean')

        return normalised == 'true'

    def validate_data(self, value):
        t = self.type()
        if t == STRING:
            return self._validate_string(value)
        elif t == INTEGER:
            return self._validate_integer(value)
        elif t == NUMBER:
            return self._validate_number(value)
        elif t == MAP:
            return self._validate_map(value)
        elif t == LIST:
            return self._validate_list(value)
        elif t == BOOLEAN:
            return self._validate_bool(value)


class Properties(collections.Mapping):

    def __init__(self, schema, data, resolver=lambda d: d, parent_name=None):
        self.props = dict((k, Property(s, k)) for k, s in schema.items())
        self.resolve = resolver
        self.data = data
        if parent_name is None:
            self.error_prefix = ''
        else:
            self.error_prefix = parent_name + ': '

    @staticmethod
    def schema_from_params(params_snippet):
        """
        Convert a template snippet that defines parameters
        into a properties schema

        :param params_snippet: parameter definition from a template
        :returns: an equivalent properties schema for the specified params
        """
        if params_snippet:
            return dict((k, Property.schema_from_param(v)) for k, v
                        in params_snippet.items())
        return {}

    def validate(self, with_value=True):
        for (key, prop) in self.props.items():
            if with_value:
                try:
                    self[key]
                except ValueError as e:
                    msg = "Property error : %s" % str(e)
                    raise exception.StackValidationFailed(message=msg)

            # are there unimplemented Properties
            if not prop.implemented() and key in self.data:
                msg = "Property %s not implemented yet" % key
                raise exception.StackValidationFailed(message=msg)

        for key in self.data:
            if key not in self.props:
                msg = "Unknown Property %s" % key
                raise exception.StackValidationFailed(message=msg)

    def __getitem__(self, key):
        if key not in self:
            raise KeyError(self.error_prefix + 'Invalid Property %s' % key)

        prop = self.props[key]

        if key in self.data:
            value = self.resolve(self.data[key])
            try:
                return prop.validate_data(value)
            except ValueError as e:
                raise ValueError(self.error_prefix + '%s %s' % (key, str(e)))
        elif prop.has_default():
            return prop.default()
        elif prop.required():
            raise ValueError(self.error_prefix +
                             'Property %s not assigned' % key)

    def __len__(self):
        return len(self.props)

    def __contains__(self, key):
        return key in self.props

    def __iter__(self):
        return iter(self.props)

    @staticmethod
    def _generate_input(schema, params=None, path=None):
        '''Generate an input based on a path in the schema or property
        defaults.

        :param schema: The schema to generate a parameter or value for.
        :param params: A dict to map a schema to a parameter path.
        :param path: Required if params != None. The params key
            to save the schema at.
        :returns: A Ref to the parameter if path != None and params != None
        :returns: The property default if params == None or path == None
        '''
        if schema.get('Implemented') is False:
            return

        if schema[TYPE] == LIST:
            params[path] = {parameters.TYPE: parameters.COMMA_DELIMITED_LIST}
            return {'Fn::Split': {'Ref': path}}

        elif schema[TYPE] == MAP:
            params[path] = {parameters.TYPE: parameters.JSON}
            return {'Ref': path}

        elif params is not None and path is not None:
            for prop in schema.keys():
                if prop not in parameters.PARAMETER_KEYS and prop in schema:
                    del schema[prop]
            params[path] = schema
            return {'Ref': path}
        else:
            prop = Property(schema)
            return prop.has_default() and prop.default() or None

    @staticmethod
    def _schema_to_params_and_props(schema, params=None):
        '''Generates a default template based on the provided schema.

        ex: input: schema = {'foo': {'Type': 'String'}}, params = {}
            output: {'foo': {'Ref': 'foo'}},
                params = {'foo': {'Type': 'String'}}

        ex: input: schema = {'foo' :{'Type': 'List'}, 'bar': {'Type': 'Map'}}
                    ,params={}
            output: {'foo': {'Fn::Split': {'Ref': 'foo'}},
                     'bar': {'Ref': 'bar'}},
                params = {'foo' : {parameters.TYPE:
                          parameters.COMMA_DELIMITED_LIST},
                          'bar': {parameters.TYPE: parameters.JSON}}

        :param schema: The schema to generate a parameter or value for.
        :param params: A dict to map a schema to a parameter path.
        :returns: A dict of properties resolved for a template's schema
        '''
        properties = {}
        for prop, nested_schema in schema.iteritems():
            properties[prop] = Properties._generate_input(nested_schema,
                                                          params,
                                                          prop)
            #remove not implemented properties
            if properties[prop] is None:
                del properties[prop]
        return properties

    @staticmethod
    def schema_to_parameters_and_properties(schema):
        '''Generates properties with params resolved for a resource's
        properties_schema.
        :param schema: A resource's properties_schema
        :param explode_nested: True if a resource's nested properties schema
            should be resolved.
        :returns: A tuple of params and properties dicts
        '''
        params = {}
        properties = (Properties.
                      _schema_to_params_and_props(schema, params=params))
        return (params, properties)
