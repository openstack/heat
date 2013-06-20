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

from heat.common import config
from heat.common import context
from heat.common import heat_keystoneclient
from heat.tests.common import HeatTestCase


class KeystoneClientTest(HeatTestCase):
    """Test cases for heat.common.heat_keystoneclient."""

    def setUp(self):
        super(KeystoneClientTest, self).setUp()
        # load config so role checking doesn't barf
        config.register_engine_opts()
        # mock the internal keystone client and its authentication
        self.m.StubOutClassWithMocks(heat_keystoneclient.kc, "Client")
        self.mock_ks_client = heat_keystoneclient.kc.Client(
            auth_url=mox.IgnoreArg(),
            password=mox.IgnoreArg(),
            tenant_id=mox.IgnoreArg(),
            tenant_name=mox.IgnoreArg(),
            username=mox.IgnoreArg())
        self.mock_ks_client.authenticate().AndReturn(True)
        # verify all the things
        self.addCleanup(self.m.VerifyAll)

    def _create_context(self, user='stacks_test_user',
                        tenant='test_admin', password='test_password',
                        auth_url="auth_url", tenant_id='tenant_id', ctx=None):
        """
        :returns: A test context
        """
        ctx = ctx or context.get_admin_context()
        ctx.auth_url = auth_url
        ctx.username = user
        ctx.password = password
        ctx.tenant_id = tenant_id
        ctx.tenant = tenant
        return ctx

    def test_username_length(self):
        """Test that user names >64 characters are properly truncated."""

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
        heat_ks_client = heat_keystoneclient.KeystoneClient(
            self._create_context())
        heat_ks_client.create_stack_user(long_user_name, password='password')
