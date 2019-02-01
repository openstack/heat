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
from keystoneauth1 import session
import mock
import six

from heat.common import auth_plugin
from heat.common import config
from heat.common import exception
from heat.common import policy
from heat.tests import common


class TestAuthPlugin(common.HeatTestCase):

    def setUp(self):
        self.credential = (
            '{"auth_type": "v3applicationcredential", '
            '"auth": {"auth_url": "http://192.168.1.101/identity/v3", '
            '"application_credential_id": '
            '"9dfa187e5a354484bf9c49a2b674333a", '
            '"application_credential_secret": "sec"} }')
        self.m_plugin = mock.Mock()
        self.m_loader = self.patchobject(
            ks_loading, 'get_plugin_loader', return_value=self.m_plugin)
        self.patchobject(policy.Enforcer, 'check_is_admin')
        self.secret_id = '0eca0615-c330-41aa-b0cb-a2493a770409'
        self.session = session.Session(
            **config.get_ssl_options('keystone'))
        super(TestAuthPlugin, self).setUp()

    def _get_keystone_plugin_loader(self):
        auth_plugin.get_keystone_plugin_loader(self.credential, self.session)

        self.m_plugin.load_from_options.assert_called_once_with(
            application_credential_id='9dfa187e5a354484bf9c49a2b674333a',
            application_credential_secret='sec',
            auth_url='http://192.168.1.101/identity/v3')
        self.m_loader.assert_called_once_with('v3applicationcredential')

    def test_get_keystone_plugin_loader(self):
        self._get_keystone_plugin_loader()
        # called in validate_auth_plugin
        self.assertEqual(
            1, self.m_plugin.load_from_options().get_token.call_count)

    def test_get_keystone_plugin_loader_with_no_AuthZ(self):
        self.m_plugin.load_from_options().get_token.side_effect = Exception
        self.assertRaises(
            exception.AuthorizationFailure, self._get_keystone_plugin_loader)
        self.assertEqual(
            1, self.m_plugin.load_from_options().get_token.call_count)

    def test_parse_auth_credential_to_dict(self):
        cred_dict = json.loads(self.credential)
        self.assertEqual(
            cred_dict, auth_plugin.parse_auth_credential_to_dict(
                self.credential))

    def test_parse_auth_credential_to_dict_with_value_error(self):
        credential = (
            '{"auth": {"auth_url": "http://192.168.1.101/identity/v3", '
            '"application_credential_id": '
            '"9dfa187e5a354484bf9c49a2b674333a", '
            '"application_credential_secret": "sec"} }')
        error = self.assertRaises(
            ValueError, auth_plugin.parse_auth_credential_to_dict, credential)
        self.assertEqual("Missing key in auth information, the correct "
                         "format contains [\'auth_type\', \'auth\'].",
                         six.text_type(error))

    def test_parse_auth_credential_to_dict_with_json_error(self):
        credential = (
            "{'auth_type': v3applicationcredential, "
            "'auth': {'auth_url': 'http://192.168.1.101/identity/v3', "
            "'application_credential_id': "
            "'9dfa187e5a354484bf9c49a2b674333a', "
            "'application_credential_secret': 'sec'} }")
        error = self.assertRaises(
            ValueError, auth_plugin.parse_auth_credential_to_dict, credential)
        error_msg = ('Failed to parse credential, please check your Stack '
                     'Credential format.')
        self.assertEqual(error_msg, six.text_type(error))
