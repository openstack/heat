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

import json

from keystoneauth1 import loading as ks_loading
from oslo_log import log as logging

from heat.common import exception

LOG = logging.getLogger(__name__)


def parse_auth_credential_to_dict(cred):
    """Parse credential to dict"""
    def validate(cred):
        valid_keys = ['auth_type', 'auth']
        for k in valid_keys:
            if k not in cred:
                raise ValueError('Missing key in auth information, the '
                                 'correct format contains %s.' % valid_keys)
    try:
        _cred = json.loads(cred)
    except ValueError as e:
        LOG.error('Failed to parse credential with error: %s' % e)
        raise ValueError('Failed to parse credential, please check your '
                         'Stack Credential format.')
    validate(_cred)
    return _cred


def validate_auth_plugin(auth_plugin, keystone_session):
    """Validate if this auth_plugin is valid to use."""

    try:
        auth_plugin.get_token(keystone_session)
    except Exception as e:
        # TODO(ricolin) Add heat document link for plugin information,
        # once we generated one.
        failure_reason = ("Failed to validate auth_plugin with error %s. "
                          "Please make sure the credential you provide is "
                          "correct. Also make sure the it is a valid Keystone "
                          "auth plugin type and contain in your "
                          "environment." % e)
        raise exception.AuthorizationFailure(failure_reason=failure_reason)


def get_keystone_plugin_loader(auth, keystone_session):
    cred = parse_auth_credential_to_dict(auth)
    auth_plugin = ks_loading.get_plugin_loader(
        cred.get('auth_type')).load_from_options(
            **cred.get('auth'))
    validate_auth_plugin(auth_plugin, keystone_session)
    return auth_plugin
