# -*- encoding: utf-8 -*-
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo.config import cfg

from heat.common import wsgi

ssl_middleware_opts = [
    cfg.StrOpt('secure_proxy_ssl_header',
               default='X-Forwarded-Proto',
               help="The HTTP Header that will be used to determine which "
                    "the original request protocol scheme was, even if it was "
                    "removed by an SSL terminator proxy.")
]
cfg.CONF.register_opts(ssl_middleware_opts)


class SSLMiddleware(wsgi.Middleware):
    """A middleware that replaces the request wsgi.url_scheme environment
    variable with the value of HTTP header configured in
    secure_proxy_ssl_header if exists in the incoming request.
    This is useful if the server is behind a SSL termination proxy.
    """
    def __init__(self, application):
        super(SSLMiddleware, self).__init__(application)
        self.secure_proxy_ssl_header = 'HTTP_{0}'.format(
            cfg.CONF.secure_proxy_ssl_header.upper().replace('-', '_'))

    def process_request(self, req):
        req.environ['wsgi.url_scheme'] = req.environ.get(
            self.secure_proxy_ssl_header, req.environ['wsgi.url_scheme'])
