#
# Copyright (C) 2016, Red Hat, Inc.
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

import six
import webob

from heat.common import noauth
from heat.tests import common

EXPECTED_ENV_RESPONSE = {
    'HTTP_X_IDENTITY_STATUS': 'Confirmed',
    'HTTP_X_PROJECT_ID': 'admin',
    'HTTP_X_PROJECT_NAME': 'admin',
    'HTTP_X_USER_ID': 'admin',
    'HTTP_X_USER_NAME': 'admin',
    'HTTP_X_ROLES': 'admin',
    'HTTP_X_SERVICE_CATALOG': {},
    'HTTP_X_AUTH_USER': 'admin',
    'HTTP_X_AUTH_KEY': 'unset',
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
        resp.body = six.b('SUCCESS')
        return resp(env, start_response)


class KeystonePasswordAuthProtocolTest(common.HeatTestCase):

    def setUp(self):
        super(KeystonePasswordAuthProtocolTest, self).setUp()
        self.config = {'auth_uri': 'http://keystone.test.com:5000'}
        self.app = FakeApp()
        self.middleware = noauth.NoAuthProtocol(
            self.app, self.config)

    def _start_fake_response(self, status, headers):
        self.response_status = int(status.split(' ', 1)[0])
        self.response_headers = dict(headers)

    def test_request_with_bad_credentials(self):
        req = webob.Request.blank('/tenant_id1/')
        req.headers['X_AUTH_USER'] = 'admin'
        req.headers['X_AUTH_KEY'] = 'blah'
        req.headers['X_AUTH_URL'] = self.config['auth_uri']
        self.middleware(req.environ, self._start_fake_response)
        self.assertEqual(200, self.response_status)

    def test_request_with_no_tenant_in_url_or_auth_headers(self):
        req = webob.Request.blank('/')
        self.middleware(req.environ, self._start_fake_response)
        self.assertEqual(200, self.response_status)
