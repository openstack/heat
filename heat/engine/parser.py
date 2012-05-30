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
import logging
import sys
from heat.common import exception
from heat.engine import checkeddict
from heat.engine import cloud_watch
from heat.engine import eip
from heat.engine import escalation_policy
from heat.engine import instance
from heat.engine import resources
from heat.engine import security_group
from heat.engine import user
from heat.engine import volume
from heat.engine import wait_condition
from heat.db import api as db_api

logger = logging.getLogger(__file__)


(RESOURCE_CLASSES,) = ({
    'AWS::EC2::Instance': instance.Instance,
    'AWS::EC2::Volume': volume.Volume,
    'AWS::EC2::VolumeAttachment': volume.VolumeAttachment,
    'AWS::EC2::EIP': eip.ElasticIp,
    'AWS::EC2::EIPAssociation': eip.ElasticIpAssociation,
    'AWS::EC2::SecurityGroup': security_group.SecurityGroup,
    'AWS::CloudWatch::Alarm': cloud_watch.CloudWatchAlarm,
    'HEAT::Recovery::EscalationPolicy': escalation_policy.EscalationPolicy,
    'AWS::CloudFormation::WaitConditionHandle':
        wait_condition.WaitConditionHandle,
    'AWS::CloudFormation::WaitCondition': wait_condition.WaitCondition,
    'AWS::IAM::User': user.User,
    'AWS::IAM::AccessKey': user.AccessKey,
},)


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
        if parms != None:
            self._apply_user_parameters(parms)

        self.resources = {}
        for rname, res in self.t['Resources'].items():
            ResourceClass = RESOURCE_CLASSES.get(res['Type'],
                                                 resources.GenericResource)
            self.resources[rname] = ResourceClass(rname, res, self)

            self.calulate_dependencies(res, self.resources[rname])

    def validate(self):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/ \
            APIReference/API_ValidateTemplate.html
        '''
        # TODO(sdake) Should return line number of invalid reference

        response = None
        try:
            order = self.get_create_order()
        except KeyError:
            res = 'A Ref operation referenced a non-existent key '\
                  '[%s]' % sys.exc_value

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

        if response == None:
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
            stack = db_api.stack_get(None, self.name)
            if stack:
                self.parsed_template_id = stack.raw_template.parsed_template.id
            else:
                return

        pt = db_api.parsed_template_get(None, self.parsed_template_id)
        if pt:
            pt.update_and_save({'template': self.t.copy()})
        else:
            logger.warn('Cant find parsed template to update %d' % \
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
                db_api.resource_get(None, self.resources[r].id).delete()
            except Exception as ex:
                failed = True
                res.state_set(res.DELETE_FAILED)
                logger.error('delete: %s' % str(ex))

        self.status_set(failed and self.DELETE_FAILED or self.DELETE_COMPLETE)
        if not failed:
            db_api.stack_delete(None, self.name)

    def delete(self):
        pool = eventlet.GreenPool()
        pool.spawn_n(self.delete_blocking)

    def get_outputs(self):

        for r in self.resources:
            self.resources[r].reload()

        self.resolve_attributes(self.outputs)
        self.resolve_joins(self.outputs)

        outs = []
        for o in self.outputs:
            out = {}
            out['Description'] = self.outputs[o].get('Description',
                                                     'No description given')
            out['OutputKey'] = o
            out['OutputValue'] = self.outputs[o].get('Value', '')
            outs.append(out)

        return outs

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
                    logger.debug('appling user parameter %s=%s' % \
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

    def resolve_static_refs(self, s):
        '''
            looking for { "Ref": "str" }
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Ref' and \
                      isinstance(s[i], (basestring, unicode)) and \
                      s[i] in self.parms:
                    return self.parameter_get(s[i])
                else:
                    s[i] = self.resolve_static_refs(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                #print 'resolve_static_refs %d %s' % (index, item)
                s[index] = self.resolve_static_refs(item)
        return s

    def resolve_find_in_map(self, s):
        '''
            looking for { "Fn::FindInMap": ["str", "str"] }
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Fn::FindInMap':
                    obj = self.maps
                    if isinstance(s[i], list):
                        #print 'map list: %s' % s[i]
                        for index, item in enumerate(s[i]):
                            if isinstance(item, dict):
                                item = self.resolve_find_in_map(item)
                                #print 'map item dict: %s' % (item)
                            else:
                                pass
                                #print 'map item str: %s' % (item)
                            obj = obj[item]
                    else:
                        obj = obj[s[i]]
                    return obj
                else:
                    s[i] = self.resolve_find_in_map(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                s[index] = self.resolve_find_in_map(item)
        return s

    def resolve_attributes(self, s):
        '''
            looking for something like:
            {"Fn::GetAtt" : ["DBInstance", "Endpoint.Address"]}
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Ref' and s[i] in self.resources:
                    return self.resources[s[i]].FnGetRefId()
                elif i == 'Fn::GetAtt':
                    resource_name = s[i][0]
                    key_name = s[i][1]
                    res = self.resources.get(resource_name)
                    rc = None
                    if res:
                        return res.FnGetAtt(key_name)
                    else:
                        raise exception.InvalidTemplateAttribute(
                                        resource=resource_name, key=key_name)
                    return rc
                else:
                    s[i] = self.resolve_attributes(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                s[index] = self.resolve_attributes(item)
        return s

    def resolve_joins(self, s):
        '''
            looking for { "Fn::join": []}
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Fn::Join':
                    j = None
                    try:
                        j = s[i][0].join(s[i][1])
                    except Exception:
                        logger.error('Could not join %s' % str(s[i]))
                    return j
                else:
                    s[i] = self.resolve_joins(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                s[index] = self.resolve_joins(item)
        return s

    def resolve_base64(self, s):
        '''
            looking for { "Fn::join": [] }
        '''
        if isinstance(s, dict):
            for i in s:
                if i == 'Fn::Base64':
                    return s[i]
                else:
                    s[i] = self.resolve_base64(s[i])
        elif isinstance(s, list):
            for index, item in enumerate(s):
                s[index] = self.resolve_base64(item)
        return s
