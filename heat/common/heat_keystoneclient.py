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

from heat.openstack.common import exception

import eventlet
from keystoneclient.v2_0 import client as kc
from oslo.config import cfg

from heat.openstack.common import log as logging

logger = logging.getLogger('heat.common.keystoneclient')


class KeystoneClient(object):
    """
    Wrap keystone client so we can encapsulate logic used in resources
    Note this is intended to be initialized from a resource on a per-session
    basis, so the session context is passed in on initialization
    Also note that a copy of this is created every resource as self.keystone()
    via the code in engine/client.py, so there should not be any need to
    directly instantiate instances of this class inside resources themselves
    """
    def __init__(self, context):
        self.context = context
        kwargs = {
            'auth_url': context.auth_url,
        }

        if context.password is not None:
            kwargs['username'] = context.username
            kwargs['password'] = context.password
            kwargs['tenant_name'] = context.tenant
            kwargs['tenant_id'] = context.tenant_id
        elif context.auth_token is not None:
            kwargs['tenant_name'] = context.tenant
            kwargs['token'] = context.auth_token
        else:
            logger.error("Keystone connection failed, no password or " +
                         "auth_token!")
            return
        self.client = kc.Client(**kwargs)
        self.client.authenticate()

    def create_stack_user(self, username, password=''):
        """
        Create a user defined as part of a stack, either via template
        or created internally by a resource.  This user will be added to
        the heat_stack_user_role as defined in the config
        Returns the keystone ID of the resulting user
        """
        user = self.client.users.create(username,
                                        password,
                                        '%s@heat-api.org' %
                                        username,
                                        tenant_id=self.context.tenant_id,
                                        enabled=True)

        # We add the new user to a special keystone role
        # This role is designed to allow easier differentiation of the
        # heat-generated "stack users" which will generally have credentials
        # deployed on an instance (hence are implicitly untrusted)
        roles = self.client.roles.list()
        stack_user_role = [r.id for r in roles
                           if r.name == cfg.CONF.heat_stack_user_role]
        if len(stack_user_role) == 1:
            role_id = stack_user_role[0]
            logger.debug("Adding user %s to role %s" % (user.id, role_id))
            self.client.roles.add_user_role(user.id, role_id,
                                            self.context.tenant_id)
        else:
            logger.error("Failed to add user %s to role %s, check role exists!"
                         % (username,
                            cfg.CONF.heat_stack_user_role))

        return user.id

    def delete_stack_user(self, user_id):

        user = self.client.users.get(user_id)

        # FIXME (shardy) : need to test, do we still need this retry logic?
        # Copied from user.py, but seems like something we really shouldn't
        # need to do, no bug reference in the original comment (below)...
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
                    logger.warning("Problem deleting user %s: %s" %
                                   (user_id, reason))
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

    def delete_ec2_keypair(self, user_id, accesskey):
        self.client.ec2.delete(user_id, accesskey)

    def get_ec2_keypair(self, user_id):
        # We make the assumption that each user will only have one
        # ec2 keypair, it's not clear if AWS allow multiple AccessKey resources
        # to be associated with a single User resource, but for simplicity
        # we assume that here for now
        cred = self.client.ec2.list(user_id)
        if len(cred) == 0:
            return self.client.ec2.create(user_id, self.context.tenant_id)
        if len(cred) == 1:
            return cred[0]
        else:
            logger.error("Unexpected number of ec2 credentials %s for %s" %
                         (len(cred), user_id))
