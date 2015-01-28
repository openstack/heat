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

from keystoneclient.auth.identity import v3 as ks_v3_auth
from keystoneclient import exceptions as keystone_exc
from keystoneclient import session as ks_session
import mox
from oslo.config import cfg
import webob

from heat.common import auth_password
from heat.tests import common


cfg.CONF.import_opt('keystone_backend', 'heat.common.heat_keystoneclient')


EXPECTED_ENV_RESPONSE = {
    'HTTP_X_IDENTITY_STATUS': 'Confirmed',
    'HTTP_X_PROJECT_ID': 'tenant_id1',
    'HTTP_X_PROJECT_NAME': 'tenant_name1',
    'HTTP_X_TENANT_ID': 'tenant_id1',
    'HTTP_X_TENANT_NAME': 'tenant_name1',
    'HTTP_X_USER_ID': 'user_id1',
    'HTTP_X_USER_NAME': 'user_name1',
    'HTTP_X_ROLES': 'role1,role2',
    'HTTP_X_AUTH_TOKEN': 'lalalalalala',
    'HTTP_X_USER': 'user_name1',  # deprecated (diablo-compat)
    'HTTP_X_TENANT': 'tenant_name1',  # deprecated (diablo-compat)
    'HTTP_X_ROLE': 'role1,role2',  # deprecated (diablo-compat)
}


TOKEN_V2_RESPONSE = {
    'token': {
        'id': 'lalalalalala',
        'expires': '2020-01-01T00:00:10.000123Z',
        'tenant': {
            'id': 'tenant_id1',
            'name': 'tenant_name1',
        },
    },
    'user': {
        'id': 'user_id1',
        'name': 'user_name1',
        'roles': [
            {'name': 'role1'},
            {'name': 'role2'},
        ],
    },
    'serviceCatalog': {}
}


TOKEN_V3_RESPONSE = {
    'version': 'v3',
    'project': {
        'id': 'tenant_id1',
        'name': 'tenant_name1',
    },
    'token': {
        'id': 'lalalalalala',
        'expires': '2020-01-01T00:00:10.000123Z',
        'tenant': {
            'id': 'tenant_id1',
            'name': 'tenant_name1',
        },
        'methods': ['password'],
    },
    'user': {
        'id': 'user_id1',
        'name': 'user_name1',
    },
    'roles': [
        {'name': 'role1'},
        {'name': 'role2'},
    ],
    'auth_token': 'lalalalalala'
}


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
        resp.body = 'SUCCESS'
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

    def test_valid_v2_request(self):
        mock_auth = self.m.CreateMock(ks_v3_auth.Password)
        self.m.StubOutWithMock(ks_v3_auth, 'Password')

        ks_v3_auth.Password(
            auth_url=self.config['auth_uri'],
            password='goodpassword',
            project_id='tenant_id1',
            user_domain_id='default',
            username='user_name1').AndReturn(mock_auth)

        m = mock_auth.get_access(mox.IsA(ks_session.Session))
        m.AndReturn(TOKEN_V2_RESPONSE)

        self.app.expected_env['keystone.token_info'] = TOKEN_V2_RESPONSE
        self.m.ReplayAll()
        req = webob.Request.blank('/tenant_id1/')
        req.headers['X_AUTH_USER'] = 'user_name1'
        req.headers['X_AUTH_KEY'] = 'goodpassword'
        req.headers['X_AUTH_URL'] = self.config['auth_uri']
        self.middleware(req.environ, self._start_fake_response)
        self.m.VerifyAll()

    def test_valid_v3_request(self):
        mock_auth = self.m.CreateMock(ks_v3_auth.Password)
        self.m.StubOutWithMock(ks_v3_auth, 'Password')

        ks_v3_auth.Password(auth_url=self.config['auth_uri'],
                            password='goodpassword',
                            project_id='tenant_id1',
                            user_domain_id='default',
                            username='user_name1').AndReturn(mock_auth)

        m = mock_auth.get_access(mox.IsA(ks_session.Session))
        m.AndReturn(TOKEN_V3_RESPONSE)

        self.app.expected_env['keystone.token_info'] = {
            'token': TOKEN_V3_RESPONSE
        }
        self.m.ReplayAll()
        req = webob.Request.blank('/tenant_id1/')
        req.headers['X_AUTH_USER'] = 'user_name1'
        req.headers['X_AUTH_KEY'] = 'goodpassword'
        req.headers['X_AUTH_URL'] = self.config['auth_uri']
        self.middleware(req.environ, self._start_fake_response)
        self.m.VerifyAll()

    def test_request_with_bad_credentials(self):
        self.m.StubOutWithMock(ks_v3_auth, 'Password')

        m = ks_v3_auth.Password(auth_url=self.config['auth_uri'],
                                password='badpassword',
                                project_id='tenant_id1',
                                user_domain_id='default',
                                username='user_name1')
        m.AndRaise(keystone_exc.Unauthorized(401))

        self.m.ReplayAll()
        req = webob.Request.blank('/tenant_id1/')
        req.headers['X_AUTH_USER'] = 'user_name1'
        req.headers['X_AUTH_KEY'] = 'badpassword'
        req.headers['X_AUTH_URL'] = self.config['auth_uri']
        self.middleware(req.environ, self._start_fake_response)
        self.m.VerifyAll()
        self.assertEqual(401, self.response_status)

    def test_request_with_no_tenant_in_url_or_auth_headers(self):
        req = webob.Request.blank('/')
        self.middleware(req.environ, self._start_fake_response)
        self.assertEqual(401, self.response_status)
