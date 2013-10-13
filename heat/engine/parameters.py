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
import json
import re

from heat.common import exception


PARAMETER_KEYS = (
    TYPE, DEFAULT, NO_ECHO, ALLOWED_VALUES, ALLOWED_PATTERN,
    MAX_LENGTH, MIN_LENGTH, MAX_VALUE, MIN_VALUE,
    DESCRIPTION, CONSTRAINT_DESCRIPTION
) = (
    'Type', 'Default', 'NoEcho', 'AllowedValues', 'AllowedPattern',
    'MaxLength', 'MinLength', 'MaxValue', 'MinValue',
    'Description', 'ConstraintDescription'
)
PARAMETER_TYPES = (
    STRING, NUMBER, COMMA_DELIMITED_LIST, JSON
) = (
    'String', 'Number', 'CommaDelimitedList', 'Json'
)
PSEUDO_PARAMETERS = (
    PARAM_STACK_ID, PARAM_STACK_NAME, PARAM_REGION
) = (
    'AWS::StackId', 'AWS::StackName', 'AWS::Region'
)


class ParamSchema(dict):
    '''Parameter schema.'''

    def __init__(self, schema):
        super(ParamSchema, self).__init__(schema)

    def do_check(self, name, value, keys):
        for k in keys:
            check = self.check(k)
            const = self.get(k)
            if check is None or const is None:
                continue
            check(name, value, const)

    def constraints(self):
        ptype = self[TYPE]
        keys = {
            STRING: [ALLOWED_VALUES, ALLOWED_PATTERN, MAX_LENGTH, MIN_LENGTH],
            NUMBER: [ALLOWED_VALUES, MAX_VALUE, MIN_VALUE],
            JSON: [MAX_LENGTH, MIN_LENGTH]
        }.get(ptype)
        list_keys = {
            COMMA_DELIMITED_LIST: [ALLOWED_VALUES],
            JSON: [ALLOWED_VALUES]
        }.get(ptype)
        return (keys, list_keys)

    def validate(self, name, value):
        (keys, list_keys) = self.constraints()
        if keys:
            self.do_check(name, value, keys)
        if list_keys:
            values = value
            for value in values:
                self.do_check(name, value, list_keys)

    def raise_error(self, name, message, desc=True):
        if desc:
            message = self.get(CONSTRAINT_DESCRIPTION) or message
        raise ValueError('%s %s' % (name, message))

    def check_allowed_values(self, name, val, const, desc=None):
        vals = list(const)
        if val not in vals:
            err = '"%s" not in %s "%s"' % (val, ALLOWED_VALUES, vals)
            self.raise_error(name, desc or err)

    def check_allowed_pattern(self, name, val, p, desc=None):
        m = re.match(p, val)
        if m is None or m.end() != len(val):
            err = '"%s" does not match %s "%s"' % (val, ALLOWED_PATTERN, p)
            self.raise_error(name, desc or err)

    def check_max_length(self, name, val, const, desc=None):
        max_len = int(const)
        val_len = len(val)
        if val_len > max_len:
            err = 'length (%d) overflows %s (%d)' % (val_len,
                                                     MAX_LENGTH, max_len)
            self.raise_error(name, desc or err)

    def check_min_length(self, name, val, const, desc=None):
        min_len = int(const)
        val_len = len(val)
        if val_len < min_len:
            err = 'length (%d) underflows %s (%d)' % (val_len,
                                                      MIN_LENGTH, min_len)
            self.raise_error(name, desc or err)

    def check_max_value(self, name, val, const, desc=None):
        max_val = float(const)
        val = float(val)
        if val > max_val:
            err = '%d overflows %s %d' % (val, MAX_VALUE, max_val)
            self.raise_error(name, desc or err)

    def check_min_value(self, name, val, const, desc=None):
        min_val = float(const)
        val = float(val)
        if val < min_val:
            err = '%d underflows %s %d' % (val, MIN_VALUE, min_val)
            self.raise_error(name, desc or err)

    def check(self, const_key):
        return {ALLOWED_VALUES: self.check_allowed_values,
                ALLOWED_PATTERN: self.check_allowed_pattern,
                MAX_LENGTH: self.check_max_length,
                MIN_LENGTH: self.check_min_length,
                MAX_VALUE: self.check_max_value,
                MIN_VALUE: self.check_min_value}.get(const_key)


class Parameter(object):
    '''A template parameter.'''

    def __new__(cls, name, schema, value=None, validate_value=True):
        '''Create a new Parameter of the appropriate type.'''
        if cls is not Parameter:
            return super(Parameter, cls).__new__(cls)

        param_type = schema[TYPE]
        if param_type == STRING:
            ParamClass = StringParam
        elif param_type == NUMBER:
            ParamClass = NumberParam
        elif param_type == COMMA_DELIMITED_LIST:
            ParamClass = CommaDelimitedListParam
        elif param_type == JSON:
            ParamClass = JsonParam
        else:
            raise ValueError('Invalid Parameter type "%s"' % param_type)

        return ParamClass(name, schema, value, validate_value)

    def __init__(self, name, schema, value=None, validate_value=True):
        '''
        Initialise the Parameter with a name, schema and optional user-supplied
        value.
        '''
        self.name = name
        self.schema = schema
        self.user_value = value

        if validate_value:
            if self.has_default():
                self.validate(self.default())
            if self.user_value is not None:
                self.validate(self.user_value)
            elif not self.has_default():
                raise exception.UserParameterMissing(key=self.name)

    def value(self):
        '''Get the parameter value, optionally sanitising it for output.'''
        if self.user_value is not None:
            return self.user_value

        if self.has_default():
            return self.default()

        raise KeyError('Missing parameter %s' % self.name)

    def no_echo(self):
        '''
        Return whether the parameter should be sanitised in any output to
        the user.
        '''
        return str(self.schema.get(NO_ECHO, 'false')).lower() == 'true'

    def description(self):
        '''Return the description of the parameter.'''
        return self.schema.get(DESCRIPTION, '')

    def has_default(self):
        '''Return whether the parameter has a default value.'''
        return DEFAULT in self.schema

    def default(self):
        '''Return the default value of the parameter.'''
        return self.schema.get(DEFAULT)

    def __str__(self):
        '''Return a string representation of the parameter'''
        value = self.value()
        if self.no_echo():
            return '******'
        else:
            return str(value)


class NumberParam(Parameter):
    '''A template parameter of type "Number".'''

    def __int__(self):
        '''Return an integer representation of the parameter'''
        return int(super(NumberParam, self).value())

    def __float__(self):
        '''Return a float representation of the parameter'''
        return float(super(NumberParam, self).value())

    def validate(self, val):
        self.schema.validate(self.name, val)

    def value(self):
        try:
            return int(self)
        except ValueError:
            return float(self)


class StringParam(Parameter):
    '''A template parameter of type "String".'''

    def validate(self, val):
        self.schema.validate(self.name, val)


class CommaDelimitedListParam(Parameter, collections.Sequence):
    '''A template parameter of type "CommaDelimitedList".'''

    def __init__(self, name, schema, value=None, validate_value=True):
        super(CommaDelimitedListParam, self).__init__(name, schema, value,
                                                      validate_value)
        self.parsed = self.parse(self.user_value or self.default())

    def parse(self, value):
        try:
            if value:
                return value.split(',')
        except (KeyError, AttributeError) as err:
            message = 'Value must be a comma-delimited list string: %s'
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

    def validate(self, val):
        parsed = self.parse(val)
        self.schema.validate(self.name, parsed)


class JsonParam(Parameter, collections.Mapping):
    """A template parameter who's value is valid map."""

    def __init__(self, name, schema, value=None, validate_value=True):
        super(JsonParam, self).__init__(name, schema, value,
                                        validate_value)
        self.parsed = self.parse(self.user_value or self.default())

    def parse(self, value):
        try:
            val = value
            if isinstance(val, collections.Mapping):
                val = json.dumps(val)
            if val:
                return json.loads(val)
        except (ValueError, TypeError) as err:
            message = 'Value must be valid JSON: %s' % str(err)
            raise ValueError(message)
        return value

    def value(self):
        val = super(JsonParam, self).value()
        if isinstance(val, collections.Mapping):
            try:
                val = json.dumps(val)
                self.user_value = val
            except (ValueError, TypeError) as err:
                message = 'Value must be valid JSON'
                raise ValueError("%s: %s" % (message, str(err)))
        return val

    def __getitem__(self, key):
        return self.parsed[key]

    def __iter__(self):
        return iter(self.parsed)

    def __len__(self):
        return len(self.parsed)

    def validate(self, val):
        val = self.parse(val)
        self.schema.validate(self.name, val)


class Parameters(collections.Mapping):
    '''
    The parameters of a stack, with type checking, defaults &c. specified by
    the stack's template.
    '''
    def __init__(self, stack_name, tmpl, user_params={}, stack_id=None,
                 validate_value=True):
        '''
        Create the parameter container for a stack from the stack name and
        template, optionally setting the user-supplied parameter values.
        '''
        def parameters():
            yield Parameter(PARAM_STACK_ID,
                            ParamSchema({TYPE: STRING,
                                         DESCRIPTION: 'Stack ID',
                                         DEFAULT: str(stack_id)}))
            if stack_name is not None:
                yield Parameter(PARAM_STACK_NAME,
                                ParamSchema({TYPE: STRING,
                                             DESCRIPTION: 'Stack Name',
                                             DEFAULT: stack_name}))
                yield Parameter(PARAM_REGION,
                                ParamSchema({TYPE: STRING,
                                             DEFAULT: 'ap-southeast-1',
                                             ALLOWED_VALUES:
                                             ['us-east-1',
                                              'us-west-1',
                                              'us-west-2',
                                              'sa-east-1',
                                              'eu-west-1',
                                              'ap-southeast-1',
                                              'ap-northeast-1']}))

            schemata = self.tmpl.param_schemata().iteritems()
            for name, schema in schemata:
                value = user_params.get(name)
                yield Parameter(name, schema, value, validate_value)

        self.tmpl = tmpl
        self._validate_tmpl_parameters()
        self._validate(user_params)
        self.params = dict((p.name, p) for p in parameters())

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

    def set_stack_id(self, stack_id):
        '''
        Set the AWS::StackId pseudo parameter value
        '''
        self.params[PARAM_STACK_ID].schema[DEFAULT] = stack_id

    def _validate(self, user_params):
        schemata = self.tmpl.param_schemata()
        for param in user_params:
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
