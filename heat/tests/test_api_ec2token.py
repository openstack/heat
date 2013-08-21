# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


from heat.tests.common import HeatTestCase

import requests
import json
from oslo.config import cfg

from heat.api.aws import exception
from heat.common.wsgi import Request
from heat.api.aws import ec2token


class Ec2TokenTest(HeatTestCase):
    '''
    Tests the Ec2Token middleware
    '''
    def _dummy_GET_request(self, params={}, environ={}):
        # Mangle the params dict into a query string
        qs = "&".join(["=".join([k, str(params[k])]) for k in params])
        environ.update({'REQUEST_METHOD': 'GET', 'QUERY_STRING': qs})
        req = Request(environ)
        return req

    def test_conf_get_paste(self):
        dummy_conf = {'auth_uri': 'http://192.0.2.9/v2.0'}
        ec2 = ec2token.EC2Token(app=None, conf=dummy_conf)
        self.assertEqual(ec2._conf_get('auth_uri'), 'http://192.0.2.9/v2.0')
        self.assertEqual(ec2._conf_get_keystone_ec2_uri(),
                         'http://192.0.2.9/v2.0/ec2tokens')

    def test_conf_get_opts(self):
        cfg.CONF.set_default('auth_uri', 'http://192.0.2.9/v2.0/',
                             group='ec2authtoken')
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._conf_get('auth_uri'), 'http://192.0.2.9/v2.0/')
        self.assertEqual(ec2._conf_get_keystone_ec2_uri(),
                         'http://192.0.2.9/v2.0/ec2tokens')

    def test_get_signature_param_old(self):
        params = {'Signature': 'foo'}
        dummy_req = self._dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_signature(dummy_req), 'foo')

    def test_get_signature_param_new(self):
        params = {'X-Amz-Signature': 'foo'}
        dummy_req = self._dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_signature(dummy_req), 'foo')

    def test_get_signature_header_space(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                   'SignedHeaders=content-type;host;x-amz-date, '
                   'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_signature(dummy_req), 'xyz')

    def test_get_signature_header_notlast(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                    'Signature=xyz,'
                    'SignedHeaders=content-type;host;x-amz-date ')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_signature(dummy_req), 'xyz')

    def test_get_signature_header_nospace(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar,'
                   'SignedHeaders=content-type;host;x-amz-date,'
                   'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_signature(dummy_req), 'xyz')

    def test_get_access_param_old(self):
        params = {'AWSAccessKeyId': 'foo'}
        dummy_req = self._dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_access(dummy_req), 'foo')

    def test_get_access_param_new(self):
        params = {'X-Amz-Credential': 'foo/bar'}
        dummy_req = self._dummy_GET_request(params)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_access(dummy_req), 'foo')

    def test_get_access_header_space(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar, '
                   'SignedHeaders=content-type;host;x-amz-date, '
                   'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_access(dummy_req), 'foo')

    def test_get_access_header_nospace(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo  Credential=foo/bar,'
                   'SignedHeaders=content-type;host;x-amz-date,'
                   'Signature=xyz')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_access(dummy_req), 'foo')

    def test_get_access_header_last(self):
        req_env = {'HTTP_AUTHORIZATION':
                   ('Authorization: foo '
                   'SignedHeaders=content-type;host;x-amz-date,'
                   'Signature=xyz,Credential=foo/bar')}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app=None, conf={})
        self.assertEqual(ec2._get_access(dummy_req), 'foo')

    def test_call_x_auth_user(self):
        req_env = {'HTTP_X_AUTH_USER': 'foo'}
        dummy_req = self._dummy_GET_request(environ=req_env)
        ec2 = ec2token.EC2Token(app='xyz', conf={})
        self.assertEqual(ec2.__call__(dummy_req), 'xyz')

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
        self.assertEqual(ec2.__call__(dummy_req), 'xyz')

    def _stub_http_connection(self, headers={}, params={}, response=None):

        class DummyHTTPResponse(object):
            text = response

            def json(self):
                return json.loads(self.text)

        self.m.StubOutWithMock(requests, 'post')
        body_hash = ('e3b0c44298fc1c149afbf4c8996fb9'
                     '2427ae41e4649b934ca495991b7852b855')
        req_creds = json.dumps({"ec2Credentials":
                                {"access": "foo",
                                 "headers": headers,
                                 "host": "heat:8000",
                                 "verb": "GET",
                                 "params": params,
                                 "signature": "xyz",
                                 "path": "/v1",
                                 "body_hash": body_hash}})
        req_headers = {'Content-Type': 'application/json'}
        req_url = 'http://123:5000/v2.0/ec2tokens'
        requests.post(req_url, data=req_creds,
                      headers=req_headers).AndReturn(DummyHTTPResponse())

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

        ok_resp = json.dumps({'access': {'token': {
            'id': 123,
            'tenant': {'name': 'tenant', 'id': 'abcd1234'}}}})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=ok_resp)
        self.m.ReplayAll()
        self.assertEqual(ec2.__call__(dummy_req), 'woot')

        self.assertEqual('tenant', dummy_req.headers['X-Tenant-Name'])
        self.assertEqual('abcd1234', dummy_req.headers['X-Tenant-Id'])
        self.m.VerifyAll()

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

        ok_resp = json.dumps({'access': {
            'token': {
                'id': 123,
                'tenant': {'name': 'tenant', 'id': 'abcd1234'}
            },
            'metadata': {'roles': ['aa', 'bb', 'cc']}}})
        self._stub_http_connection(headers={'Authorization': auth_str},
                                   response=ok_resp)
        self.m.ReplayAll()
        self.assertEqual(ec2.__call__(dummy_req), 'woot')

        self.assertEqual('aa,bb,cc', dummy_req.headers['X-Roles'])
        self.m.VerifyAll()

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
        self.m.ReplayAll()
        self.assertRaises(exception.HeatInvalidClientTokenIdError,
                          ec2.__call__, dummy_req)

        self.m.VerifyAll()

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
        self.m.ReplayAll()
        self.assertRaises(exception.HeatSignatureError,
                          ec2.__call__, dummy_req)

        self.m.VerifyAll()

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
        self.m.ReplayAll()
        self.assertRaises(exception.HeatAccessDeniedError,
                          ec2.__call__, dummy_req)

        self.m.VerifyAll()

    def test_call_ok_v2(self):
        dummy_conf = {'auth_uri': 'http://123:5000/v2.0'}
        ec2 = ec2token.EC2Token(app='woot', conf=dummy_conf)
        params = {'AWSAccessKeyId': 'foo', 'Signature': 'xyz'}
        req_env = {'SERVER_NAME': 'heat',
                   'SERVER_PORT': '8000',
                   'PATH_INFO': '/v1'}
        dummy_req = self._dummy_GET_request(params, req_env)

        ok_resp = json.dumps({'access': {'metadata': {}, 'token': {
            'id': 123,
            'tenant': {'name': 'tenant', 'id': 'abcd1234'}}}})
        self._stub_http_connection(response=ok_resp,
                                   params={'AWSAccessKeyId': 'foo'})
        self.m.ReplayAll()
        self.assertEqual(ec2.__call__(dummy_req), 'woot')

        self.m.VerifyAll()
