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

"""Keystone Client functionality for use by resources."""

import collections
import uuid
import weakref

from keystoneauth1 import exceptions as ks_exception
from keystoneauth1.identity import generic as ks_auth

from keystoneclient.v3 import client as kc_v3
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import importutils

from heat.common import context
from heat.common import exception
from heat.common.i18n import _
from heat.common import password_gen

LOG = logging.getLogger('heat.engine.clients.keystoneclient')

AccessKey = collections.namedtuple('AccessKey', ['id', 'access', 'secret'])

_default_keystone_backend = (
    'heat.engine.clients.os.keystone.heat_keystoneclient.KsClientWrapper')

keystone_opts = [
    cfg.StrOpt('keystone_backend',
               default=_default_keystone_backend,
               help=_("Fully qualified class name to use as a "
                      "keystone backend."))
]
cfg.CONF.register_opts(keystone_opts)


class KsClientWrapper(object):
    """Wrap keystone client so we can encapsulate logic used in resources.

    Note this is intended to be initialized from a resource on a per-session
    basis, so the session context is passed in on initialization
    Also note that an instance of this is created in each request context as
    part of a lazy-loaded cloud backend and it can be easily referenced in
    each resource as ``self.keystone()``, so there should not be any need to
    directly instantiate instances of this class inside resources themselves.
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
        # - context.auth_url is expected to contain a versioned keystone
        #   path, we will work with either a v2.0 or v3 path
        self._context = weakref.ref(context)
        self._client = None
        self._admin_auth = None
        self._domain_admin_auth = None
        self._domain_admin_client = None

        self.session = self.context.keystone_session
        self.v3_endpoint = self.context.keystone_v3_endpoint

        if self.context.trust_id:
            # Create a client with the specified trust_id, this
            # populates self.context.auth_token with a trust-scoped token
            self._client = self._v3_client_init()

        # The stack domain user ID should be set in heat.conf
        # It can be created via python-openstackclient
        # openstack --os-identity-api-version=3 domain create heat
        # If the domain is specified, then you must specify a domain
        # admin user.  If no domain is specified, we fall back to
        # legacy behavior with warnings.
        self._stack_domain_id = cfg.CONF.stack_user_domain_id
        self.stack_domain_name = cfg.CONF.stack_user_domain_name
        self.domain_admin_user = cfg.CONF.stack_domain_admin
        self.domain_admin_password = cfg.CONF.stack_domain_admin_password

        LOG.debug('Using stack domain %s', self.stack_domain)

    @property
    def context(self):
        ctxt = self._context()
        assert ctxt is not None, "Need a reference to the context"
        return ctxt

    @property
    def stack_domain(self):
        """Domain scope data.

        This is only used for checking for scoping data, not using the value.
        """
        return self._stack_domain_id or self.stack_domain_name

    @property
    def client(self):
        if not self._client:
            # Create connection to v3 API
            self._client = self._v3_client_init()
        return self._client

    @property
    def auth_region_name(self):
        importutils.import_module('keystonemiddleware.auth_token')
        auth_region = cfg.CONF.keystone_authtoken.region_name
        if not auth_region:
            auth_region = (self.context.region_name or
                           cfg.CONF.region_name_for_services)
        return auth_region

    @property
    def domain_admin_auth(self):
        if not self._domain_admin_auth:
            # Note we must specify the domain when getting the token
            # as only a domain scoped token can create projects in the domain
            auth = ks_auth.Password(username=self.domain_admin_user,
                                    password=self.domain_admin_password,
                                    auth_url=self.v3_endpoint,
                                    domain_id=self._stack_domain_id,
                                    domain_name=self.stack_domain_name,
                                    user_domain_id=self._stack_domain_id,
                                    user_domain_name=self.stack_domain_name)

            # NOTE(jamielennox): just do something to ensure a valid token
            try:
                auth.get_token(self.session)
            except ks_exception.Unauthorized:
                LOG.error("Domain admin client authentication failed")
                raise exception.AuthorizationFailure()

            self._domain_admin_auth = auth

        return self._domain_admin_auth

    @property
    def domain_admin_client(self):
        if not self._domain_admin_client:
            self._domain_admin_client = kc_v3.Client(
                session=self.session,
                auth=self.domain_admin_auth,
                region_name=self.auth_region_name)

        return self._domain_admin_client

    def _v3_client_init(self):
        client = kc_v3.Client(session=self.session,
                              region_name=self.auth_region_name)

        if hasattr(self.context.auth_plugin, 'get_access'):
            # NOTE(jamielennox): get_access returns the current token without
            # reauthenticating if it's present and valid.
            try:
                auth_ref = self.context.auth_plugin.get_access(self.session)
            except ks_exception.Unauthorized:
                LOG.error("Keystone client authentication failed")
                raise exception.AuthorizationFailure()

            if self.context.trust_id:
                # Sanity check
                if not auth_ref.trust_scoped:
                    LOG.error("trust token re-scoping failed!")
                    raise exception.AuthorizationFailure()
                # Sanity check that impersonation is effective
                if self.context.trustor_user_id != auth_ref.user_id:
                    LOG.error("Trust impersonation failed")
                    raise exception.AuthorizationFailure()

        return client

    def create_trust_context(self):
        """Create a trust using the trustor identity in the current context.

        The trust is created with the trustee as the heat service user.

        If the current context already contains a trust_id, we do nothing
        and return the current context.

        Returns a context containing the new trust_id.
        """
        if self.context.trust_id:
            return self.context

        # We need the service admin user ID (not name), as the trustor user
        # can't lookup the ID in keystoneclient unless they're admin
        # workaround this by getting the user_id from admin_client
        try:
            trustee_user_id = self.context.trusts_auth_plugin.get_user_id(
                self.session)
        except ks_exception.Unauthorized:
            LOG.error("Domain admin client authentication failed")
            raise exception.AuthorizationFailure()

        trustor_user_id = self.context.auth_plugin.get_user_id(self.session)
        trustor_proj_id = self.context.auth_plugin.get_project_id(self.session)

        role_kw = {}
        # inherit the roles of the trustor, unless set trusts_delegated_roles
        if cfg.CONF.trusts_delegated_roles:
            role_kw['role_names'] = cfg.CONF.trusts_delegated_roles
        else:
            token_info = self.context.auth_token_info
            if token_info and token_info.get('token', {}).get('roles'):
                role_kw['role_ids'] = [r['id'] for r in
                                       token_info['token']['roles']]
            else:
                role_kw['role_names'] = self.context.roles
        try:
            trust = self.client.trusts.create(trustor_user=trustor_user_id,
                                              trustee_user=trustee_user_id,
                                              project=trustor_proj_id,
                                              impersonation=True,
                                              **role_kw)
        except ks_exception.NotFound:
            LOG.debug("Failed to find roles %s for user %s"
                      % (role_kw, trustor_user_id))
            raise exception.MissingCredentialError(
                required=_("roles %s") % role_kw)

        context_data = self.context.to_dict()
        context_data['overwrite'] = False
        trust_context = context.RequestContext.from_dict(context_data)
        trust_context.trust_id = trust.id
        trust_context.trustor_user_id = trustor_user_id
        return trust_context

    def delete_trust(self, trust_id):
        """Delete the specified trust."""
        try:
            self.client.trusts.delete(trust_id)
        except (ks_exception.NotFound, ks_exception.Unauthorized):
            pass

    def _get_username(self, username):
        if(len(username) > 255):
            LOG.warning("Truncating the username %s to the last 255 "
                        "characters.", username)
        # get the last 255 characters of the username
        return username[-255:]

    def create_stack_user(self, username, password=''):
        """Create a user defined as part of a stack.

        The user is defined either via template or created internally by a
        resource.  This user will be added to the heat_stack_user_role as
        defined in the config.

        Returns the keystone ID of the resulting user.
        """
        # FIXME(shardy): There's duplicated logic between here and
        # create_stack_domain user, but this function is expected to
        # be removed after the transition of all resources to domain
        # users has been completed
        stack_user_role = self.client.roles.list(
            name=cfg.CONF.heat_stack_user_role)
        if len(stack_user_role) == 1:
            role_id = stack_user_role[0].id
            # Create the user
            user = self.client.users.create(
                name=self._get_username(username), password=password,
                default_project=self.context.tenant_id)
            # Add user to heat_stack_user_role
            LOG.debug("Adding user %(user)s to role %(role)s",
                      {'user': user.id, 'role': role_id})
            self.client.roles.grant(role=role_id, user=user.id,
                                    project=self.context.tenant_id)
        else:
            LOG.error("Failed to add user %(user)s to role %(role)s, "
                      "check role exists!",
                      {'user': username,
                       'role': cfg.CONF.heat_stack_user_role})
            raise exception.Error(_("Can't find role %s")
                                  % cfg.CONF.heat_stack_user_role)

        return user.id

    def stack_domain_user_token(self, user_id, project_id, password):
        """Get a token for a stack domain user."""
        if not self.stack_domain:
            # Note, no legacy fallback path as we don't want to deploy
            # tokens for non stack-domain users inside instances
            msg = _('Cannot get stack domain user token, no stack domain id '
                    'configured, please fix your heat.conf')
            raise exception.Error(msg)

        # Create a keystone session, then request a token with no
        # catalog (the token is expected to be used inside an instance
        # where a specific endpoint will be specified, and user-data
        # space is limited..)
        # TODO(rabi): generic auth plugins don't support `include_catalog'
        # flag yet. We'll add it once it's supported..
        auth = ks_auth.Password(auth_url=self.v3_endpoint,
                                user_id=user_id,
                                password=password,
                                project_id=project_id)

        return auth.get_token(self.session)

    def create_stack_domain_user(self, username, project_id, password=None):
        """Create a domain user defined as part of a stack.

        The user is defined either via template or created internally by a
        resource.  This user will be added to the heat_stack_user_role as
        defined in the config, and created in the specified project (which is
        expected to be in the stack_domain).

        Returns the keystone ID of the resulting user.
        """
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            return self.create_stack_user(username=username, password=password)
        # We add the new user to a special keystone role
        # This role is designed to allow easier differentiation of the
        # heat-generated "stack users" which will generally have credentials
        # deployed on an instance (hence are implicitly untrusted)
        stack_user_role = self.domain_admin_client.roles.list(
            name=cfg.CONF.heat_stack_user_role)
        if len(stack_user_role) == 1:
            role_id = stack_user_role[0].id
            # Create user
            user = self.domain_admin_client.users.create(
                name=self._get_username(username), password=password,
                default_project=project_id, domain=self.stack_domain_id)
            # Add to stack user role
            LOG.debug("Adding user %(user)s to role %(role)s",
                      {'user': user.id, 'role': role_id})
            self.domain_admin_client.roles.grant(role=role_id, user=user.id,
                                                 project=project_id)
        else:
            LOG.error("Failed to add user %(user)s to role %(role)s, "
                      "check role exists!",
                      {'user': username,
                       'role': cfg.CONF.heat_stack_user_role})
            raise exception.Error(_("Can't find role %s")
                                  % cfg.CONF.heat_stack_user_role)

        return user.id

    @property
    def stack_domain_id(self):
        if not self._stack_domain_id:
            try:
                access = self.domain_admin_auth.get_access(self.session)
            except ks_exception.Unauthorized:
                LOG.error("Keystone client authentication failed")
                raise exception.AuthorizationFailure()

            self._stack_domain_id = access.domain_id

        return self._stack_domain_id

    def _check_stack_domain_user(self, user_id, project_id, action):
        """Sanity check that domain/project is correct."""
        user = self.domain_admin_client.users.get(user_id)

        if user.domain_id != self.stack_domain_id:
            raise ValueError(_('User %s in invalid domain') % action)
        if user.default_project_id != project_id:
            raise ValueError(_('User %s in invalid project') % action)

    def delete_stack_domain_user(self, user_id, project_id):
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            return self.delete_stack_user(user_id)

        try:
            self._check_stack_domain_user(user_id, project_id, 'delete')
            self.domain_admin_client.users.delete(user_id)
        except ks_exception.NotFound:
            pass

    def delete_stack_user(self, user_id):
        try:
            self.client.users.delete(user=user_id)
        except ks_exception.NotFound:
            pass

    def create_stack_domain_project(self, stack_id):
        """Create a project in the heat stack-user domain."""
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            return self.context.tenant_id
        # Note we use the tenant ID not name to ensure uniqueness in a multi-
        # domain environment (where the tenant name may not be globally unique)
        project_name = ('%s-%s' % (self.context.tenant_id, stack_id))[:64]
        desc = "Heat stack user project"
        domain_project = self.domain_admin_client.projects.create(
            name=project_name,
            domain=self.stack_domain_id,
            description=desc)
        return domain_project.id

    def delete_stack_domain_project(self, project_id):
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            return

        # If stacks are created before configuring the heat domain, they
        # exist in the default domain, in the user's project, which we
        # do *not* want to delete!  However, if the keystone v3cloudsample
        # policy is used, it's possible that we'll get Forbidden when trying
        # to get the project, so again we should do nothing
        try:
            project = self.domain_admin_client.projects.get(project=project_id)
        except ks_exception.NotFound:
            return
        except ks_exception.Forbidden:
            LOG.warning('Unable to get details for project %s, '
                        'not deleting', project_id)
            return

        if project.domain_id != self.stack_domain_id:
            LOG.warning('Not deleting non heat-domain project')
            return

        try:
            project.delete()
        except ks_exception.NotFound:
            pass

    def _find_ec2_keypair(self, access, user_id=None):
        """Lookup an ec2 keypair by access ID."""
        # FIXME(shardy): add filtering for user_id when keystoneclient
        # extensible-crud-manager-operations bp lands
        credentials = self.client.credentials.list()
        for cr in credentials:
            ec2_creds = jsonutils.loads(cr.blob)
            if ec2_creds.get('access') == access:
                return AccessKey(id=cr.id,
                                 access=ec2_creds['access'],
                                 secret=ec2_creds['secret'])

    def delete_ec2_keypair(self, credential_id=None, access=None,
                           user_id=None):
        """Delete credential containing ec2 keypair."""
        if credential_id:
            try:
                self.client.credentials.delete(credential_id)
            except ks_exception.NotFound:
                pass
        elif access:
            cred = self._find_ec2_keypair(access=access, user_id=user_id)
            if cred:
                self.client.credentials.delete(cred.id)
        else:
            raise ValueError("Must specify either credential_id or access")

    def get_ec2_keypair(self, credential_id=None, access=None, user_id=None):
        """Get an ec2 keypair via v3/credentials, by id or access."""
        # Note v3/credentials does not support filtering by access
        # because it's stored in the credential blob, so we expect
        # all resources to pass credential_id except where backwards
        # compatibility is required (resource only has access stored)
        # then we'll have to do a brute-force lookup locally
        if credential_id:
            cred = self.client.credentials.get(credential_id)
            ec2_creds = jsonutils.loads(cred.blob)
            return AccessKey(id=cred.id,
                             access=ec2_creds['access'],
                             secret=ec2_creds['secret'])
        elif access:
            return self._find_ec2_keypair(access=access, user_id=user_id)
        else:
            raise ValueError("Must specify either credential_id or access")

    def create_ec2_keypair(self, user_id=None):
        user_id = user_id or self.context.get_access(self.session).user_id
        project_id = self.context.tenant_id
        data_blob = {'access': uuid.uuid4().hex,
                     'secret': password_gen.generate_openstack_password()}
        ec2_creds = self.client.credentials.create(
            user=user_id, type='ec2', blob=jsonutils.dumps(data_blob),
            project=project_id)

        # Return a AccessKey namedtuple for easier access to the blob contents
        # We return the id as the v3 api provides no way to filter by
        # access in the blob contents, so it will be much more efficient
        # if we manage credentials by ID instead
        return AccessKey(id=ec2_creds.id,
                         access=data_blob['access'],
                         secret=data_blob['secret'])

    def create_stack_domain_user_keypair(self, user_id, project_id):
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            return self.create_ec2_keypair(user_id)
        data_blob = {'access': uuid.uuid4().hex,
                     'secret': password_gen.generate_openstack_password()}
        creds = self.domain_admin_client.credentials.create(
            user=user_id, type='ec2', blob=jsonutils.dumps(data_blob),
            project=project_id)
        return AccessKey(id=creds.id,
                         access=data_blob['access'],
                         secret=data_blob['secret'])

    def delete_stack_domain_user_keypair(self, user_id, project_id,
                                         credential_id):
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            return self.delete_ec2_keypair(credential_id=credential_id)
        self._check_stack_domain_user(user_id, project_id, 'delete_keypair')
        try:
            self.domain_admin_client.credentials.delete(credential_id)
        except ks_exception.NotFound:
            pass

    def disable_stack_user(self, user_id):
        self.client.users.update(user=user_id, enabled=False)

    def enable_stack_user(self, user_id):
        self.client.users.update(user=user_id, enabled=True)

    def disable_stack_domain_user(self, user_id, project_id):
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            return self.disable_stack_user(user_id)
        self._check_stack_domain_user(user_id, project_id, 'disable')
        self.domain_admin_client.users.update(user=user_id, enabled=False)

    def enable_stack_domain_user(self, user_id, project_id):
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            return self.enable_stack_user(user_id)
        self._check_stack_domain_user(user_id, project_id, 'enable')
        self.domain_admin_client.users.update(user=user_id, enabled=True)


class KeystoneClient(object):
    """Keystone Auth Client.

    Delay choosing the backend client module until the client's class
    needs to be initialized.
    """

    def __new__(cls, context):
        if cfg.CONF.keystone_backend == _default_keystone_backend:
            return KsClientWrapper(context)
        else:
            return importutils.import_object(
                cfg.CONF.keystone_backend,
                context
            )


def list_opts():
    yield None, keystone_opts
