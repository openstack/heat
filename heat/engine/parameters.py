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
from heat.engine import template

PARAMETER_KEYS = (
    TYPE, DEFAULT, NO_ECHO, VALUES, PATTERN,
    MAX_LENGTH, MIN_LENGTH, MAX_VALUE, MIN_VALUE,
    DESCRIPTION, CONSTRAINT_DESCRIPTION
) = (
    'Type', 'Default', 'NoEcho', 'AllowedValues', 'AllowedPattern',
    'MaxLength', 'MinLength', 'MaxValue', 'MinValue',
    'Description', 'ConstraintDescription'
)
PARAMETER_TYPES = (
    STRING, NUMBER, COMMA_DELIMITED_LIST
) = (
    'String', 'Number', 'CommaDelimitedList'
)
PSEUDO_PARAMETERS = (
    PARAM_STACK_ID, PARAM_STACK_NAME, PARAM_REGION
) = (
    'AWS::StackId', 'AWS::StackName', 'AWS::Region'
)


class Parameter(object):
    '''A template parameter.'''

    def __new__(cls, name, schema, value=None):
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
        else:
            raise ValueError('Invalid Parameter type "%s"' % param_type)

        return ParamClass(name, schema, value)

    def __init__(self, name, schema, value=None):
        '''
        Initialise the Parameter with a name, schema and optional user-supplied
        value.
        '''
        self.name = name
        self.schema = schema
        self.user_value = value
        self._constraint_error = self.schema.get(CONSTRAINT_DESCRIPTION)

        if self.has_default():
            self._validate(self.default())

        if self.user_value is not None:
            self._validate(self.user_value)

    def _error_msg(self, message):
        return '%s %s' % (self.name, self._constraint_error or message)

    def _validate(self, value):
        if VALUES in self.schema:
            allowed = self.schema[VALUES]
            if value not in allowed:
                message = '%s not in %s %s' % (value, VALUES, allowed)
                raise ValueError(self._error_msg(message))

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
        return self.schema.get(NO_ECHO, 'false').lower() == 'true'

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

    @staticmethod
    def str_to_num(s):
        '''Convert a string to an integer (if possible) or float.'''
        try:
            return int(s)
        except ValueError:
            return float(s)

    def _validate(self, value):
        '''Check that the supplied value is compatible with the constraints.'''
        num = self.str_to_num(value)
        minn = self.str_to_num(self.schema.get(MIN_VALUE, value))
        maxn = self.str_to_num(self.schema.get(MAX_VALUE, value))

        if num > maxn or num < minn:
            raise ValueError(self._error_msg('%s is out of range' % value))

        Parameter._validate(self, value)

    def __int__(self):
        '''Return an integer representation of the parameter'''
        return int(self.value())

    def __float__(self):
        '''Return a float representation of the parameter'''
        return float(self.value())


class StringParam(Parameter):
    '''A template parameter of type "String".'''

    def _validate(self, value):
        '''Check that the supplied value is compatible with the constraints.'''
        if not isinstance(value, basestring):
            raise ValueError(self._error_msg('value must be a string'))

        length = len(value)
        if MAX_LENGTH in self.schema:
            max_length = int(self.schema[MAX_LENGTH])
            if length > max_length:
                message = 'length (%d) overflows %s %s' % (length,
                                                           MAX_LENGTH,
                                                           max_length)
                raise ValueError(self._error_msg(message))

        if MIN_LENGTH in self.schema:
            min_length = int(self.schema[MIN_LENGTH])
            if length < min_length:
                message = 'length (%d) underflows %s %d' % (length,
                                                            MIN_LENGTH,
                                                            min_length)
                raise ValueError(self._error_msg(message))

        if PATTERN in self.schema:
            pattern = self.schema[PATTERN]
            match = re.match(pattern, value)
            if match is None or match.end() != length:
                message = '"%s" does not match %s "%s"' % (value,
                                                           PATTERN,
                                                           pattern)
                raise ValueError(self._error_msg(message))

        Parameter._validate(self, value)


class CommaDelimitedListParam(Parameter, collections.Sequence):
    '''A template parameter of type "CommaDelimitedList".'''

    def _validate(self, value):
        '''Check that the supplied value is compatible with the constraints.'''
        try:
            sp = value.split(',')
        except AttributeError:
            raise ValueError('Value must be a comma-delimited list string')

        for li in self:
            Parameter._validate(self, li)

    def __len__(self):
        '''Return the length of the list.'''
        return len(self.value().split(','))

    def __getitem__(self, index):
        '''Return an item from the list.'''
        return self.value().split(',')[index]


class Parameters(collections.Mapping):
    '''
    The parameters of a stack, with type checking, defaults &c. specified by
    the stack's template.
    '''
    def __init__(self, stack_name, tmpl, user_params={}, stack_id=None):
        '''
        Create the parameter container for a stack from the stack name and
        template, optionally setting the user-supplied parameter values.
        '''
        def parameters():
            yield Parameter(PARAM_STACK_ID,
                            {TYPE: STRING,
                             DESCRIPTION: 'Stack ID',
                             DEFAULT: str(stack_id)})
            if stack_name is not None:
                yield Parameter(PARAM_STACK_NAME,
                                {TYPE: STRING,
                                 DESCRIPTION: 'Stack Name',
                                 DEFAULT: stack_name})
                yield Parameter(PARAM_REGION,
                                {TYPE: STRING,
                                 DEFAULT: 'ap-southeast-1',
                                 VALUES: ['us-east-1',
                                          'us-west-1', 'us-west-2',
                                          'sa-east-1',
                                          'eu-west-1',
                                          'ap-southeast-1',
                                          'ap-northeast-1']})

            for name, schema in tmpl[template.PARAMETERS].iteritems():
                yield Parameter(name, schema, user_params.get(name))

        self.tmpl = tmpl
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

    def user_parameters(self):
        '''
        Return a dictionary of all the parameters passed in by the user
        '''
        return self.map(lambda p: p.user_value,
                        lambda p: p.user_value is not None)

    def set_stack_id(self, stack_id):
        '''
        Set the AWS::StackId pseudo parameter value
        '''
        self.params[PARAM_STACK_ID].schema[DEFAULT] = stack_id

    def _validate(self, user_params):
        for param in user_params:
            if param not in self.tmpl[template.PARAMETERS]:
                raise exception.UnknownUserParameter(key=param)
