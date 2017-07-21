#
# Copyright 2013 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from keystoneauth1 import exceptions as keystone_exceptions
from keystoneauth1 import session
from webob import exc

from heat.common import config
from heat.common import context


class KeystonePasswordAuthProtocol(object):
    """Middleware uses username and password to authenticate against Keystone.

    Alternative authentication middleware that uses username and password
    to authenticate against Keystone instead of validating existing auth token.
    The benefit being that you no longer require admin/service token to
    authenticate users.
    """

    def __init__(self, app, conf):
        self.app = app
        self.conf = conf
        self.session = session.Session(**config.get_ssl_options('keystone'))

    def __call__(self, env, start_response):
        """Authenticate incoming request."""
        username = env.get('HTTP_X_AUTH_USER')
        password = env.get('HTTP_X_AUTH_KEY')
        # Determine tenant id from path.
        tenant = env.get('PATH_INFO').split('/')[1]
        auth_url = env.get('HTTP_X_AUTH_URL')
        user_domain_id = env.get('HTTP_X_USER_DOMAIN_ID')
        if not tenant:
            return self._reject_request(env, start_response, auth_url)
        try:
            ctx = context.RequestContext(username=username,
                                         password=password,
                                         tenant=tenant,
                                         auth_url=auth_url,
                                         user_domain_id=user_domain_id,
                                         is_admin=False)
            auth_ref = ctx.auth_plugin.get_access(self.session)
        except (keystone_exceptions.Unauthorized,
                keystone_exceptions.Forbidden,
                keystone_exceptions.NotFound,
                keystone_exceptions.AuthorizationFailure):
            return self._reject_request(env, start_response, auth_url)
        env.update(self._build_user_headers(auth_ref))

        return self.app(env, start_response)

    def _reject_request(self, env, start_response, auth_url):
        """Redirect client to auth server."""
        headers = [('WWW-Authenticate', "Keystone uri='%s'" % auth_url)]
        resp = exc.HTTPUnauthorized('Authentication required', headers)
        return resp(env, start_response)

    def _build_user_headers(self, token_info):
        """Build headers that represent authenticated user from auth token."""

        if token_info.version == 'v3':
            project_id = token_info.project_id
            project_name = token_info.project_name
        else:
            project_id = token_info.tenant_id
            project_name = token_info.tenant_name

        user_id = token_info.user_id
        user_name = token_info.username
        roles = ','.join(
            [role for role in token_info.role_names])
        service_catalog = token_info.service_catalog
        auth_token = token_info.auth_token
        user_domain_id = token_info.user_domain_id

        headers = {
            'HTTP_X_IDENTITY_STATUS': 'Confirmed',
            'HTTP_X_PROJECT_ID': project_id,
            'HTTP_X_PROJECT_NAME': project_name,
            'HTTP_X_USER_ID': user_id,
            'HTTP_X_USER_NAME': user_name,
            'HTTP_X_ROLES': roles,
            'HTTP_X_SERVICE_CATALOG': service_catalog,
            'HTTP_X_AUTH_TOKEN': auth_token,
            'HTTP_X_USER_DOMAIN_ID': user_domain_id,
        }

        return headers


def filter_factory(global_conf, **local_conf):
    """Returns a WSGI filter app for use with paste.deploy."""
    conf = global_conf.copy()
    conf.update(local_conf)

    def auth_filter(app):
        return KeystonePasswordAuthProtocol(app, conf)
    return auth_filter
