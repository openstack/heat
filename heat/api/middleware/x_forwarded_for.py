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

x_forwarded_middleware_opts = [
    cfg.StrOpt('forward_header_name',
               default='X-Forwarded-For',
               help="The HTTP header that will be used as remote address.")
]
cfg.CONF.register_opts(x_forwarded_middleware_opts)


class XForwardedForMiddleware(wsgi.Middleware):
    """A middleware that replaces the request hostname with proxy hostname.
    """
    def __init__(self, application):
        super(XForwardedForMiddleware, self).__init__(application)

    def process_request(self, req):
        # If 'forward_header_name' header was not found, then do not
        # change the host name
        req.host = req.headers.get(cfg.CONF.forward_header_name, req.host)
