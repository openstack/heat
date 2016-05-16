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

import uuid

from eventlet import event as grevent
import mock
from oslo_config import cfg
from oslo_messaging.rpc import dispatcher
import six

from heat.common import exception
from heat.common import messaging
from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine import resource
from heat.engine import service
from heat.engine import stack
from heat.engine import stack_lock
from heat.engine import template as templatem
from heat.objects import stack as stack_object
from heat.rpc import api as rpc_api
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import utils


class ServiceStackUpdateTest(common.HeatTestCase):

    def setUp(self):
        super(ServiceStackUpdateTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.thread_group_mgr = tools.DummyThreadGroupManager()

    def test_stack_update(self):
        stack_name = 'service_update_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        old_stack = tools.get_stack(stack_name, self.ctx)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        stk = tools.get_stack(stack_name, self.ctx)

        # prepare mocks
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)
        mock_load = self.patchobject(stack.Stack, 'load',
                                     return_value=old_stack)
        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)

        mock_validate = self.patchobject(stk, 'validate', return_value=None)
        event_mock = mock.Mock()
        self.patchobject(grevent, 'Event', return_value=event_mock)

        # do update
        api_args = {'timeout_mins': 60}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)

        # assertions
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.assertEqual([event_mock], self.man.thread_group_mgr.events)
        mock_tmpl.assert_called_once_with(template, files=None, env=stk.env)
        mock_env.assert_called_once_with(params)
        mock_stack.assert_called_once_with(
            self.ctx, stk.name, stk.t,
            convergence=False,
            current_traversal=old_stack.current_traversal,
            prev_raw_template_id=None,
            current_deps=None,
            disable_rollback=True,
            nested_depth=0,
            owner_id=None,
            parent_resource=None,
            stack_user_project_id='1234',
            strict_validate=True,
            tenant_id='test_tenant_id',
            timeout_mins=60,
            user_creds_id=u'1',
            username='test_username')
        mock_load.assert_called_once_with(self.ctx, stack=s)
        mock_validate.assert_called_once_with()

    def test_stack_update_with_environment_files(self):
        # Setup
        stack_name = 'service_update_env_files_stack'
        params = {}
        template = '{ "Template": "data" }'
        old_stack = tools.get_stack(stack_name, self.ctx)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        stack_object.Stack.get_by_id(self.ctx, sid)

        stk = tools.get_stack(stack_name, self.ctx)

        # prepare mocks
        self.patchobject(stack, 'Stack', return_value=stk)
        self.patchobject(stack.Stack, 'load', return_value=old_stack)
        self.patchobject(templatem, 'Template', return_value=stk.t)
        self.patchobject(environment, 'Environment', return_value=stk.env)
        self.patchobject(stk, 'validate', return_value=None)
        self.patchobject(grevent, 'Event', return_value=mock.Mock())

        mock_merge = self.patchobject(self.man, '_merge_environments')

        # Test
        environment_files = ['env_1']
        self.man.update_stack(self.ctx, old_stack.identifier(),
                              template, params, None, {},
                              environment_files=environment_files)

        # Verify
        mock_merge.assert_called_once_with(environment_files, None, params)

    def test_stack_update_nested(self):
        stack_name = 'service_update_nested_test_stack'
        old_stack = tools.get_stack(stack_name, self.ctx)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        stk = tools.get_stack(stack_name, self.ctx)
        tmpl_id = stk.t.store()

        # prepare mocks
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)
        mock_load = self.patchobject(stack.Stack, 'load',
                                     return_value=old_stack)
        mock_tmpl = self.patchobject(templatem.Template, 'load',
                                     return_value=stk.t)

        mock_validate = self.patchobject(stk, 'validate', return_value=None)
        event_mock = mock.Mock()
        self.patchobject(grevent, 'Event', return_value=event_mock)

        # do update
        api_args = {'timeout_mins': 60}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       None, None, None, api_args,
                                       template_id=tmpl_id)

        # assertions
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.assertEqual([event_mock], self.man.thread_group_mgr.events)
        mock_tmpl.assert_called_once_with(self.ctx, tmpl_id)
        mock_stack.assert_called_once_with(
            self.ctx, stk.name, stk.t,
            convergence=False,
            current_traversal=old_stack.current_traversal,
            prev_raw_template_id=None,
            current_deps=None,
            disable_rollback=True,
            nested_depth=0,
            owner_id=None,
            parent_resource=None,
            stack_user_project_id='1234',
            strict_validate=True,
            tenant_id='test_tenant_id',
            timeout_mins=60,
            user_creds_id=u'1',
            username='test_username')
        mock_load.assert_called_once_with(self.ctx, stack=s)
        mock_validate.assert_called_once_with()

    def test_stack_update_existing_parameters(self):
        # Use a template with existing parameters, then update the stack
        # with a template containing additional parameters and ensure all
        # are preserved.

        stack_name = 'service_update_test_stack_existing_parameters'
        update_params = {'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'parameters': {'newparam': 123},
                         'resource_registry': {'resources': {}}}
        api_args = {rpc_api.PARAM_TIMEOUT: 60,
                    rpc_api.PARAM_EXISTING: True}
        t = template_format.parse(tools.wp_template)

        stk = tools.get_stack(stack_name, self.ctx, with_params=True)
        stk.store()
        stk.set_stack_user_project_id('1234')
        self.assertEqual({'KeyName': 'test'}, stk.t.env.params)

        t['parameters']['newparam'] = {'type': 'number'}
        with mock.patch('heat.engine.stack.Stack') as mock_stack:
            stk.update = mock.Mock()
            mock_stack.load.return_value = stk
            mock_stack.validate.return_value = None
            result = self.man.update_stack(self.ctx, stk.identifier(),
                                           t,
                                           update_params,
                                           None, api_args)
            tmpl = mock_stack.call_args[0][2]
            self.assertEqual({'KeyName': 'test', 'newparam': 123},
                             tmpl.env.params)
            self.assertEqual(stk.identifier(), result)

    def test_stack_update_existing_parameters_remove(self):
        """Test case for updating stack with changed parameters.

        Use a template with existing parameters, then update with a
        template containing additional parameters and a list of
        parameters to be removed.
        """
        stack_name = 'service_update_test_stack_existing_parameters_remove'
        update_params = {'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'event_sinks': [],
                         'parameters': {'newparam': 123},
                         'resource_registry': {'resources': {}}}
        api_args = {rpc_api.PARAM_TIMEOUT: 60,
                    rpc_api.PARAM_EXISTING: True,
                    rpc_api.PARAM_CLEAR_PARAMETERS: ['removeme']}
        t = template_format.parse(tools.wp_template)
        t['parameters']['removeme'] = {'type': 'string'}

        stk = utils.parse_stack(t, stack_name=stack_name,
                                params={'KeyName': 'test', 'removeme': 'foo'})
        stk.set_stack_user_project_id('1234')
        self.assertEqual({'KeyName': 'test', 'removeme': 'foo'},
                         stk.t.env.params)

        t['parameters']['newparam'] = {'type': 'number'}
        with mock.patch('heat.engine.stack.Stack') as mock_stack:
            stk.update = mock.Mock()
            mock_stack.load.return_value = stk
            mock_stack.validate.return_value = None
            result = self.man.update_stack(self.ctx, stk.identifier(),
                                           t,
                                           update_params,
                                           None, api_args)
            tmpl = mock_stack.call_args[0][2]
            self.assertEqual({'KeyName': 'test', 'newparam': 123},
                             tmpl.env.params)
            self.assertEqual(stk.identifier(), result)

    def test_stack_update_existing_registry(self):
        # Use a template with existing flag and ensure the
        # environment registry is preserved.

        stack_name = 'service_update_test_stack_existing_registry'
        intital_registry = {'OS::Foo': 'foo.yaml',
                            'OS::Foo2': 'foo2.yaml',
                            'resources': {
                                'myserver': {'OS::Server': 'myserver.yaml'}}}
        intial_params = {'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'parameters': {},
                         'event_sinks': [],
                         'resource_registry': intital_registry}
        initial_files = {'foo.yaml': 'foo',
                         'foo2.yaml': 'foo2',
                         'myserver.yaml': 'myserver'}
        update_registry = {'OS::Foo2': 'newfoo2.yaml',
                           'resources': {
                               'myother': {'OS::Other': 'myother.yaml'}}}
        update_params = {'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'parameters': {},
                         'resource_registry': update_registry}
        update_files = {'newfoo2.yaml': 'newfoo',
                        'myother.yaml': 'myother'}
        api_args = {rpc_api.PARAM_TIMEOUT: 60,
                    rpc_api.PARAM_EXISTING: True}
        t = template_format.parse(tools.wp_template)

        stk = utils.parse_stack(t, stack_name=stack_name, params=intial_params,
                                files=initial_files)
        stk.set_stack_user_project_id('1234')
        self.assertEqual(intial_params, stk.t.env.user_env_as_dict())

        expected_reg = {'OS::Foo': 'foo.yaml',
                        'OS::Foo2': 'newfoo2.yaml',
                        'resources': {
                            'myother': {'OS::Other': 'myother.yaml'},
                            'myserver': {'OS::Server': 'myserver.yaml'}}}
        expected_env = {'encrypted_param_names': [],
                        'parameter_defaults': {},
                        'parameters': {},
                        'event_sinks': [],
                        'resource_registry': expected_reg}
        # FIXME(shardy): Currently we don't prune unused old files
        expected_files = {'foo.yaml': 'foo',
                          'foo2.yaml': 'foo2',
                          'myserver.yaml': 'myserver',
                          'newfoo2.yaml': 'newfoo',
                          'myother.yaml': 'myother'}
        with mock.patch('heat.engine.stack.Stack') as mock_stack:
            stk.update = mock.Mock()
            mock_stack.load.return_value = stk
            mock_stack.validate.return_value = None
            result = self.man.update_stack(self.ctx, stk.identifier(),
                                           t,
                                           update_params,
                                           update_files,
                                           api_args)
            tmpl = mock_stack.call_args[0][2]
            self.assertEqual(expected_env,
                             tmpl.env.user_env_as_dict())
            self.assertEqual(expected_files,
                             tmpl.files)
            self.assertEqual(stk.identifier(), result)

    def test_stack_update_existing_parameter_defaults(self):
        """Ensure the environment parameter_defaults are preserved.

        Use a template with existing flag and ensure the environment
        parameter_defaults are preserved.
        """
        stack_name = 'service_update_test_stack_existing_param_defaults'
        intial_params = {'encrypted_param_names': [],
                         'parameter_defaults': {'mydefault': 123},
                         'parameters': {},
                         'resource_registry': {}}
        update_params = {'encrypted_param_names': [],
                         'parameter_defaults': {'default2': 456},
                         'parameters': {},
                         'resource_registry': {}}
        api_args = {rpc_api.PARAM_TIMEOUT: 60,
                    rpc_api.PARAM_EXISTING: True}
        t = template_format.parse(tools.wp_template)

        stk = utils.parse_stack(t, stack_name=stack_name, params=intial_params)
        stk.set_stack_user_project_id('1234')

        expected_env = {'encrypted_param_names': [],
                        'parameter_defaults': {
                            'mydefault': 123,
                            'default2': 456},
                        'parameters': {},
                        'event_sinks': [],
                        'resource_registry': {'resources': {}}}
        with mock.patch('heat.engine.stack.Stack') as mock_stack:
            stk.update = mock.Mock()
            mock_stack.load.return_value = stk
            mock_stack.validate.return_value = None
            result = self.man.update_stack(self.ctx, stk.identifier(),
                                           t,
                                           update_params,
                                           None, api_args)
            tmpl = mock_stack.call_args[0][2]
            self.assertEqual(expected_env,
                             tmpl.env.user_env_as_dict())
            self.assertEqual(stk.identifier(), result)

    def test_stack_update_reuses_api_params(self):
        stack_name = 'service_update_stack_reuses_api_params'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = tools.get_stack(stack_name, self.ctx)
        old_stack.timeout_mins = 1
        old_stack.disable_rollback = False
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)
        stk = tools.get_stack(stack_name, self.ctx)

        # prepare mocks
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)
        mock_load = self.patchobject(stack.Stack, 'load',
                                     return_value=old_stack)
        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)
        mock_validate = self.patchobject(stk, 'validate', return_value=None)

        # do update
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, {})

        # assertions
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])

        mock_validate.assert_called_once_with()
        mock_tmpl.assert_called_once_with(template, files=None, env=stk.env)
        mock_env.assert_called_once_with(params)
        mock_load.assert_called_once_with(self.ctx, stack=s)
        mock_stack.assert_called_once_with(
            self.ctx, stk.name, stk.t,
            convergence=False,
            current_traversal=old_stack.current_traversal,
            prev_raw_template_id=None, current_deps=None,
            disable_rollback=False, nested_depth=0,
            owner_id=None, parent_resource=None,
            stack_user_project_id='1234',
            strict_validate=True,
            tenant_id='test_tenant_id', timeout_mins=1,
            user_creds_id=u'1',
            username='test_username')

    def test_stack_cancel_update_same_engine(self):
        stack_name = 'service_update_stack_test_cancel_same_engine'
        stk = tools.get_stack(stack_name, self.ctx)
        stk.state_set(stk.UPDATE, stk.IN_PROGRESS, 'test_override')
        stk.disable_rollback = False
        stk.store()

        self.patchobject(stack.Stack, 'load', return_value=stk)
        self.patchobject(stack_lock.StackLock, 'try_acquire',
                         return_value=self.man.engine_id)
        self.patchobject(self.man.thread_group_mgr, 'send')

        self.man.stack_cancel_update(self.ctx, stk.identifier(),
                                     cancel_with_rollback=False)

        self.man.thread_group_mgr.send.assert_called_once_with(stk.id,
                                                               'cancel')

    def test_stack_cancel_update_different_engine(self):
        stack_name = 'service_update_stack_test_cancel_different_engine'
        stk = tools.get_stack(stack_name, self.ctx)
        stk.state_set(stk.UPDATE, stk.IN_PROGRESS, 'test_override')
        stk.disable_rollback = False
        stk.store()
        self.patchobject(stack.Stack, 'load', return_value=stk)
        self.patchobject(stack_lock.StackLock, 'try_acquire',
                         return_value=str(uuid.uuid4()))
        self.patchobject(stack_lock.StackLock, 'engine_alive',
                         return_value=True)
        self.man.listener = mock.Mock()
        self.man.listener.SEND = 'send'
        self.man._client = messaging.get_rpc_client(
            version=self.man.RPC_API_VERSION)

        # In fact the another engine is not alive, so the call will timeout
        self.assertRaises(dispatcher.ExpectedException,
                          self.man.stack_cancel_update,
                          self.ctx, stk.identifier())

    def test_stack_cancel_update_wrong_state_fails(self):
        stack_name = 'service_update_cancel_test_stack'
        stk = tools.get_stack(stack_name, self.ctx)
        stk.state_set(stk.UPDATE, stk.COMPLETE, 'test_override')
        stk.store()
        self.patchobject(stack.Stack, 'load', return_value=stk)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.stack_cancel_update,
                               self.ctx, stk.identifier())

        self.assertEqual(exception.NotSupported, ex.exc_info[0])
        self.assertIn("Cancelling update when stack is "
                      "UPDATE_COMPLETE",
                      six.text_type(ex.exc_info[1]))

    @mock.patch.object(stack_object.Stack, 'count_total_resources')
    def test_stack_update_equals(self, ctr):
        stack_name = 'test_stack_update_equals_resource_limit'
        params = {}
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources': {
                   'A': {'Type': 'GenericResourceType'},
                   'B': {'Type': 'GenericResourceType'},
                   'C': {'Type': 'GenericResourceType'}}}

        template = templatem.Template(tpl)

        old_stack = stack.Stack(self.ctx, stack_name, template)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)
        ctr.return_value = 3

        stk = stack.Stack(self.ctx, stack_name, template)

        # prepare mocks
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)
        mock_load = self.patchobject(stack.Stack, 'load',
                                     return_value=old_stack)
        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)
        mock_validate = self.patchobject(stk, 'validate', return_value=None)

        # do update
        cfg.CONF.set_override('max_resources_per_stack', 3, enforce_type=True)

        api_args = {'timeout_mins': 60}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)

        # assertions
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        root_stack_id = old_stack.root_stack_id()
        self.assertEqual(3, old_stack.total_resources(root_stack_id))

        mock_tmpl.assert_called_once_with(template, files=None, env=stk.env)
        mock_env.assert_called_once_with(params)
        mock_stack.assert_called_once_with(
            self.ctx, stk.name, stk.t,
            convergence=False,
            current_traversal=old_stack.current_traversal,
            prev_raw_template_id=None, current_deps=None,
            disable_rollback=True, nested_depth=0,
            owner_id=None, parent_resource=None,
            stack_user_project_id='1234', strict_validate=True,
            tenant_id='test_tenant_id',
            timeout_mins=60, user_creds_id=u'1',
            username='test_username')
        mock_load.assert_called_once_with(self.ctx, stack=s)
        mock_validate.assert_called_once_with()

    def test_stack_update_stack_id_equal(self):
        stack_name = 'test_stack_update_stack_id_equal'
        tpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'A': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Ref': 'AWS::StackId'}
                    }
                }
            }
        }
        template = templatem.Template(tpl)
        create_stack = stack.Stack(self.ctx, stack_name, template)
        sid = create_stack.store()
        create_stack.create()
        self.assertEqual((create_stack.CREATE, create_stack.COMPLETE),
                         create_stack.state)
        create_stack._persist_state()
        s = stack_object.Stack.get_by_id(self.ctx, sid)
        old_stack = stack.Stack.load(self.ctx, stack=s)

        self.assertEqual((old_stack.CREATE, old_stack.COMPLETE),
                         old_stack.state)
        self.assertEqual(create_stack.identifier().arn(),
                         old_stack['A'].properties['Foo'])

        mock_load = self.patchobject(stack.Stack, 'load',
                                     return_value=old_stack)

        result = self.man.update_stack(self.ctx, create_stack.identifier(),
                                       tpl, {}, None, {})

        old_stack._persist_state()
        self.assertEqual((old_stack.UPDATE, old_stack.COMPLETE),
                         old_stack.state)
        self.assertEqual(create_stack.identifier(), result)
        self.assertIsNotNone(create_stack.identifier().stack_id)
        self.assertEqual(create_stack.identifier().arn(),
                         old_stack['A'].properties['Foo'])

        self.assertEqual(create_stack['A'].id, old_stack['A'].id)
        mock_load.assert_called_once_with(self.ctx, stack=s)

    def test_stack_update_exceeds_resource_limit(self):
        stack_name = 'test_stack_update_exceeds_resource_limit'
        params = {}
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources': {
                   'A': {'Type': 'GenericResourceType'},
                   'B': {'Type': 'GenericResourceType'},
                   'C': {'Type': 'GenericResourceType'}}}

        template = templatem.Template(tpl)
        old_stack = stack.Stack(self.ctx, stack_name, template)
        sid = old_stack.store()
        self.assertIsNotNone(sid)

        cfg.CONF.set_override('max_resources_per_stack', 2, enforce_type=True)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack, self.ctx,
                               old_stack.identifier(), tpl, params,
                               None, {})
        self.assertEqual(exception.RequestLimitExceeded, ex.exc_info[0])
        self.assertIn(exception.StackResourceLimitExceeded.msg_fmt,
                      six.text_type(ex.exc_info[1]))

    def test_stack_update_verify_err(self):
        stack_name = 'service_update_verify_err_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = tools.get_stack(stack_name, self.ctx)
        old_stack.store()
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)
        stk = tools.get_stack(stack_name, self.ctx)

        # prepare mocks
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)
        mock_load = self.patchobject(stack.Stack, 'load',
                                     return_value=old_stack)
        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)
        ex_expected = exception.StackValidationFailed(message='fubar')
        mock_validate = self.patchobject(stk, 'validate',
                                         side_effect=ex_expected)
        # do update
        api_args = {'timeout_mins': 60}
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack,
                               self.ctx, old_stack.identifier(),
                               template, params, None, api_args)

        # assertions
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])
        mock_tmpl.assert_called_once_with(template, files=None, env=stk.env)
        mock_env.assert_called_once_with(params)
        mock_stack.assert_called_once_with(
            self.ctx, stk.name, stk.t,
            convergence=False,
            current_traversal=old_stack.current_traversal,
            prev_raw_template_id=None, current_deps=None,
            disable_rollback=True, nested_depth=0,
            owner_id=None, parent_resource=None,
            stack_user_project_id='1234', strict_validate=True,
            tenant_id='test_tenant_id',
            timeout_mins=60, user_creds_id=u'1',
            username='test_username')
        mock_load.assert_called_once_with(self.ctx, stack=s)
        mock_validate.assert_called_once_with()

    def test_stack_update_nonexist(self):
        stack_name = 'service_update_nonexist_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        stk = tools.get_stack(stack_name, self.ctx)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack,
                               self.ctx, stk.identifier(), template,
                               params, None, {})
        self.assertEqual(exception.EntityNotFound, ex.exc_info[0])

    def test_stack_update_no_credentials(self):
        cfg.CONF.set_default('deferred_auth_method', 'password')
        stack_name = 'test_stack_update_no_credentials'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stk = tools.get_stack(stack_name, self.ctx)
        # force check for credentials on create
        stk['WebServer'].requires_deferred_auth = True

        sid = stk.store()
        stk.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        self.ctx = utils.dummy_context(password=None)

        # prepare mocks
        mock_get = self.patchobject(self.man, '_get_stack', return_value=s)
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)
        mock_load = self.patchobject(stack.Stack, 'load', return_value=stk)
        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)

        api_args = {'timeout_mins': 60}
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack, self.ctx,
                               stk.identifier(),
                               template, params, None, api_args)
        self.assertEqual(exception.MissingCredentialError, ex.exc_info[0])
        self.assertEqual('Missing required credential: X-Auth-Key',
                         six.text_type(ex.exc_info[1]))

        mock_get.assert_called_once_with(self.ctx, stk.identifier())

        mock_tmpl.assert_called_once_with(template, files=None, env=stk.env)
        mock_env.assert_called_once_with(params)
        mock_stack.assert_called_once_with(
            self.ctx, stk.name, stk.t,
            convergence=False, current_traversal=stk.current_traversal,
            prev_raw_template_id=None, current_deps=None,
            disable_rollback=True, nested_depth=0,
            owner_id=None, parent_resource=None,
            stack_user_project_id='1234',
            strict_validate=True,
            tenant_id='test_tenant_id', timeout_mins=60,
            user_creds_id=u'1', username='test_username')
        mock_load.assert_called_once_with(self.ctx, stack=s)

    def test_stack_update_existing_template(self):
        '''Update a stack using the same template.'''
        stack_name = 'service_update_test_stack_existing_template'
        api_args = {rpc_api.PARAM_TIMEOUT: 60,
                    rpc_api.PARAM_EXISTING: True}
        t = template_format.parse(tools.wp_template)
        # Don't actually run the update as the mocking breaks it, instead
        # we just ensure the expected template is passed in to the updated
        # template, and that the update task is scheduled.
        self.man.thread_group_mgr = tools.DummyThreadGroupMgrLogStart()

        params = {}
        stack = utils.parse_stack(t, stack_name=stack_name,
                                  params=params)
        stack.set_stack_user_project_id('1234')
        self.assertEqual(t, stack.t.t)
        stack.action = stack.CREATE
        stack.status = stack.COMPLETE

        with mock.patch('heat.engine.stack.Stack') as mock_stack:
            mock_stack.load.return_value = stack
            mock_stack.validate.return_value = None
            result = self.man.update_stack(self.ctx, stack.identifier(),
                                           None,
                                           params,
                                           None, api_args)
            tmpl = mock_stack.call_args[0][2]
            self.assertEqual(t,
                             tmpl.t)
            self.assertEqual(stack.identifier(), result)
            self.assertEqual(1, len(self.man.thread_group_mgr.started))

    def test_stack_update_existing_failed(self):
        '''Update a stack using the same template doesn't work when FAILED.'''
        stack_name = 'service_update_test_stack_existing_template'
        api_args = {rpc_api.PARAM_TIMEOUT: 60,
                    rpc_api.PARAM_EXISTING: True}
        t = template_format.parse(tools.wp_template)
        # Don't actually run the update as the mocking breaks it, instead
        # we just ensure the expected template is passed in to the updated
        # template, and that the update task is scheduled.
        self.man.thread_group_mgr = tools.DummyThreadGroupMgrLogStart()

        params = {}
        stack = utils.parse_stack(t, stack_name=stack_name,
                                  params=params)
        stack.set_stack_user_project_id('1234')
        self.assertEqual(t, stack.t.t)
        stack.action = stack.UPDATE
        stack.status = stack.FAILED

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack,
                               self.ctx, stack.identifier(),
                               None, params, None, api_args)

        self.assertEqual(exception.NotSupported, ex.exc_info[0])
        self.assertIn("PATCH update to non-COMPLETE stack",
                      six.text_type(ex.exc_info[1]))

    def test_update_immutable_parameter_disallowed(self):

        template = '''
heat_template_version: 2014-10-16
parameters:
  param1:
    type: string
    immutable: true
    default: foo
'''

        self.ctx = utils.dummy_context(password=None)
        stack_name = 'test_update_immutable_parameters'
        old_stack = tools.get_stack(stack_name, self.ctx,
                                    template=template)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        # prepare mocks
        self.patchobject(self.man, '_get_stack', return_value=s)
        self.patchobject(stack, 'Stack', return_value=old_stack)
        self.patchobject(stack.Stack, 'load', return_value=old_stack)

        params = {'param1': 'bar'}
        exc = self.assertRaises(dispatcher.ExpectedException,
                                self.man.update_stack,
                                self.ctx, old_stack.identifier(),
                                old_stack.t.t, params,
                                None, {})
        self.assertEqual(exception.ImmutableParameterModified, exc.exc_info[0])
        self.assertEqual('The following parameters are immutable and may not '
                         'be updated: param1', exc.exc_info[1].message)

    def test_update_mutable_parameter_allowed(self):

        template = '''
heat_template_version: 2014-10-16
parameters:
  param1:
    type: string
    immutable: false
    default: foo
'''

        self.ctx = utils.dummy_context(password=None)
        stack_name = 'test_update_immutable_parameters'
        params = {}
        old_stack = tools.get_stack(stack_name, self.ctx,
                                    template=template)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        # prepare mocks
        self.patchobject(self.man, '_get_stack', return_value=s)
        self.patchobject(stack, 'Stack', return_value=old_stack)
        self.patchobject(stack.Stack, 'load', return_value=old_stack)
        self.patchobject(templatem, 'Template', return_value=old_stack.t)
        self.patchobject(environment, 'Environment',
                         return_value=old_stack.env)

        params = {'param1': 'bar'}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       templatem.Template(template), params,
                                       None, {})
        self.assertEqual(s.id, result['stack_id'])

    def test_update_immutable_parameter_same_value(self):

        template = '''
heat_template_version: 2014-10-16
parameters:
  param1:
    type: string
    immutable: true
    default: foo
'''

        self.ctx = utils.dummy_context(password=None)
        stack_name = 'test_update_immutable_parameters'
        params = {}
        old_stack = tools.get_stack(stack_name, self.ctx,
                                    template=template)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        # prepare mocks
        self.patchobject(self.man, '_get_stack', return_value=s)
        self.patchobject(stack, 'Stack', return_value=old_stack)
        self.patchobject(stack.Stack, 'load', return_value=old_stack)
        self.patchobject(templatem, 'Template', return_value=old_stack.t)
        self.patchobject(environment, 'Environment',
                         return_value=old_stack.env)

        params = {'param1': 'foo'}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       templatem.Template(template), params,
                                       None, {})
        self.assertEqual(s.id, result['stack_id'])


class ServiceStackUpdatePreviewTest(common.HeatTestCase):

    old_tmpl = """
heat_template_version: 2014-10-16
resources:
  web_server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      key_name: test
      user_data: wordpress
    """

    new_tmpl = """
heat_template_version: 2014-10-16
resources:
  web_server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      key_name: test
      user_data: wordpress
  password:
    type: OS::Heat::RandomString
    properties:
      length: 8
    """

    def setUp(self):
        super(ServiceStackUpdatePreviewTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.thread_group_mgr = tools.DummyThreadGroupManager()

    def _test_stack_update_preview(self, orig_template, new_template,
                                   environment_files=None):
        stack_name = 'service_update_test_stack_preview'
        params = {'foo': 'bar'}

        def side_effect(*args):
            return 2 if args[0] == 'm1.small' else 1

        self.patchobject(nova.NovaClientPlugin, 'find_flavor_by_name_or_id',
                         side_effect=side_effect)
        self.patchobject(glance.GlanceClientPlugin, 'find_image_by_name_or_id',
                         return_value=1)
        old_stack = tools.get_stack(stack_name, self.ctx,
                                    template=orig_template)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        stk = tools.get_stack(stack_name, self.ctx, template=new_template)

        # prepare mocks
        mock_stack = self.patchobject(stack, 'Stack', return_value=stk)
        mock_load = self.patchobject(stack.Stack, 'load',
                                     return_value=old_stack)
        mock_tmpl = self.patchobject(templatem, 'Template', return_value=stk.t)
        mock_env = self.patchobject(environment, 'Environment',
                                    return_value=stk.env)
        mock_validate = self.patchobject(stk, 'validate', return_value=None)
        mock_merge = self.patchobject(self.man, '_merge_environments')

        # Patch _resolve_all_attributes or it tries to call novaclient
        self.patchobject(resource.Resource, '_resolve_all_attributes',
                         return_value=None)

        # do preview_update_stack
        api_args = {'timeout_mins': 60}
        result = self.man.preview_update_stack(
            self.ctx,
            old_stack.identifier(),
            new_template, params, None,
            api_args,
            environment_files=environment_files)

        # assertions
        mock_stack.assert_called_once_with(
            self.ctx, stk.name, stk.t, convergence=False,
            current_traversal=old_stack.current_traversal,
            prev_raw_template_id=None, current_deps=None,
            disable_rollback=True, nested_depth=0, owner_id=None,
            parent_resource=None, stack_user_project_id='1234',
            strict_validate=True, tenant_id='test_tenant_id', timeout_mins=60,
            user_creds_id=u'1', username='test_username')
        mock_load.assert_called_once_with(self.ctx, stack=s)
        mock_tmpl.assert_called_once_with(new_template, files=None,
                                          env=stk.env)
        mock_env.assert_called_once_with(params)
        mock_validate.assert_called_once_with()

        if environment_files:
            mock_merge.assert_called_once_with(environment_files, None, params)

        return result

    def test_stack_update_preview_added_unchanged(self):
        result = self._test_stack_update_preview(self.old_tmpl, self.new_tmpl)

        added = [x for x in result['added']][0]
        self.assertEqual('password', added['resource_name'])
        unchanged = [x for x in result['unchanged']][0]
        self.assertEqual('web_server', unchanged['resource_name'])
        self.assertNotEqual('None', unchanged['resource_identity']['stack_id'])

        empty_sections = ('deleted', 'replaced', 'updated')
        for section in empty_sections:
            section_contents = [x for x in result[section]]
            self.assertEqual([], section_contents)

    def test_stack_update_preview_replaced(self):
        # new template with a different key_name
        new_tmpl = self.old_tmpl.replace('test', 'test2')

        result = self._test_stack_update_preview(self.old_tmpl, new_tmpl)

        replaced = [x for x in result['replaced']][0]
        self.assertEqual('web_server', replaced['resource_name'])
        empty_sections = ('added', 'deleted', 'unchanged', 'updated')
        for section in empty_sections:
            section_contents = [x for x in result[section]]
            self.assertEqual([], section_contents)

    def test_stack_update_preview_replaced_type(self):
        # new template with a different type for web_server
        new_tmpl = self.old_tmpl.replace('OS::Nova::Server', 'OS::Heat::None')

        result = self._test_stack_update_preview(self.old_tmpl, new_tmpl)

        replaced = [x for x in result['replaced']][0]
        self.assertEqual('web_server', replaced['resource_name'])
        empty_sections = ('added', 'deleted', 'unchanged', 'updated')
        for section in empty_sections:
            section_contents = [x for x in result[section]]
            self.assertEqual([], section_contents)

    def test_stack_update_preview_updated(self):
        # new template changes to flavor of server
        new_tmpl = self.old_tmpl.replace('m1.large', 'm1.small')
        result = self._test_stack_update_preview(self.old_tmpl, new_tmpl)

        updated = [x for x in result['updated']][0]
        self.assertEqual('web_server', updated['resource_name'])
        empty_sections = ('added', 'deleted', 'unchanged', 'replaced')
        for section in empty_sections:
            section_contents = [x for x in result[section]]
            self.assertEqual([], section_contents)

    def test_stack_update_preview_deleted(self):
        # do the reverse direction, i.e. delete resources
        result = self._test_stack_update_preview(self.new_tmpl, self.old_tmpl)

        deleted = [x for x in result['deleted']][0]
        self.assertEqual('password', deleted['resource_name'])
        unchanged = [x for x in result['unchanged']][0]
        self.assertEqual('web_server', unchanged['resource_name'])
        empty_sections = ('added', 'updated', 'replaced')
        for section in empty_sections:
            section_contents = [x for x in result[section]]
            self.assertEqual([], section_contents)

    def test_stack_update_preview_with_environment_files(self):
        # Setup
        environment_files = ['env_1']

        # Test
        self._test_stack_update_preview(self.old_tmpl, self.new_tmpl,
                                        environment_files=environment_files)

        # Assertions done in _test_stack_update_preview
