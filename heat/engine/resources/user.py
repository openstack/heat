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
from heat.common import exception
from heat.openstack.common import cfg
from heat.engine.resources import resource

from heat.openstack.common import log as logging

logger = logging.getLogger('heat.engine.user')

#
# We are ignoring Policies and Groups as keystone does not support them.
#
# For now support users and accesskeys.
#


class DummyId:
    def __init__(self, id):
        self.id = id

    def __eq__(self, other):
        return self.id == other.id


class User(resource.Resource):
    properties_schema = {'Path': {'Type': 'String'},
                         'Groups': {'Type': 'List'},
                         'LoginProfile': {'Type': 'Map',
                                          'Schema': {
                                              'Password': {'Type': 'String'}
                                           }},
                         'Policies': {'Type': 'List'}}

    def __init__(self, name, json_snippet, stack):
        super(User, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        passwd = ''
        if self.properties['LoginProfile'] and \
            'Password' in self.properties['LoginProfile']:
            passwd = self.properties['LoginProfile']['Password']

        tenant_id = self.context.tenant_id
        user = self.keystone().users.create(self.physical_resource_name(),
                                            passwd,
                                            '%s@heat-api.org' %
                                            self.physical_resource_name(),
                                            tenant_id=tenant_id,
                                            enabled=True)
        self.instance_id_set(user.id)

        # We add the new user to a special keystone role
        # This role is designed to allow easier differentiation of the
        # heat-generated "stack users" which will generally have credentials
        # deployed on an instance (hence are implicitly untrusted)
        roles = self.keystone().roles.list()
        stack_user_role = [r.id for r in roles
                         if r.name == cfg.CONF.heat_stack_user_role]
        if len(stack_user_role) == 1:
            role_id = stack_user_role[0]
            logger.debug("Adding user %s to role %s" % (user.id, role_id))
            self.keystone().roles.add_user_role(user.id, role_id, tenant_id)
        else:
            logger.error("Failed to add user %s to role %s, check role exists!"
                         % (self.physical_resource_name(),
                            cfg.CONF.heat_stack_user_role))

    def handle_update(self):
        return self.UPDATE_REPLACE

    def handle_delete(self):
        if self.instance_id is None:
            return
        try:
            user = self.keystone().users.get(DummyId(self.instance_id))
        except Exception as ex:
            logger.info('user %s/%s does not exist' %
                        (self.physical_resource_name(), self.instance_id))
            return

        # tempory hack to work around an openstack bug.
        # seems you can't delete a user first time - you have to try
        # a couple of times - go figure!
        tmo = eventlet.Timeout(10)
        status = 'WAITING'
        reason = 'Timed out trying to delete user'
        try:
            while status == 'WAITING':
                try:
                    user.delete()
                    status = 'DELETED'
                except Exception as ce:
                    reason = str(ce)
                    eventlet.sleep(1)
        except eventlet.Timeout as t:
            if t is not tmo:
                # not my timeout
                raise
            else:
                status = 'TIMEDOUT'
        finally:
            tmo.cancel()

        if status != 'DELETED':
            raise exception.Error(reason)

    def FnGetRefId(self):
        return unicode(self.physical_resource_name())

    def FnGetAtt(self, key):
        #TODO Implement Arn attribute
        raise exception.InvalidTemplateAttribute(
                resource=self.physical_resource_name(), key=key)


class AccessKey(resource.Resource):
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
        tenant_id = self.context.tenant_id
        users = self.keystone().users.list(tenant_id=tenant_id)
        for u in users:
            if u.name == username:
                return u
        return None

    def handle_create(self):
        username = self.properties['UserName']
        user = self._user_from_name(username)
        if user is None:
            raise exception.NotFound('could not find user %s' %
                                     username)

        tenant_id = self.context.tenant_id
        cred = self.keystone().ec2.create(user.id, tenant_id)
        self.instance_id_set(cred.access)
        self._secret = cred.secret

    def handle_update(self):
        return self.UPDATE_REPLACE

    def handle_delete(self):
        user = self._user_from_name(self.properties['UserName'])
        if user and self.instance_id:
            self.keystone().ec2.delete(user.id, self.instance_id)

    def _secret_accesskey(self):
        '''
        Return the user's access key, fetching it from keystone if necessary
        '''
        if self._secret is None:
            try:
                # Here we use the user_id of the user context of the request
                # We need to avoid using _user_from_name, because users.list
                # needs keystone admin role, and we want to allow an instance
                # user to retrieve data about itself:
                # - Users without admin role cannot create or delete, but they
                #   can see their own secret key (but nobody elses)
                # - Users with admin role can create/delete and view the
                #   private keys of all users in their tenant
                # This will allow "instance users" to retrieve resource
                # metadata but not manipulate user resources in any other way
                user_id = self.keystone().auth_user_id
                cred = self.keystone().ec2.get(user_id, self.instance_id)
                self._secret = cred.secret
                self.instance_id_set(cred.access)
            except Exception as ex:
                logger.warn('could not get secret for %s Error:%s' %
                            (self.properties['UserName'],
                             str(ex)))

        return self._secret or '000-000-000'

    def FnGetAtt(self, key):
        res = None
        log_res = None
        self.calculate_properties()
        if key == 'UserName':
            res = self.properties['UserName']
            log_res = res
        elif key == 'SecretAccessKey':
            res = self._secret_accesskey()
            log_res = "<SANITIZED>"
        else:
            raise exception.InvalidTemplateAttribute(
                        resource=self.physical_resource_name(), key=key)

        logger.info('%s.GetAtt(%s) == %s' % (self.physical_resource_name(),
                                             key, log_res))
        return unicode(res)
