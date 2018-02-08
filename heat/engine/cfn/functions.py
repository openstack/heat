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

from oslo_serialization import jsonutils
import six

from heat.api.aws import utils as aws_utils
from heat.common import exception
from heat.common.i18n import _
from heat.engine import function
from heat.engine.hot import functions as hot_funcs


class FindInMap(function.Function):
    """A function for resolving keys in the template mappings.

    Takes the form::

        { "Fn::FindInMap" : [ "mapping",
                              "key",
                              "value" ] }
    """

    def __init__(self, stack, fn_name, args):
        super(FindInMap, self).__init__(stack, fn_name, args)

        try:
            self._mapname, self._mapkey, self._mapvalue = self.args
        except ValueError as ex:
            raise KeyError(six.text_type(ex))

    def result(self):
        mapping = self.stack.t.maps[function.resolve(self._mapname)]
        key = function.resolve(self._mapkey)
        value = function.resolve(self._mapvalue)
        return mapping[key][value]


class GetAZs(function.Function):
    """A function for retrieving the availability zones.

    Takes the form::

        { "Fn::GetAZs" : "<region>" }
    """

    def result(self):
        # TODO(therve): Implement region scoping

        if self.stack is None:
            return ['nova']
        else:
            return self.stack.get_availability_zones()


class ParamRef(function.Function):
    """A function for resolving parameter references.

    Takes the form::

        { "Ref" : "<param_name>" }
    """

    def __init__(self, stack, fn_name, args):
        super(ParamRef, self).__init__(stack, fn_name, args)

        self.parameters = self.stack.parameters

    def result(self):
        param_name = function.resolve(self.args)

        try:
            return self.parameters[param_name]
        except KeyError:
            raise exception.InvalidTemplateReference(resource=param_name,
                                                     key='unknown')


def Ref(stack, fn_name, args):
    """A function for resolving parameters or resource references.

    Takes the form::

        { "Ref" : "<param_name>" }

    or::

        { "Ref" : "<resource_name>" }
    """
    if stack is None or args in stack:
        RefClass = hot_funcs.GetResource
    else:
        RefClass = ParamRef
    return RefClass(stack, fn_name, args)


class GetAtt(hot_funcs.GetAttThenSelect):
    """A function for resolving resource attributes.

    Takes the form::

        { "Fn::GetAtt" : [ "<resource_name>",
                           "<attribute_name>" ] }
    """

    def _parse_args(self):
        try:
            resource_name, attribute = self.args
        except ValueError:
            raise ValueError(_('Arguments to "%s" must be of the form '
                               '[resource_name, attribute]') % self.fn_name)

        return resource_name, attribute, []


class Select(function.Function):
    """A function for selecting an item from a list or map.

    Takes the form (for a list lookup)::

        { "Fn::Select" : [ "<index>", [ "<value_1>", "<value_2>", ... ] ] }

    or (for a map lookup)::

        { "Fn::Select" : [ "<index>", { "<key_1>": "<value_1>", ... } ] }

    If the selected index is not found, this function resolves to an empty
    string.
    """

    def __init__(self, stack, fn_name, args):
        super(Select, self).__init__(stack, fn_name, args)

        try:
            self._lookup, self._strings = self.args
        except ValueError:
            raise ValueError(_('Arguments to "%s" must be of the form '
                               '[index, collection]') % self.fn_name)

    def result(self):
        index = function.resolve(self._lookup)

        strings = function.resolve(self._strings)

        if strings == '':
            # an empty string is a common response from other
            # functions when result is not currently available.
            # Handle by returning an empty string
            return ''

        if isinstance(strings, six.string_types):
            # might be serialized json.
            try:
                strings = jsonutils.loads(strings)
            except ValueError as json_ex:
                fmt_data = {'fn_name': self.fn_name,
                            'err': json_ex}
                raise ValueError(_('"%(fn_name)s": %(err)s') % fmt_data)

        if isinstance(strings, collections.Mapping):
            if not isinstance(index, six.string_types):
                raise TypeError(_('Index to "%s" must be a string') %
                                self.fn_name)
            return strings.get(index, '')

        try:
            index = int(index)
        except (ValueError, TypeError):
            pass

        if (isinstance(strings, collections.Sequence) and
                not isinstance(strings, six.string_types)):
            if not isinstance(index, six.integer_types):
                raise TypeError(_('Index to "%s" must be an integer') %
                                self.fn_name)

            try:
                return strings[index]
            except IndexError:
                return ''

        if strings is None:
            return ''

        raise TypeError(_('Arguments to %s not fully resolved') %
                        self.fn_name)


class Join(hot_funcs.Join):
    """A function for joining strings.

    Takes the form::

        { "Fn::Join" : [ "<delim>", [ "<string_1>", "<string_2>", ... ] ] }

    And resolves to::

        "<string_1><delim><string_2><delim>..."
    """


class Split(function.Function):
    """A function for splitting strings.

    Takes the form::

        { "Fn::Split" : [ "<delim>", "<string_1><delim><string_2>..." ] }

    And resolves to::

        [ "<string_1>", "<string_2>", ... ]
    """

    def __init__(self, stack, fn_name, args):
        super(Split, self).__init__(stack, fn_name, args)

        example = '"%s" : [ ",", "str1,str2"]]' % self.fn_name
        fmt_data = {'fn_name': self.fn_name,
                    'example': example}

        if isinstance(self.args, (six.string_types, collections.Mapping)):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % fmt_data)

        try:
            self._delim, self._strings = self.args
        except ValueError:
            raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                               'should be: %(example)s') % fmt_data)

    def result(self):
        strings = function.resolve(self._strings)

        if not isinstance(self._delim, six.string_types):
            raise TypeError(_("Delimiter for %s must be string") %
                            self.fn_name)
        if not isinstance(strings, six.string_types):
            raise TypeError(_("String to split must be string; got %s") %
                            type(strings))

        return strings.split(self._delim)


class Replace(hot_funcs.Replace):
    """A function for performing string substitutions.

    Takes the form::

        { "Fn::Replace" : [
            { "<key_1>": "<value_1>", "<key_2>": "<value_2>", ... },
            "<key_1> <key_2>"
          ] }

    And resolves to::

        "<value_1> <value_2>"

    When keys overlap in the template, longer matches are preferred. For keys
    of equal length, lexicographically smaller keys are preferred.
    """

    def _parse_args(self):

        example = ('{"%s": '
                   '[ {"$var1": "foo", "%%var2%%": "bar"}, '
                   '"$var1 is %%var2%%"]}' % self.fn_name)
        fmt_data = {'fn_name': self.fn_name,
                    'example': example}

        if isinstance(self.args, (six.string_types, collections.Mapping)):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % fmt_data)

        try:
            mapping, string = self.args
        except ValueError:
            raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                               'should be: %(example)s') % fmt_data)
        else:
            return mapping, string


class Base64(function.Function):
    """A placeholder function for converting to base64.

    Takes the form::

        { "Fn::Base64" : "<string>" }

    This function actually performs no conversion. It is included for the
    benefit of templates that convert UserData to Base64. Heat accepts UserData
    in plain text.
    """

    def result(self):
        resolved = function.resolve(self.args)
        if not isinstance(resolved, six.string_types):
            raise TypeError(_('"%s" argument must be a string') % self.fn_name)
        return resolved


class MemberListToMap(function.Function):
    """A function to convert lists with enumerated keys and values to mapping.

    Takes the form::

        { 'Fn::MemberListToMap' : [ 'Name',
                                    'Value',
                                    [ '.member.0.Name=<key_0>',
                                      '.member.0.Value=<value_0>',
                                      ... ] ] }

    And resolves to::

        { "<key_0>" : "<value_0>", ... }

    The first two arguments are the names of the key and value.
    """

    def __init__(self, stack, fn_name, args):
        super(MemberListToMap, self).__init__(stack, fn_name, args)

        try:
            self._keyname, self._valuename, self._list = self.args
        except ValueError:
            correct = '''
            {'Fn::MemberListToMap': ['Name', 'Value',
                                     ['.member.0.Name=key',
                                      '.member.0.Value=door']]}
            '''
            raise TypeError(_('Wrong Arguments try: "%s"') % correct)

        if not isinstance(self._keyname, six.string_types):
            raise TypeError(_('%s Key Name must be a string') % self.fn_name)

        if not isinstance(self._valuename, six.string_types):
            raise TypeError(_('%s Value Name must be a string') % self.fn_name)

    def result(self):
        member_list = function.resolve(self._list)

        if not isinstance(member_list, collections.Iterable):
            raise TypeError(_('Member list must be a list'))

        def item(s):
            if not isinstance(s, six.string_types):
                raise TypeError(_("Member list items must be strings"))
            return s.split('=', 1)

        partials = dict(item(s) for s in member_list)
        return aws_utils.extract_param_pairs(partials,
                                             prefix='',
                                             keyname=self._keyname,
                                             valuename=self._valuename)


class ResourceFacade(hot_funcs.ResourceFacade):
    """A function for retrieving data in a parent provider template.

    A function for obtaining data from the facade resource from within the
    corresponding provider template.

    Takes the form::

        { "Fn::ResourceFacade": "<attribute_type>" }

    where the valid attribute types are "Metadata", "DeletionPolicy" and
    "UpdatePolicy".
    """

    _RESOURCE_ATTRIBUTES = (
        METADATA, DELETION_POLICY, UPDATE_POLICY,
    ) = (
        'Metadata', 'DeletionPolicy', 'UpdatePolicy'
    )


class If(hot_funcs.If):
    """A function to return corresponding value based on condition evaluation.

    Takes the form::

        { "Fn::If" : [ "<condition_name>",
                       "<value_if_true>",
                       "<value_if_false>" ] }

    The value_if_true to be returned if the specified condition evaluates
    to true, the value_if_false to be returned if the specified condition
    evaluates to false.
    """


class Equals(hot_funcs.Equals):
    """A function for comparing whether two values are equal.

    Takes the form::

        { "Fn::Equals" : [ "<value_1>", "<value_2>" ] }

    The value can be any type that you want to compare. Returns true
    if the two values are equal or false if they aren't.
    """


class Not(hot_funcs.Not):
    """A function that acts as a NOT operator on a condition.

    Takes the form::

        { "Fn::Not" : [ "<condition>" ] }

    Returns true for a condition that evaluates to false or
    returns false for a condition that evaluates to true.
    """

    def _check_args(self):
        msg = _('Arguments to "%s" must be of the form: '
                '[condition]') % self.fn_name
        if (not self.args or
                not isinstance(self.args, collections.Sequence) or
                isinstance(self.args, six.string_types)):
            raise ValueError(msg)
        if len(self.args) != 1:
            raise ValueError(msg)
        self.condition = self.args[0]


class And(hot_funcs.And):
    """A function that acts as an AND operator on conditions.

    Takes the form::

        { "Fn::And" : [ "<condition_1>", "<condition_2>", ... ] }

    Returns true if all the specified conditions evaluate to true, or returns
    false if any one of the conditions evaluates to false. The minimum number
    of conditions that you can include is 2.
    """


class Or(hot_funcs.Or):
    """A function that acts as an OR operator on conditions.

    Takes the form::

        { "Fn::Or" : [ "<condition_1>", "<condition_2>", ... ] }

    Returns true if any one of the specified conditions evaluate to true,
    or returns false if all of the conditions evaluates to false. The minimum
    number of conditions that you can include is 2.
    """
