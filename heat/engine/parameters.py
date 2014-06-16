
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
import itertools
import json
import six
from heat.engine import constraints as constr

from heat.common import exception
from heat.openstack.common import strutils


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
    '''Parameter schema.'''

    KEYS = (
        TYPE, DESCRIPTION, DEFAULT, SCHEMA, CONSTRAINTS, HIDDEN, LABEL
    ) = (
        'Type', 'Description', 'Default', 'Schema', 'Constraints', 'NoEcho',
        'Label'
    )

    PARAMETER_KEYS = PARAMETER_KEYS

    # For Parameters the type name for Schema.LIST is CommaDelimitedList
    # and the type name for Schema.MAP is Json
    TYPES = (
        STRING, NUMBER, LIST, MAP,
    ) = (
        'String', 'Number', 'CommaDelimitedList', 'Json',
    )

    def __init__(self, data_type, description=None, default=None, schema=None,
                 constraints=[], hidden=False, label=None):
        super(Schema, self).__init__(data_type=data_type,
                                     description=description,
                                     default=default,
                                     schema=schema,
                                     required=default is None,
                                     constraints=constraints,
                                     label=label)
        self.hidden = hidden

    # Schema class validates default value for lists assuming list type. For
    # comma delimited list string supported in paramaters Schema class, the
    # default value has to be parsed into a list if necessary so that
    # validation works.
    def _validate_default(self, context):
        if self.default is not None:
            default_value = self.default
            if self.type == self.LIST and not isinstance(self.default, list):
                try:
                    default_value = self.default.split(',')
                except (KeyError, AttributeError) as err:
                    raise constr.InvalidSchemaError(_('Default must be a '
                                                      'comma-delimited list '
                                                      'string: %s') % str(err))
            try:
                self.validate_constraints(default_value, context)
            except (ValueError, TypeError) as exc:
                raise constr.InvalidSchemaError(_('Invalid default '
                                                  '%(default)s (%(exc)s)') %
                                                dict(default=self.default,
                                                     exc=exc))

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
            raise constr.InvalidSchemaError(
                _("Invalid %s, expected a mapping") % entity)
        for key in schema_dict:
            if key not in allowed_keys:
                raise constr.InvalidSchemaError(
                    _("Invalid key '%(key)s' for %(entity)s") % {
                        "key": key, "entity": entity})

    @classmethod
    def _validate_dict(cls, schema_dict):
        cls._check_dict(schema_dict, cls.PARAMETER_KEYS, "parameter")

        if cls.TYPE not in schema_dict:
            raise constr.InvalidSchemaError(_("Missing parameter type"))

    @classmethod
    def from_dict(cls, schema_dict):
        """
        Return a Parameter Schema object from a legacy schema dictionary.
        """
        cls._validate_dict(schema_dict)

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

    def validate_value(self, name, value, context=None):
        super(Schema, self).validate_constraints(value, context)

    def __getitem__(self, key):
        if key == self.TYPE:
            return self.type
        if key == self.HIDDEN:
            return self.hidden
        else:
            return super(Schema, self).__getitem__(key)

        raise KeyError(key)


class Parameter(object):
    '''A template parameter.'''

    def __new__(cls, name, schema, value=None):
        '''Create a new Parameter of the appropriate type.'''
        if cls is not Parameter:
            return super(Parameter, cls).__new__(cls)

        # Check for fully-fledged Schema objects
        if not isinstance(schema, Schema):
            schema = Schema.from_dict(schema)

        if schema.type == schema.STRING:
            ParamClass = StringParam
        elif schema.type == schema.NUMBER:
            ParamClass = NumberParam
        elif schema.type == schema.LIST:
            ParamClass = CommaDelimitedListParam
        elif schema.type == schema.MAP:
            ParamClass = JsonParam
        else:
            raise ValueError(_('Invalid Parameter type "%s"') % schema.type)

        return ParamClass(name, schema, value)

    def __init__(self, name, schema, value=None):
        '''
        Initialise the Parameter with a name, schema and optional user-supplied
        value.
        '''
        self.name = name
        self.schema = schema
        self.user_value = value

    def validate(self, validate_value=True, context=None):
        '''
        Validates the parameter.

        This method validates if the parameter's schema is valid,
        and if the default value - if present - or the user-provided
        value for the parameter comply with the schema.
        '''
        self.schema.validate(context)

        if validate_value:
            if self.has_default():
                self._validate(self.default(), context)
            if self.user_value is not None:
                self._validate(self.user_value, context)
            elif not self.has_default():
                raise exception.UserParameterMissing(key=self.name)

    def value(self):
        '''Get the parameter value, optionally sanitising it for output.'''
        if self.user_value is not None:
            return self.user_value

        if self.has_default():
            return self.default()

        raise KeyError(_('Missing parameter %s') % self.name)

    def hidden(self):
        '''
        Return whether the parameter should be sanitised in any output to
        the user.
        '''
        return self.schema.hidden

    def description(self):
        '''Return the description of the parameter.'''
        return self.schema.description or ''

    def label(self):
        '''Return the label or param name.'''
        return self.schema.label or self.name

    def has_default(self):
        '''Return whether the parameter has a default value.'''
        return self.schema.default is not None

    def default(self):
        '''Return the default value of the parameter.'''
        return self.schema.default

    def __str__(self):
        '''Return a string representation of the parameter'''
        value = self.value()
        if self.hidden():
            return '******'
        else:
            return strutils.safe_encode(six.text_type(value))


class NumberParam(Parameter):
    '''A template parameter of type "Number".'''

    def __int__(self):
        '''Return an integer representation of the parameter'''
        return int(super(NumberParam, self).value())

    def __float__(self):
        '''Return a float representation of the parameter'''
        return float(super(NumberParam, self).value())

    def _validate(self, val, context):
        self.schema.validate_value(self.name, val, context)

    def value(self):
        try:
            return int(self)
        except ValueError:
            return float(self)


class StringParam(Parameter):
    '''A template parameter of type "String".'''

    def _validate(self, val, context):
        self.schema.validate_value(self.name, val, context)


class CommaDelimitedListParam(Parameter, collections.Sequence):
    '''A template parameter of type "CommaDelimitedList".'''

    def __init__(self, name, schema, value=None):
        super(CommaDelimitedListParam, self).__init__(name, schema, value)
        self.parsed = self.parse(self.user_value or self.default())

    def parse(self, value):
        # only parse when value is not already a list
        if isinstance(value, list):
            return value

        try:
            if value:
                return value.split(',')
        except (KeyError, AttributeError) as err:
            message = _('Value must be a comma-delimited list string: %s')
            raise ValueError(message % str(err))
        return value

    def value(self):
        return self.parsed

    def __len__(self):
        '''Return the length of the list.'''
        return len(self.parsed)

    def __getitem__(self, index):
        '''Return an item from the list.'''
        return self.parsed[index]

    def _validate(self, val, context):
        parsed = self.parse(val)
        self.schema.validate_value(self.name, parsed, context)


class JsonParam(Parameter, collections.Mapping):
    """A template parameter who's value is valid map."""

    def __init__(self, name, schema, value=None):
        super(JsonParam, self).__init__(name, schema, value)
        self.parsed = self.parse(self.user_value or self.default())

    def parse(self, value):
        try:
            val = value
            if isinstance(val, collections.Mapping):
                val = json.dumps(val)
            if val:
                return json.loads(val)
        except (ValueError, TypeError) as err:
            message = _('Value must be valid JSON: %s') % str(err)
            raise ValueError(message)
        return value

    def value(self):
        return self.parsed

    def __getitem__(self, key):
        return self.parsed[key]

    def __iter__(self):
        return iter(self.parsed)

    def __len__(self):
        return len(self.parsed)

    def _validate(self, val, context):
        val = self.parse(val)
        self.schema.validate_value(self.name, val, context)


class Parameters(collections.Mapping):
    '''
    The parameters of a stack, with type checking, defaults &c. specified by
    the stack's template.
    '''

    PSEUDO_PARAMETERS = (
        PARAM_STACK_ID, PARAM_STACK_NAME, PARAM_REGION
    ) = (
        'AWS::StackId', 'AWS::StackName', 'AWS::Region'
    )

    def __init__(self, stack_identifier, tmpl, user_params={}):
        '''
        Create the parameter container for a stack from the stack name and
        template, optionally setting the user-supplied parameter values.
        '''
        def user_parameter(schema_item):
            name, schema = schema_item
            return Parameter(name, schema,
                             user_params.get(name))

        self.tmpl = tmpl
        self.user_params = user_params

        schemata = self.tmpl.param_schemata()
        user_parameters = (user_parameter(si) for si in schemata.iteritems())
        pseudo_parameters = self._pseudo_parameters(stack_identifier)

        self.params = dict((p.name,
                            p) for p in itertools.chain(pseudo_parameters,
                                                        user_parameters))

    def validate(self, validate_value=True, context=None):
        '''
        Validates all parameters.

        This method validates if all user-provided parameters are actually
        defined in the template, and if all parameters are valid.
        '''
        self._validate_tmpl_parameters()
        self._validate_user_parameters()

        for param in self.params.values():
            param.validate(validate_value, context)

    def __contains__(self, key):
        '''Return whether the specified parameter exists.'''
        return key in self.params

    def __iter__(self):
        '''Return an iterator over the parameter names.'''
        return iter(self.params)

    def __len__(self):
        '''Return the number of parameters defined.'''
        return len(self.params)

    def __getitem__(self, key):
        '''Get a parameter value.'''
        return self.params[key].value()

    def map(self, func, filter_func=lambda p: True):
        '''
        Map the supplied filter function onto each Parameter (with an
        optional filter function) and return the resulting dictionary.
        '''
        return dict((n, func(p))
                    for n, p in self.params.iteritems() if filter_func(p))

    def set_stack_id(self, stack_identifier):
        '''
        Set the StackId pseudo parameter value
        '''
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

    def _validate_tmpl_parameters(self):
        param = None
        for key in self.tmpl.t.keys():
            if key == 'Parameters' or key == 'parameters':
                param = key
                break
        if param is not None:
            template_params = self.tmpl.t[key]
            for name, attrs in template_params.iteritems():
                if not isinstance(attrs, dict):
                    raise exception.InvalidTemplateParameter(key=name)

    def _pseudo_parameters(self, stack_identifier):
        stack_id = stack_identifier.arn() \
            if stack_identifier is not None else 'None'
        stack_name = stack_identifier and stack_identifier.stack_name

        yield Parameter(self.PARAM_STACK_ID,
                        Schema(Schema.STRING, _('Stack ID'),
                               default=str(stack_id)))
        if stack_name:
            yield Parameter(self.PARAM_STACK_NAME,
                            Schema(Schema.STRING, _('Stack Name'),
                                   default=stack_name))
            yield Parameter(self.PARAM_REGION,
                            Schema(Schema.STRING,
                                   default='ap-southeast-1',
                                   constraints=
                                   [constr.AllowedValues(['us-east-1',
                                                          'us-west-1',
                                                          'us-west-2',
                                                          'sa-east-1',
                                                          'eu-west-1',
                                                          'ap-southeast-1',
                                                          'ap-northeast-1']
                                                         )]))
