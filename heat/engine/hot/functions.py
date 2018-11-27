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
import hashlib
import itertools

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
import six
from six.moves.urllib import parse as urlparse
import yaql
from yaql.language import exceptions

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import function


LOG = logging.getLogger(__name__)

opts = [
    cfg.IntOpt('limit_iterators',
               default=200,
               help=_('The maximum number of elements in collection '
                      'expression can take for its evaluation.')),
    cfg.IntOpt('memory_quota',
               default=10000,
               help=_('The maximum size of memory in bytes that '
                      'expression can take for its evaluation.'))
]
cfg.CONF.register_opts(opts, group='yaql')


class GetParam(function.Function):
    """A function for resolving parameter references.

    Takes the form::

        get_param: <param_name>

    or::

        get_param:
          - <param_name>
          - <path1>
          - ...
    """

    def __init__(self, stack, fn_name, args):
        super(GetParam, self).__init__(stack, fn_name, args)

        if self.stack is not None:
            self.parameters = self.stack.parameters
        else:
            self.parameters = None

    def result(self):
        assert self.parameters is not None, "No stack definition in Function"

        args = function.resolve(self.args)

        if not args:
            raise ValueError(_('Function "%s" must have arguments') %
                             self.fn_name)

        if isinstance(args, six.string_types):
            param_name = args
            path_components = []
        elif isinstance(args, collections.Sequence):
            param_name = args[0]
            path_components = args[1:]
        else:
            raise TypeError(_('Argument to "%s" must be string or list') %
                            self.fn_name)

        if not isinstance(param_name, six.string_types):
            raise TypeError(_('Parameter name in "%s" must be string') %
                            self.fn_name)

        try:
            parameter = self.parameters[param_name]
        except KeyError:
            raise exception.UserParameterMissing(key=param_name)

        def get_path_component(collection, key):
            if not isinstance(collection, (collections.Mapping,
                                           collections.Sequence)):
                raise TypeError(_('"%s" can\'t traverse path') % self.fn_name)

            if not isinstance(key, (six.string_types, int)):
                raise TypeError(_('Path components in "%s" '
                                  'must be strings') % self.fn_name)

            if isinstance(collection, collections.Sequence
                          ) and isinstance(key, six.string_types):
                try:
                    key = int(key)
                except ValueError:
                    raise TypeError(_("Path components in '%s' "
                                      "must be a string that can be "
                                      "parsed into an "
                                      "integer.") % self.fn_name)
            return collection[key]

        try:
            return six.moves.reduce(get_path_component, path_components,
                                    parameter)
        except (KeyError, IndexError, TypeError):
            return ''


class GetResource(function.Function):
    """A function for resolving resource references.

    Takes the form::

        get_resource: <resource_name>
    """

    def _resource(self, path='unknown'):
        resource_name = function.resolve(self.args)

        try:
            return self.stack[resource_name]
        except KeyError:
            raise exception.InvalidTemplateReference(resource=resource_name,
                                                     key=path)

    def dependencies(self, path):
        return itertools.chain(super(GetResource, self).dependencies(path),
                               [self._resource(path)])

    def result(self):
        return self._resource().FnGetRefId()


class GetAttThenSelect(function.Function):
    """A function for resolving resource attributes.

    Takes the form::

        get_attr:
          - <resource_name>
          - <attribute_name>
          - <path1>
          - ...
    """

    def __init__(self, stack, fn_name, args):
        super(GetAttThenSelect, self).__init__(stack, fn_name, args)

        (self._resource_name,
         self._attribute,
         self._path_components) = self._parse_args()

    def _parse_args(self):
        if (not isinstance(self.args, collections.Sequence) or
                isinstance(self.args, six.string_types)):
            raise TypeError(_('Argument to "%s" must be a list') %
                            self.fn_name)

        if len(self.args) < 2:
            raise ValueError(_('Arguments to "%s" must be of the form '
                               '[resource_name, attribute, (path), ...]') %
                             self.fn_name)

        return self.args[0], self.args[1], self.args[2:]

    def _res_name(self):
        return function.resolve(self._resource_name)

    def _resource(self, path='unknown'):
        resource_name = self._res_name()

        try:
            return self.stack[resource_name]
        except KeyError:
            raise exception.InvalidTemplateReference(resource=resource_name,
                                                     key=path)

    def _attr_path(self):
        return function.resolve(self._attribute)

    def dep_attrs(self, resource_name):
        if self._res_name() == resource_name:
            try:
                attrs = [self._attr_path()]
            except Exception as exc:
                LOG.debug("Ignoring exception calculating required attributes"
                          ": %s %s", type(exc).__name__, six.text_type(exc))
                attrs = []
        else:
            attrs = []
        return itertools.chain(super(GetAttThenSelect,
                                     self).dep_attrs(resource_name),
                               attrs)

    def all_dep_attrs(self):
        try:
            attrs = [(self._res_name(), self._attr_path())]
        except Exception:
            attrs = []
        return itertools.chain(function.all_dep_attrs(self.args), attrs)

    def dependencies(self, path):
        return itertools.chain(super(GetAttThenSelect,
                                     self).dependencies(path),
                               [self._resource(path)])

    def _allow_without_attribute_name(self):
        return False

    def validate(self):
        super(GetAttThenSelect, self).validate()
        res = self._resource()

        if self._allow_without_attribute_name():
            # if allow without attribute_name, then don't check
            # when attribute_name is None
            if self._attribute is None:
                return

        attr = function.resolve(self._attribute)
        if attr not in res.attributes_schema:
            raise exception.InvalidTemplateAttribute(
                resource=self._resource_name, key=attr)

    def _result_ready(self, r):
        if r.action in (r.CREATE, r.ADOPT, r.SUSPEND, r.RESUME,
                        r.UPDATE, r.ROLLBACK, r.SNAPSHOT, r.CHECK):
            return True

        return False

    def result(self):
        attr_name = function.resolve(self._attribute)

        resource = self._resource()
        if self._result_ready(resource):
            attribute = resource.FnGetAtt(attr_name)
        else:
            attribute = None

        if attribute is None:
            return None

        path_components = function.resolve(self._path_components)
        return attributes.select_from_attribute(attribute, path_components)


class GetAtt(GetAttThenSelect):
    """A function for resolving resource attributes.

    Takes the form::

        get_attr:
          - <resource_name>
          - <attribute_name>
          - <path1>
          - ...
    """

    def result(self):
        path_components = function.resolve(self._path_components)
        attribute = function.resolve(self._attribute)

        resource = self._resource()
        if self._result_ready(resource):
            return resource.FnGetAtt(attribute, *path_components)
        else:
            return None

    def _attr_path(self):
        path = function.resolve(self._path_components)
        attr = function.resolve(self._attribute)
        if path:
            return tuple([attr] + path)
        else:
            return attr


class GetAttAllAttributes(GetAtt):
    """A function for resolving resource attributes.

    Takes the form::

        get_attr:
          - <resource_name>
          - <attributes_name>
          - <path1>
          - ...

    where <attributes_name> and <path1>, ... are optional arguments. If there
    is no <attributes_name>, result will be dict of all resource's attributes.
    Else function returns resolved resource's attribute.
    """

    def _parse_args(self):
        if not self.args:
            raise ValueError(_('Arguments to "%s" can be of the next '
                               'forms: [resource_name] or '
                               '[resource_name, attribute, (path), ...]'
                               ) % self.fn_name)
        elif isinstance(self.args, collections.Sequence):
            if len(self.args) > 1:
                return super(GetAttAllAttributes, self)._parse_args()
            else:
                return self.args[0], None, []
        else:
            raise TypeError(_('Argument to "%s" must be a list') %
                            self.fn_name)

    def _attr_path(self):
        if self._attribute is None:
            return attributes.ALL_ATTRIBUTES
        return super(GetAttAllAttributes, self)._attr_path()

    def result(self):
        if self._attribute is None:
            r = self._resource()
            if (r.status in (r.IN_PROGRESS, r.COMPLETE) and
                    r.action in (r.CREATE, r.ADOPT, r.SUSPEND, r.RESUME,
                                 r.UPDATE, r.CHECK, r.SNAPSHOT)):
                return r.FnGetAtts()
            else:
                return None
        else:
            return super(GetAttAllAttributes, self).result()

    def _allow_without_attribute_name(self):
        return True


class Replace(function.Function):
    """A function for performing string substitutions.

    Takes the form::

        str_replace:
          template: <key_1> <key_2>
          params:
            <key_1>: <value_1>
            <key_2>: <value_2>
            ...

    And resolves to::

        "<value_1> <value_2>"

    When keys overlap in the template, longer matches are preferred. For keys
    of equal length, lexicographically smaller keys are preferred.
    """

    _strict = False
    _allow_empty_value = True

    def __init__(self, stack, fn_name, args):
        super(Replace, self).__init__(stack, fn_name, args)

        self._mapping, self._string = self._parse_args()
        if not isinstance(self._mapping,
                          (collections.Mapping, function.Function)):
            raise TypeError(_('"%s" parameters must be a mapping') %
                            self.fn_name)

    def _parse_args(self):
        if not isinstance(self.args, collections.Mapping):
            raise TypeError(_('Arguments to "%s" must be a map') %
                            self.fn_name)

        try:
            mapping = self.args['params']
            string = self.args['template']
        except (KeyError, TypeError):
            example = _('''%s:
              template: This is var1 template var2
              params:
                var1: a
                var2: string''') % self.fn_name
            raise KeyError(_('"%(fn_name)s" syntax should be %(example)s') %
                           {'fn_name': self.fn_name, 'example': example})
        else:
            return mapping, string

    def _validate_replacement(self, value, param):
        if value is None:
            return ''

        if not isinstance(value,
                          (six.string_types, six.integer_types,
                           float, bool)):
            raise TypeError(_('"%(name)s" params must be strings or numbers, '
                              'param %(param)s is not valid') %
                            {'name': self.fn_name, 'param': param})

        return six.text_type(value)

    def result(self):
        template = function.resolve(self._string)
        mapping = function.resolve(self._mapping)

        if self._strict:
            unreplaced_keys = set(mapping)

        if not isinstance(template, six.string_types):
            raise TypeError(_('"%s" template must be a string') % self.fn_name)

        if not isinstance(mapping, collections.Mapping):
            raise TypeError(_('"%s" params must be a map') % self.fn_name)

        def replace(strings, keys):
            if not keys:
                return strings

            placeholder = keys[0]
            if not isinstance(placeholder, six.string_types):
                raise TypeError(_('"%s" param placeholders must be strings') %
                                self.fn_name)

            remaining_keys = keys[1:]
            value = self._validate_replacement(mapping[placeholder],
                                               placeholder)

            def string_split(s):
                ss = s.split(placeholder)
                if self._strict and len(ss) > 1:
                    unreplaced_keys.discard(placeholder)
                return ss

            return [value.join(replace(string_split(s),
                                       remaining_keys)) for s in strings]

        ret_val = replace([template], sorted(sorted(mapping),
                                             key=len, reverse=True))[0]
        if self._strict and len(unreplaced_keys) > 0:
            raise ValueError(
                _("The following params were not found in the template: %s") %
                ','.join(sorted(sorted(unreplaced_keys),
                                key=len, reverse=True)))
        return ret_val


class ReplaceJson(Replace):
    """A function for performing string substitutions.

    Takes the form::

        str_replace:
          template: <key_1> <key_2>
          params:
            <key_1>: <value_1>
            <key_2>: <value_2>
            ...

    And resolves to::

        "<value_1> <value_2>"

    When keys overlap in the template, longer matches are preferred. For keys
    of equal length, lexicographically smaller keys are preferred.

    Non-string param values (e.g maps or lists) are serialized as JSON before
    being substituted in.
    """

    def _validate_replacement(self, value, param):

        def _raise_empty_param_value_error():
            raise ValueError(
                _('%(name)s has an undefined or empty value for param '
                  '%(param)s, must be a defined non-empty value') %
                {'name': self.fn_name, 'param': param})

        if value is None:
            if self._allow_empty_value:
                return ''
            else:
                _raise_empty_param_value_error()

        if not isinstance(value, (six.string_types, six.integer_types,
                                  float, bool)):
            if isinstance(value, (collections.Mapping, collections.Sequence)):
                if not self._allow_empty_value and len(value) == 0:
                    _raise_empty_param_value_error()
                try:
                    return jsonutils.dumps(value, default=None, sort_keys=True)
                except TypeError:
                    raise TypeError(_('"%(name)s" params must be strings, '
                                      'numbers, list or map. '
                                      'Failed to json serialize %(value)s'
                                      ) % {'name': self.fn_name,
                                           'value': value})
            else:
                raise TypeError(_('"%s" params must be strings, numbers, '
                                  'list or map.') % self.fn_name)

        ret_value = six.text_type(value)
        if not self._allow_empty_value and not ret_value:
            _raise_empty_param_value_error()
        return ret_value


class ReplaceJsonStrict(ReplaceJson):
    """A function for performing string substitutions.

    str_replace_strict is identical to the str_replace function, only
    a ValueError is raised if any of the params are not present in
    the template.
    """
    _strict = True


class ReplaceJsonVeryStrict(ReplaceJsonStrict):
    """A function for performing string substitutions.

    str_replace_vstrict is identical to the str_replace_strict
    function, only a ValueError is raised if any of the params are
    None or empty.
    """
    _allow_empty_value = False


class GetFile(function.Function):
    """A function for including a file inline.

    Takes the form::

        get_file: <file_key>

    And resolves to the content stored in the files dictionary under the given
    key.
    """

    def __init__(self, stack, fn_name, args):
        super(GetFile, self).__init__(stack, fn_name, args)

        self.files = self.stack.t.files if self.stack is not None else None

    def result(self):
        assert self.files is not None, "No stack definition in Function"

        args = function.resolve(self.args)
        if not (isinstance(args, six.string_types)):
            raise TypeError(_('Argument to "%s" must be a string') %
                            self.fn_name)

        f = self.files.get(args)
        if f is None:
            fmt_data = {'fn_name': self.fn_name,
                        'file_key': args}
            raise ValueError(_('No content found in the "files" section for '
                               '%(fn_name)s path: %(file_key)s') % fmt_data)
        return f


class Join(function.Function):
    """A function for joining strings.

    Takes the form::

        list_join:
          - <delim>
          - - <string_1>
            - <string_2>
            - ...

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


class JoinMultiple(function.Function):
    """A function for joining one or more lists of strings.

    Takes the form::

        list_join:
          - <delim>
          - - <string_1>
            - <string_2>
            - ...
          - - ...

    And resolves to::

        "<string_1><delim><string_2><delim>..."

    Optionally multiple lists may be specified, which will also be joined.
    """

    def __init__(self, stack, fn_name, args):
        super(JoinMultiple, self).__init__(stack, fn_name, args)
        example = '"%s" : [ " ", [ "str1", "str2"] ...]' % fn_name
        fmt_data = {'fn_name': fn_name,
                    'example': example}

        if not isinstance(args, list):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % fmt_data)

        try:
            self._delim = args[0]
            self._joinlists = args[1:]
            if len(self._joinlists) < 1:
                raise ValueError
        except (IndexError, ValueError):
            raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                               'should be: %(example)s') % fmt_data)

    def result(self):
        r_joinlists = function.resolve(self._joinlists)

        strings = []
        for jl in r_joinlists:
            if jl:
                if (isinstance(jl, six.string_types) or
                        not isinstance(jl, collections.Sequence)):
                    raise TypeError(_('"%s" must operate on '
                                      'a list') % self.fn_name)

                strings += jl

        delim = function.resolve(self._delim)
        if not isinstance(delim, six.string_types):
            raise TypeError(_('"%s" delimiter must be a string') %
                            self.fn_name)

        def ensure_string(s):
            msg = _('Items to join must be string, map or list not %s'
                    ) % (repr(s)[:200])
            if s is None:
                return ''
            elif isinstance(s, six.string_types):
                return s
            elif isinstance(s, (collections.Mapping, collections.Sequence)):
                try:
                    return jsonutils.dumps(s, default=None, sort_keys=True)
                except TypeError:
                    msg = _('Items to join must be string, map or list. '
                            '%s failed json serialization'
                            ) % (repr(s)[:200])

            raise TypeError(msg)

        return delim.join(ensure_string(s) for s in strings)


class MapMerge(function.Function):
    """A function for merging maps.

    Takes the form::

        map_merge:
          - <k1>: <v1>
            <k2>: <v2>
          - <k1>: <v3>

    And resolves to::

        {"<k1>": "<v3>", "<k2>": "<v2>"}

    """

    def __init__(self, stack, fn_name, args):
        super(MapMerge, self).__init__(stack, fn_name, args)
        example = (_('"%s" : [ { "key1": "val1" }, { "key2": "val2" } ]')
                   % fn_name)
        self.fmt_data = {'fn_name': fn_name, 'example': example}

    def result(self):
        args = function.resolve(self.args)

        if not isinstance(args, collections.Sequence):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % self.fmt_data)

        def ensure_map(m):
            if m is None:
                return {}
            elif isinstance(m, collections.Mapping):
                return m
            else:
                msg = _('Incorrect arguments: Items to merge must be maps.')
                raise TypeError(msg)

        ret_map = {}
        for m in args:
            ret_map.update(ensure_map(m))
        return ret_map


class MapReplace(function.Function):
    """A function for performing substitutions on maps.

    Takes the form::

        map_replace:
          - <k1>: <v1>
            <k2>: <v2>
          - keys:
              <k1>: <K1>
            values:
              <v2>: <V2>

    And resolves to::

        {"<K1>": "<v1>", "<k2>": "<V2>"}

    """

    def __init__(self, stack, fn_name, args):
        super(MapReplace, self).__init__(stack, fn_name, args)
        example = (_('"%s" : [ { "key1": "val1" }, '
                     '{"keys": {"key1": "key2"}, "values": {"val1": "val2"}}]')
                   % fn_name)
        self.fmt_data = {'fn_name': fn_name, 'example': example}

    def result(self):
        args = function.resolve(self.args)

        def ensure_map(m):
            if m is None:
                return {}
            elif isinstance(m, collections.Mapping):
                return m
            else:
                msg = (_('Incorrect arguments: to "%(fn_name)s", arguments '
                         'must be a list of maps. Example:  %(example)s')
                       % self.fmt_data)
                raise TypeError(msg)

        try:
            in_map = ensure_map(args.pop(0))
            repl_map = ensure_map(args.pop(0))
            if args != []:
                raise IndexError
        except (IndexError, AttributeError):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % self.fmt_data)

        for k in repl_map:
            if k not in ('keys', 'values'):
                raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                                   'should be: %(example)s') % self.fmt_data)

        repl_keys = ensure_map(repl_map.get('keys', {}))
        repl_values = ensure_map(repl_map.get('values', {}))
        ret_map = {}
        for k, v in six.iteritems(in_map):
            key = repl_keys.get(k)
            if key is None:
                key = k
            elif key in in_map and key != k:
                # Keys collide
                msg = _('key replacement %s collides with '
                        'a key in the input map')
                raise ValueError(msg % key)
            elif key in ret_map:
                # Keys collide
                msg = _('key replacement %s collides with '
                        'a key in the output map')
                raise ValueError(msg % key)
            try:
                value = repl_values.get(v, v)
            except TypeError:
                # If the value is unhashable, we get here
                value = v
            ret_map[key] = value
        return ret_map


class ResourceFacade(function.Function):
    """A function for retrieving data in a parent provider template.

    A function for obtaining data from the facade resource from within the
    corresponding provider template.

    Takes the form::

        resource_facade: <attribute_type>

    where the valid attribute types are "metadata", "deletion_policy" and
    "update_policy".
    """

    _RESOURCE_ATTRIBUTES = (
        METADATA, DELETION_POLICY, UPDATE_POLICY,
    ) = (
        'metadata', 'deletion_policy', 'update_policy'
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


class Removed(function.Function):
    """This function existed in previous versions of HOT, but has been removed.

    Check the HOT guide for an equivalent native function.
    """

    def validate(self):
        exp = (_("The function %s is not supported in this version of HOT.") %
               self.fn_name)
        raise exception.InvalidTemplateVersion(explanation=exp)

    def result(self):
        return super(Removed, self).result()


class Repeat(function.Function):
    """A function for iterating over a list of items.

    Takes the form::

        repeat:
            template:
                <body>
            for_each:
                <var>: <list>

    The result is a new list of the same size as <list>, where each element
    is a copy of <body> with any occurrences of <var> replaced with the
    corresponding item of <list>.
    """

    def __init__(self, stack, fn_name, args):
        super(Repeat, self).__init__(stack, fn_name, args)
        self._parse_args()

    def _parse_args(self):
        if not isinstance(self.args, collections.Mapping):
            raise TypeError(_('Arguments to "%s" must be a map') %
                            self.fn_name)

        # We don't check for invalid keys appearing here, which is wrong but
        # it's probably too late to change
        try:
            self._for_each = self.args['for_each']
            self._template = self.args['template']
        except KeyError:
            example = ('''repeat:
              template: This is %var%
              for_each:
                %var%: ['a', 'b', 'c']''')
            raise KeyError(_('"repeat" syntax should be %s') % example)

        self._nested_loop = True

    def validate(self):
        super(Repeat, self).validate()

        if not isinstance(self._for_each, function.Function):
            if not isinstance(self._for_each, collections.Mapping):
                raise TypeError(_('The "for_each" argument to "%s" must '
                                  'contain a map') % self.fn_name)

    def _valid_arg(self, arg):
        if not (isinstance(arg, (collections.Sequence,
                                 function.Function)) and
                not isinstance(arg, six.string_types)):
            raise TypeError(_('The values of the "for_each" argument to '
                              '"%s" must be lists') % self.fn_name)

    def _do_replacement(self, keys, values, template):
        if isinstance(template, six.string_types):
            for (key, value) in zip(keys, values):
                template = template.replace(key, value)
            return template
        elif isinstance(template, collections.Sequence):
            return [self._do_replacement(keys, values, elem)
                    for elem in template]
        elif isinstance(template, collections.Mapping):
            return dict((self._do_replacement(keys, values, k),
                         self._do_replacement(keys, values, v))
                        for (k, v) in template.items())
        else:
            return template

    def result(self):
        for_each = function.resolve(self._for_each)
        keys, lists = six.moves.zip(*for_each.items())

        # use empty list for references(None) else validation will fail
        value_lens = []
        values = []
        for value in lists:
            if value is None:
                values.append([])
            else:
                self._valid_arg(value)
                values.append(value)
                value_lens.append(len(value))
        if not self._nested_loop and value_lens:
            if len(set(value_lens)) != 1:
                raise ValueError(_('For %s, the length of for_each values '
                                   'should be equal if no nested '
                                   'loop.') % self.fn_name)

        template = function.resolve(self._template)
        iter_func = itertools.product if self._nested_loop else six.moves.zip

        return [self._do_replacement(keys, replacements, template)
                for replacements in iter_func(*values)]


class RepeatWithMap(Repeat):
    """A function for iterating over a list of items or a dict of keys.

    Takes the form::

        repeat:
            template:
                <body>
            for_each:
                <var>: <list> or <dict>

    The result is a new list of the same size as <list> or <dict>, where each
    element is a copy of <body> with any occurrences of <var> replaced with the
    corresponding item of <list> or key of <dict>.
    """

    def _valid_arg(self, arg):
        if not (isinstance(arg, (collections.Sequence,
                                 collections.Mapping,
                                 function.Function)) and
                not isinstance(arg, six.string_types)):
            raise TypeError(_('The values of the "for_each" argument to '
                              '"%s" must be lists or maps') % self.fn_name)


class RepeatWithNestedLoop(RepeatWithMap):
    """A function for iterating over a list of items or a dict of keys.

    Takes the form::

        repeat:
            template:
                <body>
            for_each:
                <var>: <list> or <dict>

    The result is a new list of the same size as <list> or <dict>, where each
    element is a copy of <body> with any occurrences of <var> replaced with the
    corresponding item of <list> or key of <dict>.

    This function also allows to specify 'permutations' to decide
    whether to iterate nested the over all the permutations of the
    elements in the given lists.

    Takes the form::

        repeat:
          template:
            var: %var%
            bar: %bar%
          for_each:
            %var%: <list1>
            %bar%: <list2>
          permutations: false

    If 'permutations' is not specified, we set the default value to true to
    compatible with before behavior. The args have to be lists instead of
    dicts if 'permutations' is False because keys in a dict are unordered,
    and the list args all have to be of the same length.
    """

    def _parse_args(self):
        super(RepeatWithNestedLoop, self)._parse_args()
        self._nested_loop = self.args.get('permutations', True)

        if not isinstance(self._nested_loop, bool):
            raise TypeError(_('"permutations" should be boolean type '
                              'for %s function.') % self.fn_name)

    def _valid_arg(self, arg):
        if self._nested_loop:
            super(RepeatWithNestedLoop, self)._valid_arg(arg)
        else:
            Repeat._valid_arg(self, arg)


class Digest(function.Function):
    """A function for performing digest operations.

    Takes the form::

        digest:
          - <algorithm>
          - <value>

    Valid algorithms are the ones provided by natively by hashlib (md5, sha1,
    sha224, sha256, sha384, and sha512) or any one provided by OpenSSL.
    """

    def validate_usage(self, args):
        if not (isinstance(args, list) and
                all([isinstance(a, six.string_types) for a in args])):
            msg = _('Argument to function "%s" must be a list of strings')
            raise TypeError(msg % self.fn_name)

        if len(args) != 2:
            msg = _('Function "%s" usage: ["<algorithm>", "<value>"]')
            raise ValueError(msg % self.fn_name)

        if six.PY3:
            algorithms = hashlib.algorithms_available
        else:
            algorithms = hashlib.algorithms

        if args[0].lower() not in algorithms:
            msg = _('Algorithm must be one of %s')
            raise ValueError(msg % six.text_type(algorithms))

    def digest(self, algorithm, value):
        _hash = hashlib.new(algorithm)
        _hash.update(six.b(value))

        return _hash.hexdigest()

    def result(self):
        args = function.resolve(self.args)
        self.validate_usage(args)

        return self.digest(*args)


class StrSplit(function.Function):
    """A function for splitting delimited strings into a list.

    Optionally extracting a specific list member by index.

    Takes the form::

        str_split:
          - <delimiter>
          - <string>
          - <index>

    If <index> is specified, the specified list item will be returned
    otherwise, the whole list is returned, similar to get_attr with
    path based attributes accessing lists.
    """

    def __init__(self, stack, fn_name, args):
        super(StrSplit, self).__init__(stack, fn_name, args)
        example = '"%s" : [ ",", "apples,pears", <index>]' % fn_name
        self.fmt_data = {'fn_name': fn_name,
                         'example': example}
        self.fn_name = fn_name

        if isinstance(args, (six.string_types, collections.Mapping)):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % self.fmt_data)

    def result(self):
        args = function.resolve(self.args)

        try:
            delim = args.pop(0)
            str_to_split = args.pop(0)
        except (AttributeError, IndexError):
            raise ValueError(_('Incorrect arguments to "%(fn_name)s" '
                               'should be: %(example)s') % self.fmt_data)

        if str_to_split is None:
            return None

        split_list = str_to_split.split(delim)

        # Optionally allow an index to be specified
        if args:
            try:
                index = int(args.pop(0))
            except ValueError:
                raise ValueError(_('Incorrect index to "%(fn_name)s" '
                                   'should be: %(example)s') % self.fmt_data)
            else:
                try:
                    res = split_list[index]
                except IndexError:
                    raise ValueError(_('Incorrect index to "%(fn_name)s" '
                                       'should be between 0 and '
                                       '%(max_index)s')
                                     % {'fn_name': self.fn_name,
                                        'max_index': len(split_list) - 1})
        else:
            res = split_list
        return res


class Yaql(function.Function):
    """A function for executing a yaql expression.

    Takes the form::

        yaql:
            expression:
                <body>
            data:
                <var>: <list>

    Evaluates expression <body> on the given data.
    """

    _parser = None

    @classmethod
    def get_yaql_parser(cls):
        if cls._parser is None:
            global_options = {
                'yaql.limitIterators': cfg.CONF.yaql.limit_iterators,
                'yaql.memoryQuota': cfg.CONF.yaql.memory_quota
            }
            cls._parser = yaql.YaqlFactory().create(global_options)
            cls._context = yaql.create_context()
        return cls._parser

    def __init__(self, stack, fn_name, args):
        super(Yaql, self).__init__(stack, fn_name, args)

        if not isinstance(self.args, collections.Mapping):
            raise TypeError(_('Arguments to "%s" must be a map.') %
                            self.fn_name)

        try:
            self._expression = self.args['expression']
            self._data = self.args.get('data', {})
            if set(self.args) - set(['expression', 'data']):
                raise KeyError
        except (KeyError, TypeError):
            example = ('''%s:
              expression: $.data.var1.sum()
              data:
                var1: [3, 2, 1]''') % self.fn_name
            raise KeyError(_('"%(name)s" syntax should be %(example)s') % {
                'name': self.fn_name, 'example': example})

    def validate(self):
        super(Yaql, self).validate()
        if not isinstance(self._expression, function.Function):
            self._parse(self._expression)

    def _parse(self, expression):
        if not isinstance(expression, six.string_types):
            raise TypeError(_('The "expression" argument to %s must '
                              'contain a string.') % self.fn_name)

        parse = self.get_yaql_parser()
        try:
            return parse(expression)
        except exceptions.YaqlException as yex:
            raise ValueError(_('Bad expression %s.') % yex)

    def result(self):
        statement = self._parse(function.resolve(self._expression))
        data = function.resolve(self._data)
        context = self._context.create_child_context()
        return statement.evaluate({'data': data}, context)


class Equals(function.Function):
    """A function for comparing whether two values are equal.

    Takes the form::

        equals:
          - <value_1>
          - <value_2>

    The value can be any type that you want to compare. Returns true
    if the two values are equal or false if they aren't.
    """

    def __init__(self, stack, fn_name, args):
        super(Equals, self).__init__(stack, fn_name, args)
        try:
            if (not self.args or
                    not isinstance(self.args, list)):
                raise ValueError()
            self.value1, self.value2 = self.args
        except ValueError:
            msg = _('Arguments to "%s" must be of the form: '
                    '[value_1, value_2]')
            raise ValueError(msg % self.fn_name)

    def result(self):
        resolved_v1 = function.resolve(self.value1)
        resolved_v2 = function.resolve(self.value2)

        return resolved_v1 == resolved_v2


class If(function.Macro):
    """A function to return corresponding value based on condition evaluation.

    Takes the form::

        if:
          - <condition_name>
          - <value_if_true>
          - <value_if_false>

    The value_if_true to be returned if the specified condition evaluates
    to true, the value_if_false to be returned if the specified condition
    evaluates to false.
    """

    def parse_args(self, parse_func):
        try:
            if (not self.args or
                    not isinstance(self.args, collections.Sequence) or
                    isinstance(self.args, six.string_types)):
                raise ValueError()
            condition, value_if_true, value_if_false = self.args
        except ValueError:
            msg = _('Arguments to "%s" must be of the form: '
                    '[condition_name, value_if_true, value_if_false]')
            raise ValueError(msg % self.fn_name)

        cond = self.template.parse_condition(self.stack, condition,
                                             self.fn_name)
        cd = self._get_condition(function.resolve(cond))
        return parse_func(value_if_true if cd else value_if_false)

    def _get_condition(self, cond):
        if isinstance(cond, bool):
            return cond

        return self.template.conditions(self.stack).is_enabled(cond)


class ConditionBoolean(function.Function):
    """Abstract parent class of boolean condition functions."""

    def __init__(self, stack, fn_name, args):
        super(ConditionBoolean, self).__init__(stack, fn_name, args)
        self._check_args()

    def _check_args(self):
        if not (isinstance(self.args, collections.Sequence) and
                not isinstance(self.args, six.string_types)):
            msg = _('Arguments to "%s" must be a list of conditions')
            raise ValueError(msg % self.fn_name)
        if not self.args or len(self.args) < 2:
            msg = _('The minimum number of condition arguments to "%s" is 2.')
            raise ValueError(msg % self.fn_name)

    def _get_condition(self, arg):
        if isinstance(arg, bool):
            return arg

        conditions = self.stack.t.conditions(self.stack)
        return conditions.is_enabled(arg)


class Not(ConditionBoolean):
    """A function that acts as a NOT operator on a condition.

    Takes the form::

        not: <condition>

    Returns true for a condition that evaluates to false or
    returns false for a condition that evaluates to true.
    """

    def _check_args(self):
        self.condition = self.args
        if self.args is None:
            msg = _('Argument to "%s" must be a condition')
            raise ValueError(msg % self.fn_name)

    def result(self):
        cd = function.resolve(self.condition)
        return not self._get_condition(cd)


class And(ConditionBoolean):
    """A function that acts as an AND operator on conditions.

    Takes the form::

        and:
          - <condition_1>
          - <condition_2>
          - ...

    Returns true if all the specified conditions evaluate to true, or returns
    false if any one of the conditions evaluates to false. The minimum number
    of conditions that you can include is 2.
    """

    def result(self):
        return all(self._get_condition(cd)
                   for cd in function.resolve(self.args))


class Or(ConditionBoolean):
    """A function that acts as an OR operator on conditions.

    Takes the form::

        or:
          - <condition_1>
          - <condition_2>
          - ...

    Returns true if any one of the specified conditions evaluate to true,
    or returns false if all of the conditions evaluates to false. The minimum
    number of conditions that you can include is 2.
    """

    def result(self):
        return any(self._get_condition(cd)
                   for cd in function.resolve(self.args))


class Filter(function.Function):
    """A function for filtering out values from lists.

    Takes the form::

        filter:
          - <values>
          - <list>

    Returns a new list without the values.
    """
    def __init__(self, stack, fn_name, args):
        super(Filter, self).__init__(stack, fn_name, args)

        self._values, self._sequence = self._parse_args()

    def _parse_args(self):
        if (not isinstance(self.args, collections.Sequence) or
                isinstance(self.args, six.string_types)):
            raise TypeError(_('Argument to "%s" must be a list') %
                            self.fn_name)

        if len(self.args) != 2:
            raise ValueError(_('"%(fn)s" expected 2 arguments of the form '
                               '[values, sequence] but got %(len)d arguments '
                               'instead') %
                             {'fn': self.fn_name, 'len': len(self.args)})

        return self.args[0], self.args[1]

    def result(self):
        sequence = function.resolve(self._sequence)
        if not sequence:
            return sequence
        if not isinstance(sequence, list):
            raise TypeError(_('"%s" only works with lists') % self.fn_name)

        values = function.resolve(self._values)
        if not values:
            return sequence
        if not isinstance(values, list):
            raise TypeError(
                _('"%(fn)s" filters a list of values') % self.fn_name)
        return [i for i in sequence if i not in values]


class MakeURL(function.Function):
    """A function for performing substitutions on maps.

    Takes the form::

        make_url:
          scheme: <protocol>
          username: <username>
          password: <password>
          host: <hostname or IP>
          port: <port>
          path: <path>
          query:
            <key1>: <value1>
          fragment: <fragment>

    And resolves to a correctly-escaped URL constructed from the various
    components.
    """

    _ARG_KEYS = (
        SCHEME, USERNAME, PASSWORD, HOST, PORT,
        PATH, QUERY, FRAGMENT,
    ) = (
        'scheme', 'username', 'password', 'host', 'port',
        'path', 'query', 'fragment',
    )

    def _check_args(self, args):
        for arg in self._ARG_KEYS:
            if arg in args:
                if arg == self.QUERY:
                    if not isinstance(args[arg], (function.Function,
                                                  collections.Mapping)):
                        raise TypeError(_('The "%(arg)s" argument to '
                                          '"%(fn_name)s" must be a map') %
                                        {'arg': arg,
                                         'fn_name': self.fn_name})
                    return
                elif arg == self.PORT:
                    port = args[arg]
                    if not isinstance(port, function.Function):
                        if not isinstance(port, six.integer_types):
                            try:
                                port = int(port)
                            except ValueError:
                                raise ValueError(
                                    _('Invalid URL port "%(port)s" '
                                      'for %(fn_name)s called with '
                                      '%(args)s')
                                    % {'fn_name': self.fn_name,
                                       'port': port, 'args': args})

                        if not (0 < port <= 65535):
                            raise ValueError(
                                _('Invalid URL port %d, '
                                  'must be in range 1-65535') % port)
                else:
                    if not isinstance(args[arg], (function.Function,
                                                  six.string_types)):
                        raise TypeError(_('The "%(arg)s" argument to '
                                          '"%(fn_name)s" must be a string') %
                                        {'arg': arg,
                                         'fn_name': self.fn_name})

    def validate(self):
        super(MakeURL, self).validate()

        if not isinstance(self.args, collections.Mapping):
            raise TypeError(_('The arguments to "%s" must '
                              'be a map') % self.fn_name)

        invalid_keys = set(self.args) - set(self._ARG_KEYS)
        if invalid_keys:
            raise ValueError(_('Invalid arguments to "%(fn)s": %(args)s') %
                             {'fn': self.fn_name,
                              'args': ', '.join(invalid_keys)})

        self._check_args(self.args)

    def result(self):
        args = function.resolve(self.args)
        self._check_args(args)

        scheme = args.get(self.SCHEME, '')
        if ':' in scheme:
            raise ValueError(_('URL "%s" should not contain \':\'') %
                             self.SCHEME)

        def netloc():
            username = urlparse.quote(args.get(self.USERNAME, ''), safe='')
            password = urlparse.quote(args.get(self.PASSWORD, ''), safe='')
            if username or password:
                yield username
                if password:
                    yield ':'
                    yield password
                yield '@'

            host = args.get(self.HOST, '')
            if host.startswith('[') and host.endswith(']'):
                host = host[1:-1]
            host = urlparse.quote(host, safe=':')
            if ':' in host:
                host = '[%s]' % host
            yield host

            port = args.get(self.PORT, '')
            if port:
                yield ':'
                yield six.text_type(port)

        path = urlparse.quote(args.get(self.PATH, ''))

        query_dict = args.get(self.QUERY, {})
        query = urlparse.urlencode(query_dict).replace('%2F', '/')

        fragment = urlparse.quote(args.get(self.FRAGMENT, ''))

        return urlparse.urlunsplit((scheme, ''.join(netloc()),
                                    path, query, fragment))


class ListConcat(function.Function):
    """A function for extending lists.

    Takes the form::

        list_concat:
          - [<value 1>, <value 2>]
          - [<value 3>, <value 4>]

    And resolves to::

        [<value 1>, <value 2>, <value 3>, <value 4>]

    """

    _unique = False

    def __init__(self, stack, fn_name, args):
        super(ListConcat, self).__init__(stack, fn_name, args)
        example = (_('"%s" : [ [ <value 1>, <value 2> ], '
                     '[ <value 3>, <value 4> ] ]')
                   % fn_name)
        self.fmt_data = {'fn_name': fn_name, 'example': example}

    def result(self):
        args = function.resolve(self.args)

        if (isinstance(args, six.string_types) or
                not isinstance(args, collections.Sequence)):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % self.fmt_data)

        def ensure_list(m):
            if m is None:
                return []
            elif (isinstance(m, collections.Sequence) and
                  not isinstance(m, six.string_types)):
                return m
            else:
                msg = _('Incorrect arguments: Items to concat must be lists.')
                raise TypeError(msg)

        ret_list = []
        for m in args:
            ret_list.extend(ensure_list(m))

        if self._unique:
            for i in ret_list:
                while ret_list.count(i) > 1:
                    del ret_list[ret_list.index(i)]

        return ret_list


class ListConcatUnique(ListConcat):
    """A function for extending lists with unique items.

    list_concat_unique is identical to the list_concat function, only
    contains unique items in retuning list.
    """

    _unique = True


class Contains(function.Function):
    """A function for checking whether specific value is in sequence.

    Takes the form::

        contains:
          - <value>
          - <sequence>

    The value can be any type that you want to check. Returns true
    if the specific value is in the sequence, otherwise returns false.
    """

    def __init__(self, stack, fn_name, args):
        super(Contains, self).__init__(stack, fn_name, args)
        example = '"%s" : [ "value1", [ "value1", "value2"]]' % self.fn_name
        fmt_data = {'fn_name': self.fn_name,
                    'example': example}

        if not self.args or not isinstance(self.args, list):
            raise TypeError(_('Incorrect arguments to "%(fn_name)s" '
                              'should be: %(example)s') % fmt_data)
        try:
            self.value, self.sequence = self.args
        except ValueError:
            msg = _('Arguments to "%s" must be of the form: '
                    '[value1, [value1, value2]]')
            raise ValueError(msg % self.fn_name)

    def result(self):
        resolved_value = function.resolve(self.value)
        resolved_sequence = function.resolve(self.sequence)

        if not isinstance(resolved_sequence, collections.Sequence):
            raise TypeError(_('Second argument to "%s" should be '
                              'a sequence.') % self.fn_name)

        return resolved_value in resolved_sequence
