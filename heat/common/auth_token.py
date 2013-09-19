# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2012 OpenStack Foundation
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

import logging
from keystoneclient.middleware import auth_token

LOG = logging.getLogger(__name__)


class AuthProtocol(auth_token.AuthProtocol):
    """
    Subclass of keystoneclient auth_token middleware which also
    sets the 'X-Auth-Url' header to the value specified in the config.
    """
    def _build_user_headers(self, token_info):
        rval = super(AuthProtocol, self)._build_user_headers(token_info)
        rval['X-Auth-Url'] = self.auth_uri
        return rval


def filter_factory(global_conf, **local_conf):
    """Returns a WSGI filter app for use with paste.deploy."""
    conf = global_conf.copy()
    conf.update(local_conf)

    def auth_filter(app):
        return AuthProtocol(app, conf)
    return auth_filter


def app_factory(global_conf, **local_conf):
    conf = global_conf.copy()
    conf.update(local_conf)
    return AuthProtocol(None, conf)
