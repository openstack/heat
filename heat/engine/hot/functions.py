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

from heat.common import exception

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

        if isinstance(args, basestring):
            param_name = args
            path_components = []
        elif isinstance(args, collections.Sequence):
            param_name = args[0]
            path_components = args[1:]
        else:
            raise TypeError(_('Argument to "%s" must be string or list') %
                            self.fn_name)

        if not isinstance(param_name, basestring):
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

            if not isinstance(key, (basestring, int)):
                raise TypeError(_('Path components in "%s" '
                                  'must be strings') % self.fn_name)

            return collection[key]

        try:
            return reduce(get_path_component, path_components, parameter)
        except (KeyError, IndexError, TypeError):
            return ''


class GetAtt(cfn_funcs.GetAtt):
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
                isinstance(self.args, basestring)):
            raise TypeError(_('Argument to "%s" must be a list') %
                            self.fn_name)

        if len(self.args) < 2:
            raise ValueError(_('Arguments to "%s" must be of the form '
                               '[resource_name, attribute, (path), ...]') %
                             self.fn_name)

        self._path_components = self.args[2:]

        return tuple(self.args[:2])

    def result(self):
        attribute = super(GetAtt, self).result()
        if attribute is None:
            return None

        path_components = function.resolve(self._path_components)

        def get_path_component(collection, key):
            if not isinstance(collection, (collections.Mapping,
                                           collections.Sequence)):
                raise TypeError(_('"%s" can\'t traverse path') % self.fn_name)

            if not isinstance(key, (basestring, int)):
                raise TypeError(_('Path components in "%s" '
                                  'must be strings') % self.fn_name)

            return collection[key]

        try:
            return reduce(get_path_component, path_components, attribute)
        except (KeyError, IndexError, TypeError):
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

    def result(self):
        args = function.resolve(self.args)
        if not (isinstance(args, basestring)):
            raise TypeError(_('Argument to "%s" must be a string') %
                            self.fn_name)

        f = self.stack.t.files.get(args)
        if f is None:
            fmt_data = {'fn_name': self.fn_name,
                        'file_key': args}
            raise ValueError(_('No content found in the "files" section for '
                               '%(fn_name)s path: %(file_key)s') % fmt_data)
        return f


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


def function_mapping(version_key, version):
    if version_key != 'heat_template_version':
        return {}

    if version == '2013-05-23':
        return {
            'Fn::GetAZs': cfn_funcs.GetAZs,
            'get_param': GetParam,
            'get_resource': cfn_funcs.ResourceRef,
            'Ref': cfn_funcs.Ref,
            'get_attr': GetAtt,
            'Fn::Select': cfn_funcs.Select,
            'Fn::Join': cfn_funcs.Join,
            'Fn::Split': cfn_funcs.Split,
            'str_replace': Replace,
            'Fn::Replace': cfn_funcs.Replace,
            'Fn::Base64': cfn_funcs.Base64,
            'Fn::MemberListToMap': cfn_funcs.MemberListToMap,
            'resource_facade': ResourceFacade,
            'Fn::ResourceFacade': cfn_funcs.ResourceFacade,
            'get_file': GetFile,
        }

    return {}
