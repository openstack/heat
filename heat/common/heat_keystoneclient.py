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

from heat.common import context
from heat.common import exception

import eventlet

from keystoneclient.v2_0 import client as kc
from keystoneclient.v3 import client as kc_v3
from oslo.config import cfg

from heat.openstack.common import importutils
from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

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
        # We have to maintain two clients authenticated with keystone:
        # - ec2 interface is v2.0 only
        # - trusts is v3 only
        # If a trust_id is specified in the context, we immediately
        # authenticate so we can populate the context with a trust token
        # otherwise, we delay client authentication until needed to avoid
        # unnecessary calls to keystone.
        #
        # Note that when you obtain a token using a trust, it cannot be
        # used to reauthenticate and get another token, so we have to
        # get a new trust-token even if context.auth_token is set.
        #
        # - context.auth_url is expected to contain the v2.0 keystone endpoint
        self.context = context
        self._client_v2 = None
        self._client_v3 = None

        if self.context.trust_id:
            # Create a connection to the v2 API, with the trust_id, this
            # populates self.context.auth_token with a trust-scoped token
            self._client_v2 = self._v2_client_init()

    @property
    def client_v3(self):
        if not self._client_v3:
            # Create connection to v3 API
            self._client_v3 = self._v3_client_init()
        return self._client_v3

    @property
    def client_v2(self):
        if not self._client_v2:
            self._client_v2 = self._v2_client_init()
        return self._client_v2

    def _v2_client_init(self):
        kwargs = {
            'auth_url': self.context.auth_url
        }
        auth_kwargs = {}
        # Note try trust_id first, as we can't reuse auth_token in that case
        if self.context.trust_id is not None:
            # We got a trust_id, so we use the admin credentials
            # to authenticate, then re-scope the token to the
            # trust impersonating the trustor user.
            # Note that this currently requires the trustor tenant_id
            # to be passed to the authenticate(), unlike the v3 call
            kwargs.update(self._service_admin_creds(api_version=2))
            auth_kwargs['trust_id'] = self.context.trust_id
            auth_kwargs['tenant_id'] = self.context.tenant_id
        elif self.context.auth_token is not None:
            kwargs['tenant_name'] = self.context.tenant
            kwargs['token'] = self.context.auth_token
        elif self.context.password is not None:
            kwargs['username'] = self.context.username
            kwargs['password'] = self.context.password
            kwargs['tenant_name'] = self.context.tenant
            kwargs['tenant_id'] = self.context.tenant_id
        else:
            logger.error(_("Keystone v2 API connection failed, no password "
                         "or auth_token!"))
            raise exception.AuthorizationFailure()
        client_v2 = kc.Client(**kwargs)

        client_v2.authenticate(**auth_kwargs)
        # If we are authenticating with a trust auth_kwargs are set, so set
        # the context auth_token with the re-scoped trust token
        if auth_kwargs:
            # Sanity check
            if not client_v2.auth_ref.trust_scoped:
                logger.error(_("v2 trust token re-scoping failed!"))
                raise exception.AuthorizationFailure()
            # All OK so update the context with the token
            self.context.auth_token = client_v2.auth_ref.auth_token
            self.context.auth_url = kwargs.get('auth_url')

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
            logger.error(_("Keystone v3 API connection failed, no password "
                         "or auth_token!"))
            raise exception.AuthorizationFailure()

        client = kc_v3.Client(**kwargs)
        # Have to explicitly authenticate() or client.auth_ref is None
        client.authenticate()

        return client

    def create_trust_context(self):
        """
        If cfg.CONF.deferred_auth_method is trusts, we create a
        trust using the trustor identity in the current context, with the
        trustee as the heat service user and return a context containing
        the new trust_id

        If deferred_auth_method != trusts, or the current context already
        contains a trust_id, we do nothing and return the current context
        """
        if self.context.trust_id:
            return self.context

        # We need the service admin user ID (not name), as the trustor user
        # can't lookup the ID in keystoneclient unless they're admin
        # workaround this by creating a temporary admin client connection
        # then getting the user ID from the auth_ref
        admin_creds = self._service_admin_creds()
        admin_client = kc.Client(**admin_creds)
        trustee_user_id = admin_client.auth_ref.user_id
        trustor_user_id = self.client_v3.auth_ref.user_id
        trustor_project_id = self.client_v3.auth_ref.project_id
        roles = cfg.CONF.trusts_delegated_roles
        trust = self.client_v3.trusts.create(trustor_user=trustor_user_id,
                                             trustee_user=trustee_user_id,
                                             project=trustor_project_id,
                                             impersonation=True,
                                             role_names=roles)

        trust_context = context.RequestContext.from_dict(
            self.context.to_dict())
        trust_context.trust_id = trust.id
        trust_context.trustor_user_id = trustor_user_id
        return trust_context

    def delete_trust(self, trust_id):
        """
        Delete the specified trust.
        """
        self.client_v3.trusts.delete(trust_id)

    def create_stack_user(self, username, password=''):
        """
        Create a user defined as part of a stack, either via template
        or created internally by a resource.  This user will be added to
        the heat_stack_user_role as defined in the config
        Returns the keystone ID of the resulting user
        """
        if(len(username) > 64):
            logger.warning(_("Truncating the username %s to the last 64 "
                           "characters.") % username)
            #get the last 64 characters of the username
            username = username[-64:]
        user = self.client_v2.users.create(username,
                                           password,
                                           '%s@openstack.org' %
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
            logger.debug(_("Adding user %(user)s to role %(role)s") % {
                         'user': user.id, 'role': role_id})
            self.client_v2.roles.add_user_role(user.id, role_id,
                                               self.context.tenant_id)
        else:
            logger.error(_("Failed to add user %(user)s to role %(role)s, "
                         "check role exists!") % {'user': username,
                         'role': cfg.CONF.heat_stack_user_role})

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
                    logger.warning(_("Problem deleting user %(user)s: "
                                     "%(reason)s") % {'user': user_id,
                                                      'reason': reason})
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
            logger.error(_("Unexpected number of ec2 credentials %(len)s "
                           "for %(user)s") % {'len': len(cred),
                                              'user': user_id})

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
