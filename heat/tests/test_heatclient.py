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

import mox

from oslo.config import cfg

from keystoneclient.v2_0 import client as kc
from keystoneclient.v3 import client as kc_v3

from heat.common import exception
from heat.common import heat_keystoneclient
from heat.tests.common import HeatTestCase
from heat.tests import utils

from heat.openstack.common import importutils


class KeystoneClientTest(HeatTestCase):
    """Test cases for heat.common.heat_keystoneclient."""

    def setUp(self):
        super(KeystoneClientTest, self).setUp()
        self.mock_admin_client = self.m.CreateMock(kc.Client)
        self.mock_ks_client = self.m.CreateMock(kc.Client)
        self.mock_ks_v3_client = self.m.CreateMock(kc_v3.Client)
        self.m.StubOutWithMock(kc, "Client")
        self.m.StubOutWithMock(kc_v3, "Client")

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

    def _stub_admin_client(self):
        kc.Client(
            auth_url='http://server.test:5000/v2.0',
            password='verybadpass',
            tenant_name='service',
            username='heat').AndReturn(self.mock_admin_client)
        self.mock_admin_client.auth_ref = self.m.CreateMockAnything()
        self.mock_admin_client.auth_ref.user_id = '1234'

    def _stubs_v2(self, method='token', auth_ok=True,
                  trust_scoped=True):
        if method == 'token':
            kc.Client(
                auth_url=mox.IgnoreArg(),
                tenant_name='test_tenant',
                token='abcd1234').AndReturn(self.mock_ks_client)
            self.mock_ks_client.authenticate().AndReturn(auth_ok)
        elif method == 'password':
            kc.Client(
                auth_url=mox.IgnoreArg(),
                tenant_name='test_tenant',
                tenant_id='test_tenant_id',
                username='test_username',
                password='password').AndReturn(self.mock_ks_client)
            self.mock_ks_client.authenticate().AndReturn(auth_ok)
        if method == 'trust':
            kc.Client(
                auth_url='http://server.test:5000/v2.0',
                password='verybadpass',
                tenant_name='service',
                username='heat').AndReturn(self.mock_ks_client)
            self.mock_ks_client.authenticate(trust_id='atrust123',
                                             tenant_id='test_tenant_id'
                                             ).AndReturn(auth_ok)
            self.mock_ks_client.auth_ref = self.m.CreateMockAnything()
            self.mock_ks_client.auth_ref.trust_scoped = trust_scoped
            self.mock_ks_client.auth_ref.auth_token = 'atrusttoken'

    def _stubs_v3(self, method='token', auth_ok=True):
        if method == 'token':
            kc_v3.Client(
                token='abcd1234', project_name='test_tenant',
                auth_url='http://server.test:5000/v3',
                endpoint='http://server.test:5000/v3').AndReturn(
                    self.mock_ks_v3_client)
        elif method == 'password':
            kc_v3.Client(
                username='test_username',
                password='password',
                project_name='test_tenant',
                project_id='test_tenant_id',
                auth_url='http://server.test:5000/v3',
                endpoint='http://server.test:5000/v3').AndReturn(
                    self.mock_ks_v3_client)
        elif method == 'trust':
            kc_v3.Client(
                username='heat',
                password='verybadpass',
                project_name='service',
                auth_url='http://server.test:5000/v3').AndReturn(
                    self.mock_ks_v3_client)
        self.mock_ks_v3_client.authenticate().AndReturn(auth_ok)

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
        ctx = utils.dummy_context()
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.create_stack_user(long_user_name, password='password')

    def test_init_v2_password(self):

        """Test creating the client, user/password context."""

        self._stubs_v2(method='password')
        self.m.ReplayAll()

        ctx = utils.dummy_context()
        ctx.auth_token = None
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNotNone(heat_ks_client.client_v2)
        self.assertIsNone(heat_ks_client._client_v3)

    def test_init_v2_bad_nocreds(self):

        """Test creating the client without trusts, no credentials."""

        ctx = utils.dummy_context()
        ctx.auth_token = None
        ctx.username = None
        ctx.password = None
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(exception.AuthorizationFailure,
                          heat_ks_client._v2_client_init)

    def test_init_v3_token(self):

        """Test creating the client, token auth."""

        self._stubs_v3()
        self.m.ReplayAll()

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.client_v3
        self.assertIsNotNone(heat_ks_client._client_v3)
        self.assertIsNone(heat_ks_client._client_v2)

    def test_init_v3_password(self):

        """Test creating the client, password auth."""

        self._stubs_v3(method='password')
        self.m.ReplayAll()

        ctx = utils.dummy_context()
        ctx.auth_token = None
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        client_v3 = heat_ks_client.client_v3
        self.assertIsNotNone(client_v3)
        self.assertIsNone(heat_ks_client._client_v2)

    def test_init_v3_bad_nocreds(self):

        """Test creating the client, no credentials."""

        ctx = utils.dummy_context()
        ctx.auth_token = None
        ctx.trust_id = None
        ctx.username = None
        ctx.password = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(exception.AuthorizationFailure,
                          heat_ks_client._v3_client_init)

    def test_create_trust_context_trust_id(self):

        """Test create_trust_context with existing trust_id."""

        self._stubs_v2(method='trust')
        self.m.ReplayAll()

        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        ctx = utils.dummy_context()
        ctx.trust_id = 'atrust123'

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        trust_context = heat_ks_client.create_trust_context()
        self.assertEqual(trust_context.to_dict(), ctx.to_dict())

    def test_create_trust_context_trust_create(self):

        """Test create_trust_context when creating a trust."""

        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        class MockTrust(object):
            id = 'atrust123'

        self._stub_admin_client()

        self._stubs_v3()

        self.mock_ks_v3_client.auth_ref = self.m.CreateMockAnything()
        self.mock_ks_v3_client.auth_ref.user_id = '5678'
        self.mock_ks_v3_client.auth_ref.project_id = '42'
        self.mock_ks_v3_client.trusts = self.m.CreateMockAnything()
        self.mock_ks_v3_client.trusts.create(
            trustor_user='5678',
            trustee_user='1234',
            project='42',
            impersonation=True,
            role_names=['heat_stack_owner']).AndReturn(MockTrust())

        self.m.ReplayAll()

        ctx = utils.dummy_context()
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        trust_context = heat_ks_client.create_trust_context()
        self.assertEqual(trust_context.trust_id, 'atrust123')
        self.assertEqual(trust_context.trustor_user_id, '5678')

    def test_trust_init(self):

        """Test consuming a trust when initializing."""

        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        self._stubs_v2(method='trust')
        self.m.ReplayAll()

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.auth_token = None
        ctx.trust_id = 'atrust123'
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        client_v2 = heat_ks_client.client_v2
        self.assertIsNotNone(client_v2)

    def test_trust_init_fail(self):

        """Test consuming a trust when initializing, error scoping."""

        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        self._stubs_v2(method='trust', trust_scoped=False)
        self.m.ReplayAll()

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.auth_token = None
        ctx.trust_id = 'atrust123'
        self.assertRaises(exception.AuthorizationFailure,
                          heat_keystoneclient.KeystoneClient, ctx)

    def test_trust_init_pw(self):

        """Test trust_id is takes precedence username/password specified."""

        self._stubs_v2(method='trust')
        self.m.ReplayAll()

        ctx = utils.dummy_context()
        ctx.auth_token = None
        ctx.trust_id = 'atrust123'
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNotNone(heat_ks_client._client_v2)
        self.assertIsNone(heat_ks_client._client_v3)

    def test_trust_init_token(self):

        """Test trust_id takes precedence when token specified."""

        self._stubs_v2(method='trust')
        self.m.ReplayAll()

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.trust_id = 'atrust123'
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNotNone(heat_ks_client._client_v2)
        self.assertIsNone(heat_ks_client._client_v3)

    def test_delete_trust(self):

        """Test delete_trust when deleting trust."""

        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        self._stubs_v3()
        self.mock_ks_v3_client.trusts = self.m.CreateMockAnything()
        self.mock_ks_v3_client.trusts.delete('atrust123').AndReturn(None)

        self.m.ReplayAll()
        ctx = utils.dummy_context()
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNone(heat_ks_client.delete_trust(trust_id='atrust123'))
