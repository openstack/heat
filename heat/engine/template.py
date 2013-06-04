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

from heat.db import api as db_api
from heat.common import exception


SECTIONS = (VERSION, DESCRIPTION, MAPPINGS,
            PARAMETERS, RESOURCES, OUTPUTS) = \
           ('AWSTemplateFormatVersion', 'Description', 'Mappings',
            'Parameters', 'Resources', 'Outputs')


class Template(collections.Mapping):
    '''A stack template.'''

    def __init__(self, template, template_id=None):
        '''
        Initialise the template with a JSON object and a set of Parameters
        '''
        self.id = template_id
        self.t = template
        self.maps = self[MAPPINGS]

    @classmethod
    def load(cls, context, template_id):
        '''Retrieve a Template with the given ID from the database'''
        t = db_api.raw_template_get(context, template_id)
        return cls(t.template, template_id)

    def store(self, context=None):
        '''Store the Template in the database and return its ID'''
        if self.id is None:
            rt = {'template': self.t}
            new_rt = db_api.raw_template_create(context, rt)
            self.id = new_rt.id
        return self.id

    def __getitem__(self, section):
        '''Get the relevant section in the template'''
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
        '''Return an iterator over the section names'''
        return iter(SECTIONS)

    def __len__(self):
        '''Return the number of sections'''
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
    def resolve_availability_zones(s):
        '''
            looking for { "Fn::GetAZs" : "str" }
        '''
        def match_get_az(key, value):
            return (key == 'Fn::GetAZs' and
                    isinstance(value, basestring))

        def handle_get_az(ref):
            return ['nova']

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
                        r.CREATE_IN_PROGRESS,
                        r.CREATE_COMPLETE,
                        r.UPDATE_IN_PROGRESS,
                        r.UPDATE_COMPLETE):
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
    def resolve_base64(s):
        '''
        Resolve constructs of the form { "Fn::Base64" : "string" }
        '''
        def handle_base64(string):
            if not isinstance(string, basestring):
                raise TypeError('Arguments to "Fn::Base64" not fully resolved')
            return string

        return _resolve(lambda k, v: k == 'Fn::Base64', handle_base64, s)


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
        return [recurse(v) for v in snippet]
    return snippet
