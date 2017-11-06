#
# Copyright (C) 2016, Red Hat, Inc.
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

"""Middleware that accepts any authentication."""

import json
import os

from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class NoAuthProtocol(object):
    def __init__(self, app, conf):
        self.conf = conf
        self.app = app
        self._token_info = {}
        response_file = cfg.CONF.noauth.token_response
        if os.path.exists(response_file):
            with open(response_file) as f:
                self._token_info = json.loads(f.read())

    def __call__(self, env, start_response):
        """Handle incoming request.

        Authenticate send downstream on success. Reject request if
        we can't authenticate.
        """
        LOG.debug('Authenticating user token')
        env.update(self._build_user_headers(env))
        return self.app(env, start_response)

    def _build_user_headers(self, env):
        """Build headers that represent authenticated user from auth token."""

        # token = env.get('X-Auth-Token', '')
        # user_id, _sep, project_id = token.partition(':')
        # project_id = project_id or user_id

        username = env.get('HTTP_X_AUTH_USER', 'admin')
        project = env.get('HTTP_X_AUTH_PROJECT', 'admin')

        headers = {
            'HTTP_X_IDENTITY_STATUS': 'Confirmed',
            'HTTP_X_PROJECT_ID': project,
            'HTTP_X_PROJECT_NAME': project,
            'HTTP_X_USER_ID': username,
            'HTTP_X_USER_NAME': username,
            'HTTP_X_ROLES': 'admin',
            'HTTP_X_SERVICE_CATALOG': {},
            'HTTP_X_AUTH_USER': username,
            'HTTP_X_AUTH_KEY': 'unset',
            'HTTP_X_AUTH_URL': 'url',
        }
        if self._token_info:
            headers['keystone.token_info'] = self._token_info

        return headers


def filter_factory(global_conf, **local_conf):
    conf = global_conf.copy()
    conf.update(local_conf)

    def auth_filter(app):
        return NoAuthProtocol(app, conf)
    return auth_filter
