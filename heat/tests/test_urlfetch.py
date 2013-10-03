# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import requests
from requests import exceptions
import urllib2
import cStringIO

from oslo.config import cfg

from heat.common import urlfetch
from heat.tests.common import HeatTestCase


class Response:
    def __init__(self, buf=''):
        self._text = buf

    @property
    def text(self):
        return self._text

    def raise_for_status(self):
        pass


class UrlFetchTest(HeatTestCase):
    def setUp(self):
        super(UrlFetchTest, self).setUp()
        self.m.StubOutWithMock(requests, 'get')

    def test_file_scheme_default_behaviour(self):
        self.m.ReplayAll()
        self.assertRaises(IOError, urlfetch.get, 'file:///etc/profile')
        self.m.VerifyAll()

    def test_file_scheme_supported(self):
        data = '{ "foo": "bar" }'
        url = 'file:///etc/profile'

        self.m.StubOutWithMock(urllib2, 'urlopen')
        urllib2.urlopen(url).AndReturn(cStringIO.StringIO(data))
        self.m.ReplayAll()

        self.assertEqual(data, urlfetch.get(url, allowed_schemes=['file']))
        self.m.VerifyAll()

    def test_file_scheme_failure(self):
        url = 'file:///etc/profile'

        self.m.StubOutWithMock(urllib2, 'urlopen')
        urllib2.urlopen(url).AndRaise(urllib2.URLError('oops'))
        self.m.ReplayAll()

        self.assertRaises(IOError, urlfetch.get, url, allowed_schemes=['file'])
        self.m.VerifyAll()

    def test_http_scheme(self):
        url = 'http://example.com/template'
        data = '{ "foo": "bar" }'
        response = Response(data)
        response.raw = self.m.CreateMockAnything()
        max_template_fetch_size = 524289
        self.m.StubOutWithMock(response.raw, 'read')
        response.raw.read(max_template_fetch_size).\
            AndReturn('{ "foo": "bar" }')

        requests.get(url, stream=True).AndReturn(response)
        self.m.ReplayAll()

        self.assertEqual(urlfetch.get(url), data)
        self.m.VerifyAll()

    def test_https_scheme(self):
        url = 'https://example.com/template'
        data = '{ "foo": "bar" }'
        response = Response(data)
        response.raw = self.m.CreateMockAnything()
        max_template_fetch_size = 524289
        self.m.StubOutWithMock(response.raw, 'read')
        response.raw.read(max_template_fetch_size).\
            AndReturn('{ "foo": "bar" }')

        requests.get(url, stream=True).AndReturn(response)
        self.m.ReplayAll()

        self.assertEqual(urlfetch.get(url), data)
        self.m.VerifyAll()

    def test_http_error(self):
        url = 'http://example.com/template'

        requests.get(url, stream=True).AndRaise(exceptions.HTTPError())
        self.m.ReplayAll()

        self.assertRaises(IOError, urlfetch.get, url)
        self.m.VerifyAll()

    def test_non_exist_url(self):
        url = 'http://non-exist.com/template'

        requests.get(url, stream=True).AndRaise(exceptions.Timeout())
        self.m.ReplayAll()

        self.assertRaises(IOError, urlfetch.get, url)
        self.m.VerifyAll()

    def test_garbage(self):
        self.m.ReplayAll()
        self.assertRaises(IOError, urlfetch.get, 'wibble')
        self.m.VerifyAll()

    def test_max_fetch_size(self):
        url = 'http://example.com/template'
        data = '{ "foo": "bar" }'
        response = Response(data)
        response.raw = self.m.CreateMockAnything()
        cfg.CONF.set_override('max_template_size', 5)
        max_template_fetch_size = cfg.CONF.max_template_size + 1
        self.m.StubOutWithMock(response.raw, 'read')
        response.raw.read(max_template_fetch_size).AndReturn('{ "foo')

        requests.get(url, stream=True).AndReturn(response)
        self.m.ReplayAll()

        exception = self.assertRaises(IOError, urlfetch.get, url)
        self.assertTrue("Template exceeds" in str(exception))
        self.m.VerifyAll()
