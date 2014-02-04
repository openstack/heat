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

from collections import namedtuple
import json
import uuid

from heat.common import context
from heat.common import exception

import keystoneclient.exceptions as kc_exception
from keystoneclient.v3 import client as kc_v3
from oslo.config import cfg

from heat.openstack.common import importutils
from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

logger = logging.getLogger('heat.common.keystoneclient')

AccessKey = namedtuple('AccessKey', ['id', 'access', 'secret'])


class KeystoneClient(object):
    """
    Wrap keystone client so we can encapsulate logic used in resources
    Note this is intended to be initialized from a resource on a per-session
    basis, so the session context is passed in on initialization
    Also note that a copy of this is created every resource as self.keystone()
    via the code in engine/client.py, so there should not be any need to
    directly instantiate instances of this class inside resources themselves
    """
    conf = cfg.CONF

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
        # - context.auth_url is expected to contain a versioned keystone
        #   path, we will work with either a v2.0 or v3 path
        self.context = context
        self._client_v3 = None

        if self.context.trust_id:
            # Create a client with the specified trust_id, this
            # populates self.context.auth_token with a trust-scoped token
            self._client_v3 = self._v3_client_init()

    @property
    def client_v3(self):
        if not self._client_v3:
            # Create connection to v3 API
            self._client_v3 = self._v3_client_init()
        return self._client_v3

    def _v3_client_init(self):
        if self.context.auth_url:
            v3_endpoint = self.context.auth_url.replace('v2.0', 'v3')
        else:
            # Import auth_token to have keystone_authtoken settings setup.
            importutils.import_module('keystoneclient.middleware.auth_token')

            v3_endpoint = self.conf.keystone_authtoken.auth_uri.replace(
                'v2.0', 'v3')

        kwargs = {
            'auth_url': v3_endpoint,
            'endpoint': v3_endpoint
        }
        # Note try trust_id first, as we can't reuse auth_token in that case
        if self.context.trust_id is not None:
            # We got a trust_id, so we use the admin credentials
            # to authenticate with the trust_id so we can use the
            # trust impersonating the trustor user.
            kwargs.update(self._service_admin_creds())
            kwargs['trust_id'] = self.context.trust_id
        elif self.context.auth_token is not None:
            kwargs['project_name'] = self.context.tenant
            kwargs['token'] = self.context.auth_token
        elif self.context.password is not None:
            kwargs['username'] = self.context.username
            kwargs['password'] = self.context.password
            kwargs['project_name'] = self.context.tenant
            kwargs['project_id'] = self.context.tenant_id
        else:
            logger.error(_("Keystone v3 API connection failed, no password "
                         "trust or auth_token!"))
            raise exception.AuthorizationFailure()
        kwargs.update(self._ssl_options())
        client_v3 = kc_v3.Client(**kwargs)
        client_v3.authenticate()
        # If we are authenticating with a trust set the context auth_token
        # with the trust scoped token
        if 'trust_id' in kwargs:
            # Sanity check
            if not client_v3.auth_ref.trust_scoped:
                logger.error(_("trust token re-scoping failed!"))
                raise exception.AuthorizationFailure()
            # All OK so update the context with the token
            self.context.auth_token = client_v3.auth_ref.auth_token
            self.context.auth_url = kwargs.get('auth_url')
            # Sanity check that impersonation is effective
            if self.context.trustor_user_id != client_v3.auth_ref.user_id:
                logger.error("Trust impersonation failed")
                raise exception.AuthorizationFailure()

        return client_v3

    def _service_admin_creds(self):
        # Import auth_token to have keystone_authtoken settings setup.
        importutils.import_module('keystoneclient.middleware.auth_token')

        creds = {
            'username': self.conf.keystone_authtoken.admin_user,
            'password': self.conf.keystone_authtoken.admin_password,
            'auth_url': self.conf.keystone_authtoken.auth_uri.replace(
                'v2.0', 'v3'),
            'project_name': self.conf.keystone_authtoken.admin_tenant_name}
        return creds

    def _ssl_options(self):
        opts = {'cacert': self._get_client_option('ca_file'),
                'insecure': self._get_client_option('insecure'),
                'cert': self._get_client_option('cert_file'),
                'key': self._get_client_option('key_file')}
        return opts

    def _get_client_option(self, option):
        try:
            self.conf.import_opt(option, 'heat.common.config',
                                 group='clients_keystone')
            return getattr(self.conf.clients_keystone, option)
        except (cfg.NoSuchGroupError, cfg.NoSuchOptError):
            self.conf.import_opt(option, 'heat.common.config', group='clients')
            return getattr(self.conf.clients, option)

    def create_trust_context(self):
        """
        Create a trust using the trustor identity in the current context,
        with the trustee as the heat service user and return a context
        containing the new trust_id.

        If the current context already contains a trust_id, we do nothing
        and return the current context.
        """
        if self.context.trust_id:
            return self.context

        # We need the service admin user ID (not name), as the trustor user
        # can't lookup the ID in keystoneclient unless they're admin
        # workaround this by creating a temporary admin client connection
        # then getting the user ID from the auth_ref
        admin_creds = self._service_admin_creds()
        admin_creds.update(self._ssl_options())
        admin_client = kc_v3.Client(**admin_creds)
        trustee_user_id = admin_client.auth_ref.user_id
        trustor_user_id = self.client_v3.auth_ref.user_id
        trustor_project_id = self.client_v3.auth_ref.project_id
        roles = self.conf.trusts_delegated_roles
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
        try:
            self.client_v3.trusts.delete(trust_id)
        except kc_exception.NotFound:
            pass

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
        user = self.client_v3.users.create(
            name=username, password=password,
            default_project=self.context.tenant_id)

        # We add the new user to a special keystone role
        # This role is designed to allow easier differentiation of the
        # heat-generated "stack users" which will generally have credentials
        # deployed on an instance (hence are implicitly untrusted)
        # FIXME(shardy): The v3 keystoneclient doesn't currently support
        # filtering the results, so we have to do it locally, update when
        # that is fixed in keystoneclient
        roles_list = self.client_v3.roles.list()
        stack_user_role = [r for r in roles_list
                           if r.name == self.conf.heat_stack_user_role]
        if len(stack_user_role) == 1:
            role_id = stack_user_role[0].id
            logger.debug(_("Adding user %(user)s to role %(role)s") % {
                         'user': user.id, 'role': role_id})
            self.client_v3.roles.grant(role=role_id, user=user.id,
                                       project=self.context.tenant_id)
        else:
            logger.error(_("Failed to add user %(user)s to role %(role)s, "
                         "check role exists!") % {'user': username,
                         'role': self.conf.heat_stack_user_role})

        return user.id

    def delete_stack_user(self, user_id):
        self.client_v3.users.delete(user=user_id)

    def _find_ec2_keypair(self, access, user_id=None):
        '''Lookup an ec2 keypair by access ID.'''
        # FIXME(shardy): add filtering for user_id when keystoneclient
        # extensible-crud-manager-operations bp lands
        credentials = self.client_v3.credentials.list()
        for cr in credentials:
            ec2_creds = json.loads(cr.blob)
            if ec2_creds.get('access') == access:
                return AccessKey(id=cr.id,
                                 access=ec2_creds['access'],
                                 secret=ec2_creds['secret'])

    def delete_ec2_keypair(self, credential_id=None, access=None,
                           user_id=None):
        '''Delete credential containing ec2 keypair.'''
        if credential_id:
            self.client_v3.credentials.delete(credential_id)
        elif access:
            cred = self._find_ec2_keypair(access=access, user_id=user_id)
            self.client_v3.credentials.delete(cred.id)
        else:
            raise ValueError("Must specify either credential_id or access")

    def get_ec2_keypair(self, credential_id=None, access=None, user_id=None):
        '''Get an ec2 keypair via v3/credentials, by id or access.'''
        # Note v3/credentials does not support filtering by access
        # because it's stored in the credential blob, so we expect
        # all resources to pass credential_id except where backwards
        # compatibility is required (resource only has acccess stored)
        # then we'll have to to a brute-force lookup locally
        if credential_id:
            cred = self.client_v3.credentials.get(credential_id)
            ec2_creds = json.loads(cred.blob)
            return AccessKey(id=cred.id,
                             access=ec2_creds['access'],
                             secret=ec2_creds['secret'])
        elif access:
            return self._find_ec2_keypair(access=access, user_id=user_id)
        else:
            raise ValueError("Must specify either credential_id or access")

    def create_ec2_keypair(self, user_id=None):
        user_id = user_id or self.client_v3.auth_ref.user_id
        project_id = self.context.tenant_id
        data_blob = {'access': uuid.uuid4().hex,
                     'secret': uuid.uuid4().hex}
        ec2_creds = self.client_v3.credentials.create(
            user=user_id, type='ec2', data=json.dumps(data_blob),
            project=project_id)

        # Return a AccessKey namedtuple for easier access to the blob contents
        # We return the id as the v3 api provides no way to filter by
        # access in the blob contents, so it will be much more efficient
        # if we manage credentials by ID instead
        return AccessKey(id=ec2_creds.id,
                         access=data_blob['access'],
                         secret=data_blob['secret'])

    def disable_stack_user(self, user_id):
        self.client_v3.users.update(user=user_id, enabled=False)

    def enable_stack_user(self, user_id):
        self.client_v3.users.update(user=user_id, enabled=True)

    def url_for(self, **kwargs):
        return self.client_v3.service_catalog.url_for(**kwargs)

    @property
    def auth_token(self):
        return self.client_v3.auth_token
