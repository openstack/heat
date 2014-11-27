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

from collections import namedtuple
import copy
import json
from oslo.utils import importutils
import uuid

from keystoneclient.auth.identity import v3 as kc_auth_v3
import keystoneclient.exceptions as kc_exception
from keystoneclient import session
from keystoneclient.v3 import client as kc_v3
from oslo.config import cfg

from heat.common import context
from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LE
from heat.common.i18n import _LW
from heat.openstack.common import log as logging

LOG = logging.getLogger('heat.common.keystoneclient')

AccessKey = namedtuple('AccessKey', ['id', 'access', 'secret'])

_default_keystone_backend = "heat.common.heat_keystoneclient.KeystoneClientV3"

keystone_opts = [
    cfg.StrOpt('keystone_backend',
               default=_default_keystone_backend,
               help="Fully qualified class name to use as a keystone backend.")
]
cfg.CONF.register_opts(keystone_opts)


class KeystoneClientV3(object):

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
        self.context = context
        self._client = None
        self._admin_client = None
        self._domain_admin_client = None

        if self.context.auth_url:
            self.v3_endpoint = self.context.auth_url.replace('v2.0', 'v3')
        else:
            # Import auth_token to have keystone_authtoken settings setup.
            importutils.import_module('keystonemiddleware.auth_token')
            self.v3_endpoint = cfg.CONF.keystone_authtoken.auth_uri.replace(
                'v2.0', 'v3')

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
        self._stack_domain_is_id = True
        self._stack_domain_id = None
        self.stack_domain = cfg.CONF.stack_user_domain_id
        if not self.stack_domain and cfg.CONF.stack_user_domain_name:
            self.stack_domain = cfg.CONF.stack_user_domain_name
            self._stack_domain_is_id = False
        self.domain_admin_user = cfg.CONF.stack_domain_admin
        self.domain_admin_password = cfg.CONF.stack_domain_admin_password
        if self.stack_domain:
            if not (self.domain_admin_user and self.domain_admin_password):
                raise exception.Error(_('heat.conf misconfigured, cannot '
                                      'specify "stack_user_domain_id" or '
                                      '"stack_user_domain_name" without '
                                      '"stack_domain_admin" and '
                                      '"stack_domain_admin_password"'))
        else:
            LOG.warn(_LW('stack_user_domain_id or stack_user_domain_name not '
                         'set in heat.conf falling back to using default'))
        LOG.debug('Using stack domain %s' % self.stack_domain)

    @property
    def client(self):
        if not self._client:
            # Create connection to v3 API
            self._client = self._v3_client_init()
        return self._client

    @property
    def admin_client(self):
        if not self._admin_client:
            # Create admin client connection to v3 API
            admin_creds = self._service_admin_creds()
            admin_creds.update(self._ssl_options())
            c = kc_v3.Client(**admin_creds)
            if c.authenticate():
                self._admin_client = c
            else:
                LOG.error(_LE("Admin client authentication failed"))
                raise exception.AuthorizationFailure()
        return self._admin_client

    @property
    def domain_admin_client(self):
        if not self._domain_admin_client:
            # Create domain admin client connection to v3 API
            admin_creds = self._domain_admin_creds()
            admin_creds.update(self._ssl_options())
            c = kc_v3.Client(**admin_creds)
            # Note we must specify the domain when getting the token
            # as only a domain scoped token can create projects in the domain
            if self._stack_domain_is_id:
                auth_kwargs = {'domain_id': self.stack_domain}
            else:
                auth_kwargs = {'domain_name': self.stack_domain}
            if c.authenticate(**auth_kwargs):
                self._domain_admin_client = c
            else:
                LOG.error(_LE("Domain admin client authentication failed"))
                raise exception.AuthorizationFailure()
        return self._domain_admin_client

    def _v3_client_init(self):
        kwargs = {
            'auth_url': self.v3_endpoint,
            'endpoint': self.v3_endpoint
        }
        # Note try trust_id first, as we can't reuse auth_token in that case
        if self.context.trust_id is not None:
            # We got a trust_id, so we use the admin credentials
            # to authenticate with the trust_id so we can use the
            # trust impersonating the trustor user.
            kwargs.update(self._service_admin_creds())
            kwargs['trust_id'] = self.context.trust_id
            kwargs.pop('project_name')
        elif self.context.auth_token_info is not None:
            # The auth_ref version must be set according to the token version
            if 'access' in self.context.auth_token_info:
                kwargs['auth_ref'] = copy.deepcopy(
                    self.context.auth_token_info['access'])
                kwargs['auth_ref']['version'] = 'v2.0'
                kwargs['auth_ref']['token']['id'] = self.context.auth_token
            elif 'token' in self.context.auth_token_info:
                kwargs['auth_ref'] = copy.deepcopy(
                    self.context.auth_token_info['token'])
                kwargs['auth_ref']['version'] = 'v3'
                kwargs['auth_ref']['auth_token'] = self.context.auth_token
            else:
                LOG.error(_LE('Unknown version in auth_token_info'))
                raise exception.AuthorizationFailure(
                    _('Unknown token version'))
        elif self.context.auth_token is not None:
            kwargs['token'] = self.context.auth_token
            kwargs['project_id'] = self.context.tenant_id
        elif self.context.password is not None:
            kwargs['username'] = self.context.username
            kwargs['password'] = self.context.password
            kwargs['project_id'] = self.context.tenant_id
        else:
            LOG.error(_LE("Keystone v3 API connection failed, no password "
                          "trust or auth_token!"))
            raise exception.AuthorizationFailure()
        kwargs.update(self._ssl_options())
        client = kc_v3.Client(**kwargs)

        # If auth_ref has already be specified via auth_token_info, don't
        # authenticate as we want to reuse, rather than request a new token
        if 'auth_ref' not in kwargs:
            client.authenticate()

        # If we are authenticating with a trust set the context auth_token
        # with the trust scoped token
        if 'trust_id' in kwargs:
            # Sanity check
            if not client.auth_ref.trust_scoped:
                LOG.error(_LE("trust token re-scoping failed!"))
                raise exception.AuthorizationFailure()
            # Sanity check that impersonation is effective
            if self.context.trustor_user_id != client.auth_ref.user_id:
                LOG.error(_LE("Trust impersonation failed"))
                raise exception.AuthorizationFailure()

        return client

    def _service_admin_creds(self):
        # Import auth_token to have keystone_authtoken settings setup.
        importutils.import_module('keystonemiddleware.auth_token')
        creds = {
            'username': cfg.CONF.keystone_authtoken.admin_user,
            'password': cfg.CONF.keystone_authtoken.admin_password,
            'auth_url': self.v3_endpoint,
            'endpoint': self.v3_endpoint,
            'project_name': cfg.CONF.keystone_authtoken.admin_tenant_name}
        return creds

    def _domain_admin_creds(self):
        creds = {
            'username': self.domain_admin_user,
            'password': self.domain_admin_password,
            'auth_url': self.v3_endpoint,
            'endpoint': self.v3_endpoint}
        if self._stack_domain_is_id:
            creds['user_domain_id'] = self.stack_domain
        else:
            creds['user_domain_name'] = self.stack_domain
        return creds

    def _ssl_options(self):
        opts = {'cacert': self._get_client_option('ca_file'),
                'insecure': self._get_client_option('insecure'),
                'cert': self._get_client_option('cert_file'),
                'key': self._get_client_option('key_file')}
        return opts

    def _get_client_option(self, option):
        # look for the option in the [clients_keystone] section
        # unknown options raise cfg.NoSuchOptError
        cfg.CONF.import_opt(option, 'heat.common.config',
                            group='clients_keystone')
        v = getattr(cfg.CONF.clients_keystone, option)
        if v is not None:
            return v
        # look for the option in the generic [clients] section
        cfg.CONF.import_opt(option, 'heat.common.config', group='clients')
        return getattr(cfg.CONF.clients, option)

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
        trustee_user_id = self.admin_client.auth_ref.user_id
        trustor_user_id = self.client.auth_ref.user_id
        trustor_project_id = self.client.auth_ref.project_id
        # inherit the roles of the trustor, unless set trusts_delegated_roles
        if cfg.CONF.trusts_delegated_roles:
            roles = cfg.CONF.trusts_delegated_roles
        else:
            roles = self.context.roles
        try:
            trust = self.client.trusts.create(trustor_user=trustor_user_id,
                                              trustee_user=trustee_user_id,
                                              project=trustor_project_id,
                                              impersonation=True,
                                              role_names=roles)
        except kc_exception.NotFound:
            LOG.debug("Failed to find roles %s for user %s"
                      % (roles, trustor_user_id))
            raise exception.MissingCredentialError(
                required=_("roles %s") % roles)

        trust_context = context.RequestContext.from_dict(
            self.context.to_dict())
        trust_context.trust_id = trust.id
        trust_context.trustor_user_id = trustor_user_id
        return trust_context

    def delete_trust(self, trust_id):
        """Delete the specified trust."""
        try:
            self.client.trusts.delete(trust_id)
        except kc_exception.NotFound:
            pass

    def _get_username(self, username):
        if(len(username) > 64):
            LOG.warn(_LW("Truncating the username %s to the last 64 "
                         "characters."), username)
        #get the last 64 characters of the username
        return username[-64:]

    def _get_domain_id_from_name(self, domain_name):
        domains = self.domain_admin_client.domains.list(name=domain_name)
        if len(domains) == 1:
            return domains[0].id
        elif len(domains) == 0:
            LOG.error(_LE("Can't find domain id for %(domain)s!"), {
                      'domain': domain_name})
            raise exception.Error(_("Failed to find domain %s")
                                  % domain_name)
        else:
            LOG.error(_LE("Unexpected response looking for %(domain)s!"), {
                      'domain': domain_name})
            raise exception.Error(_("Unexpected response looking for "
                                    "domain %s") % domain_name)

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
            LOG.debug("Adding user %(user)s to role %(role)s" % {
                      'user': user.id, 'role': role_id})
            self.client.roles.grant(role=role_id, user=user.id,
                                    project=self.context.tenant_id)
        else:
            LOG.error(_LE("Failed to add user %(user)s to role %(role)s, "
                          "check role exists!"), {
                      'user': username,
                      'role': cfg.CONF.heat_stack_user_role})
            raise exception.Error(_("Can't find role %s")
                                  % cfg.CONF.heat_stack_user_role)

        return user.id

    def stack_domain_user_token(self, username, project_id, password):
        """Get a token for a stack domain user."""
        if not self.stack_domain:
            # Note, no legacy fallback path as we don't want to deploy
            # tokens for non stack-domain users inside instances
            msg = _('Cannot get stack domain user token, no stack domain id '
                    'configured, please fix your heat.conf')
            raise exception.Error(msg)

        # Create a keystoneclient session, then request a token with no
        # catalog (the token is expected to be used inside an instance
        # where a specific endpoint will be specified, and user-data
        # space is limited..)
        if self._stack_domain_is_id:
            auth = kc_auth_v3.Password(auth_url=self.v3_endpoint,
                                       username=username,
                                       password=password,
                                       project_id=project_id,
                                       user_domain_id=self.stack_domain)
        else:
            auth = kc_auth_v3.Password(auth_url=self.v3_endpoint,
                                       username=username,
                                       password=password,
                                       project_id=project_id,
                                       user_domain_name=self.stack_domain)
        sess = session.Session(auth=auth)
        # Note we do this directly via a post as there's currently
        # no way to get a nocatalog token via keystoneclient
        token_url = "%s/auth/tokens?nocatalog" % self.v3_endpoint
        headers = {'Accept': 'application/json'}
        if self._stack_domain_is_id:
            domain = {'id': self.stack_domain}
        else:
            domain = {'name': self.stack_domain}
        body = {'auth': {'scope':
                         {'project': {'id': project_id}},
                         'identity': {'password': {'user': {
                         'domain': domain,
                         'password': password, 'name': username}},
                             'methods': ['password']}}}
        t = sess.post(token_url, headers=headers, json=body,
                      authenticated=False)
        return t.headers['X-Subject-Token']

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
            LOG.warn(_LW('Falling back to legacy non-domain user create, '
                         'configure domain in heat.conf'))
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
            LOG.debug("Adding user %(user)s to role %(role)s" % {
                      'user': user.id, 'role': role_id})
            self.domain_admin_client.roles.grant(role=role_id, user=user.id,
                                                 project=project_id)
        else:
            LOG.error(_LE("Failed to add user %(user)s to role %(role)s, "
                          "check role exists!"),
                      {'user': username,
                       'role': cfg.CONF.heat_stack_user_role})
            raise exception.Error(_("Can't find role %s")
                                  % cfg.CONF.heat_stack_user_role)

        return user.id

    @property
    def stack_domain_id(self):
        if not self._stack_domain_id:
            if self._stack_domain_is_id:
                self._stack_domain_id = self.stack_domain
            else:
                domain_id = self._get_domain_id_from_name(self.stack_domain)
                self._stack_domain_id = domain_id
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
            LOG.warn(_LW('Falling back to legacy non-domain user delete, '
                         'configure domain in heat.conf'))
            return self.delete_stack_user(user_id)

        try:
            self._check_stack_domain_user(user_id, project_id, 'delete')
            self.domain_admin_client.users.delete(user_id)
        except kc_exception.NotFound:
            pass

    def delete_stack_user(self, user_id):
        try:
            self.client.users.delete(user=user_id)
        except kc_exception.NotFound:
            pass

    def create_stack_domain_project(self, stack_id):
        """Create a project in the heat stack-user domain."""
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            LOG.warn(_LW('Falling back to legacy non-domain project, '
                         'configure domain in heat.conf'))
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
            LOG.warn(_LW('Falling back to legacy non-domain project, '
                         'configure domain in heat.conf'))
            return

        # If stacks are created before configuring the heat domain, they
        # exist in the default domain, in the user's project, which we
        # do *not* want to delete!  However, if the keystone v3cloudsample
        # policy is used, it's possible that we'll get Forbidden when trying
        # to get the project, so again we should do nothing
        try:
            project = self.domain_admin_client.projects.get(project=project_id)
        except kc_exception.Forbidden:
            LOG.warning(_('Unable to get details for project %s, not deleting')
                        % project_id)
            return

        if project.domain_id != self.stack_domain_id:
            LOG.warning(_('Not deleting non heat-domain project'))
            return

        try:
            project.delete()
        except kc_exception.NotFound:
            pass

    def _find_ec2_keypair(self, access, user_id=None):
        """Lookup an ec2 keypair by access ID."""
        # FIXME(shardy): add filtering for user_id when keystoneclient
        # extensible-crud-manager-operations bp lands
        credentials = self.client.credentials.list()
        for cr in credentials:
            ec2_creds = json.loads(cr.blob)
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
            except kc_exception.NotFound:
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
            ec2_creds = json.loads(cred.blob)
            return AccessKey(id=cred.id,
                             access=ec2_creds['access'],
                             secret=ec2_creds['secret'])
        elif access:
            return self._find_ec2_keypair(access=access, user_id=user_id)
        else:
            raise ValueError("Must specify either credential_id or access")

    def create_ec2_keypair(self, user_id=None):
        user_id = user_id or self.client.auth_ref.user_id
        project_id = self.context.tenant_id
        data_blob = {'access': uuid.uuid4().hex,
                     'secret': uuid.uuid4().hex}
        ec2_creds = self.client.credentials.create(
            user=user_id, type='ec2', data=json.dumps(data_blob),
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
            LOG.warn(_LW('Falling back to legacy non-domain keypair, '
                         'configure domain in heat.conf'))
            return self.create_ec2_keypair(user_id)
        data_blob = {'access': uuid.uuid4().hex,
                     'secret': uuid.uuid4().hex}
        creds = self.domain_admin_client.credentials.create(
            user=user_id, type='ec2', data=json.dumps(data_blob),
            project=project_id)
        return AccessKey(id=creds.id,
                         access=data_blob['access'],
                         secret=data_blob['secret'])

    def delete_stack_domain_user_keypair(self, user_id, project_id,
                                         credential_id):
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            LOG.warn(_LW('Falling back to legacy non-domain keypair, '
                         'configure domain in heat.conf'))
            return self.delete_ec2_keypair(credential_id=credential_id)
        self._check_stack_domain_user(user_id, project_id, 'delete_keypair')
        try:
            self.domain_admin_client.credentials.delete(credential_id)
        except kc_exception.NotFound:
            pass

    def disable_stack_user(self, user_id):
        self.client.users.update(user=user_id, enabled=False)

    def enable_stack_user(self, user_id):
        self.client.users.update(user=user_id, enabled=True)

    def disable_stack_domain_user(self, user_id, project_id):
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            LOG.warn(_LW('Falling back to legacy non-domain disable, '
                         'configure domain in heat.conf'))
            return self.disable_stack_user(user_id)
        self._check_stack_domain_user(user_id, project_id, 'disable')
        self.domain_admin_client.users.update(user=user_id, enabled=False)

    def enable_stack_domain_user(self, user_id, project_id):
        if not self.stack_domain:
            # FIXME(shardy): Legacy fallback for folks using old heat.conf
            # files which lack domain configuration
            LOG.warn(_LW('Falling back to legacy non-domain enable, '
                         'configure domain in heat.conf'))
            return self.enable_stack_user(user_id)
        self._check_stack_domain_user(user_id, project_id, 'enable')
        self.domain_admin_client.users.update(user=user_id, enabled=True)

    def url_for(self, **kwargs):
        default_region_name = cfg.CONF.region_name_for_services
        kwargs.setdefault('region_name', default_region_name)
        return self.client.service_catalog.url_for(**kwargs)

    @property
    def auth_token(self):
        return self.client.auth_token


class KeystoneClient(object):

    """Keystone Auth Client.

    Delay choosing the backend client module until the client's class
    needs to be initialized.
    """

    def __new__(cls, context):
        if cfg.CONF.keystone_backend == _default_keystone_backend:
            return KeystoneClientV3(context)
        else:
            return importutils.import_object(
                cfg.CONF.keystone_backend,
                context
            )
