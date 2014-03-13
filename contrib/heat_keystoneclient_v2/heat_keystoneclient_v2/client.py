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

from keystoneclient.v2_0 import client as kc
from oslo.config import cfg

from heat.common import exception
from heat.openstack.common.gettextutils import _
from heat.openstack.common import importutils
from heat.openstack.common import log as logging

logger = logging.getLogger('heat.common.keystoneclient')
logger.info(_("Keystone V2 loaded"))


class KeystoneClientV2(object):
    """
    Wrap keystone client so we can encapsulate logic used in resources
    Note this is intended to be initialized from a resource on a per-session
    basis, so the session context is passed in on initialization
    Also note that a copy of this is created every resource as self.keystone()
    via the code in engine/client.py, so there should not be any need to
    directly instantiate instances of this class inside resources themselves
    """
    def __init__(self, context):
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
        self._client = None

        if self.context.trust_id:
            # Create a connection to the v2 API, with the trust_id, this
            # populates self.context.auth_token with a trust-scoped token
            self._client = self._v2_client_init()

    @property
    def client(self):
        if not self._client:
            self._client = self._v2_client_init()
        return self._client

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
            kwargs.update(self._service_admin_creds())
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
        kwargs['cacert'] = self._get_client_option('ca_file')
        kwargs['insecure'] = self._get_client_option('insecure')
        kwargs['cert'] = self._get_client_option('cert_file')
        kwargs['key'] = self._get_client_option('key_file')
        client = kc.Client(**kwargs)

        client.authenticate(**auth_kwargs)
        # If we are authenticating with a trust auth_kwargs are set, so set
        # the context auth_token with the re-scoped trust token
        if auth_kwargs:
            # Sanity check
            if not client.auth_ref.trust_scoped:
                logger.error(_("v2 trust token re-scoping failed!"))
                raise exception.AuthorizationFailure()
            # All OK so update the context with the token
            self.context.auth_token = client.auth_ref.auth_token
            self.context.auth_url = kwargs.get('auth_url')
            # Ensure the v2 API we're using is not impacted by keystone
            # bug #1239303, otherwise we can't trust the user_id
            if self.context.trustor_user_id != client.auth_ref.user_id:
                logger.error("Trust impersonation failed, bug #1239303 "
                             "suspected, you may need a newer keystone")
                raise exception.AuthorizationFailure()

        return client

    @staticmethod
    def _service_admin_creds():
        # Import auth_token to have keystone_authtoken settings setup.
        importutils.import_module('keystoneclient.middleware.auth_token')

        creds = {
            'username': cfg.CONF.keystone_authtoken.admin_user,
            'password': cfg.CONF.keystone_authtoken.admin_password,
            'auth_url': cfg.CONF.keystone_authtoken.auth_uri,
            'tenant_name': cfg.CONF.keystone_authtoken.admin_tenant_name,
        }

        return creds

    def _get_client_option(self, option):
        try:
            cfg.CONF.import_opt(option, 'heat.common.config',
                                group='clients_keystone')
            return getattr(cfg.CONF.clients_keystone, option)
        except (cfg.NoSuchGroupError, cfg.NoSuchOptError):
            cfg.CONF.import_opt(option, 'heat.common.config', group='clients')
            return getattr(cfg.CONF.clients, option)

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
        user = self.client.users.create(username,
                                        password,
                                        '%s@openstack.org' % username,
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
            logger.debug(_("Adding user %(user)s to role %(role)s") % {
                         'user': user.id, 'role': role_id})
            self.client.roles.add_user_role(user.id, role_id,
                                            self.context.tenant_id)
        else:
            logger.error(_("Failed to add user %(user)s to role %(role)s, "
                         "check role exists!") % {'user': username,
                         'role': cfg.CONF.heat_stack_user_role})

        return user.id

    def delete_stack_user(self, user_id):
        self.client.users.delete(user_id)

    def delete_ec2_keypair(self, user_id, accesskey):
        self.client.ec2.delete(user_id, accesskey)

    def get_ec2_keypair(self, access, user_id=None):
        uid = user_id or self.client.auth_ref.user_id
        return self.client.ec2.get(uid, access)

    def create_ec2_keypair(self, user_id=None):
        uid = user_id or self.client.auth_ref.user_id
        return self.client.ec2.create(uid, self.context.tenant_id)

    def disable_stack_user(self, user_id):
        self.client.users.update_enabled(user_id, False)

    def enable_stack_user(self, user_id):
        self.client.users.update_enabled(user_id, True)

    def url_for(self, **kwargs):
        return self.client.service_catalog.url_for(**kwargs)

    @property
    def auth_token(self):
        return self.client.auth_token

    # ##################### #
    # V3 Compatible Methods #
    # ##################### #

    def create_stack_domain_user(self, username, project_id, password=None):
        return self.create_stack_user(username, password)

    def delete_stack_domain_user(self, user_id, project_id):
        return self.delete_stack_user(user_id)

    def create_stack_domain_project(self, project_id):
        '''Use the tenant ID as domain project.'''
        return self.context.tenant_id

    def delete_stack_domain_project(self, project_id):
        '''Pass through method since no project was created.'''
        pass

    # ###################### #
    # V3 Unsupported Methods #
    # ###################### #

    def create_trust_context(self):
        raise exception.NotSupported(feature='Keystone Trusts')

    def delete_trust(self, trust_id):
        raise exception.NotSupported(feature='Keystone Trusts')
