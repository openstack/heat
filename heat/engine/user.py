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

import logging
from heat.common import exception
from heat.engine.resources import Resource


logger = logging.getLogger('heat.engine.user')

#
# We are ignoring Policies and Groups as keystone does not support them.
#
# For now support users and accesskeys.
#


class DummyId:
    def __init__(self, id):
        self.id = id


class User(Resource):
    properties_schema = {'Path': {'Type': 'String',
                                  'Implemented': False},
                         'Groups': {'Type': 'CommaDelimitedList',
                                    'Implemented': False},
                         'LoginProfile': {'Type': 'List'},
                         'Policies': {'Type': 'List',
                                      'Implemented': False}}

    def __init__(self, name, json_snippet, stack):
        super(User, self).__init__(name, json_snippet, stack)

    def create(self):
        if self.state in [self.CREATE_IN_PROGRESS, self.CREATE_COMPLETE]:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(User, self).create()

        passwd = ''
        if 'LoginProfile' in self.properties:
            if self.properties['LoginProfile'] and \
                'Password' in self.properties['LoginProfile']:
                passwd = self.properties['LoginProfile']['Password']

        tenant_id = self.stack.context.tenant_id
        user = self.keystone().users.create(self.name, passwd,
                                            '%s@heat-api.org' % self.name,
                                            tenant_id=tenant_id,
                                            enabled=True)
        self.instance_id_set(user.id)
        self.state_set(self.CREATE_COMPLETE)

    def delete(self):
        if self.state in [self.DELETE_IN_PROGRESS, self.DELETE_COMPLETE]:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        super(User, self).delete()

        try:
            user = self.keystone().users.get(DummyId(self.instance_id))
        except Exception as ex:
            logger.info('user %s/%s does not exist' % (self.name,
                                                       self.instance_id))
        else:
            user.delete()

        self.state_set(self.DELETE_COMPLETE)

    def FnGetRefId(self):
        return unicode(self.name)

    def FnGetAtt(self, key):
        res = None
        if key == 'Policies':
            res = self.properties['Policies']
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
        self._secret = None

    def _user_from_name(self, username):
        tenant_id = self.stack.context.tenant_id
        users = self.keystone().users.list(tenant_id=tenant_id)
        for u in users:
            if u.name == self.properties['UserName']:
                return u
        return None

    def create(self):
        if self.state in [self.CREATE_IN_PROGRESS, self.CREATE_COMPLETE]:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(AccessKey, self).create()

        user = self._user_from_name(self.properties['UserName'])
        if user is None:
            raise exception.NotFound('could not find user %s' %
                                     self.properties['UserName'])

        tenant_id = self.stack.context.tenant_id
        cred = self.keystone().ec2.create(user.id, tenant_id)
        self.instance_id_set(cred.access)
        self._secret = cred.secret

        self.state_set(self.CREATE_COMPLETE)

    def delete(self):
        if self.state in [self.DELETE_IN_PROGRESS, self.DELETE_COMPLETE]:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        super(AccessKey, self).delete()

        user = self._user_from_name(self.properties['UserName'])
        if user and self.instance_id:
            self.keystone().ec2.delete(user.id, self.instance_id)

        self.state_set(self.DELETE_COMPLETE)

    def _secret_accesskey(self):
        '''
        Return the user's access key, fetching it from keystone if necessary
        '''
        if self._secret is None:
            user = self._user_from_name(self.properties['UserName'])
            if user is None:
                logger.warn('could not find user %s' %
                            self.properties['UserName'])
            else:
                try:
                    cred = self.keystone().ec2.get(user.id, self.instance_id)
                    self._secret = cred.secret
                    self.instance_id_set(cred.access)
                except Exception as ex:
                    logger.warn('could not get secret for %s Error:%s' %
                                (self.properties['UserName'],
                                 str(ex)))

        return self._secret or '000-000-000'

    def FnGetAtt(self, key):
        res = None
        if key == 'UserName':
            res = self.properties['UserName']
        if key == 'SecretAccessKey':
            res = self._secret_accesskey()
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        logger.info('%s.GetAtt(%s) == %s' % (self.name, key, res))
        return unicode(res)
