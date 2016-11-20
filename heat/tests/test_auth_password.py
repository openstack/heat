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

from keystoneauth1 import exceptions as keystone_exc
import mock
from oslo_config import cfg
import six
import webob

from heat.common import auth_password
from heat.tests import common


cfg.CONF.import_opt('keystone_backend',
                    'heat.engine.clients.os.keystone.heat_keystoneclient')


EXPECTED_ENV_RESPONSE = {
    'HTTP_X_IDENTITY_STATUS': 'Confirmed',
    'HTTP_X_PROJECT_ID': 'tenant_id1',
    'HTTP_X_PROJECT_NAME': 'tenant_name1',
    'HTTP_X_USER_ID': 'user_id1',
    'HTTP_X_USER_NAME': 'user_name1',
    'HTTP_X_ROLES': 'role1,role2',
    'HTTP_X_AUTH_TOKEN': 'lalalalalala',
}

TOKEN_V3_RESPONSE = {
    'version': 'v3',
    'project_id': 'tenant_id1',
    'project_name': 'tenant_name1',
    'user_id': 'user_id1',
    'username': 'user_name1',
    'service_catalog': None,
    'role_names': ['role1', 'role2'],
    'auth_token': 'lalalalalala',
    'user_domain_id': 'domain1'
}

TOKEN_V2_RESPONSE = {
    'version': 'v2',
    'tenant_id': 'tenant_id1',
    'tenant_name': 'tenant_name1',
    'user_id': 'user_id1',
    'service_catalog': None,
    'username': 'user_name1',
    'role_names': ['role1', 'role2'],
    'auth_token': 'lalalalalala',
    'user_domain_id': 'domain1'
}


class FakeAccessInfo(object):
    def __init__(self, **args):
        self.__dict__.update(args)


class FakeApp(object):
    """This represents a WSGI app protected by our auth middleware."""

    def __init__(self, expected_env=None):
        expected_env = expected_env or {}
        self.expected_env = dict(EXPECTED_ENV_RESPONSE)
        self.expected_env.update(expected_env)

    def __call__(self, env, start_response):
        """Assert that expected environment is present when finally called."""
        for k, v in self.expected_env.items():
            assert env[k] == v, '%s != %s' % (env[k], v)
        resp = webob.Response()
        resp.body = six.b('SUCCESS')
        return resp(env, start_response)


class KeystonePasswordAuthProtocolTest(common.HeatTestCase):

    def setUp(self):
        super(KeystonePasswordAuthProtocolTest, self).setUp()
        self.config = {'auth_uri': 'http://keystone.test.com:5000'}
        self.app = FakeApp()
        self.middleware = auth_password.KeystonePasswordAuthProtocol(
            self.app, self.config)

    def _start_fake_response(self, status, headers):
        self.response_status = int(status.split(' ', 1)[0])
        self.response_headers = dict(headers)

    @mock.patch('keystoneauth1.identity.generic.Password')
    def test_valid_v2_request(self, mock_password):
        mock_auth = mock.MagicMock()
        mock_password.return_value = mock_auth

        self.patchobject(mock_auth, 'get_access',
                         return_value=FakeAccessInfo(**TOKEN_V2_RESPONSE))

        req = webob.Request.blank('/tenant_id1/')
        req.headers['X_AUTH_USER'] = 'user_name1'
        req.headers['X_AUTH_KEY'] = 'goodpassword'
        req.headers['X_AUTH_URL'] = self.config['auth_uri']
        req.headers['X_USER_DOMAIN_ID'] = 'domain1'
        self.middleware(req.environ, self._start_fake_response)
        mock_password.assert_called_once_with(auth_url=self.config['auth_uri'],
                                              password='goodpassword',
                                              project_id='tenant_id1',
                                              user_domain_id='domain1',
                                              username='user_name1')

    @mock.patch('keystoneauth1.identity.generic.Password')
    def test_valid_v3_request(self, mock_password):
        mock_auth = mock.MagicMock()
        mock_password.return_value = mock_auth

        self.patchobject(mock_auth, 'get_access',
                         return_value=FakeAccessInfo(**TOKEN_V3_RESPONSE))

        req = webob.Request.blank('/tenant_id1/')
        req.headers['X_AUTH_USER'] = 'user_name1'
        req.headers['X_AUTH_KEY'] = 'goodpassword'
        req.headers['X_AUTH_URL'] = self.config['auth_uri']
        req.headers['X_USER_DOMAIN_ID'] = 'domain1'
        self.middleware(req.environ, self._start_fake_response)
        mock_password.assert_called_once_with(auth_url=self.config['auth_uri'],
                                              password='goodpassword',
                                              project_id='tenant_id1',
                                              user_domain_id='domain1',
                                              username='user_name1')

    @mock.patch('keystoneauth1.identity.generic.Password')
    def test_request_with_bad_credentials(self, mock_password):
        mock_password.side_effect = keystone_exc.Unauthorized(401)

        req = webob.Request.blank('/tenant_id1/')
        req.headers['X_AUTH_USER'] = 'user_name1'
        req.headers['X_AUTH_KEY'] = 'badpassword'
        req.headers['X_AUTH_URL'] = self.config['auth_uri']
        req.headers['X_USER_DOMAIN_ID'] = 'domain1'
        self.middleware(req.environ, self._start_fake_response)
        self.assertEqual(401, self.response_status)
        mock_password.assert_called_once_with(auth_url=self.config['auth_uri'],
                                              password='badpassword',
                                              project_id='tenant_id1',
                                              user_domain_id='domain1',
                                              username='user_name1')

    def test_request_with_no_tenant_in_url_or_auth_headers(self):
        req = webob.Request.blank('/')
        self.middleware(req.environ, self._start_fake_response)
        self.assertEqual(401, self.response_status)
