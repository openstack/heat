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


import json
import mock

from oslo_config import cfg
from oslo_utils import importutils
import requests
import six

from heat.api.aws import ec2token
from heat.api.aws import exception
from heat.common import wsgi
from heat.tests import common
from heat.tests import utils


class Ec2TokenTest(common.HeatTestCase):
    """Tests the Ec2Token middleware."""

    def setUp(self):
        super(Ec2TokenTest, self).setUp()
        self.patchobject(requests, 'post')

    def _dummy_GET_request(self, params=None, environ=None):
        # Mangle the params dict into a query string
        params = params or {}
        environ = environ or {}
        qs = "&".join(["=".join([k, str(params[k])]) for k in params])
        environ.update({'REQUEST_METHOD': 'GET', 'QUERY_STRING': qs})
        req = wsgi.Request(environ)
        return req

    def test_conf_get_paste(self):
        dummy_conf = {'auth_uri': 'http://192.0.2.9/v2.0'}
        ec2 = ec2token.EC2Token(app=None, conf=dummy_conf)
        self.assertEqual('http://192.0.2.9/v2.0', ec2._conf_get('auth_uri'))
        self.assertEqual(
            'http://192.0.2.9/v2.0/ec2tokens',
            ec2._conf_get_keystone_ec2_uri('http://192.0.2.9/v2.0'))

    def test_conf_get_opts(self):
        cfg.CONF.set_default('auth_uri', 'http://192.0.2.9/v2.0/',
                             group='ec2authtoken')
        cfg.CONF.set_default('auth_uri', 'this-should-be-ignored',
                             group='clients_keystone')
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('http://192.0.2.9/v2.0/', ec2._conf_get('auth_uri'))
        self.assertEqual(
            'http://192.0.2.9/v2.0/ec2tokens',
            ec2._conf_get_keystone_ec2_uri('http://192.0.2.9/v2.0/'))

    def test_conf_get_clients_keystone_opts(self):
        cfg.CONF.set_default('auth_uri', None, group='ec2authtoken')
        cfg.CONF.set_default('auth_uri', 'http://192.0.2.9',
                             group='clients_keystone')
        with mock.patch('keystoneauth1.discover.Discover') as discover:
            class MockDiscover(object):
                def url_for(self, endpoint):
                    return 'http://192.0.2.9/v3/'
            discover.return_value = MockDiscover()
            ec2 = ec2token.EC2Token(app=None, conf={})
            self.assertEqual(
                'http://192.0.2.9/v3/ec2tokens',
                ec2._conf_get_keystone_ec2_uri('http://192.0.2.9/v3/'))

    def test_conf_get_ssl_default_options(self):
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertTrue(ec2.ssl_options['verify'],
                        "SSL verify should be True by default")
        self.assertIsNone(ec2.ssl_options['cert'],
                          "SSL client cert should be None by default")

    def test_conf_ssl_insecure_option(self):
        ec2 = ec2token.EC2Token(app=None, conf={})
        cfg.CONF.set_default('insecure', 'True', group='ec2authtoken')
        cfg.CONF.set_default('ca_file', None, group='ec2authtoken')
        self.assertFalse(ec2.ssl_options['verify'])

    def test_conf_get_ssl_opts(self):
        cfg.CONF.set_default('auth_uri', 'https://192.0.2.9/v2.0/',
                             group='ec2authtoken')
        cfg.CONF.set_default('ca_file', '/home/user/cacert.pem',
                             group='ec2authtoken')
        cfg.CONF.set_default('insecure', 'false', group='ec2authtoken')
        cfg.CONF.set_default('cert_file', '/home/user/mycert',
                             group='ec2authtoken')
        cfg.CONF.set_default('key_file', '/home/user/mykey',
                             group='ec2authtoken')
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('/home/user/cacert.pem', ec2.ssl_options['verify'])
        self.assertEqual(('/home/user/mycert', '/home/user/mykey'),
                         ec2.ssl_options['cert'])

    def test_get_signature_param_old(self):
        params = {'Signature': 'foo'}
        dummy_req = self._dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_signature(dummy_req))

    def test_get_signature_param_new(self):
        params = {'X-Amz-Signature': 'foo'}
        dummy_req = self._dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_signature(dummy_req))

    def test_get_signature_header_space(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('xyz', ec2._get_signature(dummy_req))

    def test_get_signature_header_notlast(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                    'Signature=xyz,'
                    'SignedHeaders=content-type;host;x-amz-date ')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('xyz', ec2._get_signature(dummy_req))

    def test_get_signature_header_nospace(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar,'
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('xyz', ec2._get_signature(dummy_req))

    def test_get_access_param_old(self):
        params = {'AWSAccessKeyId': 'foo'}
        dummy_req = self._dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_get_access_param_new(self):
        params = {'X-Amz-Credential': 'foo/bar'}
        dummy_req = self._dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_get_access_header_space(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_get_access_header_nospace(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar,'
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_get_access_header_last(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo '
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz,Credential=foo/bar')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_call_x_auth_user(self):
        req_env = {'HTTP_X_AUTH_USER': 'foo'}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertEqual('xyz', ec2.__call__(dummy_req))

    def test_call_auth_nosig(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertRaises(exception.HeatIncompleteSignatureError,
                          ec2.__call__, dummy_req)

    def test_call_auth_nouser(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo '
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertRaises(exception.HeatMissingAuthenticationTokenError,
                          ec2.__call__, dummy_req)

    def test_call_auth_noaccess(self):
        # If there's no accesskey in params or header, but there is a
        # Signature, we expect HeatMissingAuthenticationTokenError
        params = {'Signature': 'foo'}
        dummy_req = self._dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertRaises(exception.HeatMissingAuthenticationTokenError,
                          ec2.__call__, dummy_req)

    def test_call_x_auth_nouser_x_auth_user(self):
        req_env = {'HTTP_X_AUTH_USER': 'foo',
                   'HTTP_AUTHORIZATION':
                   ('Authorization: foo '
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertEqual('xyz', ec2.__call__(dummy_req))

    def _stub_http_connection(self, headers=None, params=None, response=None,
                              req_url='http://123:5000/v3/ec2tokens',
                              verify=True, cert=None, direct_mock=True):

        headers = headers or {}
        params = params or {}

        class DummyHTTPResponse(object):
            text = response
            headers = {'X-Subject-Token': 123}

            def json(self):
                return json.loads(self.text)

        body_hash = ('e3b0c44298fc1c149afbf4c8996fb9'
                     '2427ae41e4649b934ca495991b7852b855')
        req_creds = {
            "ec2Credentials": {
                "access": "foo",
                "headers": headers,
                "host": "heat:8000",
                "verb": "GET",
                "params": params,
                "signature": "xyz",
                "path": "/v1",
                "body_hash": body_hash
            }
        }
        req_headers = {'Content-Type': 'application/json'}
        self.verify_req_url = req_url
        self.verify_data = utils.JsonRepr(req_creds)
        self.verify_verify = verify
        self.verify_cert = cert
        self.verify_req_headers = req_headers
        if direct_mock:
            requests.post.return_value = DummyHTTPResponse()
        else:
            return DummyHTTPResponse()

    def test_call_ok(self):
        dummy_conf = {'auth_uri': 'http://123:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = self._dummy_GET_request(environ=req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=ok_resp)
        self.assertEqual('woot', ec2.__call__(dummy_req))

        self.assertEqual('tenant', dummy_req.headers['X-Tenant-Name'])
        self.assertEqual('abcd1234', dummy_req.headers['X-Tenant-Id'])
        requests.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_ok_roles(self):
        dummy_conf = {'auth_uri': 'http://123:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = self._dummy_GET_request(environ=req_env)

        ok_resp = json.dumps({
            'token': {
                'id': 123,
                'project': {'name': 'tenant', 'id': 'abcd1234'},
                'roles': [{'name': 'aa'}, {'name': 'bb'}, {'name': 'cc'}]}
        })
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=ok_resp)
        self.assertEqual('woot', ec2.__call__(dummy_req))

        self.assertEqual('aa,bb,cc', dummy_req.headers['X-Roles'])
        requests.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_err_tokenid(self):
        dummy_conf = {'auth_uri': 'http://123:5000/v2.0/'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = self._dummy_GET_request(environ=req_env)

        err_msg = "EC2 access key not found."
        err_resp = json.dumps({'error': {'message': err_msg}})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=err_resp)
        self.assertRaises(exception.HeatInvalidClientTokenIdError,
                          ec2.__call__, dummy_req)

        requests.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_err_signature(self):
        dummy_conf = {'auth_uri': 'http://123:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = self._dummy_GET_request(environ=req_env)

        err_msg = "EC2 signature not supplied."
        err_resp = json.dumps({'error': {'message': err_msg}})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=err_resp)
        self.assertRaises(exception.HeatSignatureError,
                          ec2.__call__, dummy_req)

        requests.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_err_denied(self):
        dummy_conf = {'auth_uri': 'http://123:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = self._dummy_GET_request(environ=req_env)

        err_resp = json.dumps({})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=err_resp)
        self.assertRaises(exception.HeatAccessDeniedError,
                          ec2.__call__, dummy_req)

        requests.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_ok_v2(self):
        dummy_conf = {'auth_uri': 'http://123:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = self._dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        self._stub_http_connection(response=ok_resp,
                                   params={'AWSAccessKeyId': 'foo'})
        self.assertEqual('woot', ec2.__call__(dummy_req))

        requests.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_ok_multicloud(self):
        dummy_conf = {
            'allowed_auth_uris': [
                'http://123:5000/v2.0', 'http://456:5000/v2.0'],
            'multi_cloud': True
        }
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = self._dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        err_msg = "EC2 access key not found."
        err_resp = json.dumps({'error': {'message': err_msg}})

        # first request fails
        m_p = self._stub_http_connection(
            req_url='http://123:5000/v2.0/ec2tokens',
            response=err_resp,
            params={'AWSAccessKeyId': 'foo'}, direct_mock=False)

        # second request passes
        m_p2 = self._stub_http_connection(
            req_url='http://456:5000/v2.0/ec2tokens',
            response=ok_resp,
            params={'AWSAccessKeyId': 'foo'}, direct_mock=False)

        requests.post.side_effect = [m_p, m_p2]

        self.assertEqual('woot', ec2.__call__(dummy_req))

        self.assertEqual(2, requests.post.call_count)
        requests.post.assert_called_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_err_multicloud(self):
        dummy_conf = {
            'allowed_auth_uris': [
                'http://123:5000/v2.0', 'http://456:5000/v2.0'],
            'multi_cloud': True
        }
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = self._dummy_GET_request(params, req_env)

        err_resp1 = json.dumps({})

        err_msg2 = "EC2 access key not found."
        err_resp2 = json.dumps({'error': {'message': err_msg2}})

        # first request fails with HeatAccessDeniedError
        m_p = self._stub_http_connection(
            req_url='http://123:5000/v2.0/ec2tokens',
            response=err_resp1,
            params={'AWSAccessKeyId': 'foo'}, direct_mock=False)

        # second request fails with HeatInvalidClientTokenIdError
        m_p2 = self._stub_http_connection(
            req_url='http://456:5000/v2.0/ec2tokens',
            response=err_resp2,
            params={'AWSAccessKeyId': 'foo'}, direct_mock=False)

        requests.post.side_effect = [m_p, m_p2]
        # raised error matches last failure
        self.assertRaises(exception.HeatInvalidClientTokenIdError,
                          ec2.__call__, dummy_req)

        self.assertEqual(2, requests.post.call_count)
        requests.post.assert_called_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_err_multicloud_none_allowed(self):
        dummy_conf = {
            'allowed_auth_uris': [],
            'multi_cloud': True
        }
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = self._dummy_GET_request(params, req_env)

        self.assertRaises(exception.HeatAccessDeniedError,
                          ec2.__call__, dummy_req)

    def test_call_badconf_no_authuri(self):
        ec2 = ec2token.EC2Token(app='woot', conf={})
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = self._dummy_GET_request(params, req_env)

        ex = self.assertRaises(exception.HeatInternalFailureError,
                               ec2.__call__, dummy_req)
        self.assertEqual('Service misconfigured', six.text_type(ex))

    def test_call_ok_auth_uri_ec2authtoken(self):
        dummy_url = 'http://123:5000/v2.0'
        cfg.CONF.set_default('auth_uri', dummy_url, group='ec2authtoken')

        ec2 = ec2token.EC2Token(app='woot', conf={})
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = self._dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        self._stub_http_connection(response=ok_resp,
                                   params={'AWSAccessKeyId': 'foo'})
        self.assertEqual('woot', ec2.__call__(dummy_req))

        requests.post.assert_called_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_ok_auth_uri_ec2authtoken_long(self):
        # Prove we tolerate a url which already includes the /ec2tokens path
        dummy_url = 'http://123:5000/v2.0/ec2tokens'
        cfg.CONF.set_default('auth_uri', dummy_url, group='ec2authtoken')

        ec2 = ec2token.EC2Token(app='woot', conf={})
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = self._dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        self._stub_http_connection(response=ok_resp,
                                   params={'AWSAccessKeyId': 'foo'})
        self.assertEqual('woot', ec2.__call__(dummy_req))

        requests.post.assert_called_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_call_ok_auth_uri_ks_authtoken(self):
        # Import auth_token to have keystone_authtoken settings setup.
        importutils.import_module('keystonemiddleware.auth_token')
        dummy_url = 'http://123:5000/v2.0'
        cfg.CONF.set_override('www_authenticate_uri', dummy_url,
                              group='keystone_authtoken')
        ec2 = ec2token.EC2Token(app='woot', conf={})
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = self._dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        self._stub_http_connection(response=ok_resp,
                                   params={'AWSAccessKeyId': 'foo'})
        self.assertEqual('woot', ec2.__call__(dummy_req))

        requests.post.assert_called_with(
            self.verify_req_url, data=self.verify_data,
            verify=self.verify_verify,
            cert=self.verify_cert, headers=self.verify_req_headers)

    def test_filter_factory(self):
        ec2_filter = ec2token.EC2Token_filter_factory(global_conf={})

        self.assertEqual('xyz', ec2_filter('xyz').application)

    def test_filter_factory_none_app(self):
        ec2_filter = ec2token.EC2Token_filter_factory(global_conf={})

        self.assertIsNone(ec2_filter(None).application)
