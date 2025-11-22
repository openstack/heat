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
import pathlib
from unittest import mock

from oslo_config import cfg

import keystoneauth1.discover
from keystoneauth1 import exceptions as ks_exceptions
import keystoneauth1.loading.conf
from keystoneauth1 import noauth as ks_noauth
import keystoneauth1.session

from heat.api.aws import ec2token
from heat.api.aws import exception
from heat.common import wsgi
from heat.tests import common
from heat.tests import utils


class Ec2TokenTest(common.HeatTestCase):
    """Tests the Ec2Token middleware."""

    def setUp(self):
        super(Ec2TokenTest, self).setUp()
        self.mock_adapter = mock.MagicMock(
            name='adapter',
            spec=('get_endpoint', 'post', 'session'))
        self.create_keystone_adapters = self.patchobject(
            ec2token.EC2Token, '_create_keystone_adapters')
        self.mock_adapter.get_endpoint.return_value = \
            'http://key1.example.com:5000'
        # Ensure that the various auth urls are available for the tests.
        self.create_keystone_adapters.return_value = {
            None: self.mock_adapter,
            'http://192.0.2.9/v2.0': self.mock_adapter,
            'http://192.0.2.9/v3': self.mock_adapter,
            'http://key1.example.com:5000/v3': self.mock_adapter,
            'http://key1.example.com:5000/v2.0': self.mock_adapter,
            'http://key2.example.com:5000/v2.0': self.mock_adapter,
        }

    def test_conf_get_paste(self):
        dummy_conf = {'auth_uri': 'http://192.0.2.9/v2.0'}
        ec2 = ec2token.EC2Token(app=None, conf=dummy_conf)
        self.assertEqual('http://192.0.2.9/v2.0', ec2._conf_get('auth_uri'))
        self.assertEqual(
            'http://192.0.2.9/v3', ec2._conf_get_auth_uri())

    def test_conf_get_opts(self):
        cfg.CONF.set_default('auth_uri', 'http://192.0.2.9/v2.0/',
                             group='ec2authtoken')
        cfg.CONF.set_default('auth_uri', 'http://this-should-be-ignored/',
                             group='clients_keystone')
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('http://192.0.2.9/v2.0/', ec2._conf_get('auth_uri'))
        self.assertEqual(
            'http://192.0.2.9/v3/', ec2._conf_get_auth_uri())

    def test_conf_get_clients_keystone_opts(self):
        cfg.CONF.set_default('auth_uri', None, group='ec2authtoken')
        cfg.CONF.set_default('auth_uri', 'http://192.0.2.9',
                             group='clients_keystone')
        with mock.patch.object(keystoneauth1.discover, 'Discover') as discover:
            discover.return_value.url_for.return_value = 'http://192.0.2.9/v3/'
            ec2 = ec2token.EC2Token(app=None, conf={})
            self.assertEqual(
                'http://192.0.2.9/v3/', ec2._conf_get_auth_uri())

    def test_get_signature_param_old(self):
        params = {'Signature': 'foo'}
        dummy_req = _dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_signature(dummy_req))

    def test_get_signature_param_new(self):
        params = {'X-Amz-Signature': 'foo'}
        dummy_req = _dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_signature(dummy_req))

    def test_get_signature_header_space(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('xyz', ec2._get_signature(dummy_req))

    def test_get_signature_header_notlast(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                    'Signature=xyz,'
                    'SignedHeaders=content-type;host;x-amz-date ')}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('xyz', ec2._get_signature(dummy_req))

    def test_get_signature_header_nospace(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar,'
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz')}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('xyz', ec2._get_signature(dummy_req))

    def test_get_access_param_old(self):
        params = {'AWSAccessKeyId': 'foo'}
        dummy_req = _dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_get_access_param_new(self):
        params = {'X-Amz-Credential': 'foo/bar'}
        dummy_req = _dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_get_access_header_space(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_get_access_header_nospace(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar,'
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz')}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_get_access_header_last(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo '
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz,Credential=foo/bar')}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual('foo', ec2._get_access(dummy_req))

    def test_call_x_auth_user(self):
        req_env = {'HTTP_X_AUTH_USER': 'foo'}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertEqual('xyz', ec2.__call__(dummy_req))

    def test_call_auth_nosig(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date')}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertRaises(exception.HeatIncompleteSignatureError,
                          ec2.__call__, dummy_req)

    def test_call_auth_nouser(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo '
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz')}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertRaises(exception.HeatMissingAuthenticationTokenError,
                          ec2.__call__, dummy_req)

    def test_call_auth_noaccess(self):
        # If there's no accesskey in params or header, but there is a
        # Signature, we expect HeatMissingAuthenticationTokenError
        params = {'Signature': 'foo'}
        dummy_req = _dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertRaises(exception.HeatMissingAuthenticationTokenError,
                          ec2.__call__, dummy_req)

    def test_call_x_auth_nouser_x_auth_user(self):
        req_env = {'HTTP_X_AUTH_USER': 'foo',
                   'HTTP_AUTHORIZATION':
                   ('Authorization: foo '
                    'SignedHeaders=content-type;host;x-amz-date,'
                    'Signature=xyz')}
        dummy_req = _dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertEqual('xyz', ec2.__call__(dummy_req))

    def _stub_http_connection(
            self, headers=None, params=None, response=None,
            req_url='http://key1.example.com:5000/v3/ec2tokens',
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
        self.verify_req_headers = req_headers
        if direct_mock:
            self.mock_adapter.post.return_value = DummyHTTPResponse()
        else:
            return DummyHTTPResponse()

    def test_call_ok(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = _dummy_GET_request(environ=req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=ok_resp)
        self.assertEqual('woot', ec2.__call__(dummy_req))

        self.assertEqual('tenant', dummy_req.headers['X-Tenant-Name'])
        self.assertEqual('abcd1234', dummy_req.headers['X-Tenant-Id'])
        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_call_ok_roles(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = _dummy_GET_request(environ=req_env)

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
        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_call_err_tokenid(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v2.0/'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = _dummy_GET_request(environ=req_env)

        err_msg = "EC2 access key not found."
        err_resp = json.dumps({'error': {'message': err_msg}})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=err_resp)
        self.assertRaises(exception.HeatInvalidClientTokenIdError,
                          ec2.__call__, dummy_req)

        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_call_err_signature(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = _dummy_GET_request(environ=req_env)

        err_msg = "EC2 signature not supplied."
        err_resp = json.dumps({'error': {'message': err_msg}})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=err_resp)
        self.assertRaises(exception.HeatSignatureError,
                          ec2.__call__, dummy_req)

        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_call_err_denied(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = _dummy_GET_request(environ=req_env)

        err_resp = json.dumps({})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=err_resp)
        self.assertRaises(exception.HeatAccessDeniedError,
                          ec2.__call__, dummy_req)

        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_call_err_unauthorized(self):
        # test when Keystone returns unauthenticated error.
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v3'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = _dummy_GET_request(environ=req_env)

        msg = "The request you have made requires authentication."
        bad_resp = json.dumps({'error': {'message': msg}})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=bad_resp)
        self.assertRaises(exception.HeatAccessDeniedError,
                          ec2.__call__, dummy_req)
        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_call_err_ks_plugin_unauthorized(self):
        # test when the keystone session fails to auth while obtaining
        # an auth token
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v3'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)

        auth_str = ('Authorization: foo  Credential=foo/bar, '
                    'SignedHeaders=content-type;host;x-amz-date, '
                    'Signature=xyz')
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1',
                   'HTTP_AUTHORIZATION': auth_str}
        dummy_req = _dummy_GET_request(environ=req_env)
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response={})
        self.mock_adapter.post.side_effect = ks_exceptions.Unauthorized()
        self.assertRaises(exception.HeatAccessDeniedError,
                          ec2.__call__, dummy_req)
        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_call_ok_v2(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = _dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        self._stub_http_connection(response=ok_resp,
                                   params={'AWSAccessKeyId': 'foo'})
        self.assertEqual('woot', ec2.__call__(dummy_req))

        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_call_ok_multicloud(self):
        dummy_conf = {
            'allowed_auth_uris': [
                'http://key1.example.com:5000/v2.0',
                'http://key2.example.com:5000/v2.0'],
            'multi_cloud': True
        }
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = _dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        err_msg = "EC2 access key not found."
        err_resp = json.dumps({'error': {'message': err_msg}})

        self.mock_adapter.get_endpoint.reset()
        self.mock_adapter.get_endpoint.side_effect = [
            'http://key1.example.com:5000', 'http://key2.example.com:5000']

        # first request fails
        m_p = self._stub_http_connection(
            req_url='http://key1.example.com:5000/v3/ec2tokens',
            response=err_resp,
            params={'AWSAccessKeyId': 'foo'}, direct_mock=False)

        # second request passes
        m_p2 = self._stub_http_connection(
            req_url='http://key2.example.com:5000/v3/ec2tokens',
            response=ok_resp,
            params={'AWSAccessKeyId': 'foo'}, direct_mock=False)

        self.mock_adapter.post.side_effect = [m_p, m_p2]

        self.assertEqual('woot', ec2.__call__(dummy_req))

        self.assertEqual(2, self.mock_adapter.post.call_count)
        self.mock_adapter.post.assert_has_calls([
            mock.call('http://key1.example.com:5000/v3/ec2tokens',
                      data=self.verify_data,
                      headers=self.verify_req_headers),
            mock.call('http://key2.example.com:5000/v3/ec2tokens',
                      data=self.verify_data,
                      headers=self.verify_req_headers)
        ])

    def test_call_err_multicloud(self):
        dummy_conf = {
            'allowed_auth_uris': [
                'http://key1.example.com:5000/v2.0',
                'http://key2.example.com:5000/v2.0'],
            'multi_cloud': True
        }
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = _dummy_GET_request(params, req_env)

        err_resp1 = json.dumps({})

        err_msg2 = "EC2 access key not found."
        err_resp2 = json.dumps({'error': {'message': err_msg2}})

        # first request fails with HeatAccessDeniedError
        m_p = self._stub_http_connection(
            req_url='http://key1.example.com:5000/v2.0/ec2tokens',
            response=err_resp1,
            params={'AWSAccessKeyId': 'foo'}, direct_mock=False)

        # second request fails with HeatInvalidClientTokenIdError
        m_p2 = self._stub_http_connection(
            req_url='http://key2.example.com:5000/v2.0/ec2tokens',
            response=err_resp2,
            params={'AWSAccessKeyId': 'foo'}, direct_mock=False)

        self.mock_adapter.post.side_effect = [m_p, m_p2]
        self.mock_adapter.get_endpoint.reset()
        self.mock_adapter.get_endpoint.side_effect = [
            'http://key1.example.com:5000', 'http://key2.example.com:5000']
        # raised error matches last failure
        self.assertRaises(exception.HeatInvalidClientTokenIdError,
                          ec2.__call__, dummy_req)

        self.assertEqual(2, self.mock_adapter.post.call_count)
        self.mock_adapter.post.assert_has_calls([
            mock.call('http://key1.example.com:5000/v3/ec2tokens',
                      data=self.verify_data,
                      headers=self.verify_req_headers),
            mock.call('http://key2.example.com:5000/v3/ec2tokens',
                      data=self.verify_data,
                      headers=self.verify_req_headers)
        ])

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
        dummy_req = _dummy_GET_request(params, req_env)

        self.assertRaises(exception.HeatAccessDeniedError,
                          ec2.__call__, dummy_req)

    def test_call_badconf_no_authuri(self):
        ec2 = ec2token.EC2Token(app='woot', conf={})
        # Clear _ks_adapters to simulate no authuri
        ec2._ks_adapters = {}
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = _dummy_GET_request(params, req_env)

        ex = self.assertRaises(exception.HeatInternalFailureError,
                               ec2.__call__, dummy_req)
        self.assertEqual('Service misconfigured', str(ex))

    def test_call_ok_auth_uri_ec2authtoken(self):
        dummy_url = 'http://key1.example.com:5000/v2.0'
        cfg.CONF.set_default('auth_uri', dummy_url, group='ec2authtoken')

        ec2 = ec2token.EC2Token(app='woot', conf={})
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = _dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        self._stub_http_connection(response=ok_resp,
                                   params={'AWSAccessKeyId': 'foo'})
        self.assertEqual('woot', ec2.__call__(dummy_req))

        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_call_ok_auth_uri_ec2authtoken_long(self):
        # Prove we tolerate a url which already includes the /ec2tokens path
        dummy_url = 'http://key1.example.com:5000/v2.0/ec2tokens'
        cfg.CONF.set_default('auth_uri', dummy_url, group='ec2authtoken')

        ec2 = ec2token.EC2Token(app='woot', conf={})
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = _dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'token': {
            'project': {'name': 'tenant', 'id': 'abcd1234'}}})
        self._stub_http_connection(response=ok_resp,
                                   params={'AWSAccessKeyId': 'foo'})
        self.assertEqual('woot', ec2.__call__(dummy_req))

        self.mock_adapter.post.assert_called_once_with(
            self.verify_req_url, data=self.verify_data,
            headers=self.verify_req_headers)

    def test_filter_factory(self):
        ec2_filter = ec2token.EC2Token_filter_factory(global_conf={})

        self.assertEqual('xyz', ec2_filter('xyz').application)

    def test_filter_factory_none_app(self):
        ec2_filter = ec2token.EC2Token_filter_factory(global_conf={})

        self.assertIsNone(ec2_filter(None).application)


class Ec2TokenConfigurationTest(common.HeatTestCase):
    """Tests the Ec2Token middleware configuration options."""

    def setUp(self, **kwargs):
        super().setUp(**kwargs)
        self.mock_discover_cls = self.patchobject(keystoneauth1.discover,
                                                  'Discover')
        self.mock_discover = self.mock_discover_cls.return_value

    def tearDown(self):
        super().tearDown()
        # unregister any dynamic opts that were creating in the testing.
        cfg.CONF.reset()
        opts = keystoneauth1.loading.conf.get_plugin_conf_options('password')
        for group in cfg.CONF.keys():
            if (group.startswith("ec2authtoken") or
                    group == "keystone_authtoken"):
                cfg.CONF.unregister_opts(opts, group)

    def test_init_ks_session_fails(self):
        ec2 = ec2token.EC2Token(app='woot', conf={})
        self.assertEqual(ec2._ks_adapters, {})

    def test_init_ks_session_multicloud(self):
        load_config_file('multi_cloud_enabled.conf')
        ec2 = ec2token.EC2Token(app='woot', conf={})
        self.assertEqual(2, len(ec2._ks_adapters))
        self.assertIsNotNone(ec2._ks_adapters['alice'].session.auth)
        self.assertEqual(
            'http://key1.example.com:5000',
            ec2._ks_adapters['alice'].get_endpoint())
        self.assertIsNotNone(ec2._ks_adapters['bob'].session.auth)
        self.assertEqual(
            'http://key2.example.com:5000',
            ec2._ks_adapters['bob'].get_endpoint())

    def test_init_ks_session_multicloud_missing(self):
        # The clouds defines three clouds
        # but only two configuration sections are present
        load_config_file('multi_cloud_partial.conf')
        dummy_conf = {'multi_cloud': True,
                      'clouds': ['alice', 'fred', 'bob']
                      }
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        self.assertEqual(3, len(ec2._ks_adapters))
        self.assertIsNotNone(ec2._ks_adapters['alice'].session.auth)
        self.assertEqual(
            'http://key1.example.com:5000',
            ec2._ks_adapters['alice'].get_endpoint())
        self.assertIsNotNone(ec2._ks_adapters['bob'].session.auth)
        self.assertEqual(
            'http://key2.example.com:5000',
            ec2._ks_adapters['bob'].get_endpoint())
        self.assertIsNone(ec2._ks_adapters['fred'].session.auth)

    def test_init_ks_session_allowed_auth_uris_in_conf(self):
        load_config_file('multi_cloud_auth_uris.conf')
        ec2 = ec2token.EC2Token(app='woot', conf={})
        self.assertEqual(2, len(ec2._ks_adapters))
        for url in [
                'http://key1.example.com:5000/v2.0',
                'http://key2.example.com:5000/v3']:
            self.assertIsInstance(ec2._ks_adapters[url].session.auth,
                                  ks_noauth.NoAuth)
            self.assertEqual(url.rsplit('/', 1)[0],
                             ec2._ks_adapters[url].get_endpoint())

    def test_init_ks_session_allowed_auth_uris_in_paste(self):
        load_config_file('ec2authtoken.conf')
        paste_conf = {
            "multi_cloud": True,
            "allowed_auth_uris": ["http://key1.example.com:5000/v2.0",
                                  "http://key2.example.com:5000/v3"]}
        ec2 = ec2token.EC2Token(app='woot', conf=paste_conf)
        self.assertSequenceEqual(
            ["http://key1.example.com:5000/v2.0",
                "http://key2.example.com:5000/v3"],
            list(ec2._ks_adapters.keys()))
        for url in [
                'http://key1.example.com:5000/v2.0',
                'http://key2.example.com:5000/v3']:
            self.assertIsInstance(ec2._ks_adapters[url].session.auth,
                                  ks_noauth.NoAuth)
            self.assertEqual(url.rsplit('/', 1)[0],
                             ec2._ks_adapters[url].get_endpoint())

    def test_init_ks_session_from_keystone_authtoken_section(self):
        load_config_file('keystone_authtoken.conf')
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIsNotNone(ec2._ks_adapters[None].session.auth)
        self.assertEqual('http://key1.example.com:5000',
                         ec2._ks_adapters[None].get_endpoint())

    def test_init_ks_session_auth_uri(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIsInstance(ec2._ks_adapters[None].session.auth,
                              ks_noauth.NoAuth)
        self.assertEqual('http://key1.example.com:5000',
                         ec2._ks_adapters[None].get_endpoint())

    def test_init_ks_session_auth_uri_trailing_slash(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIsInstance(ec2._ks_adapters[None].session.auth,
                              ks_noauth.NoAuth)
        self.assertEqual('http://key1.example.com:5000',
                         ec2._ks_adapters[None].get_endpoint())

    def test_init_ks_session_auth_uri_v2(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIsInstance(ec2._ks_adapters[None].session.auth,
                              ks_noauth.NoAuth)
        self.assertEqual('http://key1.example.com:5000',
                         ec2._ks_adapters[None].get_endpoint())

    def test_init_ks_session_auth_uri_v3(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v3'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIsInstance(ec2._ks_adapters[None].session.auth,
                              ks_noauth.NoAuth)
        self.assertEqual('http://key1.example.com:5000',
                         ec2._ks_adapters[None].get_endpoint())

    def test_init_ks_session_auth_uri_ec2tokens(self):
        dummy_conf = {'auth_uri': 'http://key1.example.com:5000/v3/ec2tokens'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIsInstance(ec2._ks_adapters[None].session.auth,
                              ks_noauth.NoAuth)
        self.assertEqual('http://key1.example.com:5000',
                         ec2._ks_adapters[None].get_endpoint())

    def test_init_ks_session_typical_standalone_config(self):
        load_config_file('typical_standalone.conf')
        self.mock_discover.url_for.return_value = \
            'http://key1.example.com:5000/v3'
        ec2 = ec2token.EC2Token(app='woot', conf={})
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIsNotNone(ec2._ks_adapters[None].session.auth)
        self.assertEqual('http://key1.example.com:5000',
                         ec2._ks_adapters[None].get_endpoint())

    def test_init_ks_session_typical_config(self):
        # The auth_uri is from the clients_keystone section
        # the auth details are in the keystone_authtoken section
        load_config_file('typical.conf')
        self.mock_discover.url_for.return_value = \
            'http://key1.example.com:5000/v3'
        ec2 = ec2token.EC2Token(app='woot', conf={})
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIsNotNone(ec2._ks_adapters[None].session.auth)
        self.assertEqual('http://key1.example.com:5000',
                         ec2._ks_adapters[None].get_endpoint())

    def test_init_ks_session_ec2authtoken_config(self):
        load_config_file('ec2authtoken.conf')
        ec2 = ec2token.EC2Token(app='woot', conf={})
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIn(None, ec2._ks_adapters)
        self.assertIsNotNone(ec2._ks_adapters[None].session.auth)
        self.assertEqual('http://key1.example.com:5000',
                         ec2._ks_adapters[None].get_endpoint())

    def test_init_ks_session_devstack_config(self):
        load_config_file('long_auth_path.conf')
        self.mock_discover.url_for.return_value = \
            'http://key1.example.com/identity/v3'
        ec2 = ec2token.EC2Token(app='woot', conf={})
        self.assertEqual(1, len(ec2._ks_adapters))
        self.assertIn(None, ec2._ks_adapters)
        self.assertIsNotNone(ec2._ks_adapters[None].session.auth)
        self.assertEqual('http://key1.example.com/identity',
                         ec2._ks_adapters[None].get_endpoint())

    def test_conf_ssl_opttions_default(self):
        cfg.CONF.set_default('auth_uri', 'https://192.0.2.9/v2.0/',
                             group='ec2authtoken')
        ec2 = ec2token.EC2Token(app=None, conf={})
        adapter = ec2._ks_adapters[None]
        self.assertTrue(adapter.session.verify)
        self.assertIsNone(adapter.session.cert)

    def test_conf_ssl_insecure(self):
        cfg.CONF.set_default('auth_uri', 'https://192.0.2.9/v2.0/',
                             group='ec2authtoken')
        cfg.CONF.set_default('insecure', True,
                             group='ec2authtoken')
        ec2 = ec2token.EC2Token(app=None, conf={})
        adapter = ec2._ks_adapters[None]
        self.assertFalse(adapter.session.verify)
        self.assertIsNone(adapter.session.cert)

    def test_conf_ssl_opttions(self):
        cfg.CONF.set_default('auth_uri', 'https://192.0.2.9/v2.0/',
                             group='ec2authtoken')
        cfg.CONF.set_default('cafile', '/home/user/cacert.pem',
                             group='ec2authtoken')
        cfg.CONF.set_default('insecure', False, group='ec2authtoken')
        cfg.CONF.set_default('certfile', '/home/user/mycert',
                             group='ec2authtoken')
        cfg.CONF.set_default('keyfile', '/home/user/mykey',
                             group='ec2authtoken')
        ec2 = ec2token.EC2Token(app=None, conf={})
        adapter = ec2._ks_adapters[None]
        self.assertEqual('/home/user/cacert.pem', adapter.session.verify)
        self.assertEqual(('/home/user/mycert', '/home/user/mykey'),
                         adapter.session.cert)

    def test_conf_ssl_insecure_paste(self):
        cfg.CONF.set_default('auth_uri', 'https://192.0.2.9/v2.0/',
                             group='ec2authtoken')
        ec2 = ec2token.EC2Token(app=None, conf={
            'insecure': 'True'
        })
        adapter = ec2._ks_adapters[None]
        self.assertFalse(adapter.session.verify)

    def test_conf_ssl_options_paste(self):
        cfg.CONF.set_default('auth_uri', 'https://192.0.2.9/v2.0/',
                             group='ec2authtoken')
        ec2 = ec2token.EC2Token(app=None, conf={
            'ca_file': '/home/user/cacert.pem',
            'cert_file': '/home/user/mycert',
            'key_file': '/home/user/mykey'
        })
        adapter = ec2._ks_adapters[None]
        self.assertEqual('/home/user/cacert.pem', adapter.session.verify)
        self.assertEqual(('/home/user/mycert', '/home/user/mykey'),
                         adapter.session.cert)


def load_config_file(file_name):
    file_path = pathlib.Path(__file__).parent / "config" / file_name
    cfg.CONF([], default_config_files=[file_path])


def _dummy_GET_request(params=None, environ=None):
    # Mangle the params dict into a query string
    params = params or {}
    environ = environ or {}
    qs = "&".join(["=".join([k, str(params[k])]) for k in params])
    environ.update({'REQUEST_METHOD': 'GET', 'QUERY_STRING': qs})
    req = wsgi.Request(environ)
    return req
