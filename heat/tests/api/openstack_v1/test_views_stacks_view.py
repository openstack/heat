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

from heat.api.openstack.v1.views import stacks_view
from heat.common import identifier
from heat.tests import common


class TestFormatStack(common.HeatTestCase):
    def setUp(self):
        super(TestFormatStack, self).setUp()
        self.request = mock.Mock()

    def test_doesnt_include_stack_action(self):
        stack = {'stack_action': 'CREATE'}

        result = stacks_view.format_stack(self.request, stack)
        self.assertEqual({}, result)

    def test_merges_stack_action_and_status(self):
        stack = {'stack_action': 'CREATE',
                 'stack_status': 'COMPLETE'}

        result = stacks_view.format_stack(self.request, stack)
        self.assertIn('stack_status', result)
        self.assertEqual('CREATE_COMPLETE', result['stack_status'])

    def test_include_stack_status_with_no_action(self):
        stack = {'stack_status': 'COMPLETE'}

        result = stacks_view.format_stack(self.request, stack)
        self.assertIn('stack_status', result)
        self.assertEqual('COMPLETE', result['stack_status'])

    @mock.patch.object(stacks_view, 'util')
    def test_replace_stack_identity_with_id_and_links(self, mock_util):
        mock_util.make_link.return_value = 'blah'
        stack = {'stack_identity': {'stack_id': 'foo'}}

        result = stacks_view.format_stack(self.request, stack)
        self.assertIn('id', result)
        self.assertNotIn('stack_identity', result)
        self.assertEqual('foo', result['id'])

        self.assertIn('links', result)
        self.assertEqual(['blah'], result['links'])

    @mock.patch.object(stacks_view, 'util', new=mock.Mock())
    def test_doesnt_add_project_by_default(self):
        stack = {'stack_identity': {'stack_id': 'foo', 'tenant': 'bar'}}

        result = stacks_view.format_stack(self.request, stack, None)
        self.assertNotIn('project', result)

    @mock.patch.object(stacks_view, 'util', new=mock.Mock())
    def test_doesnt_add_project_if_not_include_project(self):
        stack = {'stack_identity': {'stack_id': 'foo', 'tenant': 'bar'}}

        result = stacks_view.format_stack(self.request, stack,
                                          None, include_project=False)
        self.assertNotIn('project', result)

    @mock.patch.object(stacks_view, 'util', new=mock.Mock())
    def test_adds_project_if_include_project(self):
        stack = {'stack_identity': {'stack_id': 'foo', 'tenant': 'bar'}}

        result = stacks_view.format_stack(self.request, stack,
                                          None, include_project=True)
        self.assertIn('project', result)
        self.assertEqual('bar', result['project'])

    def test_includes_all_other_keys(self):
        stack = {'foo': 'bar'}

        result = stacks_view.format_stack(self.request, stack)
        self.assertIn('foo', result)
        self.assertEqual('bar', result['foo'])

    def test_filter_out_all_but_given_keys(self):
        stack = {
            'foo1': 'bar1',
            'foo2': 'bar2',
            'foo3': 'bar3',
        }

        result = stacks_view.format_stack(self.request, stack, ['foo2'])
        self.assertIn('foo2', result)
        self.assertNotIn('foo1', result)
        self.assertNotIn('foo3', result)


class TestStacksViewBuilder(common.HeatTestCase):
    def setUp(self):
        super(TestStacksViewBuilder, self).setUp()
        self.request = mock.Mock()
        self.request.params = {}
        identity = identifier.HeatIdentifier('123456', 'wordpress', '1')
        self.stack1 = {
            u'stack_identity': dict(identity),
            u'updated_time': u'2012-07-09T09:13:11Z',
            u'template_description': u'blah',
            u'description': u'blah',
            u'stack_status_reason': u'Stack successfully created',
            u'creation_time': u'2012-07-09T09:12:45Z',
            u'stack_name': identity.stack_name,
            u'stack_action': u'CREATE',
            u'stack_status': u'COMPLETE',
            u'parameters': {'foo': 'bar'},
            u'outputs': ['key', 'value'],
            u'notification_topics': [],
            u'capabilities': [],
            u'disable_rollback': True,
            u'timeout_mins': 60,
        }

    def test_stack_index(self):
        stacks = [self.stack1]
        stack_view = stacks_view.collection(self.request, stacks)
        self.assertIn('stacks', stack_view)
        self.assertEqual(1, len(stack_view['stacks']))

    @mock.patch.object(stacks_view, 'format_stack')
    def test_stack_basic_details(self, mock_format_stack):
        stacks = [self.stack1]
        expected_keys = stacks_view.basic_keys

        stacks_view.collection(self.request, stacks)
        mock_format_stack.assert_called_once_with(self.request,
                                                  self.stack1,
                                                  expected_keys,
                                                  mock.ANY)

    @mock.patch.object(stacks_view.views_common, 'get_collection_links')
    def test_append_collection_links(self, mock_get_collection_links):
        # If the page is full, assume a next page exists
        stacks = [self.stack1]
        mock_get_collection_links.return_value = 'fake links'
        stack_view = stacks_view.collection(self.request, stacks)
        self.assertIn('links', stack_view)

    @mock.patch.object(stacks_view.views_common, 'get_collection_links')
    def test_doesnt_append_collection_links(self, mock_get_collection_links):
        stacks = [self.stack1]
        mock_get_collection_links.return_value = None
        stack_view = stacks_view.collection(self.request, stacks)
        self.assertNotIn('links', stack_view)

    @mock.patch.object(stacks_view.views_common, 'get_collection_links')
    def test_append_collection_count(self, mock_get_collection_links):
        stacks = [self.stack1]
        count = 1
        stack_view = stacks_view.collection(self.request, stacks, count)
        self.assertIn('count', stack_view)
        self.assertEqual(1, stack_view['count'])

    @mock.patch.object(stacks_view.views_common, 'get_collection_links')
    def test_doesnt_append_collection_count(self, mock_get_collection_links):
        stacks = [self.stack1]
        stack_view = stacks_view.collection(self.request, stacks)
        self.assertNotIn('count', stack_view)

    @mock.patch.object(stacks_view.views_common, 'get_collection_links')
    def test_appends_collection_count_of_zero(self, mock_get_collection_links):
        stacks = [self.stack1]
        count = 0
        stack_view = stacks_view.collection(self.request, stacks, count)
        self.assertIn('count', stack_view)
        self.assertEqual(0, stack_view['count'])
