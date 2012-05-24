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
import logging
import os
from novaclient.exceptions import BadRequest
from heat.common import exception
from heat.engine.resources import Resource

logger = logging.getLogger(__file__)


class User(Resource):
    properties_schema = {'Path': {'Type': 'String',
                                  'Implemented': False},
                         'Groups': {'Type': 'CommaDelimitedList',
                                    'Implemented': False},
                         'LoginProfile': {'Type': 'String',
                                          'Implemented': False},
                         'Policies': {'Type': 'CommaDelimitedList'}}

    def __init__(self, name, json_snippet, stack):
        super(User, self).__init__(name, json_snippet, stack)
        self.instance_id = ''

    def create(self):
        self.state_set(self.CREATE_COMPLETE)

    def FnGetAtt(self, key):
        res = None
        if key == 'Policies':
            res = self.t['Properties']['Policies']
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        logger.info('%s.GetAtt(%s) == %s' % (self.name, key, res))
        return unicode(res)


class AccessKey(Resource):
    properties_schema = {'Serial': {'Type': 'Integer',
                                  'Implemented': False},
                         'UserName': {'Type': 'String',
                                  'Required': True},
                         'Status': {'Type': 'String',
                                  'Implemented': False,
                                  'AllowedValues': ['Active', 'Inactive']}}

    def __init__(self, name, json_snippet, stack):
        super(AccessKey, self).__init__(name, json_snippet, stack)

    def create(self):
        self.state_set(self.CREATE_COMPLETE)

    def FnGetRefId(self):
        return unicode(self.name)

    def FnGetAtt(self, key):
        res = None
        if key == 'UserName':
            res = self.t['Properties']['UserName']
        if key == 'SecretAccessKey':
            res = 'TODO-Add-Real-SecreateAccessKey'
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        logger.info('%s.GetAtt(%s) == %s' % (self.name, key, res))
        return unicode(res)
