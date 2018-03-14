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

from oslo_config import cfg
import requests
from requests import exceptions
import six

from heat.common import urlfetch
from heat.tests import common


class Response(object):
    def __init__(self, buf=''):
        self.buf = buf

    def iter_content(self, chunk_size=1):
        while self.buf:
            yield self.buf[:chunk_size]
            self.buf = self.buf[chunk_size:]

    def raise_for_status(self):
        pass


class UrlFetchTest(common.HeatTestCase):

    def test_file_scheme_default_behaviour(self):
        self.assertRaises(urlfetch.URLFetchError,
                          urlfetch.get, 'file:///etc/profile')

    def test_file_scheme_supported(self):
        data = '{ "foo": "bar" }'
        url = 'file:///etc/profile'
        mock_open = self.patchobject(six.moves.urllib.request, 'urlopen')
        mock_open.return_value = six.moves.cStringIO(data)
        self.assertEqual(data, urlfetch.get(url, allowed_schemes=['file']))
        mock_open.assert_called_once_with(url)

    def test_file_scheme_failure(self):
        url = 'file:///etc/profile'
        mock_open = self.patchobject(six.moves.urllib.request, 'urlopen')
        mock_open.side_effect = six.moves.urllib.error.URLError('oops')
        self.assertRaises(urlfetch.URLFetchError,
                          urlfetch.get, url, allowed_schemes=['file'])
        mock_open.assert_called_once_with(url)

    def test_http_scheme(self):
        url = 'http://example.com/template'
        data = b'{ "foo": "bar" }'
        response = Response(data)
        mock_get = self.patchobject(requests, 'get')
        mock_get.return_value = response
        self.assertEqual(data, urlfetch.get(url))
        mock_get.assert_called_once_with(url, stream=True)

    def test_https_scheme(self):
        url = 'https://example.com/template'
        data = b'{ "foo": "bar" }'
        response = Response(data)
        mock_get = self.patchobject(requests, 'get')
        mock_get.return_value = response
        self.assertEqual(data, urlfetch.get(url))
        mock_get.assert_called_once_with(url, stream=True)

    def test_http_error(self):
        url = 'http://example.com/template'
        mock_get = self.patchobject(requests, 'get')
        mock_get.side_effect = exceptions.HTTPError()
        self.assertRaises(urlfetch.URLFetchError, urlfetch.get, url)
        mock_get.assert_called_once_with(url, stream=True)

    def test_non_exist_url(self):
        url = 'http://non-exist.com/template'
        mock_get = self.patchobject(requests, 'get')
        mock_get.side_effect = exceptions.Timeout()
        self.assertRaises(urlfetch.URLFetchError, urlfetch.get, url)
        mock_get.assert_called_once_with(url, stream=True)

    def test_garbage(self):
        self.assertRaises(urlfetch.URLFetchError, urlfetch.get, 'wibble')

    def test_max_fetch_size_okay(self):
        url = 'http://example.com/template'
        data = b'{ "foo": "bar" }'
        response = Response(data)
        cfg.CONF.set_override('max_template_size', 500)
        mock_get = self.patchobject(requests, 'get')
        mock_get.return_value = response
        urlfetch.get(url)
        mock_get.assert_called_once_with(url, stream=True)

    def test_max_fetch_size_error(self):
        url = 'http://example.com/template'
        data = b'{ "foo": "bar" }'
        response = Response(data)
        cfg.CONF.set_override('max_template_size', 5)
        mock_get = self.patchobject(requests, 'get')
        mock_get.return_value = response
        exception = self.assertRaises(urlfetch.URLFetchError,
                                      urlfetch.get, url)
        self.assertIn("Template exceeds", six.text_type(exception))
        mock_get.assert_called_once_with(url, stream=True)
