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

import uuid

from eventlet import event as grevent
import mock
import mox
from oslo_config import cfg
from oslo_messaging.rpc import dispatcher
from oslo_serialization import jsonutils as json
import six

from heat.common import context
from heat.common import exception
from heat.common import identifier
from heat.common import messaging
from heat.common import template_format
from heat.engine.cfn import template as cfntemplate
from heat.engine import dependencies
from heat.engine import environment
from heat.engine.hot import functions as hot_functions
from heat.engine.hot import template as hottemplate
from heat.engine import resource as res
from heat.engine import service
from heat.engine import stack as parser
from heat.engine import stack_lock
from heat.engine import template as templatem
from heat.objects import stack as stack_object
from heat.rpc import api as rpc_api
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import generic_resource as generic_rsrc
from heat.tests.nova import fakes as fakes_nova
from heat.tests import utils

cfg.CONF.import_opt('engine_life_check_timeout', 'heat.common.config')
cfg.CONF.import_opt('enable_stack_abandon', 'heat.common.config')

wp_template_no_default = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''

policy_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "alarming",
  "Resources" : {
    "WebServerScaleDownPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : "",
        "Cooldown" : "60",
        "ScalingAdjustment" : "-1"
      }
    },
    "Random" : {
      "Type" : "OS::Heat::RandomString"
    }
  }
}
'''

user_policy_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a User",
  "Parameters" : {},
  "Resources" : {
    "CfnUser" : {
      "Type" : "AWS::IAM::User",
      "Properties" : {
        "Policies" : [ { "Ref": "WebServerAccessPolicy"} ]
      }
    },
    "WebServerAccessPolicy" : {
      "Type" : "OS::Heat::AccessPolicy",
      "Properties" : {
        "AllowedResources" : [ "WebServer" ]
      }
    },
    "HostKeys" : {
      "Type" : "AWS::IAM::AccessKey",
      "Properties" : {
        "UserName" : {"Ref": "CfnUser"}
      }
    },
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''

server_config_template = '''
heat_template_version: 2013-05-23
resources:
  WebServer:
    type: OS::Nova::Server
'''


class StackCreateTest(common.HeatTestCase):
    def setUp(self):
        super(StackCreateTest, self).setUp()

    def test_wordpress_single_instance_stack_create(self):
        stack = tools.get_stack('test_stack', utils.dummy_context())
        tools.setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()

        self.assertIsNotNone(stack['WebServer'])
        self.assertTrue(int(stack['WebServer'].resource_id) > 0)
        self.assertNotEqual(stack['WebServer'].ipaddress, '0.0.0.0')

    def test_wordpress_single_instance_stack_adopt(self):
        t = template_format.parse(tools.wp_template)
        template = templatem.Template(t)
        ctx = utils.dummy_context()
        adopt_data = {
            'resources': {
                'WebServer': {
                    'resource_id': 'test-res-id'
                }
            }
        }
        stack = parser.Stack(ctx,
                             'test_stack',
                             template,
                             adopt_stack_data=adopt_data)

        tools.setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.adopt()

        self.assertIsNotNone(stack['WebServer'])
        self.assertEqual('test-res-id', stack['WebServer'].resource_id)
        self.assertEqual((stack.ADOPT, stack.COMPLETE), stack.state)

    def test_wordpress_single_instance_stack_adopt_fail(self):
        t = template_format.parse(tools.wp_template)
        template = templatem.Template(t)
        ctx = utils.dummy_context()
        adopt_data = {
            'resources': {
                'WebServer1': {
                    'resource_id': 'test-res-id'
                }
            }
        }
        stack = parser.Stack(ctx,
                             'test_stack',
                             template,
                             adopt_stack_data=adopt_data)

        tools.setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.adopt()
        self.assertIsNotNone(stack['WebServer'])
        expected = ('Resource ADOPT failed: Exception: resources.WebServer: '
                    'Resource ID was not provided.')
        self.assertEqual(expected, stack.status_reason)
        self.assertEqual((stack.ADOPT, stack.FAILED), stack.state)

    def test_wordpress_single_instance_stack_delete(self):
        ctx = utils.dummy_context()
        stack = tools.get_stack('test_stack', ctx)
        fc = tools.setup_mocks(self.m, stack, mock_keystone=False)
        self.m.ReplayAll()
        stack_id = stack.store()
        stack.create()

        db_s = stack_object.Stack.get_by_id(ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.assertIsNotNone(stack['WebServer'])
        self.assertTrue(int(stack['WebServer'].resource_id) > 0)

        self.patchobject(fc.servers, 'delete',
                         side_effect=fakes_nova.fake_exception())
        stack.delete()

        rsrc = stack['WebServer']
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual((stack.DELETE, stack.COMPLETE), rsrc.state)
        self.assertIsNone(stack_object.Stack.get_by_id(ctx, stack_id))

        db_s.refresh()
        self.assertEqual('DELETE', db_s.action)
        self.assertEqual('COMPLETE', db_s.status, )


class StackServiceAdoptUpdateTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceAdoptUpdateTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.thread_group_mgr = tools.DummyThreadGroupManager()

    def _get_stack_adopt_data_and_template(self, environment=None):
        template = {
            "heat_template_version": "2013-05-23",
            "parameters": {"app_dbx": {"type": "string"}},
            "resources": {"res1": {"type": "GenericResourceType"}}}

        adopt_data = {
            "status": "COMPLETE",
            "name": "rtrove1",
            "environment": environment,
            "template": template,
            "action": "CREATE",
            "id": "8532f0d3-ea84-444e-b2bb-2543bb1496a4",
            "resources": {"res1": {
                    "status": "COMPLETE",
                    "name": "database_password",
                    "resource_id": "yBpuUROjfGQ2gKOD",
                    "action": "CREATE",
                    "type": "GenericResourceType",
                    "metadata": {}}}}
        return template, adopt_data

    def test_stack_adopt_with_params(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        environment = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_stack_adopt_data_and_template(
            environment)
        result = self.man.create_stack(self.ctx, "test_adopt_stack",
                                       template, {}, None,
                                       {'adopt_stack_data': str(adopt_data)})

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual(template, stack.raw_template.template)
        self.assertEqual(environment['parameters'],
                         stack.raw_template.environment['parameters'])

    def test_stack_adopt_saves_input_params(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        environment = {'parameters': {"app_dbx": "foo"}}
        input_params = {
            "parameters": {"app_dbx": "bar"}
        }
        template, adopt_data = self._get_stack_adopt_data_and_template(
            environment)
        result = self.man.create_stack(self.ctx, "test_adopt_stack",
                                       template, input_params, None,
                                       {'adopt_stack_data': str(adopt_data)})

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual(template, stack.raw_template.template)
        self.assertEqual(input_params['parameters'],
                         stack.raw_template.environment['parameters'])

    def test_stack_adopt_stack_state(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        env = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_stack_adopt_data_and_template(
            env)
        result = self.man.create_stack(self.ctx, "test_adopt_stack",
                                       template, {}, None,
                                       {'adopt_stack_data': str(adopt_data)})

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual((parser.Stack.ADOPT, parser.Stack.COMPLETE),
                         (stack.action, stack.status))

    def test_stack_adopt_disabled(self):
        # to test disable stack adopt
        cfg.CONF.set_override('enable_stack_adopt', False)
        environment = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_stack_adopt_data_and_template(
            environment)
        ex = self.assertRaises(
            dispatcher.ExpectedException,
            self.man.create_stack,
            self.ctx, "test_adopt_stack_disabled",
            template, {}, None,
            {'adopt_stack_data': str(adopt_data)})
        self.assertEqual(exception.NotSupported, ex.exc_info[0])
        self.assertIn('Stack Adopt', six.text_type(ex.exc_info[1]))

    def _stub_update_mocks(self, stack_to_load, stack_to_return):
        self.m.StubOutWithMock(parser, 'Stack')
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=stack_to_load
                          ).AndReturn(stack_to_return)

        self.m.StubOutWithMock(templatem, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')

    def test_stack_update(self):
        stack_name = 'service_update_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        old_stack = tools.get_stack(stack_name, self.ctx)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        stack = tools.get_stack(stack_name, self.ctx)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False,
                     current_traversal=None,
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
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        evt_mock = self.m.CreateMockAnything()
        self.m.StubOutWithMock(grevent, 'Event')
        grevent.Event().AndReturn(evt_mock)

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.assertEqual([evt_mock], self.man.thread_group_mgr.events)
        self.m.VerifyAll()

    def test_stack_update_existing_parameters(self):
        '''Use a template with existing parameters, then update with a
        template containing additional parameters and ensure all are preserved.
        '''
        stack_name = 'service_update_test_stack_existing_parameters'
        update_params = {'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'parameters': {'newparam': 123},
                         'resource_registry': {'resources': {}}}
        api_args = {rpc_api.PARAM_TIMEOUT: 60,
                    rpc_api.PARAM_EXISTING: True}
        t = template_format.parse(tools.wp_template)

        stack = tools.get_stack(stack_name, self.ctx, with_params=True)
        stack.store()
        stack.set_stack_user_project_id('1234')
        self.assertEqual({'KeyName': 'test'}, stack.t.env.params)

        with mock.patch('heat.engine.stack.Stack') as mock_stack:
            mock_stack.load.return_value = stack
            mock_stack.validate.return_value = None
            result = self.man.update_stack(self.ctx, stack.identifier(),
                                           t,
                                           update_params,
                                           None, api_args)
            tmpl = mock_stack.call_args[0][2]
            self.assertEqual({'KeyName': 'test', 'newparam': 123},
                             tmpl.env.params)
            self.assertEqual(stack.identifier(), result)

    def test_stack_update_existing_parameters_remove(self):
        '''Use a template with existing parameters, then update with a
        template containing additional parameters and a list of
        parameters to be removed.
        '''
        stack_name = 'service_update_test_stack_existing_parameters'
        update_params = {'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'parameters': {'newparam': 123},
                         'resource_registry': {'resources': {}}}
        api_args = {rpc_api.PARAM_TIMEOUT: 60,
                    rpc_api.PARAM_EXISTING: True,
                    rpc_api.PARAM_CLEAR_PARAMETERS: ['removeme']}
        t = template_format.parse(tools.wp_template)
        t['parameters']['removeme'] = {'type': 'string'}

        stack = utils.parse_stack(t, stack_name=stack_name,
                                  params={'KeyName': 'test',
                                          'removeme': 'foo'})
        stack.set_stack_user_project_id('1234')
        self.assertEqual({'KeyName': 'test', 'removeme': 'foo'},
                         stack.t.env.params)

        with mock.patch('heat.engine.stack.Stack') as mock_stack:
            mock_stack.load.return_value = stack
            mock_stack.validate.return_value = None
            result = self.man.update_stack(self.ctx, stack.identifier(),
                                           t,
                                           update_params,
                                           None, api_args)
            tmpl = mock_stack.call_args[0][2]
            self.assertEqual({'KeyName': 'test', 'newparam': 123},
                             tmpl.env.params)
            self.assertEqual(stack.identifier(), result)

    def test_stack_update_existing_registry(self):
        '''Use a template with existing flag and ensure the
        environment registry is preserved.
        '''
        stack_name = 'service_update_test_stack_existing_registry'
        intital_registry = {'OS::Foo': 'foo.yaml',
                            'OS::Foo2': 'foo2.yaml',
                            'resources': {
                                'myserver': {'OS::Server': 'myserver.yaml'}}}
        intial_params = {'encrypted_param_names': [],
                         'parameter_defaults': {},
                         'parameters': {},
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

        stack = utils.parse_stack(t, stack_name=stack_name,
                                  params=intial_params,
                                  files=initial_files)
        stack.set_stack_user_project_id('1234')
        self.assertEqual(intial_params,
                         stack.t.env.user_env_as_dict())

        expected_reg = {'OS::Foo': 'foo.yaml',
                        'OS::Foo2': 'newfoo2.yaml',
                        'resources': {
                            'myother': {'OS::Other': 'myother.yaml'},
                            'myserver': {'OS::Server': 'myserver.yaml'}}}
        expected_env = {'encrypted_param_names': [],
                        'parameter_defaults': {},
                        'parameters': {},
                        'resource_registry': expected_reg}
        # FIXME(shardy): Currently we don't prune unused old files
        expected_files = {'foo.yaml': 'foo',
                          'foo2.yaml': 'foo2',
                          'myserver.yaml': 'myserver',
                          'newfoo2.yaml': 'newfoo',
                          'myother.yaml': 'myother'}
        with mock.patch('heat.engine.stack.Stack') as mock_stack:
            mock_stack.load.return_value = stack
            mock_stack.validate.return_value = None
            result = self.man.update_stack(self.ctx, stack.identifier(),
                                           t,
                                           update_params,
                                           update_files,
                                           api_args)
            tmpl = mock_stack.call_args[0][2]
            self.assertEqual(expected_env,
                             tmpl.env.user_env_as_dict())
            self.assertEqual(expected_files,
                             tmpl.files)
            self.assertEqual(stack.identifier(), result)

    def test_stack_update_existing_parameter_defaults(self):
        '''Use a template with existing flag and ensure the
        environment parameter_defaults are preserved.
        '''
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

        stack = utils.parse_stack(t, stack_name=stack_name,
                                  params=intial_params)
        stack.set_stack_user_project_id('1234')

        expected_env = {'encrypted_param_names': [],
                        'parameter_defaults': {
                            'mydefault': 123,
                            'default2': 456},
                        'parameters': {},
                        'resource_registry': {'resources': {}}}
        with mock.patch('heat.engine.stack.Stack') as mock_stack:
            mock_stack.load.return_value = stack
            mock_stack.validate.return_value = None
            result = self.man.update_stack(self.ctx, stack.identifier(),
                                           t,
                                           update_params,
                                           None, api_args)
            tmpl = mock_stack.call_args[0][2]
            self.assertEqual(expected_env,
                             tmpl.env.user_env_as_dict())
            self.assertEqual(stack.identifier(), result)

    def test_stack_update_reuses_api_params(self):
        stack_name = 'service_update_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = tools.get_stack(stack_name, self.ctx)
        old_stack.timeout_mins = 1
        old_stack.disable_rollback = False
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        stack = tools.get_stack(stack_name, self.ctx)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False, current_traversal=None,
                     prev_raw_template_id=None, current_deps=None,
                     disable_rollback=False, nested_depth=0,
                     owner_id=None, parent_resource=None,
                     stack_user_project_id='1234',
                     strict_validate=True,
                     tenant_id='test_tenant_id', timeout_mins=1,
                     user_creds_id=u'1',
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.ReplayAll()

        api_args = {}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.m.VerifyAll()

    def test_stack_cancel_update_same_engine(self):
        stack_name = 'service_update_cancel_test_stack'
        old_stack = tools.get_stack(stack_name, self.ctx)
        old_stack.state_set(old_stack.UPDATE, old_stack.IN_PROGRESS,
                            'test_override')
        old_stack.disable_rollback = False
        old_stack.store()
        load_mock = self.patchobject(parser.Stack, 'load')
        load_mock.return_value = old_stack
        lock_mock = self.patchobject(stack_lock.StackLock, 'try_acquire')
        lock_mock.return_value = self.man.engine_id
        self.patchobject(self.man.thread_group_mgr, 'send')
        self.man.stack_cancel_update(self.ctx, old_stack.identifier(),
                                     cancel_with_rollback=False)
        self.man.thread_group_mgr.send.assert_called_once_with(old_stack.id,
                                                               'cancel')

    def test_stack_cancel_update_different_engine(self):
        stack_name = 'service_update_cancel_test_stack'
        old_stack = tools.get_stack(stack_name, self.ctx)
        old_stack.state_set(old_stack.UPDATE, old_stack.IN_PROGRESS,
                            'test_override')
        old_stack.disable_rollback = False
        old_stack.store()
        load_mock = self.patchobject(parser.Stack, 'load')
        load_mock.return_value = old_stack
        lock_mock = self.patchobject(stack_lock.StackLock, 'try_acquire')
        another_engine_has_lock = str(uuid.uuid4())
        lock_mock.return_value = another_engine_has_lock
        self.patchobject(stack_lock.StackLock,
                         'engine_alive').return_value(True)
        self.man.listener = mock.Mock()
        self.man.listener.SEND = 'send'
        self.man._client = messaging.get_rpc_client(
            version=self.man.RPC_API_VERSION)
        # In fact the another engine is not alive, so the call will timeout
        self.assertRaises(dispatcher.ExpectedException,
                          self.man.stack_cancel_update,
                          self.ctx, old_stack.identifier())

    def test_stack_cancel_update_wrong_state_fails(self):
        stack_name = 'service_update_cancel_test_stack'
        old_stack = tools.get_stack(stack_name, self.ctx)
        old_stack.state_set(old_stack.UPDATE, old_stack.COMPLETE,
                            'test_override')
        old_stack.store()
        load_mock = self.patchobject(parser.Stack, 'load')
        load_mock.return_value = old_stack

        ex = self.assertRaises(
            dispatcher.ExpectedException,
            self.man.stack_cancel_update, self.ctx, old_stack.identifier())

        self.assertEqual(exception.NotSupported, ex.exc_info[0])
        self.assertIn("Cancelling update when stack is "
                      "('UPDATE', 'COMPLETE')",
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

        old_stack = parser.Stack(self.ctx, stack_name, template)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)
        ctr.return_value = 3

        stack = parser.Stack(self.ctx, stack_name, template)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False, current_traversal=None,
                     prev_raw_template_id=None, current_deps=None,
                     disable_rollback=True, nested_depth=0,
                     owner_id=None, parent_resource=None,
                     stack_user_project_id='1234', strict_validate=True,
                     tenant_id='test_tenant_id',
                     timeout_mins=60, user_creds_id=u'1',
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.ReplayAll()

        cfg.CONF.set_override('max_resources_per_stack', 3)

        api_args = {'timeout_mins': 60}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        root_stack_id = old_stack.root_stack_id()
        self.assertEqual(3, old_stack.total_resources(root_stack_id))
        self.m.VerifyAll()

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

        create_stack = parser.Stack(self.ctx, stack_name, template)
        sid = create_stack.store()
        create_stack.create()
        self.assertEqual((create_stack.CREATE, create_stack.COMPLETE),
                         create_stack.state)

        s = stack_object.Stack.get_by_id(self.ctx, sid)

        old_stack = parser.Stack.load(self.ctx, stack=s)

        self.assertEqual((old_stack.CREATE, old_stack.COMPLETE),
                         old_stack.state)
        self.assertEqual(create_stack.identifier().arn(),
                         old_stack['A'].properties['Foo'])

        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(
            self.ctx,
            stack=s).AndReturn(old_stack)

        self.m.ReplayAll()

        result = self.man.update_stack(self.ctx, create_stack.identifier(),
                                       tpl, {}, None, {})

        self.assertEqual((old_stack.UPDATE, old_stack.COMPLETE),
                         old_stack.state)
        self.assertEqual(create_stack.identifier(), result)
        self.assertIsNotNone(create_stack.identifier().stack_id)
        self.assertEqual(create_stack.identifier().arn(),
                         old_stack['A'].properties['Foo'])

        self.assertEqual(create_stack['A'].id, old_stack['A'].id)
        self.m.VerifyAll()

    def test_stack_update_exceeds_resource_limit(self):
        stack_name = 'test_stack_update_exceeds_resource_limit'
        params = {}
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources': {
                   'A': {'Type': 'GenericResourceType'},
                   'B': {'Type': 'GenericResourceType'},
                   'C': {'Type': 'GenericResourceType'}}}

        template = templatem.Template(tpl)
        old_stack = parser.Stack(self.ctx, stack_name, template)
        sid = old_stack.store()
        self.assertIsNotNone(sid)

        cfg.CONF.set_override('max_resources_per_stack', 2)

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
        stack = tools.get_stack(stack_name, self.ctx)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False, current_traversal=None,
                     prev_raw_template_id=None, current_deps=None,
                     disable_rollback=True, nested_depth=0,
                     owner_id=None, parent_resource=None,
                     stack_user_project_id='1234', strict_validate=True,
                     tenant_id='test_tenant_id',
                     timeout_mins=60, user_creds_id=u'1',
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndRaise(exception.StackValidationFailed(
            message='fubar'))

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        ex = self.assertRaises(
            dispatcher.ExpectedException,
            self.man.update_stack,
            self.ctx, old_stack.identifier(),
            template, params, None, api_args)
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])
        self.m.VerifyAll()

    def test_stack_update_nonexist(self):
        stack_name = 'service_update_nonexist_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        stack = tools.get_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack,
                               self.ctx, stack.identifier(), template,
                               params, None, {})
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    def test_stack_update_no_credentials(self):
        cfg.CONF.set_default('deferred_auth_method', 'password')
        stack_name = 'test_stack_update_no_credentials'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = tools.get_stack(stack_name, self.ctx)
        # force check for credentials on create
        old_stack['WebServer'].requires_deferred_auth = True

        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        self.ctx = utils.dummy_context(password=None)

        self.m.StubOutWithMock(self.man, '_get_stack')

        self.man._get_stack(self.ctx, old_stack.identifier()).AndReturn(s)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=old_stack.env).AndReturn(old_stack.t)
        environment.Environment(params).AndReturn(old_stack.env)
        parser.Stack(self.ctx, old_stack.name,
                     old_stack.t,
                     convergence=False,
                     current_traversal=None,
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
                     username='test_username').AndReturn(old_stack)

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack, self.ctx,
                               old_stack.identifier(),
                               template, params, None, api_args)
        self.assertEqual(exception.MissingCredentialError, ex.exc_info[0])
        self.assertEqual(
            'Missing required credential: X-Auth-Key',
            six.text_type(ex.exc_info[1]))

        self.m.VerifyAll()

    def _test_stack_update_preview(self, orig_template, new_template):
        stack_name = 'service_update_test_stack'
        params = {'foo': 'bar'}
        old_stack = tools.get_stack(stack_name, self.ctx,
                                    template=orig_template)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        stack = tools.get_stack(stack_name, self.ctx, template=new_template)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(new_template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False,
                     current_traversal=None,
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
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)
        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        result = self.man.preview_update_stack(self.ctx,
                                               old_stack.identifier(),
                                               new_template, params, None,
                                               api_args)
        self.m.VerifyAll()

        return result

    def test_stack_update_preview_added_unchanged(self):
        orig_template = '''
heat_template_version: 2014-10-16
resources:
  web_server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      key_name: test
      user_data: wordpress
'''

        new_template = '''
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
'''

        result = self._test_stack_update_preview(orig_template, new_template)

        added = [x for x in result['added']][0]
        self.assertEqual(added['resource_name'], 'password')
        unchanged = [x for x in result['unchanged']][0]
        self.assertEqual(unchanged['resource_name'], 'web_server')

        empty_sections = ('deleted', 'replaced', 'updated')
        for section in empty_sections:
            section_contents = [x for x in result[section]]
            self.assertEqual(section_contents, [])

        self.m.VerifyAll()

    def test_stack_update_preview_replaced(self):
        orig_template = '''
heat_template_version: 2014-10-16
resources:
  web_server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      key_name: test
      user_data: wordpress
'''

        new_template = '''
heat_template_version: 2014-10-16
resources:
  web_server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      key_name: test2
      user_data: wordpress
'''

        result = self._test_stack_update_preview(orig_template, new_template)

        replaced = [x for x in result['replaced']][0]
        self.assertEqual(replaced['resource_name'], 'web_server')
        empty_sections = ('added', 'deleted', 'unchanged', 'updated')
        for section in empty_sections:
            section_contents = [x for x in result[section]]
            self.assertEqual(section_contents, [])

        self.m.VerifyAll()

    def test_stack_update_preview_updated(self):
        orig_template = '''
heat_template_version: 2014-10-16
resources:
  web_server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      key_name: test
      user_data: wordpress
'''

        new_template = '''
heat_template_version: 2014-10-16
resources:
  web_server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.small
      key_name: test
      user_data: wordpress
'''

        result = self._test_stack_update_preview(orig_template, new_template)

        updated = [x for x in result['updated']][0]
        self.assertEqual(updated['resource_name'], 'web_server')
        empty_sections = ('added', 'deleted', 'unchanged', 'replaced')
        for section in empty_sections:
            section_contents = [x for x in result[section]]
            self.assertEqual(section_contents, [])

        self.m.VerifyAll()

    def test_stack_update_preview_deleted(self):
        orig_template = '''
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
'''

        new_template = '''
heat_template_version: 2014-10-16
resources:
  web_server:
    type: OS::Nova::Server
    properties:
      image: F17-x86_64-gold
      flavor: m1.large
      key_name: test
      user_data: wordpress
'''

        result = self._test_stack_update_preview(orig_template, new_template)

        deleted = [x for x in result['deleted']][0]
        self.assertEqual(deleted['resource_name'], 'password')
        unchanged = [x for x in result['unchanged']][0]
        self.assertEqual(unchanged['resource_name'], 'web_server')
        empty_sections = ('added', 'updated', 'replaced')
        for section in empty_sections:
            section_contents = [x for x in result[section]]
            self.assertEqual(section_contents, [])

        self.m.VerifyAll()


class StackConvergenceServiceCreateUpdateTest(common.HeatTestCase):

    def setUp(self):
        super(StackConvergenceServiceCreateUpdateTest, self).setUp()
        cfg.CONF.set_override('convergence_engine', True)
        self.ctx = utils.dummy_context()
        self.man = service.EngineService('a-host', 'a-topic')

    def _stub_update_mocks(self, stack_to_load, stack_to_return):
        self.m.StubOutWithMock(parser, 'Stack')
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=stack_to_load
                          ).AndReturn(stack_to_return)

        self.m.StubOutWithMock(templatem, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')

    def _test_stack_create_convergence(self, stack_name):
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = tools.get_stack(stack_name, self.ctx,
                                template=tools.string_template_five,
                                convergence=True)

        self.m.StubOutWithMock(templatem, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(parser, 'Stack')

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t, owner_id=None,
                     parent_resource=None,
                     nested_depth=0, user_creds_id=None,
                     stack_user_project_id=None,
                     timeout_mins=60,
                     disable_rollback=False,
                     convergence=True).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.ReplayAll()
        api_args = {'timeout_mins': 60, 'disable_rollback': False}
        result = self.man.create_stack(self.ctx, 'service_create_test_stack',
                                       template, params, None, api_args)
        db_stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual(db_stack.convergence, True)
        self.assertEqual(result['stack_id'], db_stack.id)
        self.m.VerifyAll()

    def test_stack_create_enabled_convergence_engine(self):
        stack_name = 'service_create_test_stack'
        self._test_stack_create_convergence(stack_name)

    def test_stack_update_enabled_convergence_engine(self):
        stack_name = 'service_update_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        old_stack = tools.get_stack(stack_name, self.ctx,
                                    template=tools.string_template_five,
                                    convergence=True)
        old_stack.timeout_mins = 1
        sid = old_stack.store()
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        stack = tools.get_stack(stack_name, self.ctx,
                                template=tools.string_template_five_update,
                                convergence=True)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     owner_id=old_stack.owner_id,
                     nested_depth=old_stack.nested_depth,
                     user_creds_id=old_stack.user_creds_id,
                     stack_user_project_id=old_stack.stack_user_project_id,
                     timeout_mins=60,
                     disable_rollback=False,
                     parent_resource=None,
                     strict_validate=True,
                     tenant_id=old_stack.tenant_id,
                     username=old_stack.username,
                     convergence=old_stack.convergence,
                     current_traversal=old_stack.current_traversal,
                     prev_raw_template_id=old_stack.prev_raw_template_id,
                     current_deps=old_stack.current_deps).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60, 'disable_rollback': False}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)
        self.assertEqual(old_stack.convergence, True)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.m.VerifyAll()


class StackServiceAuthorizeTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceAuthorizeTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.engine_id = 'engine-fake-uuid'
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    @tools.stack_context('service_authorize_stack_user_nocreds_test_stack')
    def test_stack_authorize_stack_user_nocreds(self):
        self.assertFalse(self.eng._authorize_stack_user(self.ctx,
                                                        self.stack,
                                                        'foo'))

    @tools.stack_context('service_authorize_user_attribute_error_test_stack')
    def test_stack_authorize_stack_user_attribute_error(self):
        self.m.StubOutWithMock(json, 'loads')
        json.loads(None).AndRaise(AttributeError)
        self.m.ReplayAll()
        self.assertFalse(self.eng._authorize_stack_user(self.ctx,
                                                        self.stack,
                                                        'foo'))
        self.m.VerifyAll()

    @tools.stack_context('service_authorize_stack_user_type_error_test_stack')
    def test_stack_authorize_stack_user_type_error(self):
        self.m.StubOutWithMock(json, 'loads')
        json.loads(mox.IgnoreArg()).AndRaise(TypeError)
        self.m.ReplayAll()

        self.assertFalse(self.eng._authorize_stack_user(self.ctx,
                                                        self.stack,
                                                        'foo'))

        self.m.VerifyAll()

    def test_stack_authorize_stack_user(self):
        self.ctx = utils.dummy_context()
        self.ctx.aws_creds = '{"ec2Credentials": {"access": "4567"}}'
        stack_name = 'stack_authorize_stack_user'
        stack = tools.get_stack(stack_name, self.ctx, user_policy_template)
        self.stack = stack
        fc = tools.setup_mocks(self.m, stack)
        self.patchobject(fc.servers, 'delete',
                         side_effect=fakes_nova.fake_exception())

        self.m.ReplayAll()
        stack.store()
        stack.create()

        self.assertTrue(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'WebServer'))

        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'CfnUser'))

        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'NoSuchResource'))

        self.m.VerifyAll()

    def test_stack_authorize_stack_user_user_id(self):
        self.ctx = utils.dummy_context(user_id=str(uuid.uuid4()))
        stack_name = 'stack_authorize_stack_user_user_id'
        stack = tools.get_stack(stack_name, self.ctx, server_config_template)
        self.stack = stack

        def handler(resource_name):
            return resource_name == 'WebServer'

        self.stack.register_access_allowed_handler(self.ctx.user_id, handler)

        # matching credential_id and resource_name
        self.assertTrue(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'WebServer'))

        # not matching resource_name
        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'NoSuchResource'))

        # not matching credential_id
        self.ctx.user_id = str(uuid.uuid4())
        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'WebServer'))


class StackServiceTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.thread_group_mgr = tools.DummyThreadGroupManager()
        self.eng.engine_id = 'engine-fake-uuid'
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    @tools.stack_context('service_identify_test_stack', False)
    def test_stack_identify(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        self.m.ReplayAll()
        identity = self.eng.identify_stack(self.ctx, self.stack.name)
        self.assertEqual(self.stack.identifier(), identity)

        self.m.VerifyAll()

    @tools.stack_context('ef0c41a4-644f-447c-ad80-7eecb0becf79', False)
    def test_stack_identify_by_name_in_uuid(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        self.m.ReplayAll()
        identity = self.eng.identify_stack(self.ctx, self.stack.name)
        self.assertEqual(self.stack.identifier(), identity)

        self.m.VerifyAll()

    @tools.stack_context('service_identify_uuid_test_stack', False)
    def test_stack_identify_uuid(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        self.m.ReplayAll()
        identity = self.eng.identify_stack(self.ctx, self.stack.id)
        self.assertEqual(self.stack.identifier(), identity)

        self.m.VerifyAll()

    def test_stack_identify_nonexist(self):
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.identify_stack, self.ctx, 'wibble')
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])

    @tools.stack_context('service_create_existing_test_stack', False)
    def test_stack_create_existing(self):
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.create_stack, self.ctx,
                               self.stack.name, self.stack.t.t, {}, None, {})
        self.assertEqual(exception.StackExists, ex.exc_info[0])

    @tools.stack_context('service_name_tenants_test_stack', False)
    def test_stack_by_name_tenants(self):
        self.assertEqual(
            self.stack.id,
            stack_object.Stack.get_by_name(self.ctx, self.stack.name).id)
        ctx2 = utils.dummy_context(tenant_id='stack_service_test_tenant2')
        self.assertIsNone(stack_object.Stack.get_by_name(
            ctx2,
            self.stack.name))

    @tools.stack_context('service_list_all_test_stack')
    def test_stack_list_all(self):
        self.m.StubOutWithMock(parser.Stack, '_from_db')
        parser.Stack._from_db(
            self.ctx, mox.IgnoreArg(),
            resolve_data=False
        ).AndReturn(self.stack)

        self.m.ReplayAll()
        sl = self.eng.list_stacks(self.ctx)

        self.assertEqual(1, len(sl))
        for s in sl:
            self.assertIn('creation_time', s)
            self.assertIn('updated_time', s)
            self.assertIn('stack_identity', s)
            self.assertIsNotNone(s['stack_identity'])
            self.assertIn('stack_name', s)
            self.assertEqual(self.stack.name, s['stack_name'])
            self.assertIn('stack_status', s)
            self.assertIn('stack_status_reason', s)
            self.assertIn('description', s)
            self.assertIn('WordPress', s['description'])

        self.m.VerifyAll()

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_passes_marker_info(self, mock_stack_get_all):
        limit = object()
        marker = object()
        sort_keys = object()
        sort_dir = object()
        self.eng.list_stacks(self.ctx, limit=limit, marker=marker,
                             sort_keys=sort_keys, sort_dir=sort_dir)
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit,
                                                   sort_keys,
                                                   marker,
                                                   sort_dir,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_passes_filtering_info(self, mock_stack_get_all):
        filters = {'foo': 'bar'}
        self.eng.list_stacks(self.ctx, filters=filters)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   filters,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_tenant_safe_defaults_to_true(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   True,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_passes_tenant_safe_info(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, tenant_safe=False)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   False,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_show_nested(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, show_nested=True)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   True,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_show_deleted(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, show_deleted=True)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   True,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_show_hidden(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, show_hidden=True)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   True,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_tags(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, tags=['foo', 'bar'])
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   ['foo', 'bar'],
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_tags_any(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, tags_any=['foo', 'bar'])
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   ['foo', 'bar'],
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_not_tags(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, not_tags=['foo', 'bar'])
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   ['foo', 'bar'],
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_not_tags_any(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, not_tags_any=['foo', 'bar'])
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   ['foo', 'bar'],
                                                   )

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_passes_filter_info(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, filters={'foo': 'bar'})
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters={'foo': 'bar'},
                                                     tenant_safe=mock.ANY,
                                                     show_deleted=False,
                                                     show_nested=False,
                                                     show_hidden=False,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_tenant_safe_default_true(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=True,
                                                     show_deleted=False,
                                                     show_nested=False,
                                                     show_hidden=False,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_passes_tenant_safe_info(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, tenant_safe=False)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=False,
                                                     show_deleted=False,
                                                     show_nested=False,
                                                     show_hidden=False,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_show_nested(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, show_nested=True)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=True,
                                                     show_deleted=False,
                                                     show_nested=True,
                                                     show_hidden=False,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stack_show_deleted(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, show_deleted=True)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=True,
                                                     show_deleted=True,
                                                     show_nested=False,
                                                     show_hidden=False,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stack_show_hidden(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, show_hidden=True)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=True,
                                                     show_deleted=False,
                                                     show_nested=False,
                                                     show_hidden=True,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @tools.stack_context('service_abandon_stack')
    def test_abandon_stack(self):
        cfg.CONF.set_override('enable_stack_abandon', True)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        expected_res = {
            u'WebServer': {
                'action': 'CREATE',
                'metadata': {},
                'name': u'WebServer',
                'resource_data': {},
                'resource_id': '9999',
                'status': 'COMPLETE',
                'type': u'AWS::EC2::Instance'}}
        self.m.ReplayAll()
        ret = self.eng.abandon_stack(self.ctx, self.stack.identifier())
        self.assertEqual(10, len(ret))
        self.assertEqual('CREATE', ret['action'])
        self.assertEqual('COMPLETE', ret['status'])
        self.assertEqual('service_abandon_stack', ret['name'])
        self.assertEqual({}, ret['files'])
        self.assertIn('id', ret)
        self.assertEqual(expected_res, ret['resources'])
        self.assertEqual(self.stack.t.t, ret['template'])
        self.assertIn('project_id', ret)
        self.assertIn('stack_user_project_id', ret)
        self.assertIn('environment', ret)
        self.assertIn('files', ret)
        self.m.VerifyAll()

    def test_stack_describe_nonexistent(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        stack_not_found_exc = exception.StackNotFound(stack_name='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier,
            show_deleted=True).AndRaise(stack_not_found_exc)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_stack,
                               self.ctx, non_exist_identifier)
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    def test_stack_describe_bad_tenant(self):
        non_exist_identifier = identifier.HeatIdentifier(
            'wibble', 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        invalid_tenant_exc = exception.InvalidTenant(target='test',
                                                     actual='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier,
            show_deleted=True).AndRaise(invalid_tenant_exc)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_stack,
                               self.ctx, non_exist_identifier)
        self.assertEqual(exception.InvalidTenant, ex.exc_info[0])

        self.m.VerifyAll()

    @tools.stack_context('service_describe_test_stack', False)
    def test_stack_describe(self):
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier(),
                                         show_deleted=True).AndReturn(s)
        self.m.ReplayAll()

        sl = self.eng.show_stack(self.ctx, self.stack.identifier())

        self.assertEqual(1, len(sl))

        s = sl[0]
        self.assertIn('creation_time', s)
        self.assertIn('updated_time', s)
        self.assertIn('stack_identity', s)
        self.assertIsNotNone(s['stack_identity'])
        self.assertIn('stack_name', s)
        self.assertEqual(self.stack.name, s['stack_name'])
        self.assertIn('stack_status', s)
        self.assertIn('stack_status_reason', s)
        self.assertIn('description', s)
        self.assertIn('WordPress', s['description'])
        self.assertIn('parameters', s)

        self.m.VerifyAll()

    @tools.stack_context('service_describe_all_test_stack', False)
    def test_stack_describe_all(self):
        sl = self.eng.show_stack(self.ctx, None)

        self.assertEqual(1, len(sl))

        s = sl[0]
        self.assertIn('creation_time', s)
        self.assertIn('updated_time', s)
        self.assertIn('stack_identity', s)
        self.assertIsNotNone(s['stack_identity'])
        self.assertIn('stack_name', s)
        self.assertEqual(self.stack.name, s['stack_name'])
        self.assertIn('stack_status', s)
        self.assertIn('stack_status_reason', s)
        self.assertIn('description', s)
        self.assertIn('WordPress', s['description'])
        self.assertIn('parameters', s)

    @mock.patch('heat.engine.template._get_template_extension_manager')
    def test_list_template_versions(self, templ_mock):

        class DummyMgr(object):
            def names(self):
                return ['a.b', 'c.d']

            def __getitem__(self, item):
                m = mock.MagicMock()
                if item == 'a.b':
                    m.plugin = cfntemplate.CfnTemplate
                    return m
                else:
                    m.plugin = hottemplate.HOTemplate20130523
                    return m

        templ_mock.return_value = DummyMgr()
        templates = self.eng.list_template_versions(self.ctx)
        expected = [{'version': 'a.b', 'type': 'cfn'},
                    {'version': 'c.d', 'type': 'hot'}]
        self.assertEqual(expected, templates)

    @mock.patch('heat.engine.template._get_template_extension_manager')
    def test_list_template_functions(self, templ_mock):

        class DummyFunc1(object):
            """
            Dummy Func1

            Dummy Func1 Long Description
            """

        class DummyFunc2(object):
            """Dummy Func2

            Dummy Func2 Long Description
            """

        plugin_mock = mock.Mock(
            functions={'dummy1': DummyFunc1,
                       'dummy2': DummyFunc2,
                       'removed': hot_functions.Removed})
        dummy_tmpl = mock.Mock(plugin=plugin_mock)

        class DummyMgr(object):
            def __getitem__(self, item):
                return dummy_tmpl

        templ_mock.return_value = DummyMgr()
        functions = self.eng.list_template_functions(self.ctx, 'dummytemplate')
        expected = [{'functions': 'dummy1',
                     'description': 'Dummy Func1'},
                    {'functions': 'dummy2',
                     'description': 'Dummy Func2'}]
        self.assertEqual(sorted(expected, key=lambda k: k['functions']),
                         sorted(functions, key=lambda k: k['functions']))

    def _test_describe_stack_resource(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        r = self.eng.describe_stack_resource(self.ctx, self.stack.identifier(),
                                             'WebServer', with_attr=None)

        self.assertIn('resource_identity', r)
        self.assertIn('description', r)
        self.assertIn('updated_time', r)
        self.assertIn('stack_identity', r)
        self.assertIsNotNone(r['stack_identity'])
        self.assertIn('stack_name', r)
        self.assertEqual(self.stack.name, r['stack_name'])
        self.assertIn('metadata', r)
        self.assertIn('resource_status', r)
        self.assertIn('resource_status_reason', r)
        self.assertIn('resource_type', r)
        self.assertIn('physical_resource_id', r)
        self.assertIn('resource_name', r)
        self.assertIn('attributes', r)
        self.assertEqual('WebServer', r['resource_name'])

        self.m.VerifyAll()

    @tools.stack_context('service_stack_resource_describe__test_stack')
    def test_stack_resource_describe(self):
        self._test_describe_stack_resource()

    def test_stack_resource_describe_nonexist_stack(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id,
            'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        stack_not_found_exc = exception.StackNotFound(stack_name='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier).AndRaise(stack_not_found_exc)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resource,
                               self.ctx, non_exist_identifier, 'WebServer')
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])

        self.m.VerifyAll()

    @tools.stack_context('service_resource_describe_nonexist_test_stack')
    def test_stack_resource_describe_nonexist_resource(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        self.m.ReplayAll()
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resource,
                               self.ctx, self.stack.identifier(), 'foo')
        self.assertEqual(exception.ResourceNotFound, ex.exc_info[0])

        self.m.VerifyAll()

    @tools.stack_context('service_resource_describe_noncreated_test_stack',
                         create_res=False)
    def test_stack_resource_describe_noncreated_resource(self):
        self._test_describe_stack_resource()

    @tools.stack_context('service_resource_describe_user_deny_test_stack')
    def test_stack_resource_describe_stack_user_deny(self):
        self.ctx.roles = [cfg.CONF.heat_stack_user_role]
        self.m.StubOutWithMock(service.EngineService, '_authorize_stack_user')
        service.EngineService._authorize_stack_user(self.ctx, mox.IgnoreArg(),
                                                    'foo').AndReturn(False)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resource,
                               self.ctx, self.stack.identifier(), 'foo')
        self.assertEqual(exception.Forbidden, ex.exc_info[0])

        self.m.VerifyAll()

    @tools.stack_context('service_resources_describe_test_stack')
    def test_stack_resources_describe(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        resources = self.eng.describe_stack_resources(self.ctx,
                                                      self.stack.identifier(),
                                                      'WebServer')

        self.assertEqual(1, len(resources))
        r = resources[0]
        self.assertIn('resource_identity', r)
        self.assertIn('description', r)
        self.assertIn('updated_time', r)
        self.assertIn('stack_identity', r)
        self.assertIsNotNone(r['stack_identity'])
        self.assertIn('stack_name', r)
        self.assertEqual(self.stack.name, r['stack_name'])
        self.assertIn('resource_status', r)
        self.assertIn('resource_status_reason', r)
        self.assertIn('resource_type', r)
        self.assertIn('physical_resource_id', r)
        self.assertIn('resource_name', r)
        self.assertEqual('WebServer', r['resource_name'])

        self.m.VerifyAll()

    @tools.stack_context('service_resources_describe_no_filter_test_stack')
    def test_stack_resources_describe_no_filter(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        resources = self.eng.describe_stack_resources(self.ctx,
                                                      self.stack.identifier(),
                                                      None)

        self.assertEqual(1, len(resources))
        r = resources[0]
        self.assertIn('resource_name', r)
        self.assertEqual('WebServer', r['resource_name'])

        self.m.VerifyAll()

    def test_stack_resources_describe_bad_lookup(self):
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, None).AndRaise(TypeError)
        self.m.ReplayAll()

        self.assertRaises(TypeError,
                          self.eng.describe_stack_resources,
                          self.ctx, None, 'WebServer')
        self.m.VerifyAll()

    def test_stack_resources_describe_nonexist_stack(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resources,
                               self.ctx, non_exist_identifier, 'WebServer')
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])

    @tools.stack_context('find_phys_res_stack')
    def test_find_physical_resource(self):
        resources = self.eng.describe_stack_resources(self.ctx,
                                                      self.stack.identifier(),
                                                      None)
        phys_id = resources[0]['physical_resource_id']

        result = self.eng.find_physical_resource(self.ctx, phys_id)
        self.assertIsInstance(result, dict)
        resource_identity = identifier.ResourceIdentifier(**result)
        self.assertEqual(self.stack.identifier(), resource_identity.stack())
        self.assertEqual('WebServer', resource_identity.resource_name)

    def test_find_physical_resource_nonexist(self):
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.find_physical_resource,
                               self.ctx, 'foo')
        self.assertEqual(exception.PhysicalResourceNotFound, ex.exc_info[0])

    @tools.stack_context('service_resources_list_test_stack')
    def test_stack_resources_list(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        resources = self.eng.list_stack_resources(self.ctx,
                                                  self.stack.identifier())

        self.assertEqual(1, len(resources))
        r = resources[0]
        self.assertIn('resource_identity', r)
        self.assertIn('updated_time', r)
        self.assertIn('physical_resource_id', r)
        self.assertIn('resource_name', r)
        self.assertEqual('WebServer', r['resource_name'])
        self.assertIn('resource_status', r)
        self.assertIn('resource_status_reason', r)
        self.assertIn('resource_type', r)

        self.m.VerifyAll()

    @mock.patch.object(parser.Stack, 'load')
    @tools.stack_context('service_resources_list_test_stack_with_depth')
    def test_stack_resources_list_with_depth(self, mock_load):
        mock_load.return_value = self.stack
        resources = six.itervalues(self.stack)
        self.stack.iter_resources = mock.Mock(return_value=resources)
        resources = self.eng.list_stack_resources(self.ctx,
                                                  self.stack.identifier(),
                                                  2)
        self.stack.iter_resources.assert_called_once_with(2)

    @mock.patch.object(parser.Stack, 'load')
    @tools.stack_context('service_resources_list_test_stack_with_max_depth')
    def test_stack_resources_list_with_max_depth(self, mock_load):
        mock_load.return_value = self.stack
        resources = six.itervalues(self.stack)
        self.stack.iter_resources = mock.Mock(return_value=resources)
        resources = self.eng.list_stack_resources(self.ctx,
                                                  self.stack.identifier(),
                                                  99)
        max_depth = cfg.CONF.max_nested_stack_depth
        self.stack.iter_resources.assert_called_once_with(max_depth)

    @mock.patch.object(parser.Stack, 'load')
    def test_stack_resources_list_deleted_stack(self, mock_load):
        stack = tools.setup_stack('resource_list_deleted_stack', self.ctx)
        stack_id = stack.identifier()
        mock_load.return_value = stack
        tools.clean_up_stack(stack)
        resources = self.eng.list_stack_resources(self.ctx, stack_id)
        self.assertEqual(1, len(resources))

        res = resources[0]
        self.assertEqual('DELETE', res['resource_action'])
        self.assertEqual('COMPLETE', res['resource_status'])

    def test_stack_resources_list_nonexist_stack(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        stack_not_found_exc = exception.StackNotFound(stack_name='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier, show_deleted=True
        ).AndRaise(stack_not_found_exc)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.list_stack_resources,
                               self.ctx, non_exist_identifier)
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])

        self.m.VerifyAll()

    def test_signal_reception_async(self):
        self.eng.thread_group_mgr = tools.DummyThreadGroupMgrLogStart()
        stack_name = 'signal_reception_async'
        stack = tools.get_stack(stack_name, self.ctx, policy_template)
        self.stack = stack
        tools.setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()
        test_data = {'food': 'yum'}

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.ReplayAll()

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy',
                                 test_data)

        self.assertEqual([(self.stack.id, mox.IgnoreArg())],
                         self.eng.thread_group_mgr.started)
        self.m.VerifyAll()

    def test_signal_reception_sync(self):
        stack_name = 'signal_reception_sync'
        stack = tools.get_stack(stack_name, self.ctx, policy_template)
        self.stack = stack
        tools.setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()
        test_data = {'food': 'yum'}

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(res.Resource, 'signal')
        res.Resource.signal(mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy',
                                 test_data,
                                 sync_call=True)
        self.m.VerifyAll()

    def test_signal_reception_no_resource(self):
        stack_name = 'signal_reception_no_resource'
        stack = tools.get_stack(stack_name, self.ctx, policy_template)
        tools.setup_keystone_mocks(self.m, stack)
        self.stack = stack
        self.m.ReplayAll()
        stack.store()
        stack.create()
        test_data = {'food': 'yum'}

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_signal, self.ctx,
                               dict(self.stack.identifier()),
                               'resource_does_not_exist',
                               test_data)
        self.assertEqual(exception.ResourceNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    def test_signal_reception_unavailable_resource(self):
        stack_name = 'signal_reception_unavailable_resource'
        stack = tools.get_stack(stack_name, self.ctx, policy_template)
        stack.store()
        self.stack = stack
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(
            self.ctx, stack=mox.IgnoreArg(),
            use_stored_context=mox.IgnoreArg()
        ).AndReturn(self.stack)
        self.m.ReplayAll()

        test_data = {'food': 'yum'}
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_signal, self.ctx,
                               dict(self.stack.identifier()),
                               'WebServerScaleDownPolicy',
                               test_data)
        self.assertEqual(exception.ResourceNotAvailable, ex.exc_info[0])
        self.m.VerifyAll()

    def test_signal_returns_metadata(self):
        stack = tools.get_stack('signal_reception', self.ctx, policy_template)
        self.stack = stack
        tools.setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()
        test_metadata = {'food': 'yum'}
        rsrc = stack['WebServerScaleDownPolicy']
        rsrc.metadata_set(test_metadata)

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(res.Resource, 'signal')
        res.Resource.signal(mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()

        md = self.eng.resource_signal(self.ctx,
                                      dict(self.stack.identifier()),
                                      'WebServerScaleDownPolicy', None,
                                      sync_call=True)
        self.assertEqual(test_metadata, md)
        self.m.VerifyAll()

    def test_signal_calls_metadata_update(self):
        stack = tools.get_stack('signal_reception', self.ctx, policy_template)
        self.stack = stack
        tools.setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(res.Resource, 'signal')
        res.Resource.signal(mox.IgnoreArg()).AndReturn(None)
        self.m.StubOutWithMock(res.Resource, 'metadata_update')
        # this will be called once for the Random resource
        res.Resource.metadata_update().AndReturn(None)
        self.m.ReplayAll()

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy', None,
                                 sync_call=True)
        self.m.VerifyAll()

    def test_signal_no_calls_metadata_update(self):
        stack = tools.get_stack('signal_reception', self.ctx, policy_template)
        self.stack = stack
        tools.setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()

        res.Resource.signal_needs_metadata_updates = False

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(res.Resource, 'signal')
        res.Resource.signal(mox.IgnoreArg()).AndReturn(None)
        # this will never be called
        self.m.StubOutWithMock(res.Resource, 'metadata_update')
        self.m.ReplayAll()

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy', None,
                                 sync_call=True)
        self.m.VerifyAll()
        res.Resource.signal_needs_metadata_updates = True

    def test_stack_list_all_empty(self):
        sl = self.eng.list_stacks(self.ctx)

        self.assertEqual(0, len(sl))

    def test_stack_describe_all_empty(self):
        sl = self.eng.show_stack(self.ctx, None)

        self.assertEqual(0, len(sl))

    def test_lazy_load_resources(self):
        stack_name = 'lazy_load_test'

        lazy_load_template = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Ref': 'foo'},
                    }
                }
            }
        }
        templ = templatem.Template(lazy_load_template)
        stack = parser.Stack(self.ctx, stack_name, templ)

        self.assertIsNone(stack._resources)
        self.assertIsNone(stack._dependencies)

        resources = stack.resources
        self.assertIsInstance(resources, dict)
        self.assertEqual(2, len(resources))
        self.assertIsInstance(resources.get('foo'),
                              generic_rsrc.GenericResource)
        self.assertIsInstance(resources.get('bar'),
                              generic_rsrc.ResourceWithProps)

        stack_dependencies = stack.dependencies
        self.assertIsInstance(stack_dependencies, dependencies.Dependencies)
        self.assertEqual(2, len(stack_dependencies.graph()))

    def _preview_stack(self):
        res._register_class('GenericResource1', generic_rsrc.GenericResource)
        res._register_class('GenericResource2', generic_rsrc.GenericResource)

        args = {}
        params = {}
        files = None
        stack_name = 'SampleStack'
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Description': 'Lorem ipsum.',
               'Resources': {
                   'SampleResource1': {'Type': 'GenericResource1'},
                   'SampleResource2': {'Type': 'GenericResource2'}}}

        return self.eng.preview_stack(self.ctx, stack_name, tpl,
                                      params, files, args)

    def test_preview_stack_returns_a_stack(self):
        stack = self._preview_stack()
        expected_identity = {'path': '',
                             'stack_id': 'None',
                             'stack_name': 'SampleStack',
                             'tenant': 'stack_service_test_tenant'}
        self.assertEqual(expected_identity, stack['stack_identity'])
        self.assertEqual('SampleStack', stack['stack_name'])
        self.assertEqual('Lorem ipsum.', stack['description'])

    def test_preview_stack_returns_list_of_resources_in_stack(self):
        stack = self._preview_stack()
        self.assertIsInstance(stack['resources'], list)
        self.assertEqual(2, len(stack['resources']))

        resource_types = set(r['resource_type'] for r in stack['resources'])
        self.assertIn('GenericResource1', resource_types)
        self.assertIn('GenericResource2', resource_types)

        resource_names = set(r['resource_name'] for r in stack['resources'])
        self.assertIn('SampleResource1', resource_names)
        self.assertIn('SampleResource2', resource_names)

    def test_preview_stack_validates_new_stack(self):
        exc = exception.StackExists(stack_name='Validation Failed')
        self.eng._validate_new_stack = mock.Mock(side_effect=exc)
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self._preview_stack)
        self.assertEqual(exception.StackExists, ex.exc_info[0])

    @mock.patch.object(service.api, 'format_stack_preview', new=mock.Mock())
    @mock.patch.object(service.parser, 'Stack')
    def test_preview_stack_checks_stack_validity(self, mock_parser):
        exc = exception.StackValidationFailed(message='Validation Failed')
        mock_parsed_stack = mock.Mock()
        mock_parsed_stack.validate.side_effect = exc
        mock_parser.return_value = mock_parsed_stack
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self._preview_stack)
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])

    @mock.patch.object(stack_object.Stack, 'get_by_name')
    def test_validate_new_stack_checks_existing_stack(self, mock_stack_get):
        mock_stack_get.return_value = 'existing_db_stack'
        tmpl = templatem.Template(
            {'HeatTemplateFormatVersion': '2012-12-12'})
        self.assertRaises(exception.StackExists, self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', tmpl)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_validate_new_stack_checks_stack_limit(self, mock_db_count):
        cfg.CONF.set_override('max_stacks_per_tenant', 99)
        mock_db_count.return_value = 99
        template = templatem.Template(
            {'HeatTemplateFormatVersion': '2012-12-12'})
        self.assertRaises(exception.RequestLimitExceeded,
                          self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', template)

    def test_validate_new_stack_checks_incorrect_keywords_in_resource(self):
        template = {'heat_template_version': '2013-05-23',
                    'resources': {
                        'Res': {'Type': 'GenericResource1'}}}
        parsed_template = templatem.Template(template)
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.eng._validate_new_stack,
                               self.ctx, 'test_existing_stack',
                               parsed_template)
        msg = (u'"Type" is not a valid keyword '
               'inside a resource definition')

        self.assertEqual(msg, six.text_type(ex))

    def test_validate_new_stack_checks_incorrect_sections(self):
        template = {'heat_template_version': '2013-05-23',
                    'unknown_section': {
                        'Res': {'Type': 'GenericResource1'}}}
        parsed_template = templatem.Template(template)
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.eng._validate_new_stack,
                               self.ctx, 'test_existing_stack',
                               parsed_template)
        msg = u'The template section is invalid: unknown_section'
        self.assertEqual(msg, six.text_type(ex))

    def test_validate_new_stack_checks_resource_limit(self):
        cfg.CONF.set_override('max_resources_per_stack', 5)
        template = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {
                        'Res1': {'Type': 'GenericResource1'},
                        'Res2': {'Type': 'GenericResource1'},
                        'Res3': {'Type': 'GenericResource1'},
                        'Res4': {'Type': 'GenericResource1'},
                        'Res5': {'Type': 'GenericResource1'},
                        'Res6': {'Type': 'GenericResource1'}}}
        parsed_template = templatem.Template(template)
        self.assertRaises(exception.RequestLimitExceeded,
                          self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', parsed_template)

    def test_validate_new_stack_handle_assertion_error(self):
        tmpl = mock.MagicMock()
        expected_message = 'Expected assertion error'
        tmpl.validate.side_effect = AssertionError(expected_message)
        exc = self.assertRaises(AssertionError, self.eng._validate_new_stack,
                                self.ctx, 'stack_name', tmpl)
        self.assertEqual(expected_message, six.text_type(exc))

    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch.object(stack_object.Stack, 'get_all')
    @mock.patch('heat.engine.stack_lock.StackLock',
                return_value=mock.Mock())
    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(context, 'get_admin_context')
    def test_engine_reset_stack_status(
            self,
            mock_admin_context,
            mock_stack_load,
            mock_stacklock,
            mock_get_all,
            mock_thread):
        mock_admin_context.return_value = self.ctx

        db_stack = mock.MagicMock()
        db_stack.id = 'foo'
        db_stack.status = 'IN_PROGRESS'
        db_stack.status_reason = None
        mock_get_all.return_value = [db_stack]

        fake_stack = mock.MagicMock()
        fake_stack.action = 'CREATE'
        fake_stack.id = 'foo'
        fake_stack.status = 'IN_PROGRESS'
        fake_stack.state_set.return_value = None
        mock_stack_load.return_value = fake_stack

        fake_lock = mock.MagicMock()
        fake_lock.get_engine_id.return_value = 'old-engine'
        fake_lock.acquire.return_value = None
        mock_stacklock.return_value = fake_lock

        self.eng.thread_group_mgr = mock_thread

        self.eng.reset_stack_status()

        mock_admin_context.assert_called_once_with()
        filters = {'status': parser.Stack.IN_PROGRESS}
        mock_get_all.assert_called_once_with(self.ctx,
                                             filters=filters,
                                             tenant_safe=False)
        mock_stack_load.assert_called_once_with(self.ctx,
                                                stack=db_stack,
                                                use_stored_context=True)
        mock_thread.start_with_acquired_lock.assert_called_once_with(
            fake_stack, fake_lock, fake_stack.state_set, fake_stack.action,
            fake_stack.FAILED, 'Engine went down during stack CREATE'
        )
