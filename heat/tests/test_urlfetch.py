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

    def test_file_scheme(self):
        self.m.ReplayAll()
        self.assertRaises(IOError, urlfetch.get, 'file:///etc/profile')
        self.m.VerifyAll()

    def test_http_scheme(self):
        url = 'http://example.com/template'
        data = '{ "foo": "bar" }'

        requests.get(url).AndReturn(Response(data))
        self.m.ReplayAll()

        self.assertEqual(urlfetch.get(url), data)
        self.m.VerifyAll()

    def test_https_scheme(self):
        url = 'https://example.com/template'
        data = '{ "foo": "bar" }'

        requests.get(url).AndReturn(Response(data))
        self.m.ReplayAll()

        self.assertEqual(urlfetch.get(url), data)
        self.m.VerifyAll()

    def test_http_error(self):
        url = 'http://example.com/template'

        requests.get(url).AndRaise(exceptions.HTTPError())
        self.m.ReplayAll()

        self.assertRaises(IOError, urlfetch.get, url)
        self.m.VerifyAll()

    def test_non_exist_url(self):
        url = 'http://non-exist.com/template'

        requests.get(url).AndRaise(exceptions.Timeout())
        self.m.ReplayAll()

        self.assertRaises(IOError, urlfetch.get, url)
        self.m.VerifyAll()

    def test_garbage(self):
        self.m.ReplayAll()
        self.assertRaises(IOError, urlfetch.get, 'wibble')
        self.m.VerifyAll()
