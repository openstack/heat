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
import mock
import uuid

from keystoneauth1 import access as ks_access
from keystoneauth1 import exceptions as kc_exception
from keystoneauth1.identity import access as ks_auth_access
from keystoneauth1.identity import generic as ks_auth
from keystoneauth1 import loading as ks_loading
from keystoneauth1 import session as ks_session
from keystoneauth1 import token_endpoint as ks_token_endpoint
from keystoneclient.v3 import client as kc_v3
from keystoneclient.v3 import domains as kc_v3_domains
from oslo_config import cfg
import six

from heat.common import config
from heat.common import exception
from heat.common import password_gen
from heat.engine.clients.os.keystone import heat_keystoneclient
from heat.tests import common
from heat.tests import utils

cfg.CONF.import_opt('region_name_for_services', 'heat.common.config')
cfg.CONF.import_group('keystone_authtoken',
                      'keystonemiddleware.auth_token')


class KeystoneClientTest(common.HeatTestCase):
    """Test cases for heat.common.heat_keystoneclient."""

    def setUp(self):
        super(KeystoneClientTest, self).setUp()

        self.mock_ks_v3_client_domain_mngr = self.patchobject(
            kc_v3_domains, 'DomainManager', spec=kc_v3_domains.DomainManager)

        self.mock_ks_v3_client = mock.Mock()
        self.mock_ks_v3_client.domains = (
            self.mock_ks_v3_client_domain_mngr.return_value)

        self.m_client = self.patchobject(kc_v3, 'Client',
                                         return_value=self.mock_ks_v3_client)

        self.m_password = self.patchobject(ks_auth, 'Password')
        self.m_token = self.patchobject(ks_token_endpoint, 'Token')
        self.m_access = self.patchobject(ks_auth_access, 'AccessInfoPlugin')
        self.m_load_auth = self.patchobject(
            ks_loading, 'load_auth_from_conf_options')

        cfg.CONF.set_override('auth_uri', 'http://server.test:5000/v2.0',
                              group='keystone_authtoken')
        cfg.CONF.set_override('stack_user_domain_id', 'adomain123')
        cfg.CONF.set_override('stack_domain_admin', 'adminuser123')
        cfg.CONF.set_override('stack_domain_admin_password', 'adminsecret')

    def _clear_domain_override(self):
        cfg.CONF.clear_override('stack_user_domain_id')

    def _stub_domain_admin_client(self, domain_id=None):
        self.mock_ks_auth = self.m_password.return_value
        self.mock_ks_auth.get_token.return_value = 'tok'

    def _validate_stub_domain_admin_client(self):
        self.m_password.assert_called_once_with(
            auth_url='http://server.test:5000/v3',
            password='adminsecret',
            domain_id='adomain123',
            domain_name=None,
            user_domain_id='adomain123',
            user_domain_name=None,
            username='adminuser123')
        self.m_client.assert_called_once_with(
            session=utils.AnyInstance(ks_session.Session),
            auth=self.mock_ks_auth,
            region_name=None)

    def _stubs_auth(self, method='token', trust_scoped=True,
                    user_id=None, auth_ref=None, client=True, project_id=None,
                    stub_trust_context=False, version=3,
                    stub_admin_auth=False):
        self.version = version
        mock_auth_ref = mock.Mock()
        mock_ks_auth = mock.Mock()
        self.method = method
        self.project_id = project_id
        self.client = client
        self.stub_admin_auth = stub_admin_auth

        if method == 'token':
            self.m_token.return_value = mock_ks_auth
        elif method == 'auth_ref':
            self.m_access.return_value = mock_ks_auth
        elif method == 'password':
            ks_auth.Password.return_value = mock_ks_auth
        elif method == 'trust':
            mock_auth_ref.user_id = user_id or 'trustor_user_id'
            mock_auth_ref.project_id = project_id or 'test_tenant_id'
            mock_auth_ref.trust_scoped = trust_scoped
            mock_auth_ref.auth_token = 'atrusttoken'
            self.m_load_auth.return_value = mock_ks_auth

        if client:

            if stub_trust_context:
                mock_ks_auth.get_user_id.return_value = user_id

                mock_ks_auth.get_project_id.return_value = project_id

            mock_ks_auth.get_access.return_value = mock_auth_ref

        if not stub_admin_auth:
            self.m_load_auth.return_value = mock_ks_auth
        else:
            # when authenticate with trusts, we needs to mock get_user_id
            # to return trustee user
            self.mock_admin_ks_auth = mock.Mock()
            self.mock_admin_ks_auth.get_user_id.return_value = '1234'
            self.m_load_auth.return_value = self.mock_admin_ks_auth
        return mock_ks_auth, mock_auth_ref

    def _validate_stub_auth(self):

        if self.method == 'token':
            self.m_token.assert_called_once_with(
                token='abcd1234', endpoint='http://server.test:5000/v3')
        else:
            self.m_token.assert_not_called()
        if self.method == 'auth_ref':
            if self.version == 3:
                access_type = ks_access.AccessInfoV3
            else:
                access_type = ks_access.AccessInfoV2
            self.m_access.assert_called_once_with(
                auth_ref=utils.AnyInstance(access_type),
                auth_url='http://server.test:5000/v3')
        else:
            self.m_access.assert_not_called()
        if self.method == 'password':
            self.m_password.assert_called_once_with(
                auth_url='http://server.test:5000/v3',
                username='test_username',
                password='password',
                project_id=self.project_id or 'test_tenant_id',
                user_domain_id='adomain123')
        else:
            self.m_password.assert_not_called()

        if self.method == 'trust':
            self.m_load_auth.assert_called_once_with(
                cfg.CONF, 'trustee', trust_id='atrust123')
        else:
            self.m_load_auth.assert_not_called()
        if self.client:
            self.m_client.assert_any_call(
                session=utils.AnyInstance(ks_session.Session),
                region_name=None)
        if self.stub_admin_auth:
            self.mock_admin_ks_auth.get_user_id.assert_called_once_with(
                utils.AnyInstance(ks_session.Session))

    def _stubs_get_user(self, user_id, domain_id=None,
                        default_project_id=None):
        mock_user = mock.Mock()
        mock_user.id = user_id
        mock_user.domain_id = domain_id
        mock_user.default_project_id = default_project_id
        self.mock_ks_v3_client.users.get.return_value = mock_user

    def test_username_length(self):
        """Test that user names >255 characters are properly truncated."""

        self._stubs_auth()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        # a >255 character user name and the expected version
        long_user_name = 'U' * 255 + 'S'
        good_user_name = 'U' * 254 + 'S'

        mock_user = mock.Mock()
        mock_user.id = 'auser123'
        # when keystone is called, the name should have been truncated
        # to the last 255 characters of the long name
        self.mock_ks_v3_client.users.create.return_value = mock_user

        self.mock_ks_v3_client.roles.list.return_value = self._mock_roles_list(
        )
        self.mock_ks_v3_client.roles.grant.return_value = None
        # call create_stack_user with a long user name.
        # the cleanup VerifyAll should verify that though we passed
        # long_user_name, keystone was actually called with a truncated
        # user name
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.create_stack_user(long_user_name, password='password')
        self.mock_ks_v3_client.users.create.assert_called_once_with(
            name=good_user_name,
            password='password',
            default_project=ctx.tenant_id)
        self.mock_ks_v3_client.roles.list.assert_called_once_with(
            name='heat_stack_user')
        self.mock_ks_v3_client.roles.grant.assert_called_once_with(
            project=ctx.tenant_id,
            role='4546',
            user='auser123')
        self._validate_stub_auth()

    def test_create_stack_user_error_norole(self):
        """Test error path when no role is found."""

        self._stubs_auth()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        self.mock_ks_v3_client.roles.list.return_value = []
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        err = self.assertRaises(exception.Error,
                                heat_ks_client.create_stack_user,
                                'auser', password='password')
        self.assertIn("Can't find role heat_stack_user", six.text_type(err))
        self.mock_ks_v3_client.roles.list.assert_called_once_with(
            name='heat_stack_user')
        self._validate_stub_auth()

    def _mock_roles_list(self, heat_stack_user='heat_stack_user'):
        mock_roles_list = []
        mock_role = mock.Mock()
        mock_role.id = '4546'
        mock_role.name = heat_stack_user
        mock_roles_list.append(mock_role)
        return mock_roles_list

    def test_create_stack_domain_user(self):
        """Test creating a stack domain user."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self.mock_ks_v3_client.users.create.return_value.id = 'duser123'
        self.mock_ks_v3_client.roles.list.return_value = self._mock_roles_list(
        )
        self.mock_ks_v3_client.roles.grant.return_value = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.create_stack_domain_user(username='duser',
                                                project_id='aproject')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.create.assert_called_once_with(
            name='duser',
            password=None,
            default_project='aproject',
            domain='adomain123')
        self.mock_ks_v3_client.roles.grant.assert_called_once_with(
            project='aproject',
            role='4546',
            user='duser123')
        self.mock_ks_v3_client.roles.list.assert_called_once_with(
            name='heat_stack_user')

    def test_create_stack_domain_user_legacy_fallback(self):
        """Test creating a stack domain user, fallback path."""
        self._clear_domain_override()

        ctx = utils.dummy_context()
        ctx.trust_id = None
        mock_user = mock.Mock()
        mock_user.id = 'auser123'
        self.mock_ks_v3_client.users.create.return_value = mock_user

        # mock keystone client functions
        self._stubs_auth()
        self.mock_ks_v3_client.roles.list.return_value = self._mock_roles_list(
        )
        self.mock_ks_v3_client.roles.grant.return_value = None

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.create_stack_domain_user(username='auser',
                                                project_id='aproject',
                                                password='password')
        self.mock_ks_v3_client.users.create.assert_called_once_with(
            name='auser',
            password='password',
            default_project=ctx.tenant_id)
        self.mock_ks_v3_client.roles.grant.assert_called_once_with(
            project=ctx.tenant_id,
            role='4546',
            user='auser123')
        self.mock_ks_v3_client.roles.list.assert_called_once_with(
            name='heat_stack_user')
        self._validate_stub_auth()

    def test_create_stack_domain_user_error_norole(self):
        """Test creating a stack domain user, no role error path."""
        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        self._stub_domain_admin_client(domain_id=None)

        # mock keystone client functions
        self.mock_ks_v3_client.roles.list.return_value = []

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        err = self.assertRaises(exception.Error,
                                heat_ks_client.create_stack_domain_user,
                                username='duser', project_id='aproject')
        self.assertIn("Can't find role heat_stack_user", six.text_type(err))
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.roles.list.assert_called_once_with(
            name='heat_stack_user')

    def test_delete_stack_domain_user(self):
        """Test deleting a stack domain user."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        mock_user = mock.Mock()
        mock_user.id = 'duser123'
        mock_user.domain_id = 'adomain123'
        mock_user.default_project_id = 'aproject'
        self.mock_ks_v3_client.users.get.side_effect = [mock_user,
                                                        kc_exception.NotFound]

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_domain_user(user_id='duser123',
                                                project_id='aproject')
        # Second delete will raise ignored NotFound
        heat_ks_client.delete_stack_domain_user(user_id='duser123',
                                                project_id='aproject')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_with('duser123')
        self.mock_ks_v3_client.users.delete.assert_called_once_with('duser123')

    def test_delete_stack_domain_user_legacy_fallback(self):
        """Test deleting a stack domain user, fallback path."""
        self._clear_domain_override()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        # mock keystone client functions
        self._stubs_auth()

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_domain_user(user_id='user123',
                                                project_id='aproject')
        self.mock_ks_v3_client.users.delete.assert_called_once_with(
            user='user123')
        self._validate_stub_auth()

    def test_delete_stack_domain_user_error_domain(self):
        """Test deleting a stack domain user, wrong domain."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user(user_id='duser123', domain_id='notadomain123',
                             default_project_id='aproject')

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        err = self.assertRaises(ValueError,
                                heat_ks_client.delete_stack_domain_user,
                                user_id='duser123', project_id='aproject')
        self.assertIn('User delete in invalid domain', err.args)
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')

    def test_delete_stack_domain_user_error_project(self):
        """Test deleting a stack domain user, wrong project."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user(user_id='duser123', domain_id='adomain123',
                             default_project_id='notaproject')
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        err = self.assertRaises(ValueError,
                                heat_ks_client.delete_stack_domain_user,
                                user_id='duser123', project_id='aproject')
        self.assertIn('User delete in invalid project', err.args)
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')

    def test_delete_stack_user(self):

        """Test deleting a stack user."""

        self._stubs_auth()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        # mock keystone client delete function
        self.mock_ks_v3_client.users.delete.side_effect = [
            None, kc_exception.NotFound]

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_user('atestuser')
        # Second delete will raise ignored NotFound
        heat_ks_client.delete_stack_user('atestuser')
        self.mock_ks_v3_client.users.delete.assert_called_with(
            user='atestuser')
        self._validate_stub_auth()

    def test_init_v3_token(self):

        """Test creating the client, token auth."""

        self._stubs_auth()

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.client
        self.assertIsNotNone(heat_ks_client._client)
        self._validate_stub_auth()

    def test_init_v3_token_auth_ref_v2(self):

        """Test creating the client, token v2 auth_ref."""

        expected_auth_ref = {'token': {'id': 'ctx_token', 'expires': '123'},
                             'version': 'v2.0'}
        self._stubs_auth(method='auth_ref',
                         auth_ref=expected_auth_ref,
                         version=2)

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.trust_id = None
        ctx.auth_token = 'ctx_token'
        ctx.auth_token_info = {'access': {
            'token': {'id': 'abcd1234', 'expires': '123'}}}
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.client
        self.assertIsNotNone(heat_ks_client._client)
        self._validate_stub_auth()

    def test_init_v3_token_auth_ref_v3(self):

        """Test creating the client, token v3 auth_ref."""

        expected_auth_ref = {'auth_token': 'ctx_token',
                             'expires': '456',
                             'version': 'v3',
                             'methods': []}
        self._stubs_auth(method='auth_ref', auth_ref=expected_auth_ref)

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.trust_id = None
        ctx.auth_token = 'ctx_token'
        ctx.auth_token_info = {'token': {'expires': '456', 'methods': []}}
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.client
        self.assertIsNotNone(heat_ks_client._client)
        self._validate_stub_auth()

    def test_init_v3_password(self):

        """Test creating the client, password auth."""

        self._stubs_auth(method='password')

        ctx = utils.dummy_context()
        ctx.auth_token = None
        ctx.password = 'password'
        ctx.trust_id = None
        ctx.user_domain = 'adomain123'
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        client = heat_ks_client.client
        self.assertIsNotNone(client)
        self.assertIsNone(ctx.trust_id)
        self._validate_stub_auth()

    def test_init_v3_bad_nocreds(self):

        """Test creating the client, no credentials."""

        ctx = utils.dummy_context()
        ctx.auth_token = None
        ctx.trust_id = None
        ctx.username = None
        ctx.password = None
        self.assertRaises(exception.AuthorizationFailure,
                          heat_keystoneclient.KeystoneClient, ctx)

    def test_create_trust_context_trust_id(self):

        """Test create_trust_context with existing trust_id."""

        self._stubs_auth(method='trust')
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        ctx = utils.dummy_context()
        ctx.trust_id = 'atrust123'
        ctx.trustor_user_id = 'trustor_user_id'

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        trust_context = heat_ks_client.create_trust_context()
        self.assertEqual(ctx.to_dict(), trust_context.to_dict())
        self._validate_stub_auth()

    def test_create_trust_context_trust_create_deletegate_subset_roles(self):
        delegate_roles = ['heat_stack_owner']
        self._test_create_trust_context_trust_create(delegate_roles)

    def test_create_trust_context_trust_create_deletegate_all_roles(self):
        self._test_create_trust_context_trust_create()

    def _test_create_trust_context_trust_create(self, delegate_roles=None):

        """Test create_trust_context when creating a trust."""

        class MockTrust(object):
            id = 'atrust123'

        mock_ks_auth, mock_auth_ref = self._stubs_auth(user_id='5678',
                                                       project_id='42',
                                                       stub_trust_context=True,
                                                       stub_admin_auth=True)

        cfg.CONF.set_override('deferred_auth_method', 'trusts')
        if delegate_roles:
            cfg.CONF.set_override('trusts_delegated_roles', delegate_roles)

        trustor_roles = ['heat_stack_owner', 'admin', '__member__']
        trustee_roles = delegate_roles or trustor_roles
        mock_auth_ref.user_id = '5678'
        mock_auth_ref.project_id = '42'

        self.mock_ks_v3_client.trusts.create.return_value = MockTrust()

        ctx = utils.dummy_context(roles=trustor_roles)
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        trust_context = heat_ks_client.create_trust_context()
        self.assertEqual('atrust123', trust_context.trust_id)
        self.assertEqual('5678', trust_context.trustor_user_id)
        self.m_load_auth.assert_called_once_with(
            cfg.CONF, 'trustee', trust_id=None)
        self.mock_ks_v3_client.trusts.create.assert_called_once_with(
            trustor_user='5678',
            trustee_user='1234',
            project='42',
            impersonation=True,
            role_names=trustee_roles)

    def test_create_trust_context_trust_create_delegate_all_roleids(self):
        """Test create_trust_context when creating a trust using role IDs."""

        class MockTrust(object):
            id = 'atrust123'

        self._stubs_auth(user_id='5678', project_id='42',
                         stub_trust_context=True,
                         stub_admin_auth=True)

        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        self.mock_ks_v3_client.trusts.create.return_value = MockTrust()

        trustor_roles = [{'name': 'spam', 'id': 'ham'}]
        ctx = utils.dummy_context(roles=trustor_roles)
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        # doing that late monkeypatching to not mock extra keystone stuff
        ctx.auth_token_info = {'token': {'roles': trustor_roles}}
        trust_context = heat_ks_client.create_trust_context()
        self.assertEqual('atrust123', trust_context.trust_id)
        self.assertEqual('5678', trust_context.trustor_user_id)

        args, kwargs = self.mock_ks_v3_client.trusts.create.call_args
        self.assertEqual(["ham"], kwargs["role_ids"])

    def test_create_trust_context_trust_create_norole(self):

        """Test create_trust_context when creating a trust."""

        mock_auth, mock_auth_ref = self._stubs_auth(user_id='5678',
                                                    project_id='42',
                                                    stub_trust_context=True,
                                                    stub_admin_auth=True)

        cfg.CONF.set_override('deferred_auth_method', 'trusts')
        cfg.CONF.set_override('trusts_delegated_roles', ['heat_stack_owner'])

        exc = kc_exception.NotFound
        self.mock_ks_v3_client.trusts.create.side_effect = exc

        ctx = utils.dummy_context()
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        exc = self.assertRaises(exception.MissingCredentialError,
                                heat_ks_client.create_trust_context)
        expected = "Missing required credential: roles "
        "{'role_names': ['heat_stack_owner']}"
        self.assertIn(expected, six.text_type(exc))
        self.m_load_auth.assert_called_with(
            cfg.CONF, 'trustee', trust_id=None)
        self.mock_ks_v3_client.trusts.create.assert_called_once_with(
            trustor_user='5678',
            trustee_user='1234',
            project='42',
            impersonation=True,
            role_names=['heat_stack_owner'])

    def test_init_domain_cfg_not_set_fallback(self):
        """Test error path when config lacks domain config."""

        self._clear_domain_override()
        cfg.CONF.clear_override('stack_domain_admin')
        cfg.CONF.clear_override('stack_domain_admin_password')

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.username = None
        ctx.password = None
        ctx.trust_id = None
        self.assertIsNotNone(heat_keystoneclient.KeystoneClient(ctx))

    def test_init_domain_cfg_not_set_error(self):

        """Test error path when config lacks domain config."""

        cfg.CONF.clear_override('stack_domain_admin')
        cfg.CONF.clear_override('stack_domain_admin_password')

        err = self.assertRaises(exception.Error,
                                config.startup_sanity_check)
        exp_msg = ('heat.conf misconfigured, cannot specify '
                   '"stack_user_domain_id" or "stack_user_domain_name" '
                   'without "stack_domain_admin" and '
                   '"stack_domain_admin_password"')
        self.assertIn(exp_msg, six.text_type(err))

    def test_trust_init(self):

        """Test consuming a trust when initializing."""

        self._stubs_auth(method='trust')
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.auth_token = None
        ctx.trust_id = 'atrust123'
        ctx.trustor_user_id = 'trustor_user_id'
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNotNone(heat_ks_client.client)
        self.assertIsNone(ctx.auth_token)
        self._validate_stub_auth()

    def test_trust_init_fail(self):

        """Test consuming a trust when initializing, error scoping."""

        self._stubs_auth(method='trust', trust_scoped=False)
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.auth_token = None
        ctx.trust_id = 'atrust123'
        ctx.trustor_user_id = 'trustor_user_id'
        self.assertRaises(exception.AuthorizationFailure,
                          heat_keystoneclient.KeystoneClient, ctx)
        self._validate_stub_auth()

    def test_trust_init_fail_impersonation(self):

        """Test consuming a trust when initializing, impersonation error."""

        self._stubs_auth(method='trust', user_id='wrong_user_id')
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        ctx = utils.dummy_context()
        ctx.username = 'heat'
        ctx.password = None
        ctx.auth_token = None
        ctx.trust_id = 'atrust123'
        ctx.trustor_user_id = 'trustor_user_id'
        self.assertRaises(exception.AuthorizationFailure,
                          heat_keystoneclient.KeystoneClient, ctx)
        self._validate_stub_auth()

    def test_trust_init_pw(self):

        """Test trust_id is takes precedence username/password specified."""

        self._stubs_auth(method='trust')

        ctx = utils.dummy_context()
        ctx.auth_token = None
        ctx.trust_id = 'atrust123'
        ctx.trustor_user_id = 'trustor_user_id'
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNotNone(heat_ks_client._client)
        self._validate_stub_auth()

    def test_trust_init_token(self):

        """Test trust_id takes precedence when token specified."""

        self._stubs_auth(method='trust')

        ctx = utils.dummy_context()
        ctx.username = None
        ctx.password = None
        ctx.trust_id = 'atrust123'
        ctx.trustor_user_id = 'trustor_user_id'
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNotNone(heat_ks_client._client)
        self._validate_stub_auth()

    def _test_delete_trust(self, raise_ext=None):
        self._stubs_auth()
        cfg.CONF.set_override('deferred_auth_method', 'trusts')
        if raise_ext is not None:
            self.mock_ks_v3_client.trusts.delete.side_effect = raise_ext
        ctx = utils.dummy_context()
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNone(heat_ks_client.delete_trust(trust_id='atrust123'))
        self.mock_ks_v3_client.trusts.delete.assert_called_once_with(
            'atrust123')
        self._validate_stub_auth()

    def test_delete_trust(self):

        """Test delete_trust when deleting trust."""

        self._test_delete_trust()

    def test_delete_trust_not_found(self):

        """Test delete_trust when trust already deleted."""

        self._test_delete_trust(raise_ext=kc_exception.NotFound)

    def test_delete_trust_unauthorized(self):

        """Test delete_trust when trustor is deleted or trust is expired."""

        self._test_delete_trust(raise_ext=kc_exception.Unauthorized)

    def test_disable_stack_user(self):

        """Test disabling a stack user."""

        self._stubs_auth()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.disable_stack_user('atestuser')
        self.mock_ks_v3_client.users.update.assert_called_once_with(
            user='atestuser', enabled=False)
        self._validate_stub_auth()

    def test_enable_stack_user(self):

        """Test enabling a stack user."""

        self._stubs_auth()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.enable_stack_user('atestuser')
        self.mock_ks_v3_client.users.update.assert_called_once_with(
            user='atestuser', enabled=True)
        self._validate_stub_auth()

    def test_enable_stack_domain_user(self):
        """Test enabling a stack domain user."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user('duser123', 'adomain123', 'aproject')

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.enable_stack_domain_user(user_id='duser123',
                                                project_id='aproject')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')
        self.mock_ks_v3_client.users.update.assert_called_once_with(
            user='duser123', enabled=True)

    def test_enable_stack_domain_user_legacy_fallback(self):
        """Test enabling a stack domain user, fallback path."""
        self._clear_domain_override()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        # mock keystone client functions
        self._stubs_auth()

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.enable_stack_domain_user(user_id='user123',
                                                project_id='aproject')
        self.mock_ks_v3_client.users.update.assert_called_once_with(
            user='user123', enabled=True)
        self._validate_stub_auth()

    def test_enable_stack_domain_user_error_project(self):
        """Test enabling a stack domain user, wrong project."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user('duser123', 'adomain123', 'notaproject')

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(ValueError, heat_ks_client.enable_stack_domain_user,
                          user_id='duser123', project_id='aproject')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')

    def test_enable_stack_domain_user_error_domain(self):
        """Test enabling a stack domain user, wrong domain."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user('duser123', 'notadomain123', 'aproject')

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(ValueError, heat_ks_client.enable_stack_domain_user,
                          user_id='duser123', project_id='aproject')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')

    def test_disable_stack_domain_user(self):
        """Test disabling a stack domain user."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user('duser123', 'adomain123', 'aproject')
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.disable_stack_domain_user(user_id='duser123',
                                                 project_id='aproject')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')
        self.mock_ks_v3_client.users.update.assert_called_once_with(
            user='duser123', enabled=False)

    def test_disable_stack_domain_user_legacy_fallback(self):
        """Test enabling a stack domain user, fallback path."""
        self._clear_domain_override()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        # mock keystone client functions
        self._stubs_auth()
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.disable_stack_domain_user(user_id='user123',
                                                 project_id='aproject')
        self.mock_ks_v3_client.users.update.assert_called_once_with(
            user='user123', enabled=False)
        self._validate_stub_auth()

    def test_disable_stack_domain_user_error_project(self):
        """Test disabling a stack domain user, wrong project."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user('duser123', 'adomain123', 'notaproject')

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(ValueError, heat_ks_client.disable_stack_domain_user,
                          user_id='duser123', project_id='aproject')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')

    def test_disable_stack_domain_user_error_domain(self):
        """Test disabling a stack domain user, wrong domain."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user('duser123', 'notadomain123', 'aproject')

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(ValueError, heat_ks_client.disable_stack_domain_user,
                          user_id='duser123', project_id='aproject')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')

    def test_delete_stack_domain_user_keypair(self):
        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user('duser123', 'adomain123', 'aproject')

        exc = kc_exception.NotFound
        self.mock_ks_v3_client.credentials.delete.side_effect = [None, exc]

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_domain_user_keypair(
            user_id='duser123', project_id='aproject',
            credential_id='acredentialid')
        # Second delete will raise ignored NotFound
        heat_ks_client.delete_stack_domain_user_keypair(
            user_id='duser123', project_id='aproject',
            credential_id='acredentialid')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_with('duser123')
        self.mock_ks_v3_client.credentials.delete.assert_called_with(
            'acredentialid')

    def test_delete_stack_domain_user_keypair_legacy_fallback(self):
        self._clear_domain_override()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        # mock keystone client functions
        self._stubs_auth()

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_domain_user_keypair(
            user_id='user123', project_id='aproject',
            credential_id='acredentialid')
        self.mock_ks_v3_client.credentials.delete.assert_called_once_with(
            'acredentialid')
        self._validate_stub_auth()

    def test_delete_stack_domain_user_keypair_error_project(self):
        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user('duser123', 'adomain123', 'notaproject')

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(ValueError,
                          heat_ks_client.delete_stack_domain_user_keypair,
                          user_id='duser123', project_id='aproject',
                          credential_id='acredentialid')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')

    def test_delete_stack_domain_user_keypair_error_domain(self):
        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        # mock keystone client functions
        self._stub_domain_admin_client()
        self._stubs_get_user('duser123', 'notadomain123', 'aproject')

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(ValueError,
                          heat_ks_client.delete_stack_domain_user_keypair,
                          user_id='duser123', project_id='aproject',
                          credential_id='acredentialid')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.users.get.assert_called_once_with('duser123')

    def _stub_gen_creds(self, access, secret):
        # stub UUID.hex to return the values specified
        mock_access_uuid = mock.Mock()
        mock_access_uuid.hex = access
        self.patchobject(uuid, 'uuid4', return_value=mock_access_uuid)
        self.patchobject(password_gen, 'generate_openstack_password',
                         return_value=secret)

    def test_create_ec2_keypair(self):

        """Test creating ec2 credentials."""

        self._stubs_auth()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        ex_data = {'access': 'dummy_access',
                   'secret': 'dummy_secret'}
        ex_data_json = json.dumps(ex_data)

        # stub UUID.hex to match ex_data
        self._stub_gen_creds('dummy_access', 'dummy_secret')

        # mock keystone client credentials functions
        mock_cred = mock.Mock()
        mock_cred.id = '123456'
        mock_cred.user_id = 'atestuser'
        mock_cred.blob = ex_data_json
        mock_cred.type = 'ec2'

        # mock keystone client create function
        self.mock_ks_v3_client.credentials.create.return_value = mock_cred
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        ec2_cred = heat_ks_client.create_ec2_keypair(user_id='atestuser')
        self.assertEqual('123456', ec2_cred.id)
        self.assertEqual('dummy_access', ec2_cred.access)
        self.assertEqual('dummy_secret', ec2_cred.secret)
        self.mock_ks_v3_client.credentials.create.assert_called_once_with(
            user='atestuser', type='ec2', blob=ex_data_json,
            project=ctx.tenant_id)
        self._validate_stub_auth()

    def test_create_stack_domain_user_keypair(self):

        """Test creating ec2 credentials for domain user."""

        self._stub_domain_admin_client(domain_id=None)

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        ex_data = {'access': 'dummy_access2',
                   'secret': 'dummy_secret2'}
        ex_data_json = json.dumps(ex_data)

        # stub UUID.hex to match ex_data
        self._stub_gen_creds('dummy_access2', 'dummy_secret2')

        # mock keystone client credentials functions
        mock_cred = mock.Mock()
        mock_cred.id = '1234567'
        mock_cred.user_id = 'atestuser2'
        mock_cred.blob = ex_data_json
        mock_cred.type = 'ec2'

        # mock keystone client create function
        self.mock_ks_v3_client.credentials.create.return_value = mock_cred
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        ec2_cred = heat_ks_client.create_stack_domain_user_keypair(
            user_id='atestuser2', project_id='aproject')
        self.assertEqual('1234567', ec2_cred.id)
        self.assertEqual('dummy_access2', ec2_cred.access)
        self.assertEqual('dummy_secret2', ec2_cred.secret)
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.credentials.create.assert_called_once_with(
            user='atestuser2', type='ec2', blob=ex_data_json,
            project='aproject')

    def test_create_stack_domain_user_keypair_legacy_fallback(self):

        """Test creating ec2 credentials for domain user, fallback path."""
        self._clear_domain_override()

        self._stubs_auth()

        ctx = utils.dummy_context()
        ctx.trust_id = None

        ex_data = {'access': 'dummy_access2',
                   'secret': 'dummy_secret2'}
        ex_data_json = json.dumps(ex_data)

        # stub UUID.hex to match ex_data
        self._stub_gen_creds('dummy_access2', 'dummy_secret2')

        # mock keystone client credentials functions
        mock_cred = mock.Mock()
        mock_cred.id = '1234567'
        mock_cred.user_id = 'atestuser2'
        mock_cred.blob = ex_data_json
        mock_cred.type = 'ec2'

        # mock keystone client create function
        self.mock_ks_v3_client.credentials.create.return_value = mock_cred
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        ec2_cred = heat_ks_client.create_stack_domain_user_keypair(
            user_id='atestuser2', project_id='aproject')
        self.assertEqual('1234567', ec2_cred.id)
        self.assertEqual('dummy_access2', ec2_cred.access)
        self.assertEqual('dummy_secret2', ec2_cred.secret)
        self.mock_ks_v3_client.credentials.create.assert_called_once_with(
            user='atestuser2', type='ec2', blob=ex_data_json,
            project=ctx.tenant_id)
        self._validate_stub_auth()

    def test_get_ec2_keypair_id(self):

        """Test getting ec2 credential by id."""

        user_id = 'atestuser'
        self._stubs_auth(user_id=user_id)

        ctx = utils.dummy_context()
        ctx.trust_id = None

        ex_data = {'access': 'access123',
                   'secret': 'secret456'}
        ex_data_json = json.dumps(ex_data)

        # Create a mock credential response
        credential_id = 'acredential123'
        mock_cred = mock.Mock()
        mock_cred.id = credential_id
        mock_cred.user_id = user_id
        mock_cred.blob = ex_data_json
        mock_cred.type = 'ec2'

        # mock keystone client get function
        self.mock_ks_v3_client.credentials.get.return_value = mock_cred
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        ec2_cred = heat_ks_client.get_ec2_keypair(credential_id=credential_id)
        self.assertEqual(credential_id, ec2_cred.id)
        self.assertEqual('access123', ec2_cred.access)
        self.assertEqual('secret456', ec2_cred.secret)
        self.mock_ks_v3_client.credentials.get.assert_called_once_with(
            credential_id)
        self._validate_stub_auth()

    def _mock_credential_list(self, user_id):
        """Create a mock credential list response."""
        mock_cred_list = []
        for x in (1, 2, 3):
            mock_credential = mock.Mock()
            mock_credential.id = 'credential_id%s' % x
            mock_credential.user_id = user_id
            mock_credential.blob = json.dumps({'access': 'access%s' % x,
                                               'secret': 'secret%s' % x})
            mock_credential.type = 'ec2'
            mock_cred_list.append(mock_credential)

        # mock keystone client list function
        self.mock_ks_v3_client.credentials.list.return_value = mock_cred_list

    def test_get_ec2_keypair_access(self):

        """Test getting ec2 credential by access."""

        user_id = 'atestuser'
        self._stubs_auth(user_id=user_id)

        ctx = utils.dummy_context()
        ctx.trust_id = None

        self._mock_credential_list(user_id=user_id)
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        ec2_cred = heat_ks_client.get_ec2_keypair(access='access2')
        self.assertEqual('credential_id2', ec2_cred.id)
        self.assertEqual('access2', ec2_cred.access)
        self.assertEqual('secret2', ec2_cred.secret)
        self._validate_stub_auth()

    def test_get_ec2_keypair_error(self):

        """Test getting ec2 credential error path."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(ValueError, heat_ks_client.get_ec2_keypair)

    def test_delete_ec2_keypair_id(self):

        """Test deleting ec2 credential by id."""

        user_id = 'atestuser'
        self._stubs_auth(user_id=user_id)

        ctx = utils.dummy_context()
        ctx.trust_id = None

        credential_id = 'acredential123'

        # mock keystone client delete function
        exc = kc_exception.NotFound
        self.mock_ks_v3_client.credentials.delete.side_effect = exc
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNone(heat_ks_client.delete_ec2_keypair(
                          credential_id=credential_id))
        # Second delete will raise ignored NotFound
        self.assertIsNone(heat_ks_client.delete_ec2_keypair(
                          credential_id=credential_id))
        self.mock_ks_v3_client.credentials.delete.assert_called_with(
            credential_id)
        self._validate_stub_auth()

    def test_delete_ec2_keypair_access(self):

        """Test deleting ec2 credential by access."""

        user_id = 'atestuser'
        self._stubs_auth(user_id=user_id)

        ctx = utils.dummy_context()
        ctx.trust_id = None

        self._mock_credential_list(user_id=user_id)

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNone(heat_ks_client.delete_ec2_keypair(access='access2'))
        self.mock_ks_v3_client.credentials.delete.assert_called_once_with(
            'credential_id2')
        self._validate_stub_auth()

    def test_deleting_ec2_keypair_error(self):

        """Test deleting ec2 credential error path."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(ValueError, heat_ks_client.delete_ec2_keypair)

    def test_create_stack_domain_project(self):

        """Test the create_stack_domain_project function."""

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None
        expected_name = '%s-astack' % ctx.tenant_id

        self._stub_domain_admin_client()
        dummy = mock.Mock()
        dummy.id = 'aproject123'
        self.mock_ks_v3_client.projects.create.return_value = dummy

        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertEqual('aproject123',
                         heat_ks_client.create_stack_domain_project('astack'))
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.projects.create.assert_called_once_with(
            name=expected_name,
            domain='adomain123',
            description='Heat stack user project')

    def test_create_stack_domain_project_legacy_fallback(self):
        """Test the create_stack_domain_project function, fallback path."""
        self._clear_domain_override()

        ctx = utils.dummy_context()
        ctx.trust_id = None
        self.patchobject(ctx, '_create_auth_plugin')
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertEqual(ctx.tenant_id,
                         heat_ks_client.create_stack_domain_project('astack'))

    def test_delete_stack_domain_project(self):

        """Test the delete_stack_domain_project function."""

        self._stub_domain_admin_client()
        dummy = mock.Mock()
        dummy.id = 'aproject123'
        dummy.domain_id = 'adomain123'
        self.mock_ks_v3_client.projects.get.return_value = dummy

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_domain_project(project_id='aprojectid')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.projects.get.assert_called_once_with(
            project='aprojectid')

    def test_delete_stack_domain_project_notfound(self):

        """Test the delete_stack_domain_project function."""

        self._stub_domain_admin_client(domain_id=None)
        self.mock_ks_v3_client.projects.get.side_effect = kc_exception.NotFound

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_domain_project(project_id='aprojectid')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.projects.get.assert_called_once_with(
            project='aprojectid')

    def test_delete_stack_domain_project_forbidden(self):

        """Test the delete_stack_domain_project function."""

        self._stub_domain_admin_client(domain_id=None)
        exc = kc_exception.Forbidden
        self.mock_ks_v3_client.projects.get.side_effect = exc

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_domain_project(project_id='aprojectid')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.projects.get.assert_called_once_with(
            project='aprojectid')

    def test_delete_stack_domain_project_wrongdomain(self):

        """Test the delete_stack_domain_project function."""

        self._stub_domain_admin_client()
        dummy = mock.Mock()
        dummy.id = 'aproject123'
        dummy.domain_id = 'default'
        self.mock_ks_v3_client.projects.get.return_value = dummy

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_domain_project(project_id='aprojectid')
        self._validate_stub_domain_admin_client()
        self.mock_ks_v3_client.projects.get.assert_called_once_with(
            project='aprojectid')

    def test_delete_stack_domain_project_nodomain(self):

        """Test the delete_stack_domain_project function."""

        self._clear_domain_override()

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        heat_ks_client.delete_stack_domain_project(project_id='aprojectid')

    def test_stack_domain_user_token(self):
        """Test stack_domain_user_token function."""
        dum_tok = 'dummytoken'
        ctx = utils.dummy_context()
        mock_ks_auth = mock.Mock()
        mock_ks_auth.get_token.return_value = dum_tok
        self.patchobject(ctx, '_create_auth_plugin')
        ks_auth.Password.return_value = mock_ks_auth

        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        token = heat_ks_client.stack_domain_user_token(user_id='duser',
                                                       project_id='aproject',
                                                       password='apassw')
        self.assertEqual(dum_tok, token)
        ks_auth.Password.assert_called_once_with(
            auth_url='http://server.test:5000/v3',
            password='apassw',
            project_id='aproject',
            user_id='duser')
        mock_ks_auth.get_token.assert_called_once_with(
            utils.AnyInstance(ks_session.Session))

    def test_stack_domain_user_token_err_nodomain(self):
        """Test stack_domain_user_token error path."""
        self._clear_domain_override()
        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')

        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertRaises(exception.Error,
                          heat_ks_client.stack_domain_user_token,
                          user_id='user',
                          project_id='aproject',
                          password='password')

    def test_delete_stack_domain_project_legacy_fallback(self):
        """Test the delete_stack_domain_project function, fallback path."""
        self._clear_domain_override()

        ctx = utils.dummy_context()
        self.patchobject(ctx, '_create_auth_plugin')
        ctx.trust_id = None
        heat_ks_client = heat_keystoneclient.KeystoneClient(ctx)
        self.assertIsNone(heat_ks_client.delete_stack_domain_project(
            project_id='aprojectid'))


class KeystoneClientTestDomainName(KeystoneClientTest):
    def setUp(self):
        cfg.CONF.set_override('stack_user_domain_name', 'fake_domain_name')
        super(KeystoneClientTestDomainName, self).setUp()
        cfg.CONF.clear_override('stack_user_domain_id')

    def _clear_domain_override(self):
        cfg.CONF.clear_override('stack_user_domain_name')

    def _validate_stub_domain_admin_client(self):
        ks_auth.Password.assert_called_once_with(
            auth_url='http://server.test:5000/v3',
            password='adminsecret',
            domain_id=None,
            domain_name='fake_domain_name',
            user_domain_id=None,
            user_domain_name='fake_domain_name',
            username='adminuser123')

        self.m_client.assert_called_once_with(
            session=utils.AnyInstance(ks_session.Session),
            auth=self.mock_ks_auth,
            region_name=None)

    def _stub_domain_admin_client(self, domain_id='adomain123'):
        super(KeystoneClientTestDomainName, self)._stub_domain_admin_client()

        if domain_id:
            self.mock_ks_auth.get_access.return_value.domain_id = domain_id

    def test_enable_stack_domain_user_error_project(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_enable_stack_domain_user_error_project()

    def test_delete_stack_domain_user_keypair(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_delete_stack_domain_user_keypair()

    def test_delete_stack_domain_user_error_project(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_delete_stack_domain_user_error_project()

    def test_delete_stack_domain_user_keypair_error_project(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_delete_stack_domain_user_keypair_error_project()

    def test_delete_stack_domain_user(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_delete_stack_domain_user()

    def test_enable_stack_domain_user(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_enable_stack_domain_user()

    def test_delete_stack_domain_user_error_domain(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_delete_stack_domain_user_error_domain()

    def test_disable_stack_domain_user_error_project(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_disable_stack_domain_user_error_project()

    def test_enable_stack_domain_user_error_domain(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_enable_stack_domain_user_error_domain()

    def test_delete_stack_domain_user_keypair_error_domain(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_delete_stack_domain_user_keypair_error_domain()

    def test_disable_stack_domain_user(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_disable_stack_domain_user()

    def test_disable_stack_domain_user_error_domain(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_disable_stack_domain_user_error_domain()

    def test_delete_stack_domain_project(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_delete_stack_domain_project()

    def test_delete_stack_domain_project_notfound(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_delete_stack_domain_project_notfound()

    def test_delete_stack_domain_project_wrongdomain(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_delete_stack_domain_project_wrongdomain()

    def test_create_stack_domain_project(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_create_stack_domain_project()

    def test_create_stack_domain_user(self):
        p = super(KeystoneClientTestDomainName, self)
        p.test_create_stack_domain_user()
