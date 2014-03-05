
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

import webob

from heat.api.middleware import ssl
from oslo.config import cfg

from heat.tests.common import HeatTestCase


class SSLMiddlewareTest(HeatTestCase):
    scenarios = [('with_forwarded_proto_default_header',
                  dict(forwarded_protocol='https',
                       secure_proxy_ssl_header=None,
                       headers={'X-Forwarded-Proto': 'https'})),
                 ('with_forwarded_proto_non_default_header',
                  dict(forwarded_protocol='http',
                       secure_proxy_ssl_header='X-My-Forwarded-Proto',
                       headers={})),
                 ('without_forwarded_proto',
                  dict(forwarded_protocol='http',
                       secure_proxy_ssl_header=None,
                       headers={}))]

    def test_ssl_middleware(self):
        if self.secure_proxy_ssl_header:
            cfg.CONF.set_override('secure_proxy_ssl_header',
                                  self.secure_proxy_ssl_header)

        middleware = ssl.SSLMiddleware(None)
        request = webob.Request.blank('/stacks', headers=self.headers)
        self.assertIsNone(middleware.process_request(request))
        self.assertEqual(self.forwarded_protocol,
                         request.environ['wsgi.url_scheme'])
