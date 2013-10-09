# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from heat.common import context
from heat.tests.common import HeatTestCase


class TestRequestContext(HeatTestCase):

    def setUp(self):
        self.ctx = {'username': 'mick',
                    'trustor_user_id': None,
                    'auth_token': '123',
                    'is_admin': True,
                    'password': 'foo',
                    'trust_id': None,
                    'roles': ['arole', 'admin'],
                    'tenant_id': '456tenant',
                    'tenant': 'atenant',
                    'auth_url': 'http://xyz',
                    'aws_creds': 'blah'}

        super(TestRequestContext, self).setUp()

    def test_request_context_init(self):
        ctx = context.RequestContext(auth_token=self.ctx.get('auth_token'),
                                     username=self.ctx.get('username'),
                                     password=self.ctx.get('password'),
                                     aws_creds=self.ctx.get('aws_creds'),
                                     tenant=self.ctx.get('tenant'),
                                     tenant_id=self.ctx.get('tenant_id'),
                                     auth_url=self.ctx.get('auth_url'),
                                     roles=self.ctx.get('roles'),
                                     is_admin=self.ctx.get('is_admin'))
        ctx_dict = ctx.to_dict()
        self.assertEqual(ctx_dict, self.ctx)

    def test_request_context_from_dict(self):
        ctx = context.RequestContext.from_dict(self.ctx)
        ctx_dict = ctx.to_dict()
        self.assertEqual(ctx_dict, self.ctx)

    def test_request_context_update(self):
        ctx = context.RequestContext.from_dict(self.ctx)

        for k in self.ctx:
            self.assertEqual(ctx.to_dict().get(k), self.ctx.get(k))
            override = '%s_override' % k
            setattr(ctx, k, override)
            self.assertEqual(ctx.to_dict().get(k), override)
