# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import mock
import mox
from oslo.config import cfg

from heat.common import exception
from heat.openstack.common import importutils
from heat.tests.common import HeatTestCase
from heat.tests import utils

from .. import client as heat_keystoneclient  # noqa


class KeystoneClientTest(HeatTestCase):
    """Test cases for heat.common.heat_keystoneclient."""

    def setUp(self):
        super(KeystoneClientTest, self).setUp()
        self.ctx = utils.dummy_context()

        # Import auth_token to have keystone_authtoken settings setup.
        importutils.import_module('keystoneclient.middleware.auth_token')

        dummy_url = 'http://server.test:5000/v2.0'
        cfg.CONF.set_override('auth_uri', dummy_url,
                              group='keystone_authtoken')
        cfg.CONF.set_override('admin_user', 'heat',
                              group='keystone_authtoken')
        cfg.CONF.set_override('admin_password', 'verybadpass',
                              group='keystone_authtoken')
        cfg.CONF.set_override('admin_tenant_name', 'service',
                              group='keystone_authtoken')
        self.addCleanup(self.m.VerifyAll)

    def _stubs_v2(self, method='token', auth_ok=True, trust_scoped=True,
                  user_id='trustor_user_id'):
        self.mock_ks_client = self.m.CreateMock(heat_keystoneclient.kc.Client)
        self.m.StubOutWithMock(heat_keystoneclient.kc, "Client")
        if method == 'token':
            heat_keystoneclient.kc.Client(
                auth_url=mox.IgnoreArg(),
                tenant_name='test_tenant',
                token='abcd1234',
                cacert=None,
                cert=None,
                insecure=False,
                key=None).AndReturn(self.mock_ks_client)
            self.mock_ks_client.authenticate().AndReturn(auth_ok)
        elif method == 'password':
            heat_keystoneclient.kc.Client(
                auth_url=mox.IgnoreArg(),
                tenant_name='test_tenant',
                tenant_id='test_tenant_id',
                username='test_username',
                password='password',
                cacert=None,
                cert=None,
                insecure=False,
                key=None).AndReturn(self.mock_ks_client)
            self.mock_ks_client.authenticate().AndReturn(auth_ok)
        if method == 'trust':
            heat_keystoneclient.kc.Client(
                auth_url='http://server.test:5000/v2.0',
                password='verybadpass',
                tenant_name='service',
                username='heat',
                cacert=None,
                cert=None,
                insecure=False,
                key=None).AndReturn(self.mock_ks_client)
            self.mock_ks_client.authenticate(trust_id='atrust123',
                                             tenant_id='test_tenant_id'
                                             ).AndReturn(auth_ok)
            self.mock_ks_client.auth_ref = self.m.CreateMockAnything()
            self.mock_ks_client.auth_ref.trust_scoped = trust_scoped
            self.mock_ks_client.auth_ref.auth_token = 'atrusttoken'
            self.mock_ks_client.auth_ref.user_id = user_id

    def test_username_length(self):
        """Test that user names >64 characters are properly truncated."""

        self._stubs_v2()

        # a >64 character user name and the expected version
        long_user_name = 'U' * 64 + 'S'
        good_user_name = long_user_name[-64:]
        # mock keystone client user functions
        self.mock_ks_client.users = self.m.CreateMockAnything()
        mock_user = self.m.CreateMockAnything()
        # when keystone is called, the name should have been truncated
        # to the last 64 characters of the long name
        (self.mock_ks_client.users.create(good_user_name, 'password',
                                          mox.IgnoreArg(), enabled=True,
                                          tenant_id=mox.IgnoreArg())
         .AndReturn(mock_user))
        # mock out the call to roles; will send an error log message but does
        # not raise an exception
        self.mock_ks_client.roles = self.m.CreateMockAnything()
        self.mock_ks_client.roles.list().AndReturn([])
        self.m.ReplayAll()
        # call create_stack_user with a long user name.
        # the cleanup VerifyAll should verify that though we passed
        # long_user_name, keystone was actually called with a truncated
        # user name
        self.ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        heat_ks_client.create_stack_user(long_user_name, password='password')

    def test_init_v2_password(self):
        """Test creating the client, user/password context."""

        self._stubs_v2(method='password')
        self.m.ReplayAll()

        self.ctx.auth_token = None
        self.ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        self.assertIsNotNone(heat_ks_client.client)

    def test_init_v2_bad_nocreds(self):
        """Test creating the client without trusts, no credentials."""

        self.ctx.auth_token = None
        self.ctx.username = None
        self.ctx.password = None
        self.ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        self.assertRaises(exception.AuthorizationFailure,
                          heat_ks_client._v2_client_init)

    def test_trust_init(self):
        """Test consuming a trust when initializing."""

        self._stubs_v2(method='trust')
        self.m.ReplayAll()

        self.ctx.username = None
        self.ctx.password = None
        self.ctx.auth_token = None
        self.ctx.trust_id = 'atrust123'
        self.ctx.trustor_user_id = 'trustor_user_id'
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        client = heat_ks_client.client
        self.assertIsNotNone(client)

    def test_trust_init_fail(self):
        """Test consuming a trust when initializing, error scoping."""

        self._stubs_v2(method='trust', trust_scoped=False)
        self.m.ReplayAll()

        self.ctx.username = None
        self.ctx.password = None
        self.ctx.auth_token = None
        self.ctx.trust_id = 'atrust123'
        self.ctx.trustor_user_id = 'trustor_user_id'
        self.assertRaises(exception.AuthorizationFailure,
                          heat_keystoneclient.KeystoneClientV2, self.ctx)

    def test_trust_init_fail_impersonation(self):
        """Test consuming a trust when initializing, impersonation error."""

        self._stubs_v2(method='trust', user_id='wrong_user_id')
        self.m.ReplayAll()

        self.ctx.username = 'heat'
        self.ctx.password = None
        self.ctx.auth_token = None
        self.ctx.trust_id = 'atrust123'
        self.ctx.trustor_user_id = 'trustor_user_id'
        self.assertRaises(exception.AuthorizationFailure,
                          heat_keystoneclient.KeystoneClientV2, self.ctx)

    def test_trust_init_pw(self):
        """Test trust_id is takes precedence username/password specified."""

        self._stubs_v2(method='trust')
        self.m.ReplayAll()

        self.ctx.auth_token = None
        self.ctx.trust_id = 'atrust123'
        self.ctx.trustor_user_id = 'trustor_user_id'
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        self.assertIsNotNone(heat_ks_client._client)

    def test_trust_init_token(self):
        """Test trust_id takes precedence when token specified."""

        self._stubs_v2(method='trust')
        self.m.ReplayAll()

        self.ctx.username = None
        self.ctx.password = None
        self.ctx.trust_id = 'atrust123'
        self.ctx.trustor_user_id = 'trustor_user_id'
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        self.assertIsNotNone(heat_ks_client._client)

    # ##################### #
    # V3 Compatible Methods #
    # ##################### #

    def test_create_stack_domain_user_pass_through_to_create_stack_user(self):
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        mock_create_stack_user = mock.Mock()
        heat_ks_client.create_stack_user = mock_create_stack_user
        heat_ks_client.create_stack_domain_user('username', 'project_id',
                                                'password')
        mock_create_stack_user.assert_called_once_with('username', 'password')

    def test_delete_stack_domain_user_pass_through_to_delete_stack_user(self):
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        mock_delete_stack_user = mock.Mock()
        heat_ks_client.delete_stack_user = mock_delete_stack_user
        heat_ks_client.delete_stack_domain_user('user_id', 'project_id')
        mock_delete_stack_user.assert_called_once_with('user_id')

    def test_create_stack_domain_project(self):
        tenant_id = self.ctx.tenant_id
        ks = heat_keystoneclient.KeystoneClientV2(self.ctx)
        self.assertEqual(tenant_id, ks.create_stack_domain_project('fakeid'))

    def test_delete_stack_domain_project(self):
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        self.assertIsNone(heat_ks_client.delete_stack_domain_project('fakeid'))

    # ###################### #
    # V3 Unsupported Methods #
    # ###################### #

    def test_create_trust_context(self):
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        self.assertRaises(exception.NotSupported,
                          heat_ks_client.create_trust_context)

    def test_delete_trust(self):
        heat_ks_client = heat_keystoneclient.KeystoneClientV2(self.ctx)
        self.assertRaises(exception.NotSupported,
                          heat_ks_client.delete_trust,
                          'fake_trust_id')
