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

import eventlet
import json
import functools
import copy

from heat.common import exception
from heat.engine import checkeddict
from heat.engine import dependencies
from heat.engine import resources
from heat.db import api as db_api

from heat.openstack.common import log as logging

logger = logging.getLogger('heat.engine.parser')

SECTIONS = (VERSION, DESCRIPTION, MAPPINGS,
            PARAMETERS, RESOURCES, OUTPUTS) = \
           ('AWSTemplateFormatVersion', 'Description', 'Mappings',
            'Parameters', 'Resources', 'Outputs')

(PARAM_STACK_NAME, PARAM_REGION) = ('AWS::StackName', 'AWS::Region')


class Parameters(checkeddict.CheckedDict):
    '''
    The parameters of a stack, with type checking, defaults &c. specified by
    the stack's template.
    '''

    def __init__(self, stack_name, template, user_params={}):
        '''
        Create the parameter container for a stack from the stack name and
        template, optionally setting the initial set of parameters.
        '''
        checkeddict.CheckedDict.__init__(self, PARAMETERS)
        self._init_schemata(template[PARAMETERS])

        self[PARAM_STACK_NAME] = stack_name
        self.update(user_params)

    def _init_schemata(self, schemata):
        '''
        Initialise the parameter schemata with the pseudo-parameters and the
        list of schemata obtained from the template.
        '''
        self.addschema(PARAM_STACK_NAME, {"Description": "AWS StackName",
                                          "Type": "String"})
        self.addschema(PARAM_REGION, {
            "Description": "AWS Regions",
            "Default": "ap-southeast-1",
            "Type": "String",
            "AllowedValues": ["us-east-1", "us-west-1", "us-west-2",
                              "sa-east-1", "eu-west-1", "ap-southeast-1",
                              "ap-northeast-1"],
            "ConstraintDescription": "must be a valid EC2 instance type.",
        })

        for param, schema in schemata.items():
            self.addschema(param, copy.deepcopy(schema))

    def user_parameters(self):
        '''
        Return a dictionary of all the parameters passed in by the user
        '''
        return dict((k, v['Value']) for k, v in self.data.iteritems()
                                    if 'Value' in v)


class Template(object):
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
                return resources[resource].FnGetAtt(att)
            except KeyError:
                raise exception.InvalidTemplateAttribute(resource=resource,
                                                         key=att)

        return _resolve(lambda k, v: k == 'Fn::GetAtt', handle_getatt, s)

    @staticmethod
    def resolve_joins(s):
        '''
        Resolve constructs of the form { "Fn::Join" : [ "delim", [ "str1",
                                                                   "str2" ] }
        '''
        def handle_join(args):
            if not isinstance(args, (list, tuple)):
                raise TypeError('Arguments to "Fn::Join" must be a list')
            delim, strings = args
            if not isinstance(strings, (list, tuple)):
                raise TypeError('Arguments to "Fn::Join" not fully resolved')
            return delim.join(strings)

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


class Stack(object):
    IN_PROGRESS = 'IN_PROGRESS'
    CREATE_FAILED = 'CREATE_FAILED'
    CREATE_COMPLETE = 'CREATE_COMPLETE'
    DELETE_IN_PROGRESS = 'DELETE_IN_PROGRESS'
    DELETE_FAILED = 'DELETE_FAILED'
    DELETE_COMPLETE = 'DELETE_COMPLETE'

    created_time = resources.Timestamp(db_api.stack_get, 'created_at')
    updated_time = resources.Timestamp(db_api.stack_get, 'updated_at')

    def __init__(self, context, stack_name, template, parameters=None,
                 stack_id=None, state=None, state_description='',
                 timeout_mins=60):
        '''
        Initialise from a context, name, Template object and (optionally)
        Parameters object. The database ID may also be initialised, if the
        stack is already in the database.
        '''
        self.id = stack_id
        self.context = context
        self.t = template
        self.name = stack_name
        self.state = state
        self.state_description = state_description
        self.timeout_mins = timeout_mins

        if parameters is None:
            parameters = Parameters(stack_name, template)
        self.parameters = parameters

        self.outputs = self.resolve_static_data(self.t[OUTPUTS])

        self.resources = dict((name,
                               resources.Resource(name, data, self))
                              for (name, data) in self.t[RESOURCES].items())

        self.dependencies = self._get_dependencies(self.resources.itervalues())

    @staticmethod
    def _get_dependencies(resources):
        '''Return the dependency graph for a list of resources'''
        deps = dependencies.Dependencies()
        for resource in resources:
            resource.add_dependencies(deps)

        return deps

    @classmethod
    def load(cls, context, stack_id):
        '''Retrieve a Stack from the database'''
        s = db_api.stack_get(context, stack_id)
        if s is None:
            message = 'No stack exists with id "%s"' % str(stack_id)
            raise exception.NotFound(message)

        template = Template.load(context, s.raw_template_id)
        params = Parameters(s.name, template, s.parameters)
        stack = cls(context, s.name, template, params,
                    stack_id, s.status, s.status_reason, s.timeout)

        return stack

    def store(self, owner=None):
        '''Store the stack in the database and return its ID'''
        if self.id is None:
            new_creds = db_api.user_creds_create(self.context.to_dict())

            s = {
                'name': self.name,
                'raw_template_id': self.t.store(),
                'parameters': self.parameters.user_parameters(),
                'owner_id': owner and owner.id,
                'user_creds_id': new_creds.id,
                'username': self.context.username,
                'status': self.state,
                'status_reason': self.state_description,
                'timeout': self.timeout_mins,
            }
            new_s = db_api.stack_create(self.context, s)
            self.id = new_s.id

        return self.id

    def __iter__(self):
        '''
        Return an iterator over this template's resources in the order that
        they should be started.
        '''
        return iter(self.dependencies)

    def __reversed__(self):
        '''
        Return an iterator over this template's resources in the order that
        they should be stopped.
        '''
        return reversed(self.dependencies)

    def __len__(self):
        '''Return the number of resources'''
        return len(self.resources)

    def __getitem__(self, key):
        '''Get the resource with the specified name.'''
        return self.resources[key]

    def __contains__(self, key):
        '''Determine whether the stack contains the specified resource'''
        return key in self.resources

    def keys(self):
        '''Return a list of resource keys for the stack'''
        return self.resources.keys()

    def __str__(self):
        '''Return a human-readable string representation of the stack'''
        return 'Stack "%s"' % self.name

    def validate(self):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/\
        APIReference/API_ValidateTemplate.html
        '''
        # TODO(sdake) Should return line number of invalid reference

        for res in self:
            try:
                result = res.validate()
            except Exception as ex:
                logger.exception('validate')
                result = str(ex)

            if result:
                err_str = 'Malformed Query Response %s' % result
                response = {'Description': err_str,
                            'Parameters': []}
                return response

        def format_param(p):
            return {'NoEcho': 'false',
                    'ParameterKey': p,
                    'Description': self.parameters.get_attr(p, 'Description'),
                    'DefaultValue': self.parameters.get_attr(p, 'Default')}

        response = {'Description': 'Successfully validated',
                    'Parameters': [format_param(p) for p in self.parameters]}

        return response

    def state_set(self, new_status, reason):
        '''Update the stack state in the database'''
        self.state = new_status
        self.state_description = reason

        if self.id is None:
            return

        stack = db_api.stack_get(self.context, self.id)
        stack.update_and_save({'status': new_status,
                               'status_reason': reason})

    def create(self):
        '''
        Create the stack and all of the resources.

        Creation will fail if it exceeds the specified timeout. The default is
        60 minutes, set in the constructor
        '''
        self.state_set(self.IN_PROGRESS, 'Stack creation started')

        stack_status = self.CREATE_COMPLETE
        reason = 'Stack successfully created'
        res = None

        with eventlet.Timeout(self.timeout_mins * 60) as tmo:
            try:
                for res in self:
                    if stack_status != self.CREATE_FAILED:
                        result = res.create()
                        if result:
                            stack_status = self.CREATE_FAILED
                            reason = 'Resource %s failed with: %s' % (str(res),
                                                                      result)

                    else:
                        res.state_set(res.CREATE_FAILED,
                                      'Stack creation aborted')

            except eventlet.Timeout as t:
                if t is tmo:
                    stack_status = self.CREATE_FAILED
                    reason = 'Timed out waiting for %s' % str(res)
                else:
                    # not my timeout
                    raise

        self.state_set(stack_status, reason)

    def delete(self):
        '''
        Delete all of the resources, and then the stack itself.
        '''
        self.state_set(self.DELETE_IN_PROGRESS, 'Stack deletion started')

        failures = []

        for res in reversed(self):
            result = res.destroy()
            if result:
                failures.append(str(res))

        if failures:
            self.state_set(self.DELETE_FAILED,
                           'Failed to delete ' + ', '.join(failures))
        else:
            self.state_set(self.DELETE_COMPLETE, 'Deleted successfully')
            db_api.stack_delete(self.context, self.id)

    def output(self, key):
        '''
        Get the value of the specified stack output.
        '''
        value = self.outputs[key].get('Value', '')
        return self.resolve_runtime_data(value)

    def restart_resource(self, resource_name):
        '''
        stop resource_name and all that depend on it
        start resource_name and all that depend on it
        '''
        deps = self.dependencies[self[resource_name]]
        failed = False

        for res in reversed(deps):
            try:
                res.delete()
                re = db_api.resource_get(self.context, res.id)
                re.delete()
            except Exception as ex:
                failed = True
                logger.error('delete: %s' % str(ex))

        for res in deps:
            if not failed:
                try:
                    res.create()
                except Exception as ex:
                    logger.exception('create')
                    failed = True
            else:
                res.state_set(res.CREATE_FAILED, 'Resource restart aborted')
        # TODO(asalkeld) if any of this fails we Should
        # restart the whole stack

    def resolve_static_data(self, snippet):
        return transform(snippet,
                         [functools.partial(self.t.resolve_param_refs,
                                            parameters=self.parameters),
                          self.t.resolve_availability_zones,
                          self.t.resolve_find_in_map])

    def resolve_runtime_data(self, snippet):
        return transform(snippet,
                         [functools.partial(self.t.resolve_resource_refs,
                                            resources=self.resources),
                          functools.partial(self.t.resolve_attributes,
                                            resources=self.resources),
                          self.t.resolve_joins,
                          self.t.resolve_base64])


def transform(data, transformations):
    '''
    Apply each of the transformation functions in the supplied list to the data
    in turn.
    '''
    for t in transformations:
        data = t(data)
    return data


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
