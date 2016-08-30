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

from oslo_serialization import jsonutils
import six

from heat.api.aws import utils as aws_utils
from heat.common import exception
from heat.common.i18n import _
from heat.engine import function


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


class ResourceRef(function.Function):
    """A function for resolving resource references.

    Takes the form::

        { "Ref" : "<resource_name>" }
    """

    def _resource(self, path='unknown'):
        resource_name = function.resolve(self.args)

        try:
            return self.stack[resource_name]
        except KeyError:
            raise exception.InvalidTemplateReference(resource=resource_name,
                                                     key=path)

    def dependencies(self, path):
        return itertools.chain(super(ResourceRef, self).dependencies(path),
                               [self._resource(path)])

    def result(self):
        return self._resource().FnGetRefId()


def Ref(stack, fn_name, args):
    """A function for resolving parameters or resource references.

    Takes the form::

        { "Ref" : "<param_name>" }

    or::

        { "Ref" : "<resource_name>" }
    """
    if args in stack:
        RefClass = ResourceRef
    else:
        RefClass = ParamRef
    return RefClass(stack, fn_name, args)


class GetAtt(function.Function):
    """A function for resolving resource attributes.

    Takes the form::

        { "Fn::GetAtt" : [ "<resource_name>",
                           "<attribute_name" ] }
    """

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

    def _resource(self, path='unknown'):
        resource_name = function.resolve(self._resource_name)

        try:
            return self.stack[resource_name]
        except KeyError:
            raise exception.InvalidTemplateReference(resource=resource_name,
                                                     key=path)

    def dep_attrs(self, resource_name):
        if self._resource().name == resource_name:
            attrs = [function.resolve(self._attribute)]
        else:
            attrs = []
        return itertools.chain(super(GetAtt, self).dep_attrs(resource_name),
                               attrs)

    def dependencies(self, path):
        return itertools.chain(super(GetAtt, self).dependencies(path),
                               [self._resource(path)])

    def _allow_without_attribute_name(self):
        return False

    def validate(self):
        super(GetAtt, self).validate()
        res = self._resource()

        if self._allow_without_attribute_name():
            # if allow without attribute_name, then don't check
            # when attribute_name is None
            if self._attribute is None:
                return

        attr = function.resolve(self._attribute)
        from heat.engine import resource
        if (type(res).get_attribute == resource.Resource.get_attribute and
                attr not in res.attributes_schema):
            raise exception.InvalidTemplateAttribute(
                resource=self._resource_name, key=attr)

    def result(self):
        attribute = function.resolve(self._attribute)

        r = self._resource()
        if r.action in (r.CREATE, r.ADOPT, r.SUSPEND, r.RESUME,
                        r.UPDATE, r.ROLLBACK, r.SNAPSHOT, r.CHECK):
            return r.FnGetAtt(attribute)
        # NOTE(sirushtim): Add r.INIT to states above once convergence
        # is the default.
        elif r.stack.has_cache_data(r.name) and r.action == r.INIT:
            return r.FnGetAtt(attribute)
        else:
            return None


class Select(function.Function):
    """A function for selecting an item from a list or map.

    Takes the form (for a list lookup)::

        { "Fn::Select" : [ "<index>", [ "<value_1>", "<value_2>", ... ] ] }

    Takes the form (for a map lookup)::

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


class Join(function.Function):
    """A function for joining strings.

    Takes the form::

        { "Fn::Join" : [ "<delim>", [ "<string_1>", "<string_2>", ... ] ] }

    And resolves to::

        "<string_1><delim><string_2><delim>..."
    """

    def __init__(self, stack, fn_name, args):
        super(Join, self).__init__(stack, fn_name, args)

        example = '"%s" : [ " ", [ "str1", "str2"]]' % self.fn_name
        fmt_data = {'fn_name': self.fn_name,
                    'example': example}

        if not isinstance(self.args, list):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % fmt_data)

        try:
            self._delim, self._strings = self.args
        except ValueError:
            raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                               'should be: %(example)s') % fmt_data)

    def result(self):
        strings = function.resolve(self._strings)
        if strings is None:
            strings = []
        if (isinstance(strings, six.string_types) or
                not isinstance(strings, collections.Sequence)):
            raise TypeError(_('"%s" must operate on a list') % self.fn_name)

        delim = function.resolve(self._delim)
        if not isinstance(delim, six.string_types):
            raise TypeError(_('"%s" delimiter must be a string') %
                            self.fn_name)

        def ensure_string(s):
            if s is None:
                return ''
            if not isinstance(s, six.string_types):
                raise TypeError(
                    _('Items to join must be strings not %s'
                      ) % (repr(s)[:200]))
            return s

        return delim.join(ensure_string(s) for s in strings)


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


class Replace(function.Function):
    """A function for performing string substitutions.

    Takes the form::

        { "Fn::Replace" : [
            { "<key_1>": "<value_1>", "<key_2>": "<value_2>", ... },
            "<key_1> <key_2>"
          ] }

    And resolves to::

        "<value_1> <value_2>"

    This is implemented using python str.replace on each key. Longer keys are
    substituted before shorter ones, but the order in which replacements are
    performed is otherwise undefined.
    """

    def __init__(self, stack, fn_name, args):
        super(Replace, self).__init__(stack, fn_name, args)

        self._mapping, self._string = self._parse_args()
        if not isinstance(self._mapping,
                          (collections.Mapping, function.Function)):
            raise TypeError(_('"%s" parameters must be a mapping') %
                            self.fn_name)

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

    def result(self):
        template = function.resolve(self._string)
        mapping = function.resolve(self._mapping)

        if not isinstance(template, six.string_types):
            raise TypeError(_('"%s" template must be a string') % self.fn_name)

        if not isinstance(mapping, collections.Mapping):
            raise TypeError(_('"%s" params must be a map') % self.fn_name)

        def replace(string, change):
            placeholder, value = change

            if not isinstance(placeholder, six.string_types):
                raise TypeError(_('"%s" param placeholders must be strings') %
                                self.fn_name)

            if value is None:
                value = ''

            if not isinstance(value,
                              (six.string_types, six.integer_types,
                               float, bool)):
                raise TypeError(_('"%s" params must be strings or numbers') %
                                self.fn_name)

            return string.replace(placeholder, six.text_type(value))

        mapping = collections.OrderedDict(sorted(mapping.items(),
                                                 key=lambda t: len(t[0]),
                                                 reverse=True))
        return six.moves.reduce(replace, six.iteritems(mapping), template)


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


class ResourceFacade(function.Function):
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
            return self.stack.parent_resource.metadata_get()
        elif attr == self.UPDATE_POLICY:
            up = self.stack.parent_resource.t._update_policy or {}
            return function.resolve(up)
        elif attr == self.DELETION_POLICY:
            return self.stack.parent_resource.t.deletion_policy()


class Not(function.Macro):
    """A function acts as a NOT operator.

    Takes the form::

        { "Fn::Not" : [condition] }

    Returns true for a condition that evaluates to false or
    returns false for a condition that evaluates to true.
    """

    def parse_args(self, parse_func):
        try:
            if (not self.args or
                    not isinstance(self.args, collections.Sequence) or
                    isinstance(self.args, six.string_types)):
                raise ValueError()
            if len(self.args) != 1:
                raise ValueError()
            condition = self.args[0]
        except ValueError:
            msg = _('Arguments to "%s" must be of the form: '
                    '[condition]')
            raise ValueError(msg % self.fn_name)

        if isinstance(condition, six.string_types):
            cd_snippets = self.template.get_condition_definitions()
            if condition in cd_snippets:
                condition = cd_snippets[condition]

        return parse_func(condition)

    def result(self):
        resolved_value = function.resolve(self.parsed)
        if not isinstance(resolved_value, bool):
            msg = _('The condition value should be boolean, '
                    'after resolved the value is: %s')
            raise ValueError(msg % resolved_value)
        return not resolved_value
