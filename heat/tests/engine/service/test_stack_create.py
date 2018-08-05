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
from oslo_config import cfg
from oslo_messaging.rpc import dispatcher
from oslo_service import threadgroup
import six
from swiftclient import exceptions

from heat.common import environment_util as env_util
from heat.common import exception
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine.clients.os import swift
from heat.engine import environment
from heat.engine import properties
from heat.engine.resources.aws.ec2 import instance as instances
from heat.engine import service
from heat.engine import stack
from heat.engine import template as templatem
from heat.objects import stack as stack_object
from heat.tests import common
from heat.tests.engine import tools
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


class StackCreateTest(common.HeatTestCase):
    def setUp(self):
        super(StackCreateTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.thread_group_mgr = service.ThreadGroupManager()
        cfg.CONF.set_override('convergence_engine', False)

    @mock.patch.object(threadgroup, 'ThreadGroup')
    @mock.patch.object(stack.Stack, 'validate')
    def _test_stack_create(self, stack_name, mock_validate, mock_tg,
                           environment_files=None, files_container=None,
                           error=False):
        mock_tg.return_value = tools.DummyThreadGroup()

        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stk = tools.get_stack(stack_name, self.ctx,
                              convergence=cfg.CONF.convergence_engine)

        files = None
        if files_container:
            files = {'/env/test.yaml': "{'resource_registry': {}}"}

        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)
        mock_merge = self.patchobject(env_util, 'merge_environments')
        if not error:
            result = self.man.create_stack(self.ctx, stack_name,
                                           template, params, None, {},
                                           environment_files=environment_files,
                                           files_container=files_container)
            self.assertEqual(stk.identifier(), result)
            self.assertIsInstance(result, dict)
            self.assertTrue(result['stack_id'])
            mock_tmpl.assert_called_once_with(template, files=files)
            mock_env.assert_called_once_with(params)
            mock_stack.assert_called_once_with(
                self.ctx, stack_name, stk.t, owner_id=None, nested_depth=0,
                user_creds_id=None, stack_user_project_id=None,
                convergence=cfg.CONF.convergence_engine, parent_resource=None)
            if environment_files:
                mock_merge.assert_called_once_with(environment_files, files,
                                                   params, mock.ANY)
            mock_validate.assert_called_once_with()
        else:
            ex = self.assertRaises(dispatcher.ExpectedException,
                                   self.man.create_stack,
                                   self.ctx, stack_name,
                                   template, params, None, {},
                                   environment_files=environment_files,
                                   files_container=files_container)
            self.assertEqual(exception.NotFound, ex.exc_info[0])
            self.assertIn('Could not fetch files from container '
                          'test_container, reason: error.',
                          six.text_type(ex.exc_info[1]))

    def test_stack_create(self):
        stack_name = 'service_create_test_stack'
        self._test_stack_create(stack_name)

    def test_stack_create_with_environment_files(self):
        stack_name = 'env_files_test_stack'
        environment_files = ['env_1', 'env_2']
        self._test_stack_create(stack_name,
                                environment_files=environment_files)

    def test_stack_create_with_files_container(self):
        stack_name = 'env_files_test_stack'
        environment_files = ['env_1', 'env_2']
        files_container = 'test_container'
        fake_get_object = (None, "{'resource_registry': {}}")
        fake_get_container = ({'x-container-bytes-used': 100},
                              [{'name': '/env/test.yaml'}])
        mock_client = mock.Mock()
        mock_client.get_object.return_value = fake_get_object
        mock_client.get_container.return_value = fake_get_container
        self.patchobject(swift.SwiftClientPlugin, '_create',
                         return_value=mock_client)
        self._test_stack_create(stack_name,
                                environment_files=environment_files,
                                files_container=files_container)
        mock_client.get_container.assert_called_with(files_container)
        mock_client.get_object.assert_called_with(files_container,
                                                  '/env/test.yaml')

    def test_stack_create_with_container_notfound_swift(self):
        stack_name = 'env_files_test_stack'
        environment_files = ['env_1', 'env_2']
        files_container = 'test_container'
        mock_client = mock.Mock()
        mock_client.get_container.side_effect = exceptions.ClientException(
            'error')
        self.patchobject(swift.SwiftClientPlugin, '_create',
                         return_value=mock_client)
        self._test_stack_create(stack_name,
                                environment_files=environment_files,
                                files_container=files_container,
                                error=True)
        mock_client.get_container.assert_called_with(files_container)
        mock_client.get_object.assert_not_called()

    def test_stack_create_equals_max_per_tenant(self):
        cfg.CONF.set_override('max_stacks_per_tenant', 1)
        stack_name = 'service_create_test_stack_equals_max'
        self._test_stack_create(stack_name)

    def test_stack_create_exceeds_max_per_tenant(self):
        cfg.CONF.set_override('max_stacks_per_tenant', 0)
        stack_name = 'service_create_test_stack_exceeds_max'
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self._test_stack_create, stack_name)
        self.assertEqual(exception.RequestLimitExceeded, ex.exc_info[0])
        self.assertIn("You have reached the maximum stacks per tenant",
                      six.text_type(ex.exc_info[1]))

    @mock.patch.object(stack.Stack, 'validate')
    def test_stack_create_verify_err(self, mock_validate):
        mock_validate.side_effect = exception.StackValidationFailed(message='')

        stack_name = 'service_create_verify_err_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stk = tools.get_stack(stack_name, self.ctx)

        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack,
                               self.ctx, stack_name, template, params,
                               None, {})
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])

        mock_tmpl.assert_called_once_with(template, files=None)
        mock_env.assert_called_once_with(params)
        mock_stack.assert_called_once_with(
            self.ctx, stack_name, stk.t, owner_id=None, nested_depth=0,
            user_creds_id=None, stack_user_project_id=None,
            convergence=cfg.CONF.convergence_engine, parent_resource=None)

    def test_stack_create_invalid_stack_name(self):
        stack_name = 'service_create_test_stack_invalid_name'
        stack = tools.get_stack('test_stack', self.ctx)

        self.assertRaises(dispatcher.ExpectedException,
                          self.man.create_stack,
                          self.ctx, stack_name, stack.t.t, {}, None, {})

    def test_stack_create_invalid_resource_name(self):
        stack_name = 'stack_create_invalid_resource_name'
        stk = tools.get_stack(stack_name, self.ctx)
        tmpl = dict(stk.t)
        tmpl['resources']['Web/Server'] = tmpl['resources']['WebServer']
        del tmpl['resources']['WebServer']

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack,
                               self.ctx, stack_name,
                               stk.t.t, {}, None, {})
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])

    @mock.patch.object(stack.Stack, 'create_stack_user_project_id')
    def test_stack_create_authorization_failure(self, mock_create):
        stack_name = 'stack_create_authorization_failure'
        stk = tools.get_stack(stack_name, self.ctx)
        mock_create.side_effect = exception.AuthorizationFailure
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack,
                               self.ctx, stack_name,
                               stk.t.t, {}, None, {})
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])

    def test_stack_create_no_credentials(self):
        cfg.CONF.set_default('deferred_auth_method', 'password')
        stack_name = 'test_stack_create_no_credentials'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stk = tools.get_stack(stack_name, self.ctx)
        # force check for credentials on create
        stk['WebServer'].requires_deferred_auth = True

        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)

        # test stack create using context without password
        ctx_no_pwd = utils.dummy_context(password=None)
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack,
                               ctx_no_pwd, stack_name,
                               template, params, None, {}, None)
        self.assertEqual(exception.MissingCredentialError, ex.exc_info[0])
        self.assertEqual('Missing required credential: X-Auth-Key',
                         six.text_type(ex.exc_info[1]))

        mock_tmpl.assert_called_once_with(template, files=None)
        mock_env.assert_called_once_with(params)
        mock_stack.assert_called_once_with(
            ctx_no_pwd, stack_name, stk.t, owner_id=None, nested_depth=0,
            user_creds_id=None, stack_user_project_id=None,
            convergence=cfg.CONF.convergence_engine, parent_resource=None)
        mock_tmpl.reset_mock()
        mock_env.reset_mock()
        mock_stack.reset_mock()

        # test stack create using context without user
        ctx_no_pwd = utils.dummy_context(password=None)
        ctx_no_user = utils.dummy_context(user=None)
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack,
                               ctx_no_user, stack_name,
                               template, params, None, {})
        self.assertEqual(exception.MissingCredentialError, ex.exc_info[0])
        self.assertEqual('Missing required credential: X-Auth-User',
                         six.text_type(ex.exc_info[1]))

        mock_tmpl.assert_called_once_with(template, files=None)
        mock_env.assert_called_once_with(params)
        mock_stack.assert_called_once_with(
            ctx_no_user, stack_name, stk.t, owner_id=None, nested_depth=0,
            user_creds_id=None, stack_user_project_id=None,
            convergence=cfg.CONF.convergence_engine, parent_resource=None)

    @mock.patch.object(stack_object.Stack, 'count_total_resources')
    def test_stack_create_total_resources_equals_max(self, ctr):
        stack_name = 'stack_create_total_resources_equals_max'
        params = {}
        tpl = {
            'heat_template_version': '2014-10-16',
            'resources': {
                'A': {'type': 'GenericResourceType'},
                'B': {'type': 'GenericResourceType'},
                'C': {'type': 'GenericResourceType'}
            }
        }

        template = templatem.Template(tpl)
        stk = stack.Stack(self.ctx, stack_name, template)
        ctr.return_value = 3

        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)

        cfg.CONF.set_override('max_resources_per_stack', 3)

        result = self.man.create_stack(self.ctx, stack_name, template, params,
                                       None, {})

        mock_tmpl.assert_called_once_with(template, files=None)
        mock_env.assert_called_once_with(params)
        mock_stack.assert_called_once_with(
            self.ctx, stack_name, stk.t, owner_id=None, nested_depth=0,
            user_creds_id=None, stack_user_project_id=None,
            convergence=cfg.CONF.convergence_engine, parent_resource=None)

        self.assertEqual(stk.identifier(), result)
        root_stack_id = stk.root_stack_id()
        self.assertEqual(3, stk.total_resources(root_stack_id))
        self.man.thread_group_mgr.groups[stk.id].wait()
        stk.delete()

    def test_stack_create_total_resources_exceeds_max(self):
        stack_name = 'stack_create_total_resources_exceeds_max'
        params = {}
        tpl = {
            'heat_template_version': '2014-10-16',
            'resources': {
                'A': {'type': 'GenericResourceType'},
                'B': {'type': 'GenericResourceType'},
                'C': {'type': 'GenericResourceType'}
            }
        }

        cfg.CONF.set_override('max_resources_per_stack', 2)
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack, self.ctx, stack_name,
                               tpl, params, None, {})
        self.assertEqual(exception.RequestLimitExceeded, ex.exc_info[0])
        self.assertIn(exception.StackResourceLimitExceeded.msg_fmt,
                      six.text_type(ex.exc_info[1]))

    @mock.patch.object(threadgroup, 'ThreadGroup')
    @mock.patch.object(stack.Stack, 'validate')
    def test_stack_create_nested(self, mock_validate, mock_tg):
        convergence_engine = cfg.CONF.convergence_engine
        stack_name = 'service_create_nested_test_stack'
        parent_stack = tools.get_stack(stack_name + '_parent', self.ctx)
        owner_id = parent_stack.store()
        mock_tg.return_value = tools.DummyThreadGroup()

        stk = tools.get_stack(stack_name, self.ctx, with_params=True,
                              owner_id=owner_id, nested_depth=1)
        tmpl_id = stk.t.store(self.ctx)

        mock_load = self.patchobject(templatem.Template, 'load',
                                     return_value=stk.t)
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)
        result = self.man.create_stack(self.ctx, stack_name, None,
                                       None, None, {},
                                       owner_id=owner_id, nested_depth=1,
                                       template_id=tmpl_id)
        self.assertEqual(stk.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])

        mock_load.assert_called_once_with(self.ctx, tmpl_id)
        mock_stack.assert_called_once_with(self.ctx, stack_name, stk.t,
                                           owner_id=owner_id, nested_depth=1,
                                           user_creds_id=None,
                                           stack_user_project_id=None,
                                           convergence=convergence_engine,
                                           parent_resource=None)

        mock_validate.assert_called_once_with()

    def test_stack_validate(self):
        stack_name = 'stack_create_test_validate'
        stk = tools.get_stack(stack_name, self.ctx)

        fc = fakes_nova.FakeClient()
        self.patchobject(nova.NovaClientPlugin, 'client', return_value=fc)
        self.patchobject(glance.GlanceClientPlugin, 'find_image_by_name_or_id',
                         return_value=744)

        resource = stk['WebServer']
        resource.properties = properties.Properties(
            resource.properties_schema,
            {
                'ImageId': 'CentOS 5.2',
                'KeyName': 'test',
                'InstanceType': 'm1.large'
            },
            context=self.ctx)
        stk.validate()

        resource.properties = properties.Properties(
            resource.properties_schema,
            {
                'KeyName': 'test',
                'InstanceType': 'm1.large'
            },
            context=self.ctx)
        self.assertRaises(exception.StackValidationFailed, stk.validate)

    def test_validate_deferred_auth_context_trusts(self):
        stk = tools.get_stack('test_deferred_auth', self.ctx)
        stk['WebServer'].requires_deferred_auth = True
        ctx = utils.dummy_context(user=None, password=None)
        cfg.CONF.set_default('deferred_auth_method', 'trusts')

        # using trusts, no username or password required
        self.man._validate_deferred_auth_context(ctx, stk)

    def test_validate_deferred_auth_context_not_required(self):
        stk = tools.get_stack('test_deferred_auth', self.ctx)
        stk['WebServer'].requires_deferred_auth = False
        ctx = utils.dummy_context(user=None, password=None)
        cfg.CONF.set_default('deferred_auth_method', 'password')

        # stack performs no deferred operations, so no username or
        # password required
        self.man._validate_deferred_auth_context(ctx, stk)

    def test_validate_deferred_auth_context_missing_credentials(self):
        stk = tools.get_stack('test_deferred_auth', self.ctx)
        stk['WebServer'].requires_deferred_auth = True
        cfg.CONF.set_default('deferred_auth_method', 'password')

        # missing username
        ctx = utils.dummy_context(user=None)
        ex = self.assertRaises(exception.MissingCredentialError,
                               self.man._validate_deferred_auth_context,
                               ctx, stk)
        self.assertEqual('Missing required credential: X-Auth-User',
                         six.text_type(ex))

        # missing password
        ctx = utils.dummy_context(password=None)
        ex = self.assertRaises(exception.MissingCredentialError,
                               self.man._validate_deferred_auth_context,
                               ctx, stk)
        self.assertEqual('Missing required credential: X-Auth-Key',
                         six.text_type(ex))

    @mock.patch.object(instances.Instance, 'validate')
    @mock.patch.object(stack.Stack, 'total_resources')
    def test_stack_create_max_unlimited(self, total_res_mock, validate_mock):
        total_res_mock.return_value = 9999
        validate_mock.return_value = None
        cfg.CONF.set_override('max_resources_per_stack', -1)
        stack_name = 'service_create_test_max_unlimited'
        self._test_stack_create(stack_name)
