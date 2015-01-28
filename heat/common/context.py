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
from keystoneclient.auth.identity import base
from keystoneclient.auth.identity import v3
from keystoneclient.auth import token_endpoint
from oslo.config import cfg
from oslo.middleware import request_id as oslo_request_id
from oslo.utils import importutils
from oslo_context import context

from heat.common import exception
from heat.common.i18n import _LE
from heat.common import policy
from heat.common import wsgi
from heat.db import api as db_api
from heat.engine import clients
from heat.openstack.common import local
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


# FIXME(jamielennox): I copied this out of a review that is proposed against
# keystoneclient which can be used when available.
# https://review.openstack.org/#/c/143338/
class _AccessInfoPlugin(base.BaseIdentityPlugin):
    """A plugin that turns an existing AccessInfo object into a usable plugin.

    In certain circumstances you already have an auth_ref/AccessInfo object
    that you just want to reuse. This could have been from a cache, in
    auth_token middleware or other.

    Turn that existing object into a simple identity plugin. This plugin cannot
    be refreshed as the AccessInfo object does not contain any authorizing
    information.

    :param auth_ref: the existing AccessInfo object.
    :type auth_ref: keystoneclient.access.AccessInfo
    :param auth_url: the url where this AccessInfo was retrieved from. Required
                     if using the AUTH_INTERFACE with get_endpoint. (optional)
    """

    def __init__(self, auth_url, auth_ref):
        super(_AccessInfoPlugin, self).__init__(auth_url=auth_url,
                                                reauthenticate=False)
        self.auth_ref = auth_ref

    def get_auth_ref(self, session, **kwargs):
        return self.auth_ref

    def invalidate(self):
        # NOTE(jamielennox): Don't allow the default invalidation to occur
        # because on next authentication request we will only get the same
        # auth_ref object again.
        return False


class RequestContext(context.RequestContext):
    """
    Stores information about the security context under which the user
    accesses the system, as well as additional request information.
    """

    def __init__(self, auth_token=None, username=None, password=None,
                 aws_creds=None, tenant=None, user_id=None,
                 tenant_id=None, auth_url=None, roles=None, is_admin=None,
                 read_only=False, show_deleted=False,
                 overwrite=True, trust_id=None, trustor_user_id=None,
                 request_id=None, auth_token_info=None, region_name=None,
                 auth_plugin=None, **kwargs):
        """
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
                                             request_id=request_id)

        self.username = username
        self.user_id = user_id
        self.password = password
        self.region_name = region_name
        self.aws_creds = aws_creds
        self.tenant_id = tenant_id
        self.auth_token_info = auth_token_info
        self.auth_url = auth_url
        self.roles = roles or []
        if overwrite or not hasattr(local.store, 'context'):
            self.update_store()
        self._session = None
        self._clients = None
        self.trust_id = trust_id
        self.trustor_user_id = trustor_user_id
        self.policy = policy.Enforcer()
        self._auth_plugin = auth_plugin

        if is_admin is None:
            self.is_admin = self.policy.check_is_admin(self)
        else:
            self.is_admin = is_admin

    def update_store(self):
        local.store.context = self

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
                'region_name': self.region_name}

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    @property
    def _keystone_v3_endpoint(self):
        if self.auth_url:
            auth_uri = self.auth_url
        else:
            importutils.import_module('keystonemiddleware.auth_token')
            auth_uri = cfg.CONF.keystone_authtoken.auth_uri

        return auth_uri.replace('v2.0', 'v3')

    def _create_auth_plugin(self):
        if self.trust_id:
            importutils.import_module('keystonemiddleware.auth_token')
            username = cfg.CONF.keystone_authtoken.admin_user
            password = cfg.CONF.keystone_authtoken.admin_password

            return v3.Password(username=username,
                               password=password,
                               user_domain_id='default',
                               auth_url=self._keystone_v3_endpoint,
                               trust_id=self.trust_id)

        if self.auth_token_info:
            auth_ref = access.AccessInfo.factory(body=self.auth_token_info,
                                                 auth_token=self.auth_token)
            return _AccessInfoPlugin(self._keystone_v3_endpoint, auth_ref)

        if self.auth_token:
            # FIXME(jamielennox): This is broken but consistent. If you
            # only have a token but don't load a service catalog then
            # url_for wont work. Stub with the keystone endpoint so at
            # least it might be right.
            return token_endpoint.Token(endpoint=self._keystone_v3_endpoint,
                                        token=self.auth_token)

        if self.password:
            return v3.Password(username=self.username,
                               password=self.password,
                               project_id=self.tenant_id,
                               user_domain_id='default',
                               auth_url=self._keystone_v3_endpoint)

        LOG.error(_LE("Keystone v3 API connection failed, no password "
                      "trust or auth_token!"))
        raise exception.AuthorizationFailure()

    @property
    def auth_plugin(self):
        if not self._auth_plugin:
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
        """
        Create a context with the given arguments.
        """
        return self.ctxcls(*args, **kwargs)

    def process_request(self, req):
        """
        Extract any authentication information in the request and
        construct an appropriate context from it.
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
            token = headers.get('X-Auth-Token')
            tenant = headers.get('X-Tenant-Name')
            tenant_id = headers.get('X-Tenant-Id')
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

        req.context = self.make_context(auth_token=token,
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
                                        auth_plugin=auth_plugin)


def ContextMiddleware_filter_factory(global_conf, **local_conf):
    """
    Factory method for paste.deploy
    """
    conf = global_conf.copy()
    conf.update(local_conf)

    def filter(app):
        return ContextMiddleware(app, conf)

    return filter
