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

import eventlet
import hashlib

from keystoneclient.v2_0 import client as kc
from keystoneclient.v3 import client as kc_v3
from oslo.config import cfg

from heat.openstack.common import importutils
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
        # We have to maintain two clients authenticated with keystone:
        # - ec2 interface is v2.0 only
        # - trusts is v3 only
        # - passing a v2 auth_token to the v3 client won't work until lp bug
        #   #1212778 is fixed
        # - passing a v3 token to the v2 client works but we have to either
        #   md5sum it or use the nocatalog option to auth/tokens (not yet
        #   supported by keystoneclient), or we hit the v2 8192byte size limit
        # - context.auth_url is expected to contain the v2.0 keystone endpoint
        if cfg.CONF.deferred_auth_method == 'trusts':
            # Create connection to v3 API
            self.client_v3 = self._v3_client_init()

            # Set context auth_token to md5sum of v3 token
            auth_token = self.client_v3.auth_ref.get('auth_token')
            self.context.auth_token = self._md5_token(auth_token)

            # Create the connection to the v2 API, reusing the md5-ified token
            self.client_v2 = self._v2_client_init()
        else:
            # Create the connection to the v2 API, using the context creds
            self.client_v2 = self._v2_client_init()
            self.client_v3 = None

    def _md5_token(self, auth_token):
        # Get the md5sum of the v3 token, which we can pass instead of the
        # actual token to avoid v2 8192byte size limit on the v2 token API
        m_enc = hashlib.md5()
        m_enc.update(auth_token)
        return m_enc.hexdigest()

    def _v2_client_init(self):
        kwargs = {
            'auth_url': self.context.auth_url
        }
        # Note check for auth_token first so we use existing token if
        # available from v3 auth
        if self.context.auth_token is not None:
            kwargs['tenant_name'] = self.context.tenant
            kwargs['token'] = self.context.auth_token
        elif self.context.password is not None:
            kwargs['username'] = self.context.username
            kwargs['password'] = self.context.password
            kwargs['tenant_name'] = self.context.tenant
            kwargs['tenant_id'] = self.context.tenant_id
        else:
            logger.error("Keystone v2 API connection failed, no password or "
                         "auth_token!")
            raise exception.AuthorizationFailure()
        client_v2 = kc.Client(**kwargs)
        if not client_v2.authenticate():
            logger.error("Keystone v2 API authentication failed")
            raise exception.AuthorizationFailure()
        return client_v2

    @staticmethod
    def _service_admin_creds(api_version=2):
        # Import auth_token to have keystone_authtoken settings setup.
        importutils.import_module('keystoneclient.middleware.auth_token')

        creds = {
            'username': cfg.CONF.keystone_authtoken.admin_user,
            'password': cfg.CONF.keystone_authtoken.admin_password,
        }
        if api_version >= 3:
            creds['auth_url'] =\
                cfg.CONF.keystone_authtoken.auth_uri.replace('v2.0', 'v3')
            creds['project_name'] =\
                cfg.CONF.keystone_authtoken.admin_tenant_name
        else:
            creds['auth_url'] = cfg.CONF.keystone_authtoken.auth_uri
            creds['tenant_name'] =\
                cfg.CONF.keystone_authtoken.admin_tenant_name

        return creds

    def _v3_client_init(self):
        kwargs = {}
        if self.context.auth_token is not None:
            kwargs['project_name'] = self.context.tenant
            kwargs['token'] = self.context.auth_token
            kwargs['auth_url'] = self.context.auth_url.replace('v2.0', 'v3')
            kwargs['endpoint'] = kwargs['auth_url']
        elif self.context.trust_id is not None:
            # We got a trust_id, so we use the admin credentials and get a
            # Token back impersonating the trustor user
            kwargs.update(self._service_admin_creds(api_version=3))
            kwargs['trust_id'] = self.context.trust_id
        elif self.context.password is not None:
            kwargs['username'] = self.context.username
            kwargs['password'] = self.context.password
            kwargs['project_name'] = self.context.tenant
            kwargs['project_id'] = self.context.tenant_id
            kwargs['auth_url'] = self.context.auth_url.replace('v2.0', 'v3')
            kwargs['endpoint'] = kwargs['auth_url']
        else:
            logger.error("Keystone v3 API connection failed, no password or "
                         "auth_token!")
            raise exception.AuthorizationFailure()

        client_v3 = kc_v3.Client(**kwargs)
        if not client_v3.authenticate():
            logger.error("Keystone v3 API authentication failed")
            raise exception.AuthorizationFailure()
        return client_v3

    def create_trust_context(self):
        """
        If cfg.CONF.deferred_auth_method is trusts, we create a
        trust using the trustor identity in the current context, with the
        trustee as the heat service user

        If deferred_auth_method != trusts, we do nothing

        If the current context already contains a trust_id, we do nothing
        """
        if cfg.CONF.deferred_auth_method != 'trusts':
            return

        if self.context.trust_id:
            return

        # We need the service admin user ID (not name), as the trustor user
        # can't lookup the ID in keystoneclient unless they're admin
        # workaround this by creating a temporary admin client connection
        # then getting the user ID from the auth_ref
        admin_creds = self._service_admin_creds()
        admin_client = kc.Client(**admin_creds)
        if not admin_client.authenticate():
            logger.error("Keystone v2 API admin authentication failed")
            raise exception.AuthorizationFailure()

        trustee_user_id = admin_client.auth_ref['user']['id']
        trustor_user_id = self.client_v3.auth_ref['user']['id']
        trustor_project_id = self.client_v3.auth_ref['project']['id']
        roles = cfg.CONF.trusts_delegated_roles
        trust = self.client_v3.trusts.create(trustor_user=trustor_user_id,
                                             trustee_user=trustee_user_id,
                                             project=trustor_project_id,
                                             impersonation=True,
                                             role_names=roles)
        self.context.trust_id = trust.id
        self.context.trustor_user_id = trustor_user_id

    def delete_trust_context(self):
        """
        If a trust_id exists in the context, we delete it

        """
        if not self.context.trust_id:
            return

        self.client_v3.trusts.delete(self.context.trust_id)

        self.context.trust_id = None
        self.context.trustor_user_id = None

    def create_stack_user(self, username, password=''):
        """
        Create a user defined as part of a stack, either via template
        or created internally by a resource.  This user will be added to
        the heat_stack_user_role as defined in the config
        Returns the keystone ID of the resulting user
        """
        if(len(username) > 64):
            logger.warning("Truncating the username %s to the last 64 "
                           "characters." % username)
            #get the last 64 characters of the username
            username = username[-64:]
        user = self.client_v2.users.create(username,
                                           password,
                                           '%s@heat-api.org' %
                                           username,
                                           tenant_id=self.context.tenant_id,
                                           enabled=True)

        # We add the new user to a special keystone role
        # This role is designed to allow easier differentiation of the
        # heat-generated "stack users" which will generally have credentials
        # deployed on an instance (hence are implicitly untrusted)
        roles = self.client_v2.roles.list()
        stack_user_role = [r.id for r in roles
                           if r.name == cfg.CONF.heat_stack_user_role]
        if len(stack_user_role) == 1:
            role_id = stack_user_role[0]
            logger.debug("Adding user %s to role %s" % (user.id, role_id))
            self.client_v2.roles.add_user_role(user.id, role_id,
                                               self.context.tenant_id)
        else:
            logger.error("Failed to add user %s to role %s, check role exists!"
                         % (username, cfg.CONF.heat_stack_user_role))

        return user.id

    def delete_stack_user(self, user_id):

        user = self.client_v2.users.get(user_id)

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
        self.client_v2.ec2.delete(user_id, accesskey)

    def get_ec2_keypair(self, user_id):
        # We make the assumption that each user will only have one
        # ec2 keypair, it's not clear if AWS allow multiple AccessKey resources
        # to be associated with a single User resource, but for simplicity
        # we assume that here for now
        cred = self.client_v2.ec2.list(user_id)
        if len(cred) == 0:
            return self.client_v2.ec2.create(user_id, self.context.tenant_id)
        if len(cred) == 1:
            return cred[0]
        else:
            logger.error("Unexpected number of ec2 credentials %s for %s" %
                         (len(cred), user_id))

    def disable_stack_user(self, user_id):
        # FIXME : This won't work with the v3 keystone API
        self.client_v2.users.update_enabled(user_id, False)

    def enable_stack_user(self, user_id):
        # FIXME : This won't work with the v3 keystone API
        self.client_v2.users.update_enabled(user_id, True)

    def url_for(self, **kwargs):
        return self.client_v2.service_catalog.url_for(**kwargs)

    @property
    def auth_token(self):
        return self.client_v2.auth_token
