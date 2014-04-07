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

import mock
import os
from oslo.config import cfg
import webob

from heat.common import context
from heat.common import exception
from heat.openstack.common import policy as base_policy
from heat.tests.common import HeatTestCase

policy_path = os.path.dirname(os.path.realpath(__file__)) + "/policy/"


class TestRequestContext(HeatTestCase):

    def setUp(self):
        self.ctx = {'username': 'mick',
                    'trustor_user_id': None,
                    'auth_token': '123',
                    'is_admin': False,
                    'user': 'mick',
                    'password': 'foo',
                    'trust_id': None,
                    'show_deleted': False,
                    'roles': ['arole', 'notadmin'],
                    'tenant_id': '456tenant',
                    'user_id': 'fooUser',
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
                                     user_id=self.ctx.get('user_id'),
                                     auth_url=self.ctx.get('auth_url'),
                                     roles=self.ctx.get('roles'),
                                     show_deleted=self.ctx.get('show_deleted'),
                                     is_admin=self.ctx.get('is_admin'))
        ctx_dict = ctx.to_dict()
        del(ctx_dict['request_id'])
        self.assertEqual(self.ctx, ctx_dict)

    def test_request_context_from_dict(self):
        ctx = context.RequestContext.from_dict(self.ctx)
        ctx_dict = ctx.to_dict()
        del(ctx_dict['request_id'])
        self.assertEqual(self.ctx, ctx_dict)

    def test_request_context_update(self):
        ctx = context.RequestContext.from_dict(self.ctx)

        for k in self.ctx:
            self.assertEqual(self.ctx.get(k), ctx.to_dict().get(k))
            override = '%s_override' % k
            setattr(ctx, k, override)
            self.assertEqual(override, ctx.to_dict().get(k))

    def test_get_admin_context(self):
        ctx = context.get_admin_context()
        self.assertTrue(ctx.is_admin)
        self.assertFalse(ctx.show_deleted)

    def test_get_admin_context_show_deleted(self):
        ctx = context.get_admin_context(show_deleted=True)
        self.assertTrue(ctx.is_admin)
        self.assertTrue(ctx.show_deleted)

    def test_admin_context_policy_true(self):
        policy_check = 'heat.common.policy.Enforcer.check_is_admin'
        with mock.patch(policy_check) as pc:
            pc.return_value = True
            ctx = context.RequestContext(roles=['admin'])
            self.assertTrue(ctx.is_admin)

    def test_admin_context_policy_false(self):
        policy_check = 'heat.common.policy.Enforcer.check_is_admin'
        with mock.patch(policy_check) as pc:
            pc.return_value = False
            ctx = context.RequestContext(roles=['notadmin'])
            self.assertFalse(ctx.is_admin)


class RequestContextMiddlewareTest(HeatTestCase):

    scenarios = [(
        'empty_headers',
        dict(
            headers={},
            expected_exception=None,
            context_dict={
                'auth_token': None,
                'auth_url': None,
                'aws_creds': None,
                'is_admin': False,
                'password': None,
                'roles': [],
                'show_deleted': False,
                'tenant': None,
                'tenant_id': None,
                'trust_id': None,
                'trustor_user_id': None,
                'user': None,
                'user_id': None,
                'username': None
            })
    ), (
        'username_password',
        dict(
            headers={
                'X-Auth-User': 'my_username',
                'X-Auth-Key': 'my_password',
                'X-Auth-EC2-Creds': '{"ec2Credentials": {}}',
                'X-User-Id': '7a87ff18-31c6-45ce-a186-ec7987f488c3',
                'X-Auth-Token': 'atoken',
                'X-Tenant-Name': 'my_tenant',
                'X-Tenant-Id': 'db6808c8-62d0-4d92-898c-d644a6af20e9',
                'X-Auth-Url': 'http://192.0.2.1:5000/v1',
                'X-Roles': 'role1,role2,role3'
            },
            expected_exception=None,
            context_dict={
                'auth_token': 'atoken',
                'auth_url': 'http://192.0.2.1:5000/v1',
                'aws_creds': None,
                'is_admin': False,
                'password': 'my_password',
                'roles': ['role1', 'role2', 'role3'],
                'show_deleted': False,
                'tenant': 'my_tenant',
                'tenant_id': 'db6808c8-62d0-4d92-898c-d644a6af20e9',
                'trust_id': None,
                'trustor_user_id': None,
                'user': 'my_username',
                'user_id': '7a87ff18-31c6-45ce-a186-ec7987f488c3',
                'username': 'my_username'
            })
    ), (
        'aws_creds',
        dict(
            headers={
                'X-Auth-EC2-Creds': '{"ec2Credentials": {}}',
                'X-User-Id': '7a87ff18-31c6-45ce-a186-ec7987f488c3',
                'X-Auth-Token': 'atoken',
                'X-Tenant-Name': 'my_tenant',
                'X-Tenant-Id': 'db6808c8-62d0-4d92-898c-d644a6af20e9',
                'X-Auth-Url': 'http://192.0.2.1:5000/v1',
                'X-Roles': 'role1,role2,role3',
            },
            expected_exception=None,
            context_dict={
                'auth_token': 'atoken',
                'auth_url': 'http://192.0.2.1:5000/v1',
                'aws_creds': '{"ec2Credentials": {}}',
                'is_admin': False,
                'password': None,
                'roles': ['role1', 'role2', 'role3'],
                'show_deleted': False,
                'tenant': 'my_tenant',
                'tenant_id': 'db6808c8-62d0-4d92-898c-d644a6af20e9',
                'trust_id': None,
                'trustor_user_id': None,
                'user': None,
                'user_id': '7a87ff18-31c6-45ce-a186-ec7987f488c3',
                'username': None
            })
    ), (
        'malformed_roles',
        dict(
            headers={
                'X-Roles': [],
            },
            expected_exception=exception.NotAuthenticated)
    )]

    def setUp(self):
        super(RequestContextMiddlewareTest, self).setUp()
        opts = [
            cfg.StrOpt('config_dir', default=policy_path),
            cfg.StrOpt('config_file', default='foo'),
            cfg.StrOpt('project', default='heat'),
        ]
        cfg.CONF.register_opts(opts)
        pf = policy_path + 'check_admin.json'
        self.m.StubOutWithMock(base_policy.Enforcer, '_get_policy_path')
        base_policy.Enforcer._get_policy_path().MultipleTimes().AndReturn(pf)
        self.m.ReplayAll()

    def test_context_middleware(self):

        middleware = context.ContextMiddleware(None, None)
        request = webob.Request.blank('/stacks', headers=self.headers)
        if self.expected_exception:
            self.assertRaises(
                self.expected_exception, middleware.process_request, request)
        else:
            self.assertIsNone(middleware.process_request(request))
            ctx = request.context.to_dict()
            for k, v in self.context_dict.items():
                self.assertEqual(v, ctx[k], 'Key %s values do not match' % k)
