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

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine.cfn import functions as cfn_funcs
from heat.engine import function


class GetParam(function.Function):
    '''
    A function for resolving parameter references.

    Takes the form::

        get_param: <param_name>

    or::

        get_param:
          - <param_name>
          - <path1>
          - ...
    '''

    def __init__(self, stack, fn_name, args):
        super(GetParam, self).__init__(stack, fn_name, args)

        self.parameters = self.stack.parameters

    def result(self):
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

            return collection[key]

        try:
            return reduce(get_path_component, path_components, parameter)
        except (KeyError, IndexError, TypeError):
            return ''


class GetAttThenSelect(cfn_funcs.GetAtt):
    '''
    A function for resolving resource attributes.

    Takes the form::

        get_attr:
          - <resource_name>
          - <attribute_name>
          - <path1>
          - ...
    '''

    def _parse_args(self):
        if (not isinstance(self.args, collections.Sequence) or
                isinstance(self.args, six.string_types)):
            raise TypeError(_('Argument to "%s" must be a list') %
                            self.fn_name)

        if len(self.args) < 2:
            raise ValueError(_('Arguments to "%s" must be of the form '
                               '[resource_name, attribute, (path), ...]') %
                             self.fn_name)

        self._path_components = self.args[2:]

        return tuple(self.args[:2])

    def result(self):
        attribute = super(GetAttThenSelect, self).result()
        if attribute is None:
            return None

        path_components = function.resolve(self._path_components)
        return attributes.select_from_attribute(attribute, path_components)


class GetAtt(GetAttThenSelect):
    '''
    A function for resolving resource attributes.

    Takes the form::

        get_attr:
          - <resource_name>
          - <attribute_name>
          - <path1>
          - ...
    '''

    def result(self):
        path_components = function.resolve(self._path_components)
        attribute = function.resolve(self._attribute)

        r = self._resource()
        if (r.status in (r.IN_PROGRESS, r.COMPLETE) and
                r.action in (r.CREATE, r.ADOPT, r.SUSPEND, r.RESUME,
                             r.UPDATE)):
            return r.FnGetAtt(attribute, *path_components)
        else:
            return None


class Replace(cfn_funcs.Replace):
    '''
    A function for performing string substitutions.

    Takes the form::

        str_replace:
          template: <key_1> <key_2>
          params:
            <key_1>: <value_1>
            <key_2>: <value_2>
            ...

    And resolves to::

        "<value_1> <value_2>"

    This is implemented using Python's str.replace on each key. The order in
    which replacements are performed is undefined.
    '''

    def _parse_args(self):
        if not isinstance(self.args, collections.Mapping):
            raise TypeError(_('Arguments to "%s" must be a map') %
                            self.fn_name)

        try:
            mapping = self.args['params']
            string = self.args['template']
        except (KeyError, TypeError):
            example = ('''str_replace:
              template: This is var1 template var2
              params:
                var1: a
                var2: string''')
            raise KeyError(_('"str_replace" syntax should be %s') %
                           example)
        else:
            return mapping, string


class GetFile(function.Function):
    """
    A function for including a file inline.

    Takes the form::

        get_file: <file_key>

    And resolves to the content stored in the files dictionary under the given
    key.
    """

    def __init__(self, stack, fn_name, args):
        super(GetFile, self).__init__(stack, fn_name, args)

        self.files = self.stack.t.files

    def result(self):
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


class Join(cfn_funcs.Join):
    '''
    A function for joining strings.

    Takes the form::

        { "list_join" : [ "<delim>", [ "<string_1>", "<string_2>", ... ] }

    And resolves to::

        "<string_1><delim><string_2><delim>..."
    '''


class ResourceFacade(cfn_funcs.ResourceFacade):
    '''
    A function for obtaining data from the facade resource from within the
    corresponding provider template.

    Takes the form::

        resource_facade: <attribute_type>

    where the valid attribute types are "metadata", "deletion_policy" and
    "update_policy".
    '''

    _RESOURCE_ATTRIBUTES = (
        METADATA, DELETION_POLICY, UPDATE_POLICY,
    ) = (
        'metadata', 'deletion_policy', 'update_policy'
    )


class Removed(function.Function):
    '''
    This function existed in previous versions of HOT, but has been removed.
    Check the HOT guide for an equivalent native function.
    '''

    def validate(self):
        exp = (_("The function %s is not supported in this version of HOT.") %
               self.fn_name)
        raise exception.InvalidTemplateVersion(explanation=exp)

    def result(self):
        return super(Removed, self).result()


class Repeat(function.Function):
    '''
    A function for iterating over a list of items.

    Takes the form::

        repeat:
            template:
                <body>
            for_each:
                <var>: <list>

    The result is a new list of the same size as <list>, where each element
    is a copy of <body> with any occurrences of <var> replaced with the
    corresponding item of <list>.
    '''
    def __init__(self, stack, fn_name, args):
        super(Repeat, self).__init__(stack, fn_name, args)

        self._for_each, self._template = self._parse_args()

    def _parse_args(self):
        if not isinstance(self.args, collections.Mapping):
            raise TypeError(_('Arguments to "%s" must be a map') %
                            self.fn_name)

        try:
            for_each = function.resolve(self.args['for_each'])
            template = self.args['template']
        except (KeyError, TypeError):
            example = ('''repeat:
              template: This is %var%
              for_each:
                %var%: ['a', 'b', 'c']''')
            raise KeyError(_('"repeat" syntax should be %s') %
                           example)

        if not isinstance(for_each, collections.Mapping):
            raise TypeError(_('The "for_each" argument to "%s" must contain '
                              'a map') % self.fn_name)
        for v in six.itervalues(for_each):
            if not isinstance(v, list):
                raise TypeError(_('The values of the "for_each" argument to '
                                  '"%s" must be lists') % self.fn_name)

        return for_each, template

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

    def result(self):
        keys = list(six.iterkeys(self._for_each))
        lists = [self._for_each[key] for key in keys]
        template = function.resolve(self._template)
        return [self._do_replacement(keys, items, template)
                for items in itertools.product(*lists)]


class Digest(function.Function):
    '''
    A function for performing digest operations.

    Takes the form::

        digest:
          - <algorithm>
          - <value>

    Valid algorithms are the ones provided by natively by hashlib (md5, sha1,
    sha224, sha256, sha384, and sha512) or any one provided by OpenSSL.
    '''

    def validate_usage(self, args):
        if not (isinstance(args, list) and
                all([isinstance(a, six.string_types) for a in args])):
            msg = _('Argument to function "%s" must be a list of strings')
            raise TypeError(msg % self.fn_name)

        if len(args) != 2:
            msg = _('Function "%s" usage: ["<algorithm>", "<value>"]')
            raise ValueError(msg % self.fn_name)

        if args[0].lower() not in hashlib.algorithms:
            msg = _('Algorithm must be one of %s')
            raise ValueError(msg % six.text_type(hashlib.algorithms))

    def digest(self, algorithm, value):
        _hash = hashlib.new(algorithm)
        _hash.update(value)

        return _hash.hexdigest()

    def result(self):
        args = function.resolve(self.args)
        self.validate_usage(args)

        return self.digest(*args)
