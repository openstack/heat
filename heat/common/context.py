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

from keystoneclient import access
from keystoneclient import auth
from keystoneclient.auth.identity import access as access_plugin
from keystoneclient.auth.identity import v3
from keystoneclient.auth import token_endpoint
from oslo_config import cfg
from oslo_context import context
from oslo_log import log as logging
import oslo_messaging
from oslo_middleware import request_id as oslo_request_id
from oslo_utils import importutils
import six

from heat.common import endpoint_utils
from heat.common import exception
from heat.common.i18n import _LE, _LW
from heat.common import policy
from heat.common import wsgi
from heat.db import api as db_api
from heat.engine import clients

LOG = logging.getLogger(__name__)


# Note, we yield the options via list_opts to enable generation of the
# sample heat.conf, but we don't register these options directly via
# cfg.CONF.register*, it's done via auth.register_conf_options
# Note, only auth_plugin = v3password is expected to work, example config:
# [trustee]
# auth_plugin = password
# auth_url = http://192.168.1.2:35357
# username = heat
# password = password
# user_domain_id = default
V3_PASSWORD_PLUGIN = 'v3password'
TRUSTEE_CONF_GROUP = 'trustee'
auth.register_conf_options(cfg.CONF, TRUSTEE_CONF_GROUP)


def list_opts():
    trustee_opts = auth.conf.get_common_conf_options()
    trustee_opts.extend(auth.conf.get_plugin_options(V3_PASSWORD_PLUGIN))
    yield TRUSTEE_CONF_GROUP, trustee_opts


class RequestContext(context.RequestContext):
    """Stores information about the security context.

    Under the security context the user accesses the system, as well as
    additional request information.
    """

    def __init__(self, auth_token=None, username=None, password=None,
                 aws_creds=None, tenant=None, user_id=None,
                 tenant_id=None, auth_url=None, roles=None, is_admin=None,
                 read_only=False, show_deleted=False,
                 overwrite=True, trust_id=None, trustor_user_id=None,
                 request_id=None, auth_token_info=None, region_name=None,
                 auth_plugin=None, trusts_auth_plugin=None,
                 user_domain_id=None, project_domain_id=None, **kwargs):
        """Initialisation of the request context.

        :param overwrite: Set to False to ensure that the greenthread local
            copy of the index is not overwritten.

         :param kwargs: Extra arguments that might be present, but we ignore
            because they possibly came in from older rpc messages.
        """
        super(RequestContext, self).__init__(auth_token=auth_token,
                                             user=username, tenant=tenant,
                                             is_admin=is_admin,
                                             read_only=read_only,
                                             show_deleted=show_deleted,
                                             request_id=request_id,
                                             user_domain=user_domain_id,
                                             project_domain=project_domain_id)

        self.username = username
        self.user_id = user_id
        self.password = password
        self.region_name = region_name
        self.aws_creds = aws_creds
        self.tenant_id = tenant_id
        self.auth_token_info = auth_token_info
        self.auth_url = auth_url
        self.roles = roles or []
        self._session = None
        self._clients = None
        self.trust_id = trust_id
        self.trustor_user_id = trustor_user_id
        self.policy = policy.Enforcer()
        self._auth_plugin = auth_plugin
        self._trusts_auth_plugin = trusts_auth_plugin

        if is_admin is None:
            self.is_admin = self.policy.check_is_admin(self)
        else:
            self.is_admin = is_admin

    @property
    def session(self):
        if self._session is None:
            self._session = db_api.get_session()
        return self._session

    @property
    def clients(self):
        if self._clients is None:
            self._clients = clients.Clients(self)
        return self._clients

    def to_dict(self):
        user_idt = '{user} {tenant}'.format(user=self.user_id or '-',
                                            tenant=self.tenant_id or '-')

        return {'auth_token': self.auth_token,
                'username': self.username,
                'user_id': self.user_id,
                'password': self.password,
                'aws_creds': self.aws_creds,
                'tenant': self.tenant,
                'tenant_id': self.tenant_id,
                'trust_id': self.trust_id,
                'trustor_user_id': self.trustor_user_id,
                'auth_token_info': self.auth_token_info,
                'auth_url': self.auth_url,
                'roles': self.roles,
                'is_admin': self.is_admin,
                'user': self.user,
                'request_id': self.request_id,
                'show_deleted': self.show_deleted,
                'region_name': self.region_name,
                'user_identity': user_idt,
                'user_domain_id': self.user_domain,
                'project_domain_id': self.project_domain}

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    @property
    def keystone_v3_endpoint(self):
        if self.auth_url:
            return self.auth_url.replace('v2.0', 'v3')
        else:
            auth_uri = endpoint_utils.get_auth_uri()
            if auth_uri:
                return auth_uri
            else:
                LOG.error('Keystone API endpoint not provided. Set '
                          'auth_uri in section [clients_keystone] '
                          'of the configuration file.')
                raise exception.AuthorizationFailure()

    @property
    def trusts_auth_plugin(self):
        if self._trusts_auth_plugin:
            return self._trusts_auth_plugin

        self._trusts_auth_plugin = auth.load_from_conf_options(
            cfg.CONF, TRUSTEE_CONF_GROUP, trust_id=self.trust_id)

        if self._trusts_auth_plugin:
            LOG.warn(_LW('SHDEBUG NOT Using the keystone_authtoken'))
            return self._trusts_auth_plugin

        LOG.warning(_LW('Using the keystone_authtoken user as the heat '
                        'trustee user directly is deprecated. Please add the '
                        'trustee credentials you need to the %s section of '
                        'your heat.conf file.') % TRUSTEE_CONF_GROUP)

        cfg.CONF.import_group('keystone_authtoken',
                              'keystonemiddleware.auth_token')

        self._trusts_auth_plugin = v3.Password(
            username=cfg.CONF.keystone_authtoken.admin_user,
            password=cfg.CONF.keystone_authtoken.admin_password,
            user_domain_id=self.user_domain,
            auth_url=self.keystone_v3_endpoint,
            trust_id=self.trust_id)
        return self._trusts_auth_plugin

    def _create_auth_plugin(self):
        if self.auth_token_info:
            auth_ref = access.AccessInfo.factory(body=self.auth_token_info,
                                                 auth_token=self.auth_token)
            return access_plugin.AccessInfoPlugin(
                auth_url=self.keystone_v3_endpoint,
                auth_ref=auth_ref)

        if self.auth_token:
            # FIXME(jamielennox): This is broken but consistent. If you
            # only have a token but don't load a service catalog then
            # url_for wont work. Stub with the keystone endpoint so at
            # least it might be right.
            return token_endpoint.Token(endpoint=self.keystone_v3_endpoint,
                                        token=self.auth_token)

        if self.password:
            return v3.Password(username=self.username,
                               password=self.password,
                               project_id=self.tenant_id,
                               user_domain_id=self.user_domain,
                               auth_url=self.keystone_v3_endpoint)

        LOG.error(_LE("Keystone v3 API connection failed, no password "
                      "trust or auth_token!"))
        raise exception.AuthorizationFailure()

    def reload_auth_plugin(self):
        self._auth_plugin = None

    @property
    def auth_plugin(self):
        if not self._auth_plugin:
            if self.trust_id:
                self._auth_plugin = self.trusts_auth_plugin
            else:
                self._auth_plugin = self._create_auth_plugin()

        return self._auth_plugin


def get_admin_context(show_deleted=False):
    return RequestContext(is_admin=True, show_deleted=show_deleted)


class ContextMiddleware(wsgi.Middleware):

    def __init__(self, app, conf, **local_conf):
        # Determine the context class to use
        self.ctxcls = RequestContext
        if 'context_class' in local_conf:
            self.ctxcls = importutils.import_class(local_conf['context_class'])

        super(ContextMiddleware, self).__init__(app)

    def make_context(self, *args, **kwargs):
        """Create a context with the given arguments."""
        return self.ctxcls(*args, **kwargs)

    def process_request(self, req):
        """Constructs an appropriate context from extracted auth information.

        Extract any authentication information in the request and construct an
        appropriate context from it.
        """
        headers = req.headers
        environ = req.environ

        try:
            username = None
            password = None
            aws_creds = None

            if headers.get('X-Auth-User') is not None:
                username = headers.get('X-Auth-User')
                password = headers.get('X-Auth-Key')
            elif headers.get('X-Auth-EC2-Creds') is not None:
                aws_creds = headers.get('X-Auth-EC2-Creds')

            user_id = headers.get('X-User-Id')
            user_domain_id = headers.get('X_User_Domain_Id')
            token = headers.get('X-Auth-Token')
            tenant = headers.get('X-Project-Name')
            tenant_id = headers.get('X-Project-Id')
            project_domain_id = headers.get('X_Project_Domain_Id')
            region_name = headers.get('X-Region-Name')
            auth_url = headers.get('X-Auth-Url')

            roles = headers.get('X-Roles')
            if roles is not None:
                roles = roles.split(',')
            token_info = environ.get('keystone.token_info')
            auth_plugin = environ.get('keystone.token_auth')
            req_id = environ.get(oslo_request_id.ENV_REQUEST_ID)

        except Exception:
            raise exception.NotAuthenticated()

        req.context = self.make_context(
            auth_token=token,
            tenant=tenant, tenant_id=tenant_id,
            aws_creds=aws_creds,
            username=username,
            user_id=user_id,
            password=password,
            auth_url=auth_url,
            roles=roles,
            request_id=req_id,
            auth_token_info=token_info,
            region_name=region_name,
            auth_plugin=auth_plugin,
            user_domain_id=user_domain_id,
            project_domain_id=project_domain_id)


def ContextMiddleware_filter_factory(global_conf, **local_conf):
    """Factory method for paste.deploy."""
    conf = global_conf.copy()
    conf.update(local_conf)

    def filter(app):
        return ContextMiddleware(app, conf)

    return filter


def request_context(func):
    @six.wraps(func)
    def wrapped(self, ctx, *args, **kwargs):
        try:
            return func(self, ctx, *args, **kwargs)
        except exception.HeatException:
            raise oslo_messaging.rpc.dispatcher.ExpectedException()
    return wrapped
