#
# Copyright (C) 2012, Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Middleware for authenticating against custom backends."""

from oslo_context import context
from oslo_log import log as logging
import webob.exc

from heat.common.i18n import _
from heat.rpc import client as rpc_client

LOG = logging.getLogger(__name__)


class AuthProtocol(object):
    def __init__(self, app, conf):
        self.conf = conf
        self.app = app
        self.rpc_client = rpc_client.EngineClient()

    def __call__(self, env, start_response):
        """Handle incoming request.

        Authenticate send downstream on success. Reject request if
        we can't authenticate.
        """
        LOG.debug('Authenticating user token')
        ctx = context.get_current()
        authenticated = self.rpc_client.authenticated_to_backend(ctx)
        if authenticated:
            return self.app(env, start_response)
        else:
            return self._reject_request(env, start_response)

    def _reject_request(self, env, start_response):
        """Redirect client to auth server.

        :param env: wsgi request environment
        :param start_response: wsgi response callback
        :returns: HTTPUnauthorized http response
        """
        resp = webob.exc.HTTPUnauthorized(_("Backend authentication failed"),
                                          [])
        return resp(env, start_response)


def filter_factory(global_conf, **local_conf):
    conf = global_conf.copy()
    conf.update(local_conf)

    def auth_filter(app):
        return AuthProtocol(app, conf)
    return auth_filter
