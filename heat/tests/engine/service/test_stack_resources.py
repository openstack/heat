# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock
from oslo_config import cfg
from oslo_messaging.rpc import dispatcher
import six

from heat.common import exception
from heat.common import identifier
from heat.engine.clients.os import keystone
from heat.engine import dependencies
from heat.engine import resource as res
from heat.engine import service
from heat.engine import stack
from heat.engine import template as templatem
from heat.objects import stack as stack_object
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import fakes as test_fakes
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils

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


class StackResourcesServiceTest(common.HeatTestCase):

    def setUp(self):
        super(StackResourcesServiceTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_resource_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.thread_group_mgr = tools.DummyThreadGroupManager()
        self.eng.engine_id = 'engine-fake-uuid'
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

    @mock.patch.object(stack.Stack, 'load')
    def _test_describe_stack_resource(self, mock_load):
        mock_load.return_value = self.stack

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

        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)

    @tools.stack_context('service_stack_resource_describe__test_stack')
    def test_stack_resource_describe(self):
        self._test_describe_stack_resource()

    @mock.patch.object(service.EngineService, '_get_stack')
    def test_stack_resource_describe_nonexist_stack(self, mock_get):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')
        mock_get.side_effect = exception.EntityNotFound(
            entity='Stack', name='test')

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resource,
                               self.ctx, non_exist_identifier, 'WebServer')
        self.assertEqual(exception.EntityNotFound, ex.exc_info[0])
        mock_get.assert_called_once_with(self.ctx, non_exist_identifier)

    @mock.patch.object(stack.Stack, 'load')
    @tools.stack_context('service_resource_describe_nonexist_test_stack')
    def test_stack_resource_describe_nonexist_resource(self, mock_load):
        mock_load.return_value = self.stack

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resource,
                               self.ctx, self.stack.identifier(), 'foo')
        self.assertEqual(exception.ResourceNotFound, ex.exc_info[0])
        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)

    @tools.stack_context('service_resource_describe_noncreated_test_stack',
                         create_res=False)
    def test_stack_resource_describe_noncreated_resource(self):
        self._test_describe_stack_resource()

    @mock.patch.object(service.EngineService, '_authorize_stack_user')
    @tools.stack_context('service_resource_describe_user_deny_test_stack')
    def test_stack_resource_describe_stack_user_deny(self, mock_auth):
        self.ctx.roles = [cfg.CONF.heat_stack_user_role]
        mock_auth.return_value = False

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resource,
                               self.ctx, self.stack.identifier(), 'foo')
        self.assertEqual(exception.Forbidden, ex.exc_info[0])
        mock_auth.assert_called_once_with(self.ctx, mock.ANY, 'foo')

    @mock.patch.object(stack.Stack, 'load')
    @tools.stack_context('service_resources_describe_test_stack')
    def test_stack_resources_describe(self, mock_load):
        mock_load.return_value = self.stack

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

        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)

    @mock.patch.object(stack.Stack, 'load')
    @tools.stack_context('service_resources_describe_no_filter_test_stack')
    def test_stack_resources_describe_no_filter(self, mock_load):
        mock_load.return_value = self.stack

        resources = self.eng.describe_stack_resources(
            self.ctx, self.stack.identifier(), None)

        self.assertEqual(1, len(resources))
        r = resources[0]
        self.assertIn('resource_name', r)
        self.assertEqual('WebServer', r['resource_name'])
        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)

    @mock.patch.object(service.EngineService, '_get_stack')
    def test_stack_resources_describe_bad_lookup(self, mock_get):
        mock_get.side_effect = TypeError

        self.assertRaises(TypeError,
                          self.eng.describe_stack_resources,
                          self.ctx, None, 'WebServer')
        mock_get.assert_called_once_with(self.ctx, None)

    def test_stack_resources_describe_nonexist_stack(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resources,
                               self.ctx, non_exist_identifier, 'WebServer')
        self.assertEqual(exception.EntityNotFound, ex.exc_info[0])

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

    @mock.patch.object(stack.Stack, 'load')
    @tools.stack_context('service_resources_list_test_stack')
    def test_stack_resources_list(self, mock_load):
        mock_load.return_value = self.stack

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
        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY)

    @mock.patch.object(stack.Stack, 'load')
    @tools.stack_context('service_resources_list_test_stack_with_depth')
    def test_stack_resources_list_with_depth(self, mock_load):
        mock_load.return_value = self.stack
        resources = six.itervalues(self.stack)
        self.stack.iter_resources = mock.Mock(return_value=resources)
        resources = self.eng.list_stack_resources(self.ctx,
                                                  self.stack.identifier(),
                                                  2)
        self.stack.iter_resources.assert_called_once_with(2)

    @mock.patch.object(stack.Stack, 'load')
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

    @mock.patch.object(stack.Stack, 'load')
    def test_stack_resources_list_deleted_stack(self, mock_load):
        stk = tools.setup_stack('resource_list_deleted_stack', self.ctx)
        stack_id = stk.identifier()
        mock_load.return_value = stk
        tools.clean_up_stack(stk)
        resources = self.eng.list_stack_resources(self.ctx, stack_id)
        self.assertEqual(1, len(resources))

        res = resources[0]
        self.assertEqual('DELETE', res['resource_action'])
        self.assertEqual('COMPLETE', res['resource_status'])

    @mock.patch.object(service.EngineService, '_get_stack')
    def test_stack_resources_list_nonexist_stack(self, mock_get):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')
        mock_get.side_effect = exception.EntityNotFound(entity='Stack',
                                                        name='test')

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.list_stack_resources,
                               self.ctx, non_exist_identifier)
        self.assertEqual(exception.EntityNotFound, ex.exc_info[0])
        mock_get.assert_called_once_with(self.ctx, non_exist_identifier,
                                         show_deleted=True)

    def _stack_create(self, stack_name):
        self.patchobject(keystone.KeystoneClientPlugin, '_create',
                         return_value=test_fakes.FakeKeystoneClient())

        stk = tools.get_stack(stack_name, self.ctx, policy_template)
        stk.store()
        stk.create()

        s = stack_object.Stack.get_by_id(self.ctx, stk.id)
        self.patchobject(service.EngineService, '_get_stack', return_value=s)
        return stk

    def test_signal_reception_async(self):
        self.eng.thread_group_mgr = tools.DummyThreadGroupMgrLogStart()
        stack_name = 'signal_reception_async'
        self.stack = self._stack_create(stack_name)
        test_data = {'food': 'yum'}

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy',
                                 test_data)

        self.assertEqual([(self.stack.id, mock.ANY)],
                         self.eng.thread_group_mgr.started)

    @mock.patch.object(res.Resource, 'signal')
    def test_signal_reception_sync(self, mock_signal):
        mock_signal.return_value = None

        stack_name = 'signal_reception_sync'
        self.stack = self._stack_create(stack_name)
        test_data = {'food': 'yum'}

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy',
                                 test_data,
                                 sync_call=True)
        mock_signal.assert_called_once_with(mock.ANY, False)

    def test_signal_reception_no_resource(self):
        stack_name = 'signal_reception_no_resource'
        self.stack = self._stack_create(stack_name)
        test_data = {'food': 'yum'}

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_signal, self.ctx,
                               dict(self.stack.identifier()),
                               'resource_does_not_exist',
                               test_data)
        self.assertEqual(exception.ResourceNotFound, ex.exc_info[0])

    @mock.patch.object(stack.Stack, 'load')
    @mock.patch.object(service.EngineService, '_get_stack')
    def test_signal_reception_unavailable_resource(self, mock_get, mock_load):
        stack_name = 'signal_reception_unavailable_resource'
        stk = tools.get_stack(stack_name, self.ctx, policy_template)
        stk.store()
        self.stack = stk
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        mock_load.return_value = stk
        mock_get.return_value = s

        test_data = {'food': 'yum'}
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_signal, self.ctx,
                               dict(self.stack.identifier()),
                               'WebServerScaleDownPolicy',
                               test_data)
        self.assertEqual(exception.ResourceNotAvailable, ex.exc_info[0])
        mock_load.assert_called_once_with(self.ctx, stack=mock.ANY,
                                          use_stored_context=mock.ANY)
        mock_get.assert_called_once_with(self.ctx, self.stack.identifier())

    @mock.patch.object(res.Resource, 'signal')
    def test_signal_returns_metadata(self, mock_signal):
        mock_signal.return_value = None
        self.stack = self._stack_create('signal_reception')
        rsrc = self.stack['WebServerScaleDownPolicy']
        test_metadata = {'food': 'yum'}
        rsrc.metadata_set(test_metadata)

        md = self.eng.resource_signal(self.ctx,
                                      dict(self.stack.identifier()),
                                      'WebServerScaleDownPolicy', None,
                                      sync_call=True)
        self.assertEqual(test_metadata, md)
        mock_signal.assert_called_once_with(mock.ANY, False)

    def test_signal_unset_invalid_hook(self):
        self.stack = self._stack_create('signal_unset_invalid_hook')
        details = {'unset_hook': 'invalid_hook'}

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_signal,
                               self.ctx,
                               dict(self.stack.identifier()),
                               'WebServerScaleDownPolicy',
                               details)
        msg = 'Invalid hook type "invalid_hook"'
        self.assertIn(msg, six.text_type(ex.exc_info[1]))
        self.assertEqual(exception.InvalidBreakPointHook,
                         ex.exc_info[0])

    def test_signal_unset_not_defined_hook(self):
        self.stack = self._stack_create('signal_unset_not_defined_hook')
        details = {'unset_hook': 'pre-update'}
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_signal,
                               self.ctx,
                               dict(self.stack.identifier()),
                               'WebServerScaleDownPolicy',
                               details)
        msg = ('The "pre-update" hook is not defined on '
               'AWSScalingPolicy "WebServerScaleDownPolicy"')
        self.assertIn(msg, six.text_type(ex.exc_info[1]))
        self.assertEqual(exception.InvalidBreakPointHook,
                         ex.exc_info[0])

    @mock.patch.object(res.Resource, 'metadata_update')
    @mock.patch.object(res.Resource, 'signal')
    @mock.patch.object(service.EngineService, '_get_stack')
    def test_signal_calls_metadata_update(self, mock_get, mock_signal,
                                          mock_update):
        # fake keystone client
        self.patchobject(keystone.KeystoneClientPlugin, '_create',
                         return_value=test_fakes.FakeKeystoneClient())

        stk = tools.get_stack('signal_reception', self.ctx, policy_template)
        self.stack = stk
        stk.store()
        stk.create()
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)

        mock_get.return_value = s
        mock_signal.return_value = None
        # this will be called once for the Random resource
        mock_update.return_value = None

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy', None,
                                 sync_call=True)
        mock_get.assert_called_once_with(self.ctx, self.stack.identifier())
        mock_signal.assert_called_once_with(mock.ANY, False)
        mock_update.assert_called_once_with()

    @mock.patch.object(res.Resource, 'metadata_update')
    @mock.patch.object(res.Resource, 'signal')
    @mock.patch.object(service.EngineService, '_get_stack')
    def test_signal_no_calls_metadata_update(self, mock_get, mock_signal,
                                             mock_update):
        # fake keystone client
        self.patchobject(keystone.KeystoneClientPlugin, '_create',
                         return_value=test_fakes.FakeKeystoneClient())

        stk = tools.get_stack('signal_reception', self.ctx, policy_template)
        self.stack = stk
        stk.store()
        stk.create()
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        mock_get.return_value = s
        mock_signal.return_value = None
        res.Resource.signal_needs_metadata_updates = False

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy', None,
                                 sync_call=True)

        mock_get.assert_called_once_with(self.ctx, self.stack.identifier())
        mock_signal.assert_called_once_with(mock.ANY, False)
        # this will never be called
        self.assertEqual(0, mock_update.call_count)

        res.Resource.signal_needs_metadata_updates = True

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
        stk = stack.Stack(self.ctx, stack_name, templ)

        self.assertIsNone(stk._resources)
        self.assertIsNone(stk._dependencies)

        resources = stk.resources
        self.assertIsInstance(resources, dict)
        self.assertEqual(2, len(resources))
        self.assertIsInstance(resources.get('foo'),
                              generic_rsrc.GenericResource)
        self.assertIsInstance(resources.get('bar'),
                              generic_rsrc.ResourceWithProps)

        stack_dependencies = stk.dependencies
        self.assertIsInstance(stack_dependencies, dependencies.Dependencies)
        self.assertEqual(2, len(stack_dependencies.graph()))
