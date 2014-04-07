
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

from heat.api.aws import utils as aws_utils
from heat.common import exception

from heat.engine import function


class FindInMap(function.Function):
    '''
    A function for resolving keys in the template mappings.

    Takes the form::

        { "Fn::FindInMap" : [ "mapping",
                              "key",
                              "value" ] }
    '''

    def __init__(self, stack, fn_name, args):
        super(FindInMap, self).__init__(stack, fn_name, args)

        try:
            self._mapname, self._mapkey, self._mapvalue = self.args
        except ValueError as ex:
            raise KeyError(str(ex))

    def result(self):
        mapping = self.stack.t.maps[function.resolve(self._mapname)]
        key = function.resolve(self._mapkey)
        value = function.resolve(self._mapvalue)
        return mapping[key][value]


class GetAZs(function.Function):
    '''
    A function for retrieving the availability zones.

    Takes the form::

        { "Fn::GetAZs" : "<region>" }
    '''

    def result(self):
        # TODO(therve): Implement region scoping
        #region = function.resolve(self.args)

        if self.stack is None:
            return ['nova']
        else:
            return self.stack.get_availability_zones()


class ParamRef(function.Function):
    '''
    A function for resolving parameter references.

    Takes the form::

        { "Ref" : "<param_name>" }
    '''

    def __init__(self, stack, fn_name, args):
        super(ParamRef, self).__init__(stack, fn_name, args)

        self.parameters = self.stack.parameters

    def result(self):
        param_name = function.resolve(self.args)

        try:
            return self.parameters[param_name]
        except (KeyError, ValueError):
            raise exception.UserParameterMissing(key=param_name)


class ResourceRef(function.Function):
    '''
    A function for resolving resource references.

    Takes the form::

        { "Ref" : "<resource_name>" }
    '''

    def _resource(self):
        resource_name = function.resolve(self.args)

        return self.stack[resource_name]

    def result(self):
        return self._resource().FnGetRefId()


def Ref(stack, fn_name, args):
    '''
    A function for resolving parameters or resource references.

    Takes the form::

        { "Ref" : "<param_name>" }

    or::

        { "Ref" : "<resource_name>" }
    '''
    if args in stack:
        RefClass = ResourceRef
    else:
        RefClass = ParamRef
    return RefClass(stack, fn_name, args)


class GetAtt(function.Function):
    '''
    A function for resolving resource attributes.

    Takes the form::

        { "Fn::GetAtt" : [ "<resource_name>",
                           "<attribute_name" ] }
    '''

    def __init__(self, stack, fn_name, args):
        super(GetAtt, self).__init__(stack, fn_name, args)

        self._resource_name, self._attribute = self._parse_args()

    def _parse_args(self):
        try:
            resource_name, attribute = self.args
        except ValueError:
            raise ValueError(_('Arguments to "%s" must be of the form '
                               '[resource_name, attribute]') % self.fn_name)

        return resource_name, attribute

    def _resource(self):
        resource_name = function.resolve(self._resource_name)

        try:
            return self.stack[resource_name]
        except KeyError:
            raise exception.InvalidTemplateAttribute(
                resource=resource_name,
                key=function.resolve(self._attribute))

    def result(self):
        attribute = function.resolve(self._attribute)

        r = self._resource()
        if (r.status in (r.IN_PROGRESS, r.COMPLETE) and
                r.action in (r.CREATE, r.ADOPT, r.SUSPEND, r.RESUME,
                             r.UPDATE)):
            return r.FnGetAtt(attribute)
        else:
            return None


class Select(function.Function):
    '''
    A function for selecting an item from a list or map.

    Takes the form (for a list lookup)::

        { "Fn::Select" : [ "<index>", [ "<value_1>", "<value_2>", ... ] ] }

    Takes the form (for a map lookup)::

        { "Fn::Select" : [ "<index>", { "<key_1>": "<value_1>", ... } ] }

    If the selected index is not found, this function resolves to an empty
    string.
    '''

    def __init__(self, stack, fn_name, args):
        super(Select, self).__init__(stack, fn_name, args)

        try:
            self._lookup, self._strings = self.args
        except ValueError:
            raise ValueError(_('Arguments to "%s" must be of the form '
                               '[index, collection]') % self.fn_name)

    def result(self):
        index = function.resolve(self._lookup)

        try:
            index = int(index)
        except (ValueError, TypeError):
            pass

        strings = function.resolve(self._strings)

        if strings == '':
            # an empty string is a common response from other
            # functions when result is not currently available.
            # Handle by returning an empty string
            return ''

        if isinstance(strings, basestring):
            # might be serialized json.
            try:
                strings = json.loads(strings)
            except ValueError as json_ex:
                fmt_data = {'fn_name': self.fn_name,
                            'err': json_ex}
                raise ValueError(_('"%(fn_name)s": %(err)s') % fmt_data)

        if isinstance(strings, collections.Mapping):
            if not isinstance(index, basestring):
                raise TypeError(_('Index to "%s" must be a string') %
                                self.fn_name)
            return strings.get(index, '')

        if (isinstance(strings, collections.Sequence) and
                not isinstance(strings, basestring)):
            if not isinstance(index, (int, long)):
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


class Join(function.Function):
    '''
    A function for joining strings.

    Takes the form::

        { "Fn::Join" : [ "<delim>", [ "<string_1>", "<string_2>", ... ] }

    And resolves to::

        "<string_1><delim><string_2><delim>..."
    '''

    def __init__(self, stack, fn_name, args):
        super(Join, self).__init__(stack, fn_name, args)

        example = '"%s" : [ " ", [ "str1", "str2"]]' % self.fn_name
        fmt_data = {'fn_name': self.fn_name,
                    'example': example}

        if isinstance(self.args, (basestring, collections.Mapping)):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % fmt_data)

        try:
            self._delim, self._strings = self.args
        except ValueError:
            raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                               'should be: %(example)s') % fmt_data)

    def result(self):
        strings = function.resolve(self._strings)
        if (isinstance(strings, basestring) or
                not isinstance(strings, collections.Sequence)):
            raise TypeError(_('"%s" must operate on a list') % self.fn_name)

        delim = function.resolve(self._delim)
        if not isinstance(delim, basestring):
            raise TypeError(_('"%s" delimiter must be a string') %
                            self.fn_name)

        def ensure_string(s):
            if s is None:
                return ''
            if not isinstance(s, basestring):
                raise TypeError(_('Items to join must be strings'))
            return s

        return delim.join(ensure_string(s) for s in strings)


class Split(function.Function):
    '''
    A function for splitting strings.

    Takes the form::

        { "Fn::Split" : [ "<delim>", "<string_1><delim><string_2>..." ] }

    And resolves to::

        [ "<string_1>", "<string_2>", ... ]
    '''

    def __init__(self, stack, fn_name, args):
        super(Split, self).__init__(stack, fn_name, args)

        example = '"%s" : [ ",", "str1,str2"]]' % self.fn_name
        fmt_data = {'fn_name': self.fn_name,
                    'example': example}

        if isinstance(self.args, (basestring, collections.Mapping)):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % fmt_data)

        try:
            self._delim, self._strings = self.args
        except ValueError:
            raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                               'should be: %(example)s') % fmt_data)

    def result(self):
        strings = function.resolve(self._strings)

        if not isinstance(self._delim, basestring):
            raise TypeError(_("Delimiter for %s must be string") %
                            self.fn_name)
        if not isinstance(strings, basestring):
            raise TypeError(_("String to split must be string; got %s") %
                            type(strings))

        return strings.split(self._delim)


class Replace(function.Function):
    '''
    A function for performing string subsitutions.

    Takes the form::

        { "Fn::Replace" : [
            { "<key_1>": "<value_1>", "<key_2>": "<value_2>", ... },
            "<key_1> <key_2>"
          ] }

    And resolves to::

        "<value_1> <value_2>"

    This is implemented using python str.replace on each key. The order in
    which replacements are performed is undefined.
    '''

    def __init__(self, stack, fn_name, args):
        super(Replace, self).__init__(stack, fn_name, args)

        self._mapping, self._string = self._parse_args()

        if not isinstance(self._mapping, collections.Mapping):
            raise TypeError(_('"%s" parameters must be a mapping') %
                            self.fn_name)

    def _parse_args(self):

        example = ('{"%s": '
                   '[ {"$var1": "foo", "%%var2%%": "bar"}, '
                   '"$var1 is %%var2%%"]}' % self.fn_name)
        fmt_data = {'fn_name': self.fn_name,
                    'example': example}

        if isinstance(self.args, (basestring, collections.Mapping)):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % fmt_data)

        try:
            mapping, string = self.args
        except ValueError:
            raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                               'should be: %(example)s') % fmt_data)
        else:
            return mapping, string

    def result(self):
        template = function.resolve(self._string)
        mapping = function.resolve(self._mapping)

        if not isinstance(template, basestring):
            raise TypeError(_('"%s" template must be a string') % self.fn_name)

        if not isinstance(mapping, collections.Mapping):
            raise TypeError(_('"%s" params must be a map') % self.fn_name)

        def replace(string, change):
            placeholder, value = change

            if not isinstance(placeholder, basestring):
                raise TypeError(_('"%s" param placeholders must be strings') %
                                self.fn_name)

            if value is None:
                value = ''

            if not isinstance(value, (basestring, int, long, float, bool)):
                raise TypeError(_('"%s" params must be strings or numbers') %
                                self.fn_name)

            return string.replace(placeholder, unicode(value))

        return reduce(replace, mapping.iteritems(), template)


class Base64(function.Function):
    '''
    A placeholder function for converting to base64.

    Takes the form::

        { "Fn::Base64" : "<string>" }

    This function actually performs no conversion. It is included for the
    benefit of templates that convert UserData to Base64. Heat accepts UserData
    in plain text.
    '''

    def result(self):
        resolved = function.resolve(self.args)
        if not isinstance(resolved, basestring):
            raise TypeError(_('"%s" argument must be a string') % self.fn_name)
        return resolved


class MemberListToMap(function.Function):
    '''
    A function for converting lists containing enumerated keys and values to
    a mapping.

    Takes the form::

        { 'Fn::MemberListToMap' : [ 'Name',
                                    'Value',
                                    [ '.member.0.Name=<key_0>',
                                      '.member.0.Value=<value_0>',
                                      ... ] ] }

    And resolves to::

        { "<key_0>" : "<value_0>", ... }

    The first two arguments are the names of the key and value.
    '''

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

        if not isinstance(self._keyname, basestring):
            raise TypeError(_('%s Key Name must be a string') % self.fn_name)

        if not isinstance(self._valuename, basestring):
            raise TypeError(_('%s Value Name must be a string') % self.fn_name)

    def result(self):
        member_list = function.resolve(self._list)

        if not isinstance(member_list, collections.Iterable):
            raise TypeError(_('Member list must be a list'))

        def item(s):
            if not isinstance(s, basestring):
                raise TypeError(_("Member list items must be strings"))
            return s.split('=', 1)

        partials = dict(item(s) for s in member_list)
        return aws_utils.extract_param_pairs(partials,
                                             prefix='',
                                             keyname=self._keyname,
                                             valuename=self._valuename)


class ResourceFacade(function.Function):
    '''
    A function for obtaining data from the facade resource from within the
    corresponding provider template.

    Takes the form::

        { "Fn::ResourceFacade": "<attribute_type>" }

    where the valid attribute types are "Metadata", "DeletionPolicy" and
    "UpdatePolicy".
    '''

    _RESOURCE_ATTRIBUTES = (
        METADATA, DELETION_POLICY, UPDATE_POLICY,
    ) = (
        'Metadata', 'DeletionPolicy', 'UpdatePolicy'
    )

    def __init__(self, stack, fn_name, args):
        super(ResourceFacade, self).__init__(stack, fn_name, args)

        if self.args not in self._RESOURCE_ATTRIBUTES:
            fmt_data = {'fn_name': self.fn_name,
                        'allowed': ', '.join(self._RESOURCE_ATTRIBUTES)}
            raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                               'should be one of: %(allowed)s') % fmt_data)

    def result(self):
        attr = function.resolve(self.args)

        if attr == self.METADATA:
            return self.stack.parent_resource.metadata
        elif attr == self.UPDATE_POLICY:
            up = self.stack.parent_resource.t.get('UpdatePolicy', {})
            return function.resolve(up)
        elif attr == self.DELETION_POLICY:
            dp = self.stack.parent_resource.t.get('DeletionPolicy', 'Delete')
            return function.resolve(dp)


def function_mapping(version_key, version):
    if version_key == 'AWSTemplateFormatVersion':
        return {
            'Fn::FindInMap': FindInMap,
            'Fn::GetAZs': GetAZs,
            'Ref': Ref,
            'Fn::GetAtt': GetAtt,
            'Fn::Select': Select,
            'Fn::Join': Join,
            'Fn::Base64': Base64,
        }
    elif version_key != 'HeatTemplateFormatVersion':
        return {}

    if version == '2012-12-12':
        return {
            'Fn::FindInMap': FindInMap,
            'Fn::GetAZs': GetAZs,
            'Ref': Ref,
            'Fn::GetAtt': GetAtt,
            'Fn::Select': Select,
            'Fn::Join': Join,
            'Fn::Split': Split,
            'Fn::Replace': Replace,
            'Fn::Base64': Base64,
            'Fn::MemberListToMap': MemberListToMap,
            'Fn::ResourceFacade': ResourceFacade,
        }

    return {}
