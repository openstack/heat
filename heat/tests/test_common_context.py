# -*- coding: utf-8 -*-
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

import os

from keystoneauth1 import loading as ks_loading
import mock
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_middleware import request_id
from oslo_policy import opts as policy_opts
from oslo_utils import importutils
import webob

from heat.common import context
from heat.common import exception
from heat.tests import common

policy_path = os.path.dirname(os.path.realpath(__file__)) + "/policy/"


class TestRequestContext(common.HeatTestCase):

    def setUp(self):
        self.ctx = {'username': 'mick',
                    'trustor_user_id': None,
                    'auth_token': '123',
                    'auth_token_info': {'123info': 'woop'},
                    'is_admin': False,
                    'user': 'mick',
                    'password': 'foo',
                    'trust_id': None,
                    'global_request_id': None,
                    'show_deleted': False,
                    'roles': ['arole', 'notadmin'],
                    'tenant_id': '456tenant',
                    'user_id': 'fooUser',
                    'tenant': u'\u5218\u80dc',
                    'auth_url': 'http://xyz',
                    'aws_creds': 'blah',
                    'region_name': 'RegionOne',
                    'user_identity': 'fooUser 456tenant',
                    'user_domain': None,
                    'project_domain': None}

        super(TestRequestContext, self).setUp()

    def test_request_context_init(self):
        ctx = context.RequestContext(
            auth_token=self.ctx.get('auth_token'),
            username=self.ctx.get('username'),
            password=self.ctx.get('password'),
            aws_creds=self.ctx.get('aws_creds'),
            project_name=self.ctx.get('tenant'),
            tenant=self.ctx.get('tenant_id'),
            user=self.ctx.get('user_id'),
            auth_url=self.ctx.get('auth_url'),
            roles=self.ctx.get('roles'),
            show_deleted=self.ctx.get('show_deleted'),
            is_admin=self.ctx.get('is_admin'),
            auth_token_info=self.ctx.get('auth_token_info'),
            trustor_user_id=self.ctx.get('trustor_user_id'),
            trust_id=self.ctx.get('trust_id'),
            region_name=self.ctx.get('region_name'),
            user_domain_id=self.ctx.get('user_domain'),
            project_domain_id=self.ctx.get('project_domain'))
        ctx_dict = ctx.to_dict()
        del ctx_dict['request_id']
        del ctx_dict['project_id']
        del ctx_dict['project_name']
        self.assertEqual(self.ctx, ctx_dict)

    def test_request_context_to_dict_unicode(self):

        ctx_origin = {'username': 'mick',
                      'trustor_user_id': None,
                      'auth_token': '123',
                      'auth_token_info': {'123info': 'woop'},
                      'is_admin': False,
                      'user': 'mick',
                      'password': 'foo',
                      'trust_id': None,
                      'global_request_id': None,
                      'show_deleted': False,
                      'roles': ['arole', 'notadmin'],
                      'tenant_id': '456tenant',
                      'project_id': '456tenant',
                      'user_id': u'Gāo',
                      'tenant': u'\u5218\u80dc',
                      'project_name': u'\u5218\u80dc',
                      'auth_url': 'http://xyz',
                      'aws_creds': 'blah',
                      'region_name': 'RegionOne',
                      'user_identity': u'Gāo 456tenant',
                      'user_domain': None,
                      'project_domain': None}

        ctx = context.RequestContext(
            auth_token=ctx_origin.get('auth_token'),
            username=ctx_origin.get('username'),
            password=ctx_origin.get('password'),
            aws_creds=ctx_origin.get('aws_creds'),
            project_name=ctx_origin.get('tenant'),
            tenant=ctx_origin.get('tenant_id'),
            user=ctx_origin.get('user_id'),
            auth_url=ctx_origin.get('auth_url'),
            roles=ctx_origin.get('roles'),
            show_deleted=ctx_origin.get('show_deleted'),
            is_admin=ctx_origin.get('is_admin'),
            auth_token_info=ctx_origin.get('auth_token_info'),
            trustor_user_id=ctx_origin.get('trustor_user_id'),
            trust_id=ctx_origin.get('trust_id'),
            region_name=ctx_origin.get('region_name'),
            user_domain_id=ctx_origin.get('user_domain'),
            project_domain_id=ctx_origin.get('project_domain'))
        ctx_dict = ctx.to_dict()
        del(ctx_dict['request_id'])
        self.assertEqual(ctx_origin, ctx_dict)

    def test_request_context_from_dict(self):
        ctx = context.RequestContext.from_dict(self.ctx)
        ctx_dict = ctx.to_dict()
        del ctx_dict['request_id']
        del ctx_dict['project_id']
        del ctx_dict['project_name']
        self.assertEqual(self.ctx, ctx_dict)

    def test_request_context_update(self):
        ctx = context.RequestContext.from_dict(self.ctx)

        for k in self.ctx:
            if (k == 'user_identity' or
                    k == 'user_domain_id' or
                    k == 'project_domain_id'):
                continue

            # these values are different between attribute and context
            if k == 'tenant' or k == 'user':
                continue

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

    def test_keystone_v3_endpoint_in_context(self):
        """Ensure that the context is the preferred source for the auth_uri."""
        cfg.CONF.set_override('auth_uri', 'http://xyz',
                              group='clients_keystone')
        policy_check = 'heat.common.policy.Enforcer.check_is_admin'
        with mock.patch(policy_check) as pc:
            pc.return_value = False
            ctx = context.RequestContext(
                auth_url='http://example.com:5000/v2.0')
            self.assertEqual(ctx.keystone_v3_endpoint,
                             'http://example.com:5000/v3')

    def test_keystone_v3_endpoint_in_clients_keystone_config(self):
        """Ensure that the [clients_keystone] section is the preferred source.

        Ensure that the [clients_keystone] section of the configuration is
        the preferred source when the context does not have the auth_uri.
        """
        cfg.CONF.set_override('auth_uri', 'http://xyz',
                              group='clients_keystone')
        policy_check = 'heat.common.policy.Enforcer.check_is_admin'
        with mock.patch(policy_check) as pc:
            pc.return_value = False
            with mock.patch('keystoneauth1.discover.Discover') as discover:
                class MockDiscover(object):
                    def url_for(self, endpoint):
                        return 'http://xyz/v3'
                discover.return_value = MockDiscover()

                ctx = context.RequestContext(auth_url=None)
                self.assertEqual(ctx.keystone_v3_endpoint, 'http://xyz/v3')

    def test_keystone_v3_endpoint_in_keystone_authtoken_config(self):
        """Ensure that the [keystone_authtoken] section is used.

        Ensure that the [keystone_authtoken] section of the configuration
        is used when the auth_uri is not defined in the context or the
        [clients_keystone] section.
        """
        importutils.import_module('keystonemiddleware.auth_token')
        cfg.CONF.set_override('www_authenticate_uri', 'http://abc/v2.0',
                              group='keystone_authtoken')
        policy_check = 'heat.common.policy.Enforcer.check_is_admin'
        with mock.patch(policy_check) as pc:
            pc.return_value = False
            ctx = context.RequestContext(auth_url=None)
            self.assertEqual(ctx.keystone_v3_endpoint, 'http://abc/v3')

    def test_keystone_v3_endpoint_not_set_in_config(self):
        """Ensure an exception is raised when the auth_uri cannot be obtained.

        Ensure an exception is raised when the auth_uri cannot be obtained
        from any source.
        """
        policy_check = 'heat.common.policy.Enforcer.check_is_admin'
        with mock.patch(policy_check) as pc:
            pc.return_value = False
            ctx = context.RequestContext(auth_url=None)
            self.assertRaises(exception.AuthorizationFailure, getattr, ctx,
                              'keystone_v3_endpoint')

    def test_get_trust_context_auth_plugin_unauthorized(self):
        self.ctx['trust_id'] = 'trust_id'
        ctx = context.RequestContext.from_dict(self.ctx)
        self.patchobject(ks_loading, 'load_auth_from_conf_options',
                         return_value=None)
        self.assertRaises(exception.AuthorizationFailure, getattr,
                          ctx, 'auth_plugin')

    def test_cache(self):
        ctx = context.RequestContext.from_dict(self.ctx)

        class Class1(object):
            pass

        class Class2(object):
            pass

        self.assertEqual(0, len(ctx._object_cache))

        cache1 = ctx.cache(Class1)
        self.assertIsInstance(cache1, Class1)
        self.assertEqual(1, len(ctx._object_cache))

        cache1a = ctx.cache(Class1)
        self.assertEqual(cache1, cache1a)
        self.assertEqual(1, len(ctx._object_cache))

        cache2 = ctx.cache(Class2)
        self.assertIsInstance(cache2, Class2)
        self.assertEqual(2, len(ctx._object_cache))


class RequestContextMiddlewareTest(common.HeatTestCase):

    scenarios = [(
        'empty_headers',
        dict(
            environ=None,
            headers={},
            context_dict={
                'auth_token': None,
                'auth_token_info': None,
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
            environ=None,
            headers={
                'X-Auth-User': 'my_username',
                'X-Auth-Key': 'my_password',
                'X-Auth-EC2-Creds': '{"ec2Credentials": {}}',
                'X-User-Id': '7a87ff18-31c6-45ce-a186-ec7987f488c3',
                'X-Auth-Token': 'atoken',
                'X-Project-Name': 'my_tenant',
                'X-Project-Id': 'db6808c8-62d0-4d92-898c-d644a6af20e9',
                'X-Auth-Url': 'http://192.0.2.1:5000/v1',
                'X-Roles': 'role1,role2,role3'
            },
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
            environ=None,
            headers={
                'X-Auth-EC2-Creds': '{"ec2Credentials": {}}',
                'X-User-Id': '7a87ff18-31c6-45ce-a186-ec7987f488c3',
                'X-Auth-Token': 'atoken',
                'X-Project-Name': 'my_tenant',
                'X-Project-Id': 'db6808c8-62d0-4d92-898c-d644a6af20e9',
                'X-Auth-Url': 'http://192.0.2.1:5000/v1',
                'X-Roles': 'role1,role2,role3',
            },
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
        'token_creds',
        dict(
            environ={'keystone.token_info': {'info': 123}},
            headers={
                'X-User-Id': '7a87ff18-31c6-45ce-a186-ec7987f488c3',
                'X-Auth-Token': 'atoken2',
                'X-Project-Name': 'my_tenant2',
                'X-Project-Id': 'bb9108c8-62d0-4d92-898c-d644a6af20e9',
                'X-Auth-Url': 'http://192.0.2.1:5000/v1',
                'X-Roles': 'role1,role2,role3',
            },
            context_dict={
                'auth_token': 'atoken2',
                'auth_token_info': {'info': 123},
                'auth_url': 'http://192.0.2.1:5000/v1',
                'aws_creds': None,
                'is_admin': False,
                'password': None,
                'roles': ['role1', 'role2', 'role3'],
                'show_deleted': False,
                'tenant': 'my_tenant2',
                'tenant_id': 'bb9108c8-62d0-4d92-898c-d644a6af20e9',
                'trust_id': None,
                'trustor_user_id': None,
                'user': None,
                'user_id': '7a87ff18-31c6-45ce-a186-ec7987f488c3',
                'username': None
            })
    )]

    def setUp(self):
        super(RequestContextMiddlewareTest, self).setUp()
        self.fixture = self.useFixture(config_fixture.Config())
        self.fixture.conf(args=['--config-dir', policy_path])
        policy_opts.set_defaults(cfg.CONF, 'check_admin.json')

    def test_context_middleware(self):

        middleware = context.ContextMiddleware(None, None)
        request = webob.Request.blank('/stacks', headers=self.headers,
                                      environ=self.environ)

        self.assertIsNone(middleware.process_request(request))
        ctx = request.context.to_dict()
        for k, v in self.context_dict.items():
            self.assertEqual(v, ctx[k], 'Key %s values do not match' % k)
        self.assertIsNotNone(ctx.get('request_id'))

    def test_context_middleware_with_requestid(self):

        middleware = context.ContextMiddleware(None, None)
        request = webob.Request.blank('/stacks', headers=self.headers,
                                      environ=self.environ)
        req_id = 'req-5a63f0d7-1b69-447b-b621-4ea87cc7186d'
        request.environ[request_id.ENV_REQUEST_ID] = req_id

        self.assertIsNone(middleware.process_request(request))
        ctx = request.context.to_dict()
        for k, v in self.context_dict.items():
            self.assertEqual(v, ctx[k], 'Key %s values do not match' % k)
        self.assertEqual(
            ctx.get('request_id'), req_id,
            'Key request_id values do not match')
