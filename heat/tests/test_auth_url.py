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

import mock
import six
import webob
from webob import exc

from heat.common import auth_url
from heat.tests import common


class FakeApp(object):
    """This represents a WSGI app protected by our auth middleware."""

    def __call__(self, environ, start_response):
        """Assert that headers are correctly set up when finally called."""
        resp = webob.Response()
        resp.body = six.b('SUCCESS')
        return resp(environ, start_response)


class AuthUrlFilterTest(common.HeatTestCase):

    def setUp(self):
        super(AuthUrlFilterTest, self).setUp()
        self.app = FakeApp()
        self.config = {'auth_uri': 'foobar'}
        self.middleware = auth_url.AuthUrlFilter(self.app, self.config)

    @mock.patch.object(auth_url.cfg, 'CONF')
    def test_adds_default_auth_url_from_clients_keystone(self, mock_cfg):
        self.config = {}
        mock_cfg.clients_keystone.auth_uri = 'foobar'
        mock_cfg.keystone_authtoken.www_authenticate_uri = 'should-be-ignored'
        mock_cfg.auth_password.multi_cloud = False
        with mock.patch('keystoneauth1.discover.Discover') as discover:
            class MockDiscover(object):
                def url_for(self, endpoint):
                    return 'foobar/v3'
            discover.return_value = MockDiscover()
            self.middleware = auth_url.AuthUrlFilter(self.app, self.config)
            req = webob.Request.blank('/tenant_id/')
            self.middleware(req)
            self.assertIn('X-Auth-Url', req.headers)
            self.assertEqual('foobar/v3', req.headers['X-Auth-Url'])

    @mock.patch.object(auth_url.cfg, 'CONF')
    def test_adds_default_auth_url_from_keystone_authtoken(self, mock_cfg):
        self.config = {}
        mock_cfg.clients_keystone.auth_uri = ''
        mock_cfg.keystone_authtoken.www_authenticate_uri = 'foobar'
        mock_cfg.auth_password.multi_cloud = False
        self.middleware = auth_url.AuthUrlFilter(self.app, self.config)
        req = webob.Request.blank('/tenant_id/')
        self.middleware(req)
        self.assertIn('X-Auth-Url', req.headers)
        self.assertEqual('foobar', req.headers['X-Auth-Url'])

    def test_overwrites_auth_url_from_headers_with_local_config(self):
        req = webob.Request.blank('/tenant_id/')
        req.headers['X-Auth-Url'] = 'should_be_overwritten'
        self.middleware(req)
        self.assertEqual('foobar', req.headers['X-Auth-Url'])

    def test_reads_auth_url_from_local_config(self):
        req = webob.Request.blank('/tenant_id/')
        self.middleware(req)
        self.assertIn('X-Auth-Url', req.headers)
        self.assertEqual('foobar', req.headers['X-Auth-Url'])

    @mock.patch.object(auth_url.AuthUrlFilter, '_validate_auth_url')
    @mock.patch.object(auth_url.cfg, 'CONF')
    def test_multicloud_reads_auth_url_from_headers(self, mock_cfg, mock_val):
        mock_cfg.auth_password.multi_cloud = True
        mock_val.return_value = True
        req = webob.Request.blank('/tenant_id/')
        req.headers['X-Auth-Url'] = 'overwrites config'
        self.middleware(req)
        self.assertIn('X-Auth-Url', req.headers)
        self.assertEqual('overwrites config', req.headers['X-Auth-Url'])

    @mock.patch.object(auth_url.AuthUrlFilter, '_validate_auth_url')
    @mock.patch.object(auth_url.cfg, 'CONF')
    def test_multicloud_validates_auth_url(self, mock_cfg, mock_validate):
        mock_cfg.auth_password.multi_cloud = True
        req = webob.Request.blank('/tenant_id/')

        self.middleware(req)
        self.assertTrue(mock_validate.called)

    def test_validate_auth_url_with_missing_url(self):
        self.assertRaises(exc.HTTPBadRequest,
                          self.middleware._validate_auth_url,
                          auth_url='')

        self.assertRaises(exc.HTTPBadRequest,
                          self.middleware._validate_auth_url,
                          auth_url=None)

    @mock.patch.object(auth_url.cfg, 'CONF')
    def test_validate_auth_url_with_url_not_allowed(self, mock_cfg):
        mock_cfg.auth_password.allowed_auth_uris = ['foobar']

        self.assertRaises(exc.HTTPUnauthorized,
                          self.middleware._validate_auth_url,
                          auth_url='not foobar')

    @mock.patch.object(auth_url.cfg, 'CONF')
    def test_validate_auth_url_with_valid_url(self, mock_cfg):
        mock_cfg.auth_password.allowed_auth_uris = ['foobar']

        self.assertTrue(self.middleware._validate_auth_url('foobar'))
