# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from keystoneclient.v2_0 import client as keystone_client
from keystoneclient import exceptions as keystone_exceptions
from oslo.config import cfg
from webob.exc import HTTPBadRequest
from webob.exc import HTTPUnauthorized

from heat.openstack.common import importutils


class KeystonePasswordAuthProtocol(object):
    """
    Alternative authentication middleware that uses username and password
    to authenticate against Keystone instead of validating existing auth token.
    The benefit being that you no longer require admin/service token to
    authenticate users.
    """

    def __init__(self, app, conf):
        self.app = app
        self.conf = conf
        auth_url = None
        if not cfg.CONF.auth_password.multi_cloud:
            if 'auth_uri' in self.conf:
                auth_url = self.conf['auth_uri']
            else:
                # Import auth_token to have keystone_authtoken settings setup.
                importutils.import_module(
                    'keystoneclient.middleware.auth_token')
                auth_url = cfg.CONF.keystone_authtoken['auth_uri']
        self.auth_url = auth_url

    def __call__(self, env, start_response):
        """Authenticate incoming request."""
        username = env.get('HTTP_X_AUTH_USER')
        password = env.get('HTTP_X_AUTH_KEY')
        # Determine tenant id from path.
        tenant = env.get('PATH_INFO').split('/')[1]
        auth_url = self.auth_url
        if cfg.CONF.auth_password.multi_cloud:
            auth_url = env.get('HTTP_X_AUTH_URL')
            error = self._validate_auth_url(env, start_response, auth_url)
            if error:
                return error
        if not tenant:
            return self._reject_request(env, start_response, auth_url)
        try:
            client = keystone_client.Client(
                username=username, password=password, tenant_id=tenant,
                auth_url=auth_url)
        except (keystone_exceptions.Unauthorized,
                keystone_exceptions.Forbidden,
                keystone_exceptions.NotFound,
                keystone_exceptions.AuthorizationFailure):
            return self._reject_request(env, start_response, auth_url)
        env['keystone.token_info'] = client.auth_ref
        env.update(self._build_user_headers(client.auth_ref, auth_url))
        return self.app(env, start_response)

    def _reject_request(self, env, start_response, auth_url):
        """Redirect client to auth server."""
        headers = [('WWW-Authenticate', 'Keystone uri=\'%s\'' % auth_url)]
        resp = HTTPUnauthorized('Authentication required', headers)
        return resp(env, start_response)

    def _build_user_headers(self, token_info, auth_url):
        """Build headers that represent authenticated user from auth token."""
        tenant_id = token_info['token']['tenant']['id']
        tenant_name = token_info['token']['tenant']['name']
        user_id = token_info['user']['id']
        user_name = token_info['user']['name']
        roles = ','.join(
            [role['name'] for role in token_info['user']['roles']])
        service_catalog = token_info['serviceCatalog']
        auth_token = token_info['token']['id']

        headers = {
            'HTTP_X_IDENTITY_STATUS': 'Confirmed',
            'HTTP_X_PROJECT_ID': tenant_id,
            'HTTP_X_PROJECT_NAME': tenant_name,
            'HTTP_X_USER_ID': user_id,
            'HTTP_X_USER_NAME': user_name,
            'HTTP_X_ROLES': roles,
            'HTTP_X_SERVICE_CATALOG': service_catalog,
            'HTTP_X_AUTH_TOKEN': auth_token,
            'HTTP_X_AUTH_URL': auth_url,
            # DEPRECATED
            'HTTP_X_USER': user_name,
            'HTTP_X_TENANT_ID': tenant_id,
            'HTTP_X_TENANT_NAME': tenant_name,
            'HTTP_X_TENANT': tenant_name,
            'HTTP_X_ROLE': roles,
        }

        return headers

    def _validate_auth_url(self, env, start_response, auth_url):
        """Validate auth_url to ensure it can be used."""
        if not auth_url:
            resp = HTTPBadRequest(_('Request missing required header '
                                    'X-Auth-Url'))
            return resp(env, start_response)
        allowed = cfg.CONF.auth_password.allowed_auth_uris
        if auth_url not in allowed:
            resp = HTTPUnauthorized(_('Header X-Auth-Url "%s" not an allowed '
                                      'endpoint')
                                    % auth_url)
            return resp(env, start_response)
        return None


def filter_factory(global_conf, **local_conf):
    """Returns a WSGI filter app for use with paste.deploy."""
    conf = global_conf.copy()
    conf.update(local_conf)

    def auth_filter(app):
        return KeystonePasswordAuthProtocol(app, conf)
    return auth_filter
