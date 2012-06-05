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
from heat.engine.resources import Resource
from heat.db import api as db_api

logger = logging.getLogger(__file__)


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
        self.outputs = self.t.get('Outputs', {})
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
            self._apply_user_parameters(parms)

        self.resources = {}
        for rname, rdesc in self.t['Resources'].items():
            res = Resource(rname, rdesc, self)
            self.resources[rname] = res

            self.calulate_dependencies(res.t, res)

    def validate(self):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/ \
            APIReference/API_ValidateTemplate.html
        '''
        # TODO(sdake) Should return line number of invalid reference

        response = None
        try:
            order = self.get_create_order()
        except KeyError as ex:
            res = 'A Ref operation referenced a non-existent key '\
                  '[%s]' % str(ex)

            response = {'ValidateTemplateResult': {
                        'Description': 'Malformed Query Response [%s]' % (res),
                        'Parameters': []}}
            return response

        for r in order:
            try:
                res = self.resources[r].validate()
            except Exception as ex:
                logger.exception('validate')
                res = str(ex)
            finally:
                if res:
                    err_str = 'Malformed Query Response [%s]' % (res)
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

    def resource_append_deps(self, resource, order_list):
        '''
        For the given resource first append it's dependancies then
        it's self to order_list.
        '''
        for r in resource.depends_on:
            self.resource_append_deps(self.resources[r], order_list)
        if not resource.name in order_list:
            order_list.append(resource.name)

    def get_create_order(self):
        '''
        return a list of Resource names in the correct order
        for startup.
        '''
        order = []
        for r in self.t['Resources']:
            if self.t['Resources'][r]['Type'] == 'AWS::EC2::Volume' or \
               self.t['Resources'][r]['Type'] == 'AWS::EC2::EIP':
                if len(self.resources[r].depends_on) == 0:
                    order.append(r)

        for r in self.t['Resources']:
            self.resource_append_deps(self.resources[r], order)

        return order

    def update_parsed_template(self):
        '''
        Update the parsed template after each resource has been
        created, so commands like describe will work.
        '''
        if self.parsed_template_id == 0:
            stack = db_api.stack_get(self.context, self.name)
            if stack:
                self.parsed_template_id = stack.raw_template.parsed_template.id
            else:
                return

        pt = db_api.parsed_template_get(self.context, self.parsed_template_id)
        if pt:
            pt.update_and_save({'template': self.t.copy()})
        else:
            logger.warn('Cant find parsed template to update %d' %
                        self.parsed_template_id)

    def status_set(self, new_status, reason='change in resource state'):

        self.t['stack_status'] = new_status
        self.update_parsed_template()

    def create_blocking(self):
        '''
        create all the resources in the order specified by get_create_order
        '''
        order = self.get_create_order()
        failed = False
        self.status_set(self.IN_PROGRESS)

        for r in order:
            res = self.resources[r]
            if not failed:
                try:
                    res.create()
                except Exception as ex:
                    logger.exception('create')
                    failed = True
                    res.state_set(res.CREATE_FAILED, str(ex))

                try:
                    self.update_parsed_template()
                except Exception as ex:
                    logger.exception('update_parsed_template')

            else:
                res.state_set(res.CREATE_FAILED)

        self.status_set(failed and self.CREATE_FAILED or self.CREATE_COMPLETE)

    def create(self):

        pool = eventlet.GreenPool()
        pool.spawn_n(self.create_blocking)

    def delete_blocking(self):
        '''
        delete all the resources in the reverse order specified by
        get_create_order().
        '''
        order = self.get_create_order()
        failed = False
        self.status_set(self.DELETE_IN_PROGRESS)

        for r in reversed(order):
            res = self.resources[r]
            try:
                res.delete()
                re = db_api.resource_get(self.context, self.resources[r].id)
                re.delete()
            except Exception as ex:
                failed = True
                res.state_set(res.DELETE_FAILED)
                logger.error('delete: %s' % str(ex))

        self.status_set(failed and self.DELETE_FAILED or self.DELETE_COMPLETE)
        if not failed:
            db_api.stack_delete(self.context, self.name)

    def delete(self):
        pool = eventlet.GreenPool()
        pool.spawn_n(self.delete_blocking)

    def get_outputs(self):
        outputs = self.resolve_runtime_data(self.outputs)

        def output_dict(k):
            return {'Description': outputs[k].get('Description',
                                                  'No description given'),
                    'OutputKey': k,
                    'OutputValue': outputs[k].get('Value', '')}

        return [output_dict(key) for key in outputs]

    def restart_resource_blocking(self, resource_name):
        '''
        stop resource_name and all that depend on it
        start resource_name and all that depend on it
        '''
        order = []
        self.resource_append_deps(self.resources[resource_name], order)

        for r in reversed(order):
            res = self.resources[r]
            try:
                res.delete()
                #db_api.resource_get(context, self.resources[r].id).delete()
            except Exception as ex:
                failed = True
                res.state_set(res.DELETE_FAILED)
                logger.error('delete: %s' % str(ex))

        for r in order:
            res = self.resources[r]
            if not failed:
                try:
                    res.create()
                except Exception as ex:
                    logger.exception('create')
                    failed = True
                    res.state_set(res.CREATE_FAILED, str(ex))

                try:
                    self.update_parsed_template()
                except Exception as ex:
                    logger.exception('update_parsed_template')

            else:
                res.state_set(res.CREATE_FAILED)
        # TODO(asalkeld) if any of this fails we Should
        # restart the whole stack

    def restart_resource(self, resource_name):
        pool = eventlet.GreenPool()
        pool.spawn_n(self.restart_resource_blocking)

    def calulate_dependencies(self, s, r):
        if isinstance(s, dict):
            for i in s:
                if i == 'Fn::GetAtt':
                    #print '%s seems to depend on %s' % (r.name, s[i][0])
                    #r.depends_on.append(s[i][0])
                    pass
                elif i == 'Ref':
                    #print '%s Refences %s' % (r.name, s[i])
                    if r.strict_dependency():
                        r.depends_on.append(s[i])
                elif i == 'DependsOn':
                    #print '%s DependsOn on %s' % (r.name, s[i])
                    r.depends_on.append(s[i])
                else:
                    self.calulate_dependencies(s[i], r)
        elif isinstance(s, list):
            for index, item in enumerate(s):
                self.calulate_dependencies(item, r)

    def _apply_user_parameters(self, parms):
        for p in parms:
            if 'Parameters.member.' in p and 'ParameterKey' in p:
                s = p.split('.')
                try:
                    key_name = 'Parameters.member.%s.ParameterKey' % s[2]
                    value_name = 'Parameters.member.%s.ParameterValue' % s[2]
                    logger.debug('appling user parameter %s=%s' %
                        (key_name, value_name))
                    self.parms[parms[key_name]] = parms[value_name]
                except Exception:
                    logger.error('Could not apply parameter %s' % p)

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
            return key == 'Ref' and value in self.resources

        def handle_ref(arg):
            return self.resources[arg].FnGetRefId()

        def handle_getatt(args):
            resource, att = args
            try:
                return self.resources[resource].FnGetAtt(att)
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
    recurse = lambda k: _resolve(match, handle, snippet[k])

    if isinstance(snippet, dict):
        should_handle = lambda k: match(k, snippet[k])
        matches = itertools.imap(recurse,
                                 itertools.ifilter(should_handle, snippet))
        try:
            args = next(matches)
        except StopIteration:
            # No matches
            return dict((k, recurse(k)) for k in snippet)
        else:
            return handle(args)
    elif isinstance(snippet, list):
        return [recurse(i) for i in range(len(snippet))]
    return snippet
