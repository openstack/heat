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
from oslo_messaging import conffixture

from heat.engine import resource as res
from heat.engine.resources.aws.ec2 import instance as instances
from heat.engine import service
from heat.engine import stack as parser
from heat.objects import event as event_object
from heat.objects import stack as stack_object
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils


class StackEventTest(common.HeatTestCase):

    def setUp(self):
        super(StackEventTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_event_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.thread_group_mgr = service.ThreadGroupManager()

    @tools.stack_context('service_event_list_test_stack')
    @mock.patch.object(service.EngineService, '_get_stack')
    def test_event_list(self, mock_get):
        mock_get.return_value = stack_object.Stack.get_by_id(self.ctx,
                                                             self.stack.id)
        events = self.eng.list_events(self.ctx, self.stack.identifier())

        self.assertEqual(4, len(events))
        for ev in events:
            self.assertNotIn('root_stack_id', ev)
            self.assertIn('event_identity', ev)
            self.assertIsInstance(ev['event_identity'], dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertIn('resource_name', ev)
            self.assertIn(ev['resource_name'],
                          ('service_event_list_test_stack', 'WebServer'))

            self.assertIn('physical_resource_id', ev)

            self.assertEqual('CREATE', ev['resource_action'])
            self.assertIn(ev['resource_status'], ('IN_PROGRESS', 'COMPLETE'))

            self.assertIn('resource_status_reason', ev)
            self.assertIn(ev['resource_status_reason'],
                          ('state changed',
                           'Stack CREATE started',
                           'Stack CREATE completed successfully'))

            self.assertIn('resource_type', ev)
            self.assertIn(ev['resource_type'],
                          ('AWS::EC2::Instance', 'OS::Heat::Stack'))

            self.assertIn('stack_identity', ev)

            self.assertIn('stack_name', ev)
            self.assertEqual(self.stack.name, ev['stack_name'])

            self.assertIn('event_time', ev)

        mock_get.assert_called_once_with(self.ctx, self.stack.identifier(),
                                         show_deleted=True)

    @tools.stack_context('service_event_list_test_stack')
    @mock.patch.object(service.EngineService, '_get_stack')
    def test_event_list_nested_depth(self, mock_get):
        mock_get.return_value = stack_object.Stack.get_by_id(self.ctx,
                                                             self.stack.id)
        events = self.eng.list_events(self.ctx, self.stack.identifier(),
                                      nested_depth=1)

        self.assertEqual(4, len(events))
        for ev in events:
            self.assertIn('root_stack_id', ev)
        mock_get.assert_called_once_with(self.ctx, self.stack.identifier(),
                                         show_deleted=True)

    @tools.stack_context('service_event_list_deleted_resource')
    @mock.patch.object(instances.Instance, 'handle_delete')
    def test_event_list_deleted_resource(self, mock_delete):
        self.useFixture(conffixture.ConfFixture(cfg.CONF))
        mock_delete.return_value = None

        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)

        thread = mock.Mock()
        thread.link = mock.Mock(return_value=None)

        def run(stack_id, func, *args, **kwargs):
            func(*args, **kwargs)
            return thread
        self.eng.thread_group_mgr.start = run

        new_tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {'AResource': {'Type':
                                                'GenericResourceType'}}}

        result = self.eng.update_stack(self.ctx, self.stack.identifier(),
                                       new_tmpl, None, None, {})

        # The self.stack reference needs to be updated. Since the underlying
        # stack is updated in update_stack, the original reference is now
        # pointing to an orphaned stack object.
        self.stack = parser.Stack.load(self.ctx, stack_id=result['stack_id'])

        self.assertEqual(result, self.stack.identifier())
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        events = self.eng.list_events(self.ctx, self.stack.identifier())

        self.assertEqual(10, len(events))

        for ev in events:
            self.assertIn('event_identity', ev)
            self.assertIsInstance(ev['event_identity'], dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertIn('resource_name', ev)
            self.assertIn('physical_resource_id', ev)
            self.assertIn('resource_status_reason', ev)

            self.assertIn(ev['resource_action'],
                          ('CREATE', 'UPDATE', 'DELETE'))
            self.assertIn(ev['resource_status'], ('IN_PROGRESS', 'COMPLETE'))

            self.assertIn('resource_type', ev)
            self.assertIn(ev['resource_type'], ('AWS::EC2::Instance',
                                                'GenericResourceType',
                                                'OS::Heat::Stack'))

            self.assertIn('stack_identity', ev)

            self.assertIn('stack_name', ev)
            self.assertEqual(self.stack.name, ev['stack_name'])

            self.assertIn('event_time', ev)

        mock_delete.assert_called_once_with()
        expected = [
            mock.call(mock.ANY),
            mock.call(mock.ANY, self.stack.id, mock.ANY)
        ]
        self.assertEqual(expected, thread.link.call_args_list)

    @tools.stack_context('service_event_list_by_tenant')
    def test_event_list_by_tenant(self):
        events = self.eng.list_events(self.ctx, None)

        self.assertEqual(4, len(events))
        for ev in events:
            self.assertIn('event_identity', ev)
            self.assertIsInstance(ev['event_identity'], dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertIn('resource_name', ev)
            self.assertIn(ev['resource_name'],
                          ('WebServer', 'service_event_list_by_tenant'))

            self.assertIn('physical_resource_id', ev)

            self.assertEqual('CREATE', ev['resource_action'])
            self.assertIn(ev['resource_status'], ('IN_PROGRESS', 'COMPLETE'))

            self.assertIn('resource_status_reason', ev)
            self.assertIn(ev['resource_status_reason'],
                          ('state changed',
                           'Stack CREATE started',
                           'Stack CREATE completed successfully'))

            self.assertIn('resource_type', ev)
            self.assertIn(ev['resource_type'],
                          ('AWS::EC2::Instance', 'OS::Heat::Stack'))

            self.assertIn('stack_identity', ev)

            self.assertIn('stack_name', ev)
            self.assertEqual(self.stack.name, ev['stack_name'])

            self.assertIn('event_time', ev)

    @mock.patch.object(event_object.Event, 'get_all_by_stack')
    @mock.patch.object(service.EngineService, '_get_stack')
    def test_event_list_with_marker_and_filters(self, mock_get, mock_get_all):
        limit = object()
        marker = object()
        sort_keys = object()
        sort_dir = object()
        filters = {}
        mock_get.return_value = mock.Mock(id=1)
        self.eng.list_events(self.ctx, 1, limit=limit, marker=marker,
                             sort_keys=sort_keys, sort_dir=sort_dir,
                             filters=filters)

        mock_get_all.assert_called_once_with(self.ctx, 1, limit=limit,
                                             sort_keys=sort_keys,
                                             marker=marker, sort_dir=sort_dir,
                                             filters=filters)

    @mock.patch.object(event_object.Event, 'get_all_by_tenant')
    def test_tenant_events_list_with_marker_and_filters(self, mock_get_all):
        limit = object()
        marker = object()
        sort_keys = object()
        sort_dir = object()
        filters = {}

        self.eng.list_events(self.ctx, None, limit=limit, marker=marker,
                             sort_keys=sort_keys, sort_dir=sort_dir,
                             filters=filters)
        mock_get_all.assert_called_once_with(self.ctx, limit=limit,
                                             sort_keys=sort_keys,
                                             marker=marker,
                                             sort_dir=sort_dir,
                                             filters=filters)

    @tools.stack_context('service_event_list_single_event')
    @mock.patch.object(service.EngineService, '_get_stack')
    def test_event_list_single_has_rsrc_prop_data(self, mock_get):
        mock_get.return_value = stack_object.Stack.get_by_id(self.ctx,
                                                             self.stack.id)
        events = self.eng.list_events(self.ctx, self.stack.identifier())
        self.assertEqual(4, len(events))
        for ev in events:
            self.assertNotIn('resource_properties', ev)

        event_objs = event_object.Event.get_all_by_stack(
            self.ctx,
            self.stack.id)

        for i in range(2):
            event_uuid = event_objs[i]['uuid']
            events = self.eng.list_events(self.ctx, self.stack.identifier(),
                                          filters={'uuid': event_uuid})
            self.assertEqual(1, len(events))
            self.assertIn('resource_properties', events[0])
            if i > 0:
                self.assertEqual(4, len(events[0]['resource_properties']))
