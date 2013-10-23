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

from heat.api.aws import utils as aws_utils
from heat.db import api as db_api
from heat.common import exception
from heat.engine.parameters import ParamSchema

SECTIONS = (VERSION, DESCRIPTION, MAPPINGS,
            PARAMETERS, RESOURCES, OUTPUTS) = \
           ('AWSTemplateFormatVersion', 'Description', 'Mappings',
            'Parameters', 'Resources', 'Outputs')


class Template(collections.Mapping):
    '''A stack template.'''

    def __new__(cls, template, *args, **kwargs):
        '''Create a new Template of the appropriate class.'''

        if cls == Template:
            if 'heat_template_version' in template:
                # deferred import of HOT module to avoid circular dependency
                # at load time
                from heat.engine import hot
                return hot.HOTemplate(template, *args, **kwargs)

        return super(Template, cls).__new__(cls)

    def __init__(self, template, template_id=None, files=None):
        '''
        Initialise the template with a JSON object and a set of Parameters
        '''
        self.id = template_id
        self.t = template
        self.files = files or {}
        self.maps = self[MAPPINGS]

    @classmethod
    def load(cls, context, template_id):
        '''Retrieve a Template with the given ID from the database.'''
        t = db_api.raw_template_get(context, template_id)
        return cls(t.template, template_id)

    def store(self, context=None):
        '''Store the Template in the database and return its ID.'''
        if self.id is None:
            rt = {'template': self.t}
            new_rt = db_api.raw_template_create(context, rt)
            self.id = new_rt.id
        return self.id

    def __getitem__(self, section):
        '''Get the relevant section in the template.'''
        if section not in SECTIONS:
            raise KeyError('"%s" is not a valid template section' % section)
        if section == VERSION:
            return self.t[section]

        if section == DESCRIPTION:
            default = 'No description'
        else:
            default = {}

        return self.t.get(section, default)

    def __iter__(self):
        '''Return an iterator over the section names.'''
        return iter(SECTIONS)

    def __len__(self):
        '''Return the number of sections.'''
        return len(SECTIONS)

    def resolve_find_in_map(self, s):
        '''
        Resolve constructs of the form { "Fn::FindInMap" : [ "mapping",
                                                             "key",
                                                             "value" ] }
        '''
        def handle_find_in_map(args):
            try:
                name, key, value = args
                return self.maps[name][key][value]
            except (ValueError, TypeError) as ex:
                raise KeyError(str(ex))

        return _resolve(lambda k, v: k == 'Fn::FindInMap',
                        handle_find_in_map, s)

    @staticmethod
    def resolve_availability_zones(s, stack):
        '''
            looking for { "Fn::GetAZs" : "str" }
        '''
        def match_get_az(key, value):
            return (key == 'Fn::GetAZs' and
                    isinstance(value, basestring))

        def handle_get_az(ref):
            if stack is None:
                return ['nova']
            else:
                return stack.get_availability_zones()

        return _resolve(match_get_az, handle_get_az, s)

    @staticmethod
    def resolve_param_refs(s, parameters):
        '''
        Resolve constructs of the form { "Ref" : "string" }
        '''
        def match_param_ref(key, value):
            return (key == 'Ref' and
                    isinstance(value, basestring) and
                    value in parameters)

        def handle_param_ref(ref):
            try:
                return parameters[ref]
            except (KeyError, ValueError):
                raise exception.UserParameterMissing(key=ref)

        return _resolve(match_param_ref, handle_param_ref, s)

    @staticmethod
    def resolve_resource_refs(s, resources):
        '''
        Resolve constructs of the form { "Ref" : "resource" }
        '''
        def match_resource_ref(key, value):
            return key == 'Ref' and value in resources

        def handle_resource_ref(arg):
            return resources[arg].FnGetRefId()

        return _resolve(match_resource_ref, handle_resource_ref, s)

    @staticmethod
    def resolve_attributes(s, resources):
        '''
        Resolve constructs of the form { "Fn::GetAtt" : [ "WebServer",
                                                          "PublicIp" ] }
        '''
        def handle_getatt(args):
            resource, att = args
            try:
                r = resources[resource]
                if r.state in (
                        (r.CREATE, r.IN_PROGRESS),
                        (r.CREATE, r.COMPLETE),
                        (r.RESUME, r.IN_PROGRESS),
                        (r.RESUME, r.COMPLETE),
                        (r.UPDATE, r.IN_PROGRESS),
                        (r.UPDATE, r.COMPLETE)):
                    return r.FnGetAtt(att)
            except KeyError:
                raise exception.InvalidTemplateAttribute(resource=resource,
                                                         key=att)

        return _resolve(lambda k, v: k == 'Fn::GetAtt', handle_getatt, s)

    @staticmethod
    def reduce_joins(s):
        '''
        Reduces contiguous strings in Fn::Join to a single joined string
        eg the following
        { "Fn::Join" : [ " ", [ "str1", "str2", {"f": "b"}, "str3", "str4"]}
        is reduced to
        { "Fn::Join" : [ " ", [ "str1 str2", {"f": "b"}, "str3 str4"]}
        '''
        def handle_join(args):
            if not isinstance(args, (list, tuple)):
                raise TypeError('Arguments to "Fn::Join" must be a list')
            try:
                delim, items = args
            except ValueError as ex:
                example = '"Fn::Join" : [ " ", [ "str1", "str2"]]'
                raise ValueError('Incorrect arguments to "Fn::Join" %s: %s' %
                                ('should be', example))

            if not isinstance(items, (list, tuple)):
                raise TypeError('Arguments to "Fn::Join" not fully resolved')
            reduced = []
            contiguous = []
            for item in items:
                if isinstance(item, (str, unicode)):
                    contiguous.append(item)
                else:
                    if contiguous:
                        reduced.append(delim.join(contiguous))
                        contiguous = []
                    reduced.append(item)
            if contiguous:
                reduced.append(delim.join(contiguous))
            return {'Fn::Join': [delim, reduced]}

        return _resolve(lambda k, v: k == 'Fn::Join', handle_join, s)

    @staticmethod
    def resolve_select(s):
        '''
        Resolve constructs of the form:
        (for a list lookup)
        { "Fn::Select" : [ "2", [ "apples", "grapes", "mangoes" ] ] }
        returns "mangoes"
        { "Fn::Select" : [ "3", [ "apples", "grapes", "mangoes" ] ] }
        returns ""

        (for a dict lookup)
        { "Fn::Select" : [ "red", {"red": "a", "flu": "b"} ] }
        returns "a"
        { "Fn::Select" : [ "blue", {"red": "a", "flu": "b"} ] }
        returns ""

        Note: can raise ValueError and TypeError
        '''
        def handle_select(args):
            if not isinstance(args, (list, tuple)):
                raise TypeError('Arguments to "Fn::Select" must be a list')

            try:
                lookup, strings = args
            except ValueError as ex:
                example = '"Fn::Select" : [ "4", [ "str1", "str2"]]'
                raise ValueError('Incorrect arguments to "Fn::Select" %s: %s' %
                                ('should be', example))

            try:
                index = int(lookup)
            except ValueError as ex:
                index = lookup

            if strings == '':
                # an empty string is a common response from other
                # functions when result is not currently available.
                # Handle by returning an empty string
                return ''

            if isinstance(strings, basestring):
                # might be serialized json.
                # if not allow it to raise a ValueError
                strings = json.loads(strings)

            if isinstance(strings, (list, tuple)) and isinstance(index, int):
                try:
                    return strings[index]
                except IndexError:
                    return ''
            if isinstance(strings, dict) and isinstance(index, basestring):
                return strings.get(index, '')
            if strings is None:
                return ''

            raise TypeError('Arguments to "Fn::Select" not fully resolved')

        return _resolve(lambda k, v: k == 'Fn::Select', handle_select, s)

    @staticmethod
    def resolve_joins(s):
        '''
        Resolve constructs of the form { "Fn::Join" : [ "delim", [ "str1",
                                                                   "str2" ] }
        '''
        def handle_join(args):
            if not isinstance(args, (list, tuple)):
                raise TypeError('Arguments to "Fn::Join" must be a list')

            try:
                delim, strings = args
            except ValueError as ex:
                example = '"Fn::Join" : [ " ", [ "str1", "str2"]]'
                raise ValueError('Incorrect arguments to "Fn::Join" %s: %s' %
                                ('should be', example))

            if not isinstance(strings, (list, tuple)):
                raise TypeError('Arguments to "Fn::Join" not fully resolved')

            def empty_for_none(v):
                if v is None:
                    return ''
                else:
                    return v

            return delim.join(empty_for_none(value) for value in strings)

        return _resolve(lambda k, v: k == 'Fn::Join', handle_join, s)

    @staticmethod
    def resolve_split(s):
        '''
        Split strings in Fn::Split to a list of sub strings
        eg the following
        { "Fn::Split" : [ ",", "str1,str2,str3,str4"]}
        is reduced to
        {["str1", "str2", "str3", "str4"]}
        '''
        def handle_split(args):
            if not isinstance(args, (list, tuple)):
                raise TypeError('Arguments to "Fn::Split" must be a list')

            example = '"Fn::Split" : [ ",", "str1, str2"]]'
            try:
                delim, strings = args
            except ValueError as ex:
                raise ValueError('Incorrect arguments to "Fn::Split" %s: %s' %
                                ('should be', example))
            if not isinstance(strings, basestring):
                raise TypeError('Incorrect arguments to "Fn::Split" %s: %s' %
                                ('should be', example))
            return strings.split(delim)
        return _resolve(lambda k, v: k == 'Fn::Split', handle_split, s)

    @staticmethod
    def resolve_replace(s):
        """
        Resolve constructs of the form.
        {"Fn::Replace": [
          {'$var1': 'foo', '%var2%': 'bar'},
          '$var1 is %var2%'
        ]}
        This is implemented using python str.replace on each key
        """
        def handle_replace(args):
            if not isinstance(args, (list, tuple)):
                raise TypeError('Arguments to "Fn::Replace" must be a list')

            try:
                mapping, string = args
            except ValueError as ex:
                example = ('{"Fn::Replace": '
                           '[ {"$var1": "foo", "%var2%": "bar"}, '
                           '"$var1 is %var2%"]}')
                raise ValueError(
                    'Incorrect arguments to "Fn::Replace" %s: %s' %
                    ('should be', example))

            if not isinstance(mapping, dict):
                raise TypeError(
                    'Arguments to "Fn::Replace" not fully resolved')
            if not isinstance(string, basestring):
                raise TypeError(
                    'Arguments to "Fn::Replace" not fully resolved')

            for k, v in mapping.items():
                if v is None:
                    v = ''
                string = string.replace(k, v)
            return string

        return _resolve(lambda k, v: k == 'Fn::Replace', handle_replace, s)

    @staticmethod
    def resolve_base64(s):
        '''
        Resolve constructs of the form { "Fn::Base64" : "string" }
        '''
        def handle_base64(string):
            if not isinstance(string, basestring):
                raise TypeError('Arguments to "Fn::Base64" not fully resolved')
            return string

        return _resolve(lambda k, v: k == 'Fn::Base64', handle_base64, s)

    @staticmethod
    def resolve_member_list_to_map(s):
        '''
        Resolve constructs of the form
        {'Fn::MemberListToMap': ['Name', 'Value', ['.member.0.Name=key',
                                                   '.member.0.Value=door']]}
        the first two arguments are the names of the key and value.
        '''

        def handle_member_list_to_map(args):
            correct = '''
            {'Fn::MemberListToMap': ['Name', 'Value',
                                     ['.member.0.Name=key',
                                      '.member.0.Value=door']]}
            '''
            if not isinstance(args, (list, tuple)):
                raise TypeError('Wrong Arguments try: "%s"' % correct)
            if len(args) != 3:
                raise TypeError('Wrong Arguments try: "%s"' % correct)
            if not isinstance(args[0], basestring):
                raise TypeError('Wrong Arguments try: "%s"' % correct)
            if not isinstance(args[1], basestring):
                raise TypeError('Wrong Arguments try: "%s"' % correct)
            if not isinstance(args[2], (list, tuple)):
                raise TypeError('Wrong Arguments try: "%s"' % correct)

            partial = {}
            for item in args[2]:
                sp = item.split('=')
                partial[sp[0]] = sp[1]
            return aws_utils.extract_param_pairs(partial,
                                                 prefix='',
                                                 keyname=args[0],
                                                 valuename=args[1])

        return _resolve(lambda k, v: k == 'Fn::MemberListToMap',
                        handle_member_list_to_map, s)

    @staticmethod
    def resolve_resource_facade(s, stack):
        '''
        Resolve constructs of the form {'Fn::ResourceFacade': 'Metadata'}
        '''
        resource_attributes = ('Metadata', 'DeletionPolicy', 'UpdatePolicy')

        def handle_resource_facade(arg):
            if arg not in resource_attributes:
                raise ValueError(
                    'Incorrect arguments to "Fn::ResourceFacade" %s: %s' %
                    ('should be one of', str(resource_attributes)))
            try:
                if arg == 'Metadata':
                    return stack.parent_resource.metadata
                return stack.parent_resource.t[arg]
            except KeyError:
                raise KeyError('"%s" is not specified in parent resource' %
                               arg)

        return _resolve(lambda k, v: k == 'Fn::ResourceFacade',
                        handle_resource_facade,
                        s)

    def param_schemata(self):
        parameters = self[PARAMETERS].iteritems()
        return dict((name, ParamSchema(schema)) for name, schema in parameters)


def _resolve(match, handle, snippet):
    '''
    Resolve constructs in a snippet of a template. The supplied match function
    should return True if a particular key-value pair should be substituted,
    and the handle function should return the correct substitution when passed
    the argument list as parameters.

    Returns a copy of the original snippet with the substitutions performed.
    '''
    recurse = lambda s: _resolve(match, handle, s)

    if isinstance(snippet, dict):
        if len(snippet) == 1:
            k, v = snippet.items()[0]
            if match(k, v):
                return handle(recurse(v))
        return dict((k, recurse(v)) for k, v in snippet.items())
    elif isinstance(snippet, list):
        return [recurse(s) for s in snippet]
    return snippet
