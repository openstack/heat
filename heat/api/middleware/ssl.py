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

from debtcollector import removals
from oslo_config import cfg
from oslo_middleware import ssl

ssl_middleware_opts = [
    cfg.StrOpt('secure_proxy_ssl_header',
               default='X-Forwarded-Proto',
               deprecated_group='DEFAULT',
               help="The HTTP Header that will be used to determine which "
                    "the original request protocol scheme was, even if it was "
                    "removed by an SSL terminator proxy.")
]


removals.removed_module(__name__,
                        "oslo_middleware.http_proxy_to_wsgi")


class SSLMiddleware(ssl.SSLMiddleware):

    def __init__(self, application, *args, **kwargs):
        # NOTE(cbrandily): calling super(ssl.SSLMiddleware, self).__init__
        # allows to define our opt (including a deprecation).
        super(ssl.SSLMiddleware, self).__init__(application, *args, **kwargs)
        self.oslo_conf.register_opts(
            ssl_middleware_opts, group='oslo_middleware')


def list_opts():
    yield None, ssl_middleware_opts
