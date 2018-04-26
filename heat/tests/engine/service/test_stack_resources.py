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
from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine import dependencies
from heat.engine import resource as res
from heat.engine.resources.aws.ec2 import instance as ins
from heat.engine import service
from heat.engine import stack
from heat.engine import stack_lock
from heat.engine import template as templatem
from heat.objects import stack as stack_object
from heat.tests import common
from heat.tests.engine import tools
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
      "Type" : "OS::Heat::RandomString",
      "DependsOn" : "WebServerScaleDownPolicy"
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

        # Patch _resolve_any_attribute or it tries to call novaclient
        self.patchobject(res.Resource, '_resolve_any_attribute',
                         return_value=None)

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
        self.assertEqual(exception.EntityNotFound, ex.exc_info[0])

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
        self.eng.list_stack_resources(self.ctx,
                                      self.stack.identifier(),
                                      2)
        self.stack.iter_resources.assert_called_once_with(2,
                                                          filters=None)

    @mock.patch.object(stack.Stack, 'load')
    @tools.stack_context('service_resources_list_test_stack_with_max_depth')
    def test_stack_resources_list_with_max_depth(self, mock_load):
        mock_load.return_value = self.stack
        resources = six.itervalues(self.stack)
        self.stack.iter_resources = mock.Mock(return_value=resources)
        self.eng.list_stack_resources(self.ctx,
                                      self.stack.identifier(),
                                      99)
        max_depth = cfg.CONF.max_nested_stack_depth
        self.stack.iter_resources.assert_called_once_with(max_depth,
                                                          filters=None)

    @mock.patch.object(stack.Stack, 'load')
    @tools.stack_context('service_resources_list_test_stack')
    def test_stack_resources_filter_type(self, mock_load):
        mock_load.return_value = self.stack
        resources = six.itervalues(self.stack)
        self.stack.iter_resources = mock.Mock(return_value=resources)
        filters = {'type': 'AWS::EC2::Instance'}
        resources = self.eng.list_stack_resources(self.ctx,
                                                  self.stack.identifier(),
                                                  filters=filters)
        self.stack.iter_resources.assert_called_once_with(
            0, filters={})
        self.assertIn('AWS::EC2::Instance', resources[0]['resource_type'])

    @mock.patch.object(stack.Stack, 'load')
    @tools.stack_context('service_resources_list_test_stack')
    def test_stack_resources_filter_type_not_found(self, mock_load):
        mock_load.return_value = self.stack
        resources = six.itervalues(self.stack)
        self.stack.iter_resources = mock.Mock(return_value=resources)
        filters = {'type': 'NonExisted'}
        resources = self.eng.list_stack_resources(self.ctx,
                                                  self.stack.identifier(),
                                                  filters=filters)
        self.stack.iter_resources.assert_called_once_with(
            0, filters={})
        self.assertEqual(0, len(resources))

    @mock.patch.object(stack.Stack, 'load')
    def test_stack_resources_list_deleted_stack(self, mock_load):
        stk = tools.setup_stack_with_mock(self, 'resource_list_deleted_stack',
                                          self.ctx)
        stack_id = stk.identifier()
        mock_load.return_value = stk
        tools.clean_up_stack(self, stk)
        resources = self.eng.list_stack_resources(self.ctx, stack_id)
        self.assertEqual(0, len(resources))

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
                         return_value=fake_ks.FakeKeystoneClient())

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

    def test_signal_reception_get_resource_none(self):
        stack_name = 'signal_reception_no_resource'
        self.stack = self._stack_create(stack_name)
        test_data = {'food': 'yum'}

        self.patchobject(stack.Stack, 'resource_get',
                         return_value=None)
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_signal, self.ctx,
                               dict(self.stack.identifier()),
                               'WebServerScaleDownPolicy',
                               test_data)
        self.assertEqual(exception.ResourceNotFound, ex.exc_info[0])

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
                         return_value=fake_ks.FakeKeystoneClient())

        stk = tools.get_stack('signal_reception', self.ctx, policy_template)
        self.stack = stk
        stk.store()
        stk.create()
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)

        mock_get.return_value = s
        mock_signal.return_value = True
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
                         return_value=fake_ks.FakeKeystoneClient())

        stk = tools.get_stack('signal_reception', self.ctx, policy_template)
        self.stack = stk
        stk.store()
        stk.create()
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        mock_get.return_value = s
        mock_signal.return_value = False

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy', None,
                                 sync_call=True)

        mock_get.assert_called_once_with(self.ctx, self.stack.identifier())
        mock_signal.assert_called_once_with(mock.ANY, False)
        # this will never be called
        self.assertEqual(0, mock_update.call_count)

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

    @tools.stack_context('service_find_resource_logical_name')
    def test_find_resource_logical_name(self):
        rsrc = self.stack['WebServer']
        physical_rsrc = self.eng._find_resource_in_stack(self.ctx,
                                                         'WebServer',
                                                         self.stack)
        self.assertEqual(rsrc.id, physical_rsrc.id)

    @tools.stack_context('service_find_resource_physical_id')
    def test_find_resource_physical_id(self):
        rsrc = self.stack['WebServer']
        physical_rsrc = self.eng._find_resource_in_stack(self.ctx,
                                                         rsrc.resource_id,
                                                         self.stack)
        self.assertEqual(rsrc.id, physical_rsrc.id)

    @tools.stack_context('service_find_resource_not_found')
    def test_find_resource_nonexist(self):
        self.assertRaises(exception.ResourceNotFound,
                          self.eng._find_resource_in_stack,
                          self.ctx, 'wibble', self.stack)

    def _test_mark_healthy_asserts(self, action='CHECK', status='FAILED',
                                   reason='state changed', meta=None):
        rs = self.eng.describe_stack_resource(
            self.ctx, self.stack.identifier(),
            'WebServer', with_attr=None)
        self.assertIn('resource_action', rs)
        self.assertIn('resource_status', rs)
        self.assertIn('resource_status_reason', rs)

        self.assertEqual(action, rs['resource_action'])
        self.assertEqual(status, rs['resource_status'])
        self.assertEqual(reason, rs['resource_status_reason'])
        if meta is not None:
            self.assertIn('metadata', rs)
            self.assertEqual(meta, rs['metadata'])

    @tools.stack_context('service_mark_healthy_create_complete_test_stk')
    def test_mark_healthy_in_create_complete(self):
        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', False,
                                         resource_status_reason='noop')

        self._test_mark_healthy_asserts(action='CREATE',
                                        status='COMPLETE')

    @tools.stack_context('service_mark_unhealthy_create_complete_test_stk')
    def test_mark_unhealthy_in_create_complete(self):

        reason = 'Some Reason'
        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', True,
                                         resource_status_reason=reason)

        self._test_mark_healthy_asserts(reason=reason)

    @tools.stack_context('service_mark_healthy_check_failed_test_stk')
    def test_mark_healthy_check_failed(self):
        reason = 'Some Reason'
        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', True,
                                         resource_status_reason=reason)
        self._test_mark_healthy_asserts(reason=reason)

        meta = {'for_test': True}

        def override_metadata_reset(rsrc):
            rsrc.metadata_set(meta)

        ins.Instance.handle_metadata_reset = override_metadata_reset

        reason = 'Good Reason'
        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', False,
                                         resource_status_reason=reason)
        self._test_mark_healthy_asserts(status='COMPLETE',
                                        reason=reason,
                                        meta=meta)

    @tools.stack_context('service_mark_unhealthy_check_failed_test_stack')
    def test_mark_unhealthy_check_failed(self):
        reason = 'Some Reason'
        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', True,
                                         resource_status_reason=reason)
        self._test_mark_healthy_asserts(reason=reason)

        new_reason = 'New Reason'
        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', True,
                                         resource_status_reason=new_reason)
        self._test_mark_healthy_asserts(reason=new_reason)

    @tools.stack_context('service_mark_unhealthy_invalid_value_test_stk')
    def test_mark_unhealthy_invalid_value(self):
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_mark_unhealthy,
                               self.ctx,
                               self.stack.identifier(),
                               'WebServer', "This is wrong",
                               resource_status_reason="Some Reason")
        self.assertEqual(exception.Invalid, ex.exc_info[0])

    @tools.stack_context('service_mark_unhealthy_none_reason_test_stk')
    def test_mark_unhealthy_none_reason(self):
        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', True)
        default_reason = 'state changed by resource_mark_unhealthy api'
        self._test_mark_healthy_asserts(reason=default_reason)

    @tools.stack_context('service_mark_unhealthy_empty_reason_test_stk')
    def test_mark_unhealthy_empty_reason(self):
        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', True,
                                         resource_status_reason="")
        default_reason = 'state changed by resource_mark_unhealthy api'
        self._test_mark_healthy_asserts(reason=default_reason)

    @tools.stack_context('service_mark_unhealthy_lock_no_converge_test_stk')
    def test_mark_unhealthy_lock_no_convergence(self):
        mock_acquire = self.patchobject(stack_lock.StackLock,
                                        'acquire',
                                        return_value=None)

        mock_release = self.patchobject(stack_lock.StackLock,
                                        'release',
                                        return_value=None)

        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', True,
                                         resource_status_reason="")

        mock_acquire.assert_called_once_with()
        mock_release.assert_called_once_with()

    @tools.stack_context('service_mark_unhealthy_lock_converge_test_stk',
                         convergence=True)
    def test_mark_unhealthy_stack_lock_convergence(self):
        mock_store_with_lock = self.patchobject(res.Resource,
                                                '_store_with_lock',
                                                return_value=None)

        self.eng.resource_mark_unhealthy(self.ctx, self.stack.identifier(),
                                         'WebServer', True,
                                         resource_status_reason="")

        self.assertEqual(2, mock_store_with_lock.call_count)

    @tools.stack_context('service_mark_unhealthy_lockexc_converge_test_stk',
                         convergence=True)
    def test_mark_unhealthy_stack_lock_exc_convergence(self):
        def _store_with_lock(*args, **kwargs):
            raise exception.UpdateInProgress(self.stack.name)

        self.patchobject(
            res.Resource,
            '_store_with_lock',
            return_value=None,
            side_effect=exception.UpdateInProgress(self.stack.name))
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_mark_unhealthy,
                               self.ctx,
                               self.stack.identifier(),
                               'WebServer', True,
                               resource_status_reason="")
        self.assertEqual(exception.ActionInProgress, ex.exc_info[0])

    @tools.stack_context('service_mark_unhealthy_lockexc_no_converge_test_stk')
    def test_mark_unhealthy_stack_lock_exc_no_convergence(self):
        self.patchobject(
            stack_lock.StackLock,
            'acquire',
            return_value=None,
            side_effect=exception.ActionInProgress(
                stack_name=self.stack.name,
                action=self.stack.action))
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_mark_unhealthy,
                               self.ctx,
                               self.stack.identifier(),
                               'WebServer', True,
                               resource_status_reason="")
        self.assertEqual(exception.ActionInProgress, ex.exc_info[0])
