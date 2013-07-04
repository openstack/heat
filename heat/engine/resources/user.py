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

from heat.common import exception
from heat.engine import clients
from heat.engine import resource

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)

#
# We are ignoring Groups as keystone does not support them.
# For now support users and accesskeys,
# We also now support a limited heat-native Policy implementation
#


class User(resource.Resource):
    properties_schema = {'Path': {'Type': 'String'},
                         'Groups': {'Type': 'List'},
                         'LoginProfile': {'Type': 'Map',
                                          'Schema': {
                                              'Password': {'Type': 'String'}
                                          }},
                         'Policies': {'Type': 'List'}}

    def _validate_policies(self, policies):
        for policy in (policies or []):
            # When we support AWS IAM style policies, we will have to accept
            # either a ref to an AWS::IAM::Policy defined in the stack, or
            # and embedded dict describing the policy directly, but for now
            # we only expect this list to contain strings, which must map
            # to an OS::Heat::AccessPolicy in this stack
            # If a non-string (e.g embedded IAM dict policy) is passed, we
            # ignore the policy (don't reject it because we previously ignored
            # and we don't want to break templates which previously worked
            if not isinstance(policy, basestring):
                logger.warning("Ignoring policy %s, " % policy
                               + "must be string resource name")
                continue

            try:
                policy_rsrc = self.stack.resources[policy]
            except KeyError:
                logger.error("Policy %s does not exist in stack %s" %
                             (policy, self.stack.name))
                return False

            if not callable(getattr(policy_rsrc, 'access_allowed', None)):
                logger.error("Policy %s is not an AccessPolicy resource" %
                             policy)
                return False

        return True

    def handle_create(self):
        passwd = ''
        if self.properties['LoginProfile'] and \
                'Password' in self.properties['LoginProfile']:
                passwd = self.properties['LoginProfile']['Password']

        if self.properties['Policies']:
            if not self._validate_policies(self.properties['Policies']):
                raise exception.InvalidTemplateAttribute(resource=self.name,
                                                         key='Policies')

        uid = self.keystone().create_stack_user(self.physical_resource_name(),
                                                passwd)
        self.resource_id_set(uid)

    def handle_delete(self):
        if self.resource_id is None:
            logger.error("Cannot delete User resource before user created!")
            return
        try:
            self.keystone().delete_stack_user(self.resource_id)
        except clients.hkc.kc.exceptions.NotFound:
            pass

    def handle_suspend(self):
        if self.resource_id is None:
            logger.error("Cannot suspend User resource before user created!")
            return
        self.keystone().disable_stack_user(self.resource_id)

    def handle_resume(self):
        if self.resource_id is None:
            logger.error("Cannot resume User resource before user created!")
            return
        self.keystone().enable_stack_user(self.resource_id)

    def FnGetRefId(self):
        return unicode(self.physical_resource_name())

    def FnGetAtt(self, key):
        #TODO(asalkeld) Implement Arn attribute
        raise exception.InvalidTemplateAttribute(
            resource=self.name, key=key)

    def access_allowed(self, resource_name):
        policies = (self.properties['Policies'] or [])
        for policy in policies:
            if not isinstance(policy, basestring):
                logger.warning("Ignoring policy %s, " % policy
                               + "must be string resource name")
                continue
            policy_rsrc = self.stack.resources[policy]
            if not policy_rsrc.access_allowed(resource_name):
                return False
        return True


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

    def _get_user(self):
        """
        Helper function to derive the keystone userid, which is stored in the
        resource_id of the User associated with this key.  We want to avoid
        looking the name up via listing keystone users, as this requires admin
        rights in keystone, so FnGetAtt which calls _secret_accesskey won't
        work for normal non-admin users
        """
        # Lookup User resource by intrinsic reference (which is what is passed
        # into the UserName parameter.  Would be cleaner to just make the User
        # resource return resource_id for FnGetRefId but the AWS definition of
        # user does say it returns a user name not ID
        return self.stack.resource_by_refid(self.properties['UserName'])

    def handle_create(self):
        user = self._get_user()
        if user is None:
            raise exception.NotFound('could not find user %s' %
                                     self.properties['UserName'])

        kp = self.keystone().get_ec2_keypair(user.resource_id)
        if not kp:
            raise exception.Error("Error creating ec2 keypair for user %s" %
                                  user)

        self.resource_id_set(kp.access)
        self._secret = kp.secret

    def handle_delete(self):
        self._secret = None
        if self.resource_id is None:
            return

        user = self._get_user()
        if user is None:
            logger.warning('Error deleting %s - user not found' % str(self))
            return
        user_id = user.resource_id
        if user_id:
            try:
                self.keystone().delete_ec2_keypair(user_id, self.resource_id)
            except clients.hkc.kc.exceptions.NotFound:
                pass

        self.resource_id_set(None)

    def _secret_accesskey(self):
        '''
        Return the user's access key, fetching it from keystone if necessary
        '''
        if self._secret is None:
            if not self.resource_id:
                logger.warn('could not get secret for %s Error:%s' %
                            (self.properties['UserName'],
                            "resource_id not yet set"))
            else:
                try:
                    user_id = self._get_user().resource_id
                    kp = self.keystone().get_ec2_keypair(user_id)
                except Exception as ex:
                    logger.warn('could not get secret for %s Error:%s' %
                                (self.properties['UserName'],
                                 str(ex)))
                else:
                    if kp.access == self.resource_id:
                        self._secret = kp.secret
                    else:
                        msg = ("Unexpected ec2 keypair, for %s access %s" %
                               (user_id, kp.access))
                        logger.error(msg)

        return self._secret or '000-000-000'

    def FnGetAtt(self, key):
        res = None
        log_res = None
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

    def access_allowed(self, resource_name):
        return self._get_user().access_allowed(resource_name)


class AccessPolicy(resource.Resource):
    properties_schema = {'AllowedResources': {'Type': 'List',
                                              'Required': True}}

    def handle_create(self):
        resources = self.properties['AllowedResources']
        # All of the provided resource names must exist in this stack
        for resource in resources:
            if resource not in self.stack:
                logger.error("AccessPolicy resource %s not in stack" %
                             resource)
                raise exception.ResourceNotFound(resource_name=resource,
                                                 stack_name=self.stack.name)

    def access_allowed(self, resource_name):
        return resource_name in self.properties['AllowedResources']


def resource_mapping():
    return {
        'AWS::IAM::User': User,
        'AWS::IAM::AccessKey': AccessKey,
        'OS::Heat::AccessPolicy': AccessPolicy,
    }
