# -*- encoding: utf-8 -*-
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

import webob

from heat.api.middleware import x_forwarded_for
from oslo.config import cfg

from heat.tests.common import HeatTestCase


class XForwardedForMiddlewareTest(HeatTestCase):

    def test_default_header_found(self):
        headers = {'X-Forwarded-For': 'www.test.com'}
        middleware = x_forwarded_for.XForwardedForMiddleware(None)
        request = webob.Request.blank('/stacks', headers=headers)
        self.assertIsNone(middleware.process_request(request))
        self.assertEqual('www.test.com', request.host)

    def test_custom_header_found(self):
        cfg.CONF.set_override('forward_header_name', 'X-Fwd-Custom')
        headers = {'X-Fwd-Custom': 'www.test.com'}
        middleware = x_forwarded_for.XForwardedForMiddleware(None)
        request = webob.Request.blank('/stacks', headers=headers)
        self.assertIsNone(middleware.process_request(request))
        self.assertEqual('www.test.com', request.host)

    def test_default_header_not_found(self):
        headers = {}
        middleware = x_forwarded_for.XForwardedForMiddleware(None)
        request = webob.Request.blank('/stacks', headers=headers)
        self.assertIsNone(middleware.process_request(request))
        self.assertEqual('localhost:80', request.host)

    def test_custom_header_not_found(self):
        cfg.CONF.set_override('forward_header_name', 'X-Fwd-Custom')
        headers = {}
        middleware = x_forwarded_for.XForwardedForMiddleware(None)
        request = webob.Request.blank('/stacks', headers=headers)
        self.assertIsNone(middleware.process_request(request))
        self.assertEqual('localhost:80', request.host)
