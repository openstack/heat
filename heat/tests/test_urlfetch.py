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

import StringIO
import urllib2

from heat.common import urlfetch
from heat.tests.common import HeatTestCase


class UrlFetchTest(HeatTestCase):
    def setUp(self):
        super(UrlFetchTest, self).setUp()
        self.m.StubOutWithMock(urllib2, 'urlopen')

    def test_file_scheme(self):
        self.m.ReplayAll()
        self.assertRaises(IOError, urlfetch.get, 'file:///etc/profile')
        self.m.VerifyAll()

    def test_http_scheme(self):
        url = 'http://example.com/template'
        data = '{ "foo": "bar" }'

        urllib2.urlopen(url).AndReturn(StringIO.StringIO(data))
        self.m.ReplayAll()

        self.assertEqual(urlfetch.get(url), data)
        self.m.VerifyAll()

    def test_https_scheme(self):
        url = 'https://example.com/template'
        data = '{ "foo": "bar" }'

        urllib2.urlopen(url).AndReturn(StringIO.StringIO(data))
        self.m.ReplayAll()

        self.assertEqual(urlfetch.get(url), data)
        self.m.VerifyAll()

    def test_http_error(self):
        url = 'http://example.com/template'

        urllib2.urlopen(url).AndRaise(urllib2.URLError('fubar'))
        self.m.ReplayAll()

        self.assertRaises(IOError, urlfetch.get, url)
        self.m.VerifyAll()

    def test_garbage(self):
        self.m.ReplayAll()
        self.assertRaises(IOError, urlfetch.get, 'wibble')
        self.m.VerifyAll()
