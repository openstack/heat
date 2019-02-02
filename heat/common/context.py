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

from keystoneauth1 import access
from keystoneauth1.identity import access as access_plugin
from keystoneauth1.identity import generic
from keystoneauth1 import loading as ks_loading
from keystoneauth1 import session
from keystoneauth1 import token_endpoint
from oslo_config import cfg
from oslo_context import context
from oslo_log import log as logging
import oslo_messaging
from oslo_middleware import request_id as oslo_request_id
from oslo_utils import importutils
import six

from heat.common import config
from heat.common import endpoint_utils
from heat.common import exception
from heat.common import policy
from heat.common import wsgi
from heat.db.sqlalchemy import api as db_api
from heat.engine import clients

LOG = logging.getLogger(__name__)


# Note, we yield the options via list_opts to enable generation of the
# sample heat.conf, but we don't register these options directly via
# cfg.CONF.register*, it's done via ks_loading.register_auth_conf_options
# Note, only auth_type = v3password is expected to work, example config:
# [trustee]
# auth_type = password
# auth_url = http://192.168.1.2:35357
# username = heat
# password = password
# user_domain_id = default
PASSWORD_PLUGIN = 'password'
TRUSTEE_CONF_GROUP = 'trustee'
ks_loading.register_auth_conf_options(cfg.CONF, TRUSTEE_CONF_GROUP)


def list_opts():
    trustee_opts = ks_loading.get_auth_common_conf_options()
    trustee_opts.extend(ks_loading.get_auth_plugin_conf_options(
        PASSWORD_PLUGIN))
    yield TRUSTEE_CONF_GROUP, trustee_opts


def _moved_attr(new_name):

    def getter(self):
        return getattr(self, new_name)

    def setter(self, value):
        setattr(self, new_name, value)

    return property(getter, setter)


class RequestContext(context.RequestContext):
    """Stores information about the security context.

    Under the security context the user accesses the system, as well as
    additional request information.
    """

    def __init__(self, username=None, password=None, aws_creds=None,
                 auth_url=None, roles=None, is_admin=None, read_only=False,
                 show_deleted=False, overwrite=True, trust_id=None,
                 trustor_user_id=None, request_id=None, auth_token_info=None,
                 region_name=None, auth_plugin=None, trusts_auth_plugin=None,
                 user_domain_id=None, project_domain_id=None,
                 project_name=None, **kwargs):
        """Initialisation of the request context.

        :param overwrite: Set to False to ensure that the greenthread local
            copy of the index is not overwritten.
        """
        if user_domain_id:
            kwargs['user_domain'] = user_domain_id
        if project_domain_id:
            kwargs['project_domain'] = project_domain_id

        super(RequestContext, self).__init__(is_admin=is_admin,
                                             read_only=read_only,
                                             show_deleted=show_deleted,
                                             request_id=request_id,
                                             roles=roles,
                                             overwrite=overwrite,
                                             **kwargs)

        self.username = username
        self.password = password
        self.region_name = region_name
        self.aws_creds = aws_creds
        self.project_name = project_name
        self.auth_token_info = auth_token_info
        self.auth_url = auth_url
        self._session = None
        self._clients = None
        self._keystone_session = session.Session(
            **config.get_ssl_options('keystone'))
        self.trust_id = trust_id
        self.trustor_user_id = trustor_user_id
        self.policy = policy.get_enforcer()
        self._auth_plugin = auth_plugin
        self._trusts_auth_plugin = trusts_auth_plugin

        if is_admin is None:
            self.is_admin = self.policy.check_is_admin(self)
        else:
            self.is_admin = is_admin

        # context scoped cache dict where the key is a class of the type of
        # object being cached and the value is the cache implementation class
        self._object_cache = {}

    def cache(self, cache_cls):
        cache = self._object_cache.get(cache_cls)
        if not cache:
            cache = cache_cls()
            self._object_cache[cache_cls] = cache
        return cache

    tenant_id = _moved_attr('project_id')

    @property
    def session(self):
        if self._session is None:
            self._session = db_api.get_session()
        return self._session

    @property
    def keystone_session(self):
        if not self._keystone_session.auth:
            self._keystone_session.auth = self.auth_plugin
        return self._keystone_session

    @property
    def clients(self):
        if self._clients is None:
            self._clients = clients.Clients(self)
        return self._clients

    def to_dict(self):
        user_idt = u'{user} {tenant}'.format(user=self.user_id or '-',
                                             tenant=self.project_id or '-')

        return {'auth_token': self.auth_token,
                'username': self.username,
                'user_id': self.user_id,
                'password': self.password,
                'aws_creds': self.aws_creds,
                'tenant': self.project_name,
                'tenant_id': self.project_id,
                'project_name': self.project_name,
                'project_id': self.project_id,
                'trust_id': self.trust_id,
                'trustor_user_id': self.trustor_user_id,
                'auth_token_info': self.auth_token_info,
                'auth_url': self.auth_url,
                'roles': self.roles,
                'is_admin': self.is_admin,
                'user': self.username,
                'request_id': self.request_id,
                'global_request_id': self.global_request_id,
                'show_deleted': self.show_deleted,
                'region_name': self.region_name,
                'user_identity': user_idt,
                'user_domain': self.user_domain,
                'project_domain': self.project_domain}

    @classmethod
    def from_dict(cls, values):
        return cls(
            auth_token=values.get('auth_token'),
            username=values.get('username'),
            user_id=values.get('user_id'),
            password=values.get('password'),
            aws_creds=values.get('aws_creds'),
            project_name=values.get('project_name', values.get('tenant')),
            project_id=values.get('project_id', values.get('tenant_id')),
            trust_id=values.get('trust_id'),
            trustor_user_id=values.get('trustor_user_id'),
            auth_token_info=values.get('auth_token_info'),
            auth_url=values.get('auth_url'),
            roles=values.get('roles'),
            is_admin=values.get('is_admin'),
            request_id=values.get('request_id'),
            show_deleted=values.get('show_deleted', False),
            region_name=values.get('region_name'),
            user_domain_id=values.get('user_domain'),
            project_domain_id=values.get('project_domain')
        )

    def to_policy_values(self):
        policy = super(RequestContext, self).to_policy_values()

        # NOTE(jamielennox): These are deprecated values passed to oslo.policy
        # for enforcement. They shouldn't be needed as the base class defines
        # what should be used when writing policy but are maintained for
        # compatibility.
        policy['user'] = self.user_id
        policy['tenant'] = self.project_id
        policy['is_admin'] = self.is_admin
        policy['auth_token_info'] = self.auth_token_info

        return policy

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
        if not self._trusts_auth_plugin:
            self._trusts_auth_plugin = ks_loading.load_auth_from_conf_options(
                cfg.CONF, TRUSTEE_CONF_GROUP, trust_id=self.trust_id)

        if not self._trusts_auth_plugin:
            LOG.error('Please add the trustee credentials you need '
                      'to the %s section of your heat.conf file.',
                      TRUSTEE_CONF_GROUP)
            raise exception.AuthorizationFailure()

        return self._trusts_auth_plugin

    def _create_auth_plugin(self):
        if self.auth_token_info:
            access_info = access.create(body=self.auth_token_info,
                                        auth_token=self.auth_token)
            return access_plugin.AccessInfoPlugin(
                auth_ref=access_info, auth_url=self.keystone_v3_endpoint)

        if self.password:
            return generic.Password(username=self.username,
                                    password=self.password,
                                    project_id=self.project_id,
                                    user_domain_id=self.user_domain,
                                    auth_url=self.keystone_v3_endpoint)

        if self.auth_token:
            # FIXME(jamielennox): This is broken but consistent. If you
            # only have a token but don't load a service catalog then
            # url_for wont work. Stub with the keystone endpoint so at
            # least it might be right.
            return token_endpoint.Token(endpoint=self.keystone_v3_endpoint,
                                        token=self.auth_token)

        LOG.error("Keystone API connection failed, no password "
                  "trust or auth_token!")
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


class StoredContext(RequestContext):
    def _load_keystone_data(self):
        self._keystone_loaded = True
        auth_ref = self.auth_plugin.get_access(self.keystone_session)

        self.roles = auth_ref.role_names
        self.user_domain = auth_ref.user_domain_id
        self.project_domain = auth_ref.project_domain_id

    @property
    def roles(self):
        if not getattr(self, '_keystone_loaded', False):
            self._load_keystone_data()
        return self._roles

    @roles.setter
    def roles(self, roles):
        self._roles = roles

    @property
    def user_domain(self):
        if not getattr(self, '_keystone_loaded', False):
            self._load_keystone_data()
        return self._user_domain_id

    @user_domain.setter
    def user_domain(self, user_domain):
        self._user_domain_id = user_domain

    @property
    def project_domain(self):
        if not getattr(self, '_keystone_loaded', False):
            self._load_keystone_data()
        return self._project_domain_id

    @project_domain.setter
    def project_domain(self, project_domain):
        self._project_domain_id = project_domain


def get_admin_context(show_deleted=False):
    return RequestContext(is_admin=True, show_deleted=show_deleted)


class ContextMiddleware(wsgi.Middleware):

    def __init__(self, app, conf, **local_conf):
        # Determine the context class to use
        self.ctxcls = RequestContext
        if 'context_class' in local_conf:
            self.ctxcls = importutils.import_class(local_conf['context_class'])

        super(ContextMiddleware, self).__init__(app)

    def process_request(self, req):
        """Constructs an appropriate context from extracted auth information.

        Extract any authentication information in the request and construct an
        appropriate context from it.
        """
        headers = req.headers
        environ = req.environ

        username = None
        password = None
        aws_creds = None
        user_domain = None
        project_domain = None

        if headers.get('X-Auth-User') is not None:
            username = headers.get('X-Auth-User')
            password = headers.get('X-Auth-Key')
        elif headers.get('X-Auth-EC2-Creds') is not None:
            aws_creds = headers.get('X-Auth-EC2-Creds')

        if headers.get('X-User-Domain-Id') is not None:
            user_domain = headers.get('X-User-Domain-Id')

        if headers.get('X-Project-Domain-Id') is not None:
            project_domain = headers.get('X-Project-Domain-Id')

        project_name = headers.get('X-Project-Name')
        region_name = headers.get('X-Region-Name')
        auth_url = headers.get('X-Auth-Url')

        token_info = environ.get('keystone.token_info')
        auth_plugin = environ.get('keystone.token_auth')
        req_id = environ.get(oslo_request_id.ENV_REQUEST_ID)

        req.context = self.ctxcls.from_environ(
            environ,
            project_name=project_name,
            aws_creds=aws_creds,
            username=username,
            password=password,
            auth_url=auth_url,
            request_id=req_id,
            user_domain=user_domain,
            project_domain=project_domain,
            auth_token_info=token_info,
            region_name=region_name,
            auth_plugin=auth_plugin,
        )


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
