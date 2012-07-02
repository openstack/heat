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
import itertools
import logging

from heat.common import exception
from heat.engine import checkeddict
from heat.engine import dependencies
from heat.engine.resources import Resource
from heat.db import api as db_api

logger = logging.getLogger('heat.engine.parser')


class Stack(object):
    IN_PROGRESS = 'IN_PROGRESS'
    CREATE_FAILED = 'CREATE_FAILED'
    CREATE_COMPLETE = 'CREATE_COMPLETE'
    DELETE_IN_PROGRESS = 'DELETE_IN_PROGRESS'
    DELETE_FAILED = 'DELETE_FAILED'
    DELETE_COMPLETE = 'DELETE_COMPLETE'

    def __init__(self, context, stack_name, template, stack_id=0, parms=None,
                 metadata_server=None):
        self.id = stack_id
        self.context = context
        self.t = template
        self.maps = self.t.get('Mappings', {})
        self.res = {}
        self.doc = None
        self.name = stack_name
        self.parsed_template_id = 0
        self.metadata_server = metadata_server

        # Default Parameters
        self.parms = checkeddict.CheckedDict('Parameters')
        self.parms.addschema('AWS::StackName', {"Description": "AWS StackName",
                                                "Type": "String"})
        self.parms['AWS::StackName'] = stack_name
        self.parms.addschema('AWS::Region', {"Description": "AWS Regions",
            "Default": "ap-southeast-1",
            "Type": "String",
            "AllowedValues": ["us-east-1", "us-west-1", "us-west-2",
                              "sa-east-1", "eu-west-1", "ap-southeast-1",
                              "ap-northeast-1"],
            "ConstraintDescription": "must be a valid EC2 instance type."})

        # template Parameters
        ps = self.t.get('Parameters', {})
        for p in ps:
            self.parms.addschema(p, ps[p])

        # user Parameters
        if parms is not None:
            self.parms.update(parms)

        self.outputs = self.resolve_static_data(self.t.get('Outputs', {}))

        self.resources = dict((name,
                               Resource(name, data, self))
                              for (name, data) in self.t['Resources'].items())

        self.dependencies = dependencies.Dependencies()
        for resource in self.resources.values():
            resource.add_dependencies(self.dependencies)

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
        return self.resources.keys()

    def __str__(self):
        return 'Stack "%s"' % self.name

    def validate(self):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/\
        APIReference/API_ValidateTemplate.html
        '''
        # TODO(sdake) Should return line number of invalid reference

        response = None

        for res in self:
            try:
                result = res.validate()
            except Exception as ex:
                logger.exception('validate')
                result = str(ex)

            if result:
                err_str = 'Malformed Query Response %s' % result
                response = {'ValidateTemplateResult': {
                                'Description': err_str,
                                'Parameters': []}}
                return response

        if response is None:
            response = {'ValidateTemplateResult': {
                        'Description': 'Successfully validated',
                        'Parameters': []}}
        for p in self.parms:
            jp = {'member': {}}
            res = jp['member']
            res['NoEcho'] = 'false'
            res['ParameterKey'] = p
            res['Description'] = self.parms.get_attr(p, 'Description')
            res['DefaultValue'] = self.parms.get_attr(p, 'Default')
            response['ValidateTemplateResult']['Parameters'].append(res)
        return response

    def parsed_template_get(self):
        stack = None
        if self.parsed_template_id == 0:
            if self.id == 0:
                stack = db_api.stack_get(self.context, self.id)
            else:
                stack = db_api.stack_get_by_name(self.context, self.name)

            if stack is None:
                return None

            self.parsed_template_id = stack.raw_template.parsed_template.id
        return db_api.parsed_template_get(self.context,
                                          self.parsed_template_id)

    def update_parsed_template(self):
        '''
        Update the parsed template after each resource has been
        created, so commands like describe will work.
        '''
        pt = self.parsed_template_get()
        if pt:
            template = self.t.copy()
            template['Resources'] = dict((k, r.parsed_template())
                                         for (k, r) in self.resources.items())
            pt.update_and_save({'template': template})
        else:
            logger.warn('Cant find parsed template to update %d' %
                        self.parsed_template_id)

    def state_set(self, new_status, reason='change in resource state'):
        if self.id != 0:
            stack = db_api.stack_get(self.context, self.id)
        else:
            stack = db_api.stack_get_by_name(self.context, self.name)

        if stack is None:
            return

        self.id = stack.id
        stack.update_and_save({'status': new_status,
                               'status_reason': reason})

    def create(self, timeout_in_minutes=60):
        '''
        Create the stack and all of the resources.

        Creation will fail if it exceeds the specified timeout. The default is
        60 minutes.
        '''
        self.state_set(self.IN_PROGRESS, 'Stack creation started')

        stack_status = self.CREATE_COMPLETE
        reason = 'Stack successfully created'
        res = None

        with eventlet.Timeout(timeout_in_minutes * 60) as tmo:
            try:
                for res in self:
                    if stack_status != self.CREATE_FAILED:
                        result = res.create()
                        if result:
                            stack_status = self.CREATE_FAILED
                            reason = 'Resource %s failed with: %s' % (str(res),
                                                                      result)

                        try:
                            self.update_parsed_template()
                        except Exception as ex:
                            logger.exception('update_parsed_template')

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
        self.state_set(self.DELETE_IN_PROGRESS)

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
        value = self.outputs[key].get('Value', '')
        return self.resolve_runtime_data(value)

    def get_outputs(self):
        def output_dict(k):
            return {'Description': self.outputs[k].get('Description',
                                                       'No description given'),
                    'OutputKey': k,
                    'OutputValue': self.output(k)}

        return [output_dict(key) for key in self.outputs]

    def restart_resource(self, resource_name):
        '''
        stop resource_name and all that depend on it
        start resource_name and all that depend on it
        '''

        if self.parsed_template_id == 0:
            stack = db_api.stack_get(self.context, self.id)
            if stack:
                self.parsed_template_id = stack.raw_template.parsed_template.id

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

                try:
                    self.update_parsed_template()
                except Exception as ex:
                    logger.exception('update_parsed_template')
            else:
                res.state_set(res.CREATE_FAILED)
        # TODO(asalkeld) if any of this fails we Should
        # restart the whole stack

    def parameter_get(self, key):
        if not key in self.parms:
            raise exception.UserParameterMissing(key=key)
        try:
            return self.parms[key]
        except ValueError:
            raise exception.UserParameterMissing(key=key)

    def _resolve_static_refs(self, s):
        '''
            looking for { "Ref" : "str" }
        '''
        def match(key, value):
            return (key == 'Ref' and
                    isinstance(value, basestring) and
                    value in self.parms)

        def handle(ref):
            return self.parameter_get(ref)

        return _resolve(match, handle, s)

    def _resolve_availability_zones(self, s):
        '''
            looking for { "Fn::GetAZs" : "str" }
        '''
        def match(key, value):
            return (key == 'Fn::GetAZs' and
                    isinstance(value, basestring))

        def handle(ref):
            return ['nova']

        return _resolve(match, handle, s)

    def _resolve_find_in_map(self, s):
        def handle(args):
            try:
                name, key, value = args
                return self.maps[name][key][value]
            except (ValueError, TypeError) as ex:
                raise KeyError(str(ex))

        return _resolve(lambda k, v: k == 'Fn::FindInMap', handle, s)

    def _resolve_attributes(self, s):
        '''
            looking for something like:
            { "Fn::GetAtt" : [ "DBInstance", "Endpoint.Address" ] }
        '''
        def match_ref(key, value):
            return key == 'Ref' and value in self

        def handle_ref(arg):
            return self[arg].FnGetRefId()

        def handle_getatt(args):
            resource, att = args
            try:
                return self[resource].FnGetAtt(att)
            except KeyError:
                raise exception.InvalidTemplateAttribute(resource=resource,
                                                         key=att)

        return _resolve(lambda k, v: k == 'Fn::GetAtt', handle_getatt,
                        _resolve(match_ref, handle_ref, s))

    @staticmethod
    def _resolve_joins(s):
        '''
            looking for { "Fn::Join" : [] }
        '''
        def handle(args):
            delim, strings = args
            return delim.join(strings)

        return _resolve(lambda k, v: k == 'Fn::Join', handle, s)

    @staticmethod
    def _resolve_base64(s):
        '''
            looking for { "Fn::Base64" : "" }
        '''
        return _resolve(lambda k, v: k == 'Fn::Base64', lambda d: d, s)

    def resolve_static_data(self, snippet):
        return transform(snippet, [self._resolve_static_refs,
                                   self._resolve_availability_zones,
                                   self._resolve_find_in_map])

    def resolve_runtime_data(self, snippet):
        return transform(snippet, [self._resolve_attributes,
                                   self._resolve_joins,
                                   self._resolve_base64])


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
