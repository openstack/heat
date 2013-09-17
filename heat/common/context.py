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

from oslo.config import cfg

from heat.openstack.common import local
from heat.common import exception
from heat.common import wsgi
from heat.openstack.common import context
from heat.openstack.common import importutils
from heat.openstack.common import uuidutils
from heat.db import api as db_api


def generate_request_id():
    return 'req-' + uuidutils.generate_uuid()


class RequestContext(context.RequestContext):
    """
    Stores information about the security context under which the user
    accesses the system, as well as additional request information.
    """

    def __init__(self, auth_token=None, username=None, password=None,
                 aws_creds=None, tenant=None,
                 tenant_id=None, auth_url=None, roles=None, is_admin=False,
                 read_only=False, show_deleted=False,
                 owner_is_tenant=True, overwrite=True,
                 trust_id=None, trustor_user_id=None,
                 request_id=None, **kwargs):
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
        self.password = password
        self.aws_creds = aws_creds
        self.tenant_id = tenant_id
        self.auth_url = auth_url
        self.roles = roles or []
        self.owner_is_tenant = owner_is_tenant
        if overwrite or not hasattr(local.store, 'context'):
            self.update_store()
        self._session = None
        self.trust_id = trust_id
        self.trustor_user_id = trustor_user_id

    def update_store(self):
        local.store.context = self

    @property
    def session(self):
        if self._session is None:
            self._session = db_api.get_session()
        return self._session

    def to_dict(self):
        return {'auth_token': self.auth_token,
                'username': self.user,
                'password': self.password,
                'aws_creds': self.aws_creds,
                'tenant': self.tenant,
                'tenant_id': self.tenant_id,
                'trust_id': self.trust_id,
                'trustor_user_id': self.trustor_user_id,
                'auth_url': self.auth_url,
                'roles': self.roles,
                'is_admin': self.is_admin,
                'user': self.user,
                'request_id': self.request_id}

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    @property
    def owner(self):
        """Return the owner to correlate with an image."""
        return self.tenant if self.owner_is_tenant else self.user


def get_admin_context(read_deleted="no"):
    return RequestContext(is_admin=True)


class ContextMiddleware(wsgi.Middleware):

    opts = [cfg.BoolOpt('owner_is_tenant', default=True),
            cfg.StrOpt('admin_role', default='admin')]

    def __init__(self, app, conf, **local_conf):
        cfg.CONF.register_opts(self.opts)

        # Determine the context class to use
        self.ctxcls = RequestContext
        if 'context_class' in local_conf:
            self.ctxcls = importutils.import_class(local_conf['context_class'])

        super(ContextMiddleware, self).__init__(app)

    def make_context(self, *args, **kwargs):
        """
        Create a context with the given arguments.
        """
        kwargs.setdefault('owner_is_tenant', cfg.CONF.owner_is_tenant)

        return self.ctxcls(*args, **kwargs)

    def process_request(self, req):
        """
        Extract any authentication information in the request and
        construct an appropriate context from it.

        A few scenarios exist:

        1. If X-Auth-Token is passed in, then consult TENANT and ROLE headers
           to determine permissions.

        2. An X-Auth-Token was passed in, but the Identity-Status is not
           confirmed. For now, just raising a NotAuthenticated exception.

        3. X-Auth-Token is omitted. If we were using Keystone, then the
           tokenauth middleware would have rejected the request, so we must be
           using NoAuth. In that case, assume that is_admin=True.
        """
        headers = req.headers

        try:
            """
            This sets the username/password to the admin user because you
            need this information in order to perform token authentication.
            The real 'username' is the 'tenant'.

            We should also check here to see if X-Auth-Token is not set and
            in that case we should assign the user/pass directly as the real
            username/password and token as None.  'tenant' should still be
            the username.
            """

            username = None
            password = None
            aws_creds = None

            if headers.get('X-Auth-User') is not None:
                username = headers.get('X-Auth-User')
                password = headers.get('X-Auth-Key')
            elif headers.get('X-Auth-EC2-Creds') is not None:
                aws_creds = headers.get('X-Auth-EC2-Creds')

            token = headers.get('X-Auth-Token')
            tenant = headers.get('X-Tenant-Name')
            tenant_id = headers.get('X-Tenant-Id')
            auth_url = headers.get('X-Auth-Url')
            roles = headers.get('X-Roles')
            if roles is not None:
                roles = roles.split(',')

        except Exception:
            raise exception.NotAuthenticated()

        req.context = self.make_context(auth_token=token,
                                        tenant=tenant, tenant_id=tenant_id,
                                        aws_creds=aws_creds,
                                        username=username,
                                        password=password,
                                        auth_url=auth_url, roles=roles,
                                        is_admin=True)


def ContextMiddleware_filter_factory(global_conf, **local_conf):
    """
    Factory method for paste.deploy
    """
    conf = global_conf.copy()
    conf.update(local_conf)

    def filter(app):
        return ContextMiddleware(app, conf)

    return filter
