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

import copy
import datetime
import fixtures
import json
import logging
import time
import uuid

import mock
from oslo_config import cfg
from oslo_db import exception as db_exception
from oslo_utils import timeutils
import six
from sqlalchemy.orm import exc
from sqlalchemy.orm import session


from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.db.sqlalchemy import api as db_api
from heat.db.sqlalchemy import models
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine import resource as rsrc
from heat.engine import stack as parser
from heat.engine import template as tmpl
from heat.engine import template_files
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils

wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
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

UUIDs = (UUID1, UUID2, UUID3) = sorted([str(uuid.uuid4())
                                        for x in range(3)])


class SqlAlchemyTest(common.HeatTestCase):
    def setUp(self):
        super(SqlAlchemyTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.ctx = utils.dummy_context()

    def _mock_get_image_id_success(self, imageId_input, imageId):
        self.patchobject(glance.GlanceClientPlugin,
                         'find_image_by_name_or_id',
                         return_value=imageId)

    def _setup_test_stack(self, stack_name, stack_id=None, owner_id=None,
                          stack_user_project_id=None, backup=False):
        t = template_format.parse(wp_template)
        template = tmpl.Template(
            t, env=environment.Environment({'KeyName': 'test'}))
        stack_id = stack_id or str(uuid.uuid4())
        stack = parser.Stack(self.ctx, stack_name, template,
                             owner_id=owner_id,
                             stack_user_project_id=stack_user_project_id)
        with utils.UUIDStub(stack_id):
            stack.store(backup=backup)
        return (template, stack)

    def _mock_create(self):
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        self._mock_get_image_id_success('F17-x86_64-gold', 744)

        self.fc.servers.create = mock.Mock(
            return_value=self.fc.servers.list()[4])
        return self.fc

    def _mock_delete(self):
        self.patchobject(self.fc.servers, 'delete',
                         side_effect=fakes_nova.fake_exception())

    @mock.patch.object(db_api, '_paginate_query')
    def test_filter_and_page_query_paginates_query(self, mock_paginate_query):
        query = mock.Mock()
        db_api._filter_and_page_query(self.ctx, query)

        self.assertTrue(mock_paginate_query.called)

    @mock.patch.object(db_api, '_events_paginate_query')
    def test_events_filter_and_page_query(self, mock_events_paginate_query):
        query = mock.Mock()
        db_api._events_filter_and_page_query(self.ctx, query)

        self.assertTrue(mock_events_paginate_query.called)

    @mock.patch.object(db_api.utils, 'paginate_query')
    def test_events_filter_invalid_sort_key(self, mock_paginate_query):
        query = mock.Mock()

        class InvalidSortKey(db_api.utils.InvalidSortKey):
            @property
            def message(_):
                self.fail("_events_paginate_query() should not have tried to "
                          "access .message attribute - it's deprecated in "
                          "oslo.db and removed from base Exception in Py3K.")

        mock_paginate_query.side_effect = InvalidSortKey()
        self.assertRaises(exception.Invalid,
                          db_api._events_filter_and_page_query,
                          self.ctx, query, sort_keys=['foo'])

    @mock.patch.object(db_api.db_filters, 'exact_filter')
    def test_filter_and_page_query_handles_no_filters(self, mock_db_filter):
        query = mock.Mock()
        db_api._filter_and_page_query(self.ctx, query)

        mock_db_filter.assert_called_once_with(mock.ANY, mock.ANY, {})

    @mock.patch.object(db_api.db_filters, 'exact_filter')
    def test_events_filter_and_page_query_handles_no_filters(self,
                                                             mock_db_filter):
        query = mock.Mock()
        db_api._events_filter_and_page_query(self.ctx, query)

        mock_db_filter.assert_called_once_with(mock.ANY, mock.ANY, {})

    @mock.patch.object(db_api.db_filters, 'exact_filter')
    def test_filter_and_page_query_applies_filters(self, mock_db_filter):
        query = mock.Mock()
        filters = {'foo': 'bar'}
        db_api._filter_and_page_query(self.ctx, query, filters=filters)

        self.assertTrue(mock_db_filter.called)

    @mock.patch.object(db_api.db_filters, 'exact_filter')
    def test_events_filter_and_page_query_applies_filters(self,
                                                          mock_db_filter):
        query = mock.Mock()
        filters = {'foo': 'bar'}
        db_api._events_filter_and_page_query(self.ctx, query, filters=filters)

        self.assertTrue(mock_db_filter.called)

    @mock.patch.object(db_api, '_paginate_query')
    def test_filter_and_page_query_whitelists_sort_keys(self,
                                                        mock_paginate_query):
        query = mock.Mock()
        sort_keys = ['stack_name', 'foo']
        db_api._filter_and_page_query(self.ctx, query, sort_keys=sort_keys)

        args, _ = mock_paginate_query.call_args
        self.assertIn(['name'], args)

    @mock.patch.object(db_api, '_events_paginate_query')
    def test_events_filter_and_page_query_whitelists_sort_keys(
            self, mock_paginate_query):
        query = mock.Mock()
        sort_keys = ['event_time', 'foo']
        db_api._events_filter_and_page_query(self.ctx, query,
                                             sort_keys=sort_keys)

        args, _ = mock_paginate_query.call_args
        self.assertIn(['created_at'], args)

    @mock.patch.object(db_api.utils, 'paginate_query')
    def test_paginate_query_default_sorts_by_created_at_and_id(
            self, mock_paginate_query):
        query = mock.Mock()
        model = mock.Mock()
        db_api._paginate_query(self.ctx, query, model, sort_keys=None)
        args, _ = mock_paginate_query.call_args
        self.assertIn(['created_at', 'id'], args)

    @mock.patch.object(db_api.utils, 'paginate_query')
    def test_paginate_query_default_sorts_dir_by_desc(self,
                                                      mock_paginate_query):
        query = mock.Mock()
        model = mock.Mock()
        db_api._paginate_query(self.ctx, query, model, sort_dir=None)
        args, _ = mock_paginate_query.call_args
        self.assertIn('desc', args)

    @mock.patch.object(db_api.utils, 'paginate_query')
    def test_paginate_query_uses_given_sort_plus_id(self,
                                                    mock_paginate_query):
        query = mock.Mock()
        model = mock.Mock()
        db_api._paginate_query(self.ctx, query, model, sort_keys=['name'])
        args, _ = mock_paginate_query.call_args
        self.assertIn(['name', 'id'], args)

    @mock.patch.object(db_api.utils, 'paginate_query')
    def test_paginate_query_gets_model_marker(self, mock_paginate_query):
        query = mock.Mock()
        model = mock.Mock()
        marker = mock.Mock()

        mock_query_object = mock.Mock()
        mock_query_object.get.return_value = 'real_marker'
        ctx = mock.MagicMock()
        ctx.session.query.return_value = mock_query_object

        db_api._paginate_query(ctx, query, model, marker=marker)
        mock_query_object.get.assert_called_once_with(marker)
        args, _ = mock_paginate_query.call_args
        self.assertIn('real_marker', args)

    @mock.patch.object(db_api.utils, 'paginate_query')
    def test_paginate_query_raises_invalid_sort_key(self, mock_paginate_query):
        query = mock.Mock()
        model = mock.Mock()

        class InvalidSortKey(db_api.utils.InvalidSortKey):
            @property
            def message(_):
                self.fail("_paginate_query() should not have tried to access "
                          ".message attribute - it's deprecated in oslo.db "
                          "and removed from base Exception class in Py3K.")

        mock_paginate_query.side_effect = InvalidSortKey()
        self.assertRaises(exception.Invalid, db_api._paginate_query,
                          self.ctx, query, model, sort_keys=['foo'])

    def test_get_sort_keys_returns_empty_list_if_no_keys(self):
        sort_keys = None
        mapping = {}

        filtered_keys = db_api._get_sort_keys(sort_keys, mapping)
        self.assertEqual([], filtered_keys)

    def test_get_sort_keys_whitelists_single_key(self):
        sort_key = 'foo'
        mapping = {'foo': 'Foo'}

        filtered_keys = db_api._get_sort_keys(sort_key, mapping)
        self.assertEqual(['Foo'], filtered_keys)

    def test_get_sort_keys_whitelists_multiple_keys(self):
        sort_keys = ['foo', 'bar', 'nope']
        mapping = {'foo': 'Foo', 'bar': 'Bar'}

        filtered_keys = db_api._get_sort_keys(sort_keys, mapping)
        self.assertIn('Foo', filtered_keys)
        self.assertIn('Bar', filtered_keys)
        self.assertEqual(2, len(filtered_keys))

    def test_encryption(self):
        stack_name = 'test_encryption'
        stack = self._setup_test_stack(stack_name)[1]
        self._mock_create()

        stack.create()
        stack = parser.Stack.load(self.ctx, stack.id)
        cs = stack['WebServer']

        cs.data_set('my_secret', 'fake secret', True)
        rs = db_api.resource_get_by_name_and_stack(self.ctx,
                                                   'WebServer',
                                                   stack.id)
        encrypted_key = rs.data[0]['value']
        self.assertNotEqual(encrypted_key, "fake secret")
        # Test private_key property returns decrypted value
        self.assertEqual("fake secret", db_api.resource_data_get(
            self.ctx, cs.id, 'my_secret'))

        # do this twice to verify that the orm does not commit the unencrypted
        # value.
        self.assertEqual("fake secret", db_api.resource_data_get(
            self.ctx, cs.id, 'my_secret'))

        self.fc.servers.create.assert_called_once_with(
            image=744, flavor=3, key_name='test',
            name=mock.ANY,
            security_groups=None,
            userdata=mock.ANY, scheduler_hints=None,
            meta=None, nics=None,
            availability_zone=None,
            block_device_mapping=None
        )

    def test_resource_data_delete(self):
        stack = self._setup_test_stack('stack', UUID1)[1]
        self._mock_create()

        stack.create()
        stack = parser.Stack.load(self.ctx, stack.id)
        resource = stack['WebServer']
        resource.data_set('test', 'test_data')
        self.assertEqual('test_data', db_api.resource_data_get(
            self.ctx, resource.id, 'test'))
        db_api.resource_data_delete(self.ctx, resource.id, 'test')
        self.assertRaises(exception.NotFound,
                          db_api.resource_data_get, self.ctx,
                          resource.id, 'test')

        self.fc.servers.create.assert_called_once_with(
            image=744, flavor=3, key_name='test',
            name=mock.ANY,
            security_groups=None,
            userdata=mock.ANY, scheduler_hints=None,
            meta=None, nics=None,
            availability_zone=None,
            block_device_mapping=None
        )

    def test_stack_get_by_name(self):
        stack = self._setup_test_stack('stack', UUID1,
                                       stack_user_project_id=UUID2)[1]

        st = db_api.stack_get_by_name(self.ctx, 'stack')
        self.assertEqual(UUID1, st.id)

        self.ctx.tenant = UUID3
        st = db_api.stack_get_by_name(self.ctx, 'stack')
        self.assertIsNone(st)

        self.ctx.tenant = UUID2
        st = db_api.stack_get_by_name(self.ctx, 'stack')
        self.assertEqual(UUID1, st.id)

        stack.delete()

        st = db_api.stack_get_by_name(self.ctx, 'stack')
        self.assertIsNone(st)

    def test_nested_stack_get_by_name(self):
        stack1 = self._setup_test_stack('stack1', UUID1)[1]
        stack2 = self._setup_test_stack('stack2', UUID2,
                                        owner_id=stack1.id)[1]

        result = db_api.stack_get_by_name(self.ctx, 'stack2')
        self.assertEqual(UUID2, result.id)

        stack2.delete()

        result = db_api.stack_get_by_name(self.ctx, 'stack2')
        self.assertIsNone(result)

    def test_stack_get_by_name_and_owner_id(self):
        stack1 = self._setup_test_stack('stack1', UUID1,
                                        stack_user_project_id=UUID3)[1]
        stack2 = self._setup_test_stack('stack2', UUID2,
                                        owner_id=stack1.id,
                                        stack_user_project_id=UUID3)[1]

        result = db_api.stack_get_by_name_and_owner_id(self.ctx, 'stack2',
                                                       None)
        self.assertIsNone(result)

        result = db_api.stack_get_by_name_and_owner_id(self.ctx, 'stack2',
                                                       stack1.id)

        self.assertEqual(UUID2, result.id)

        self.ctx.tenant = str(uuid.uuid4())
        result = db_api.stack_get_by_name_and_owner_id(self.ctx, 'stack2',
                                                       None)
        self.assertIsNone(result)

        self.ctx.tenant = UUID3
        result = db_api.stack_get_by_name_and_owner_id(self.ctx, 'stack2',
                                                       stack1.id)

        self.assertEqual(UUID2, result.id)

        stack2.delete()

        result = db_api.stack_get_by_name_and_owner_id(self.ctx, 'stack2',
                                                       stack1.id)
        self.assertIsNone(result)

    def test_stack_get(self):
        stack = self._setup_test_stack('stack', UUID1)[1]

        st = db_api.stack_get(self.ctx, UUID1, show_deleted=False)
        self.assertEqual(UUID1, st.id)

        stack.delete()
        st = db_api.stack_get(self.ctx, UUID1, show_deleted=False)
        self.assertIsNone(st)

        st = db_api.stack_get(self.ctx, UUID1, show_deleted=True)
        self.assertEqual(UUID1, st.id)

    def test_stack_get_status(self):
        stack = self._setup_test_stack('stack', UUID1)[1]

        st = db_api.stack_get_status(self.ctx, UUID1)
        self.assertEqual(('CREATE', 'IN_PROGRESS', '', None), st)

        stack.delete()
        st = db_api.stack_get_status(self.ctx, UUID1)
        self.assertEqual(
            ('DELETE', 'COMPLETE',
             'Stack DELETE completed successfully', None),
            st)

        self.assertRaises(exception.NotFound,
                          db_api.stack_get_status, self.ctx, UUID2)

    def test_stack_get_show_deleted_context(self):
        stack = self._setup_test_stack('stack', UUID1)[1]

        self.assertFalse(self.ctx.show_deleted)
        st = db_api.stack_get(self.ctx, UUID1)
        self.assertEqual(UUID1, st.id)

        stack.delete()
        st = db_api.stack_get(self.ctx, UUID1)
        self.assertIsNone(st)

        self.ctx.show_deleted = True
        st = db_api.stack_get(self.ctx, UUID1)
        self.assertEqual(UUID1, st.id)

    def test_stack_get_all(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_get_all(self.ctx)
        self.assertEqual(3, len(st_db))

        stacks[0].delete()
        st_db = db_api.stack_get_all(self.ctx)
        self.assertEqual(2, len(st_db))

        stacks[1].delete()
        st_db = db_api.stack_get_all(self.ctx)
        self.assertEqual(1, len(st_db))

    def test_stack_get_all_show_deleted(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_get_all(self.ctx)
        self.assertEqual(3, len(st_db))

        stacks[0].delete()
        st_db = db_api.stack_get_all(self.ctx)
        self.assertEqual(2, len(st_db))

        st_db = db_api.stack_get_all(self.ctx, show_deleted=True)
        self.assertEqual(3, len(st_db))

    def test_stack_get_all_show_nested(self):
        stack1 = self._setup_test_stack('stack1', UUID1)[1]
        stack2 = self._setup_test_stack('stack2', UUID2,
                                        owner_id=stack1.id)[1]
        # Backup stack should not be returned
        stack3 = self._setup_test_stack('stack1*', UUID3,
                                        owner_id=stack1.id,
                                        backup=True)[1]

        st_db = db_api.stack_get_all(self.ctx)
        self.assertEqual(1, len(st_db))
        self.assertEqual(stack1.id, st_db[0].id)

        st_db = db_api.stack_get_all(self.ctx, show_nested=True)
        self.assertEqual(2, len(st_db))
        st_ids = [s.id for s in st_db]
        self.assertNotIn(stack3.id, st_ids)
        self.assertIn(stack1.id, st_ids)
        self.assertIn(stack2.id, st_ids)

    def test_stack_get_all_with_filters(self):
        self._setup_test_stack('foo', UUID1)
        self._setup_test_stack('bar', UUID2)

        filters = {'name': 'foo'}
        results = db_api.stack_get_all(self.ctx,
                                       filters=filters)

        self.assertEqual(1, len(results))
        self.assertEqual('foo', results[0]['name'])

    def test_stack_get_all_filter_matches_in_list(self):
        self._setup_test_stack('foo', UUID1)
        self._setup_test_stack('bar', UUID2)

        filters = {'name': ['bar', 'quux']}
        results = db_api.stack_get_all(self.ctx,
                                       filters=filters)

        self.assertEqual(1, len(results))
        self.assertEqual('bar', results[0]['name'])

    def test_stack_get_all_returns_all_if_no_filters(self):
        self._setup_test_stack('foo', UUID1)
        self._setup_test_stack('bar', UUID2)

        filters = None
        results = db_api.stack_get_all(self.ctx,
                                       filters=filters)

        self.assertEqual(2, len(results))

    def test_stack_get_all_default_sort_keys_and_dir(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_get_all(self.ctx)
        self.assertEqual(3, len(st_db))
        self.assertEqual(stacks[2].id, st_db[0].id)
        self.assertEqual(stacks[1].id, st_db[1].id)
        self.assertEqual(stacks[0].id, st_db[2].id)

    def test_stack_get_all_default_sort_dir(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_get_all(self.ctx, sort_dir='asc')
        self.assertEqual(3, len(st_db))
        self.assertEqual(stacks[0].id, st_db[0].id)
        self.assertEqual(stacks[1].id, st_db[1].id)
        self.assertEqual(stacks[2].id, st_db[2].id)

    def test_stack_get_all_str_sort_keys(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_get_all(self.ctx,
                                     sort_keys='creation_time')
        self.assertEqual(3, len(st_db))
        self.assertEqual(stacks[0].id, st_db[0].id)
        self.assertEqual(stacks[1].id, st_db[1].id)
        self.assertEqual(stacks[2].id, st_db[2].id)

    @mock.patch.object(db_api.utils, 'paginate_query')
    def test_stack_get_all_filters_sort_keys(self, mock_paginate):
        sort_keys = ['stack_name', 'stack_status', 'creation_time',
                     'updated_time', 'stack_owner']
        db_api.stack_get_all(self.ctx, sort_keys=sort_keys)

        args = mock_paginate.call_args[0]
        used_sort_keys = set(args[3])
        expected_keys = set(['name', 'status', 'created_at',
                             'updated_at', 'id'])
        self.assertEqual(expected_keys, used_sort_keys)

    def test_stack_get_all_marker(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_get_all(self.ctx, marker=stacks[1].id)
        self.assertEqual(1, len(st_db))
        self.assertEqual(stacks[0].id, st_db[0].id)

    def test_stack_get_all_non_existing_marker(self):
        [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        uuid = 'this stack doesn\'t exist'
        st_db = db_api.stack_get_all(self.ctx, marker=uuid)
        self.assertEqual(3, len(st_db))

    def test_stack_get_all_doesnt_mutate_sort_keys(self):
        [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        sort_keys = ['id']

        db_api.stack_get_all(self.ctx, sort_keys=sort_keys)
        self.assertEqual(['id'], sort_keys)

    def test_stack_get_all_hidden_tags(self):
        cfg.CONF.set_override('hidden_stack_tags', ['hidden'])

        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['hidden']
        stacks[0].store()
        stacks[1].tags = ['random']
        stacks[1].store()

        st_db = db_api.stack_get_all(self.ctx, show_hidden=True)
        self.assertEqual(3, len(st_db))

        st_db_visible = db_api.stack_get_all(self.ctx, show_hidden=False)
        self.assertEqual(2, len(st_db_visible))

        # Make sure the hidden stack isn't in the stacks returned by
        # stack_get_all_visible()
        for stack in st_db_visible:
            self.assertNotEqual(stacks[0].id, stack.id)

    def test_stack_get_all_by_tags(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['tag1']
        stacks[0].store()
        stacks[1].tags = ['tag1', 'tag2']
        stacks[1].store()
        stacks[2].tags = ['tag1', 'tag2', 'tag3']
        stacks[2].store()

        st_db = db_api.stack_get_all(self.ctx, tags=['tag2'])
        self.assertEqual(2, len(st_db))

        st_db = db_api.stack_get_all(self.ctx, tags=['tag1', 'tag2'])
        self.assertEqual(2, len(st_db))

        st_db = db_api.stack_get_all(self.ctx, tags=['tag1', 'tag2', 'tag3'])
        self.assertEqual(1, len(st_db))

    def test_stack_get_all_by_tags_any(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['tag2']
        stacks[0].store()
        stacks[1].tags = ['tag1', 'tag2']
        stacks[1].store()
        stacks[2].tags = ['tag1', 'tag3']
        stacks[2].store()

        st_db = db_api.stack_get_all(self.ctx, tags_any=['tag1'])
        self.assertEqual(2, len(st_db))

        st_db = db_api.stack_get_all(self.ctx, tags_any=['tag1', 'tag2',
                                                         'tag3'])
        self.assertEqual(3, len(st_db))

    def test_stack_get_all_by_not_tags(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['tag1']
        stacks[0].store()
        stacks[1].tags = ['tag1', 'tag2']
        stacks[1].store()
        stacks[2].tags = ['tag1', 'tag2', 'tag3']
        stacks[2].store()

        st_db = db_api.stack_get_all(self.ctx, not_tags=['tag2'])
        self.assertEqual(1, len(st_db))

        st_db = db_api.stack_get_all(self.ctx, not_tags=['tag1', 'tag2'])
        self.assertEqual(1, len(st_db))

        st_db = db_api.stack_get_all(self.ctx, not_tags=['tag1', 'tag2',
                                                         'tag3'])
        self.assertEqual(2, len(st_db))

    def test_stack_get_all_by_not_tags_any(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['tag2']
        stacks[0].store()
        stacks[1].tags = ['tag1', 'tag2']
        stacks[1].store()
        stacks[2].tags = ['tag1', 'tag3']
        stacks[2].store()

        st_db = db_api.stack_get_all(self.ctx, not_tags_any=['tag1'])
        self.assertEqual(1, len(st_db))

        st_db = db_api.stack_get_all(self.ctx, not_tags_any=['tag1', 'tag2',
                                                             'tag3'])
        self.assertEqual(0, len(st_db))

    def test_stack_get_all_by_tag_with_pagination(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['tag1']
        stacks[0].store()
        stacks[1].tags = ['tag2']
        stacks[1].store()
        stacks[2].tags = ['tag1']
        stacks[2].store()

        st_db = db_api.stack_get_all(self.ctx, tags=['tag1'])
        self.assertEqual(2, len(st_db))

        st_db = db_api.stack_get_all(self.ctx, tags=['tag1'], limit=1)
        self.assertEqual(1, len(st_db))
        self.assertEqual(stacks[2].id, st_db[0].id)

        st_db = db_api.stack_get_all(self.ctx, tags=['tag1'], limit=1,
                                     marker=stacks[2].id)
        self.assertEqual(1, len(st_db))
        self.assertEqual(stacks[0].id, st_db[0].id)

    def test_stack_get_all_by_tag_with_show_hidden(self):
        cfg.CONF.set_override('hidden_stack_tags', ['hidden'])

        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['tag1']
        stacks[0].store()
        stacks[1].tags = ['hidden', 'tag1']
        stacks[1].store()

        st_db = db_api.stack_get_all(self.ctx, tags=['tag1'],
                                     show_hidden=True)
        self.assertEqual(2, len(st_db))

        st_db = db_api.stack_get_all(self.ctx, tags=['tag1'],
                                     show_hidden=False)
        self.assertEqual(1, len(st_db))

    def test_stack_count_all(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_count_all(self.ctx)
        self.assertEqual(3, st_db)

        stacks[0].delete()
        st_db = db_api.stack_count_all(self.ctx)
        self.assertEqual(2, st_db)
        # show deleted
        st_db = db_api.stack_count_all(self.ctx, show_deleted=True)
        self.assertEqual(3, st_db)

        stacks[1].delete()
        st_db = db_api.stack_count_all(self.ctx)
        self.assertEqual(1, st_db)
        # show deleted
        st_db = db_api.stack_count_all(self.ctx, show_deleted=True)
        self.assertEqual(3, st_db)

    def test_count_all_hidden_tags(self):
        cfg.CONF.set_override('hidden_stack_tags', ['hidden'])

        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['hidden']
        stacks[0].store()
        stacks[1].tags = ['random']
        stacks[1].store()

        st_db = db_api.stack_count_all(self.ctx, show_hidden=True)
        self.assertEqual(3, st_db)

        st_db_visible = db_api.stack_count_all(self.ctx, show_hidden=False)
        self.assertEqual(2, st_db_visible)

    def test_count_all_by_tags(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['tag1']
        stacks[0].store()
        stacks[1].tags = ['tag2']
        stacks[1].store()
        stacks[2].tags = ['tag2']
        stacks[2].store()

        st_db = db_api.stack_count_all(self.ctx, tags=['tag1'])
        self.assertEqual(1, st_db)

        st_db = db_api.stack_count_all(self.ctx, tags=['tag2'])
        self.assertEqual(2, st_db)

    def test_count_all_by_tag_with_show_hidden(self):
        cfg.CONF.set_override('hidden_stack_tags', ['hidden'])

        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        stacks[0].tags = ['tag1']
        stacks[0].store()
        stacks[1].tags = ['hidden', 'tag1']
        stacks[1].store()

        st_db = db_api.stack_count_all(self.ctx, tags=['tag1'],
                                       show_hidden=True)
        self.assertEqual(2, st_db)

        st_db = db_api.stack_count_all(self.ctx, tags=['tag1'],
                                       show_hidden=False)
        self.assertEqual(1, st_db)

    def test_stack_count_all_with_filters(self):
        self._setup_test_stack('foo', UUID1)
        self._setup_test_stack('bar', UUID2)
        self._setup_test_stack('bar', UUID3)
        filters = {'name': 'bar'}

        st_db = db_api.stack_count_all(self.ctx, filters=filters)
        self.assertEqual(2, st_db)

    def test_stack_count_all_show_nested(self):
        stack1 = self._setup_test_stack('stack1', UUID1)[1]
        self._setup_test_stack('stack2', UUID2,
                               owner_id=stack1.id)
        # Backup stack should not be counted
        self._setup_test_stack('stack1*', UUID3,
                               owner_id=stack1.id,
                               backup=True)

        st_db = db_api.stack_count_all(self.ctx)
        self.assertEqual(1, st_db)

        st_db = db_api.stack_count_all(self.ctx, show_nested=True)
        self.assertEqual(2, st_db)

    def test_event_get_all_by_stack(self):
        stack = self._setup_test_stack('stack', UUID1)[1]
        self._mock_create()

        stack.create()
        stack._persist_state()

        events = db_api.event_get_all_by_stack(self.ctx, UUID1)
        self.assertEqual(4, len(events))

        # test filter by resource_status
        filters = {'resource_status': 'COMPLETE'}
        events = db_api.event_get_all_by_stack(self.ctx, UUID1,
                                               filters=filters)
        self.assertEqual(2, len(events))
        self.assertEqual('COMPLETE', events[0].resource_status)
        self.assertEqual('COMPLETE', events[1].resource_status)
        # test filter by resource_action
        filters = {'resource_action': 'CREATE'}
        events = db_api.event_get_all_by_stack(self.ctx, UUID1,
                                               filters=filters)
        self.assertEqual(4, len(events))
        self.assertEqual('CREATE', events[0].resource_action)
        self.assertEqual('CREATE', events[1].resource_action)
        self.assertEqual('CREATE', events[2].resource_action)
        self.assertEqual('CREATE', events[3].resource_action)
        # test filter by resource_type
        filters = {'resource_type': 'AWS::EC2::Instance'}
        events = db_api.event_get_all_by_stack(self.ctx, UUID1,
                                               filters=filters)
        self.assertEqual(2, len(events))
        self.assertEqual('AWS::EC2::Instance', events[0].resource_type)
        self.assertEqual('AWS::EC2::Instance', events[1].resource_type)

        filters = {'resource_type': 'OS::Nova::Server'}
        events = db_api.event_get_all_by_stack(self.ctx, UUID1,
                                               filters=filters)
        self.assertEqual(0, len(events))
        # test limit and marker
        events_all = db_api.event_get_all_by_stack(self.ctx, UUID1)
        marker = events_all[0].uuid
        expected = events_all[1].uuid
        events = db_api.event_get_all_by_stack(self.ctx, UUID1,
                                               limit=1, marker=marker)
        self.assertEqual(1, len(events))
        self.assertEqual(expected, events[0].uuid)

        self._mock_delete()
        stack.delete()

        # test filter by resource_status
        filters = {'resource_status': 'COMPLETE'}
        events = db_api.event_get_all_by_stack(self.ctx, UUID1,
                                               filters=filters)
        self.assertEqual(4, len(events))
        self.assertEqual('COMPLETE', events[0].resource_status)
        self.assertEqual('COMPLETE', events[1].resource_status)
        self.assertEqual('COMPLETE', events[2].resource_status)
        self.assertEqual('COMPLETE', events[3].resource_status)
        # test filter by resource_action
        filters = {'resource_action': 'DELETE',
                   'resource_status': 'COMPLETE'}
        events = db_api.event_get_all_by_stack(self.ctx, UUID1,
                                               filters=filters)
        self.assertEqual(2, len(events))
        self.assertEqual('DELETE', events[0].resource_action)
        self.assertEqual('COMPLETE', events[0].resource_status)
        self.assertEqual('DELETE', events[1].resource_action)
        self.assertEqual('COMPLETE', events[1].resource_status)
        # test limit and marker
        events_all = db_api.event_get_all_by_stack(self.ctx, UUID1)
        self.assertEqual(8, len(events_all))

        marker = events_all[1].uuid
        events2_uuid = events_all[2].uuid
        events3_uuid = events_all[3].uuid
        events = db_api.event_get_all_by_stack(self.ctx, UUID1,
                                               limit=1, marker=marker)
        self.assertEqual(1, len(events))
        self.assertEqual(events2_uuid, events[0].uuid)

        events = db_api.event_get_all_by_stack(self.ctx, UUID1,
                                               limit=2, marker=marker)
        self.assertEqual(2, len(events))
        self.assertEqual(events2_uuid, events[0].uuid)
        self.assertEqual(events3_uuid, events[1].uuid)

        self.fc.servers.create.assert_called_once_with(
            image=744, flavor=3, key_name='test',
            name=mock.ANY,
            security_groups=None,
            userdata=mock.ANY, scheduler_hints=None,
            meta=None, nics=None,
            availability_zone=None,
            block_device_mapping=None
        )

    def test_event_count_all_by_stack(self):
        stack = self._setup_test_stack('stack', UUID1)[1]
        self._mock_create()

        stack.create()
        stack._persist_state()

        num_events = db_api.event_count_all_by_stack(self.ctx, UUID1)
        self.assertEqual(4, num_events)

        self._mock_delete()
        stack.delete()

        num_events = db_api.event_count_all_by_stack(self.ctx, UUID1)
        self.assertEqual(8, num_events)

        self.fc.servers.create.assert_called_once_with(
            image=744, flavor=3, key_name='test',
            name=mock.ANY,
            security_groups=None,
            userdata=mock.ANY, scheduler_hints=None,
            meta=None, nics=None,
            availability_zone=None,
            block_device_mapping=None
        )

    def test_event_get_all_by_tenant(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        self._mock_create()

        [s.create() for s in stacks]
        [s._persist_state() for s in stacks]

        events = db_api.event_get_all_by_tenant(self.ctx)
        self.assertEqual(12, len(events))

        self._mock_delete()
        [s.delete() for s in stacks]

        events = db_api.event_get_all_by_tenant(self.ctx)
        self.assertEqual(0, len(events))

        self.fc.servers.create.assert_called_with(
            image=744, flavor=3, key_name='test',
            name=mock.ANY,
            security_groups=None,
            userdata=mock.ANY, scheduler_hints=None,
            meta=None, nics=None,
            availability_zone=None,
            block_device_mapping=None
        )
        self.assertEqual(len(stacks), self.fc.servers.create.call_count)

    def test_user_creds_password(self):
        self.ctx.password = 'password'
        self.ctx.trust_id = None
        self.ctx.region_name = 'RegionOne'
        db_creds = db_api.user_creds_create(self.ctx)
        load_creds = db_api.user_creds_get(self.ctx, db_creds['id'])

        self.assertEqual('test_username', load_creds.get('username'))
        self.assertEqual('password', load_creds.get('password'))
        self.assertEqual('test_tenant', load_creds.get('tenant'))
        self.assertEqual('test_tenant_id', load_creds.get('tenant_id'))
        self.assertEqual('RegionOne', load_creds.get('region_name'))
        self.assertIsNotNone(load_creds.get('created_at'))
        self.assertIsNone(load_creds.get('updated_at'))
        self.assertEqual('http://server.test:5000/v2.0',
                         load_creds.get('auth_url'))
        self.assertIsNone(load_creds.get('trust_id'))
        self.assertIsNone(load_creds.get('trustor_user_id'))

    def test_user_creds_password_too_long(self):
        self.ctx.trust_id = None
        self.ctx.password = 'O123456789O1234567' * 20
        error = self.assertRaises(exception.Error,
                                  db_api.user_creds_create,
                                  self.ctx)
        self.assertIn('Length of OS_PASSWORD after encryption exceeds '
                      'Heat limit (255 chars)', six.text_type(error))

    def test_user_creds_trust(self):
        self.ctx.username = None
        self.ctx.password = None
        self.ctx.trust_id = 'atrust123'
        self.ctx.trustor_user_id = 'atrustor123'
        self.ctx.tenant = 'atenant123'
        self.ctx.project_name = 'atenant'
        self.ctx.auth_url = 'anauthurl'
        self.ctx.region_name = 'aregion'
        db_creds = db_api.user_creds_create(self.ctx)
        load_creds = db_api.user_creds_get(self.ctx, db_creds['id'])

        self.assertIsNone(load_creds.get('username'))
        self.assertIsNone(load_creds.get('password'))
        self.assertIsNotNone(load_creds.get('created_at'))
        self.assertIsNone(load_creds.get('updated_at'))
        self.assertEqual('anauthurl', load_creds.get('auth_url'))
        self.assertEqual('aregion', load_creds.get('region_name'))
        self.assertEqual('atenant123', load_creds.get('tenant_id'))
        self.assertEqual('atenant', load_creds.get('tenant'))
        self.assertEqual('atrust123', load_creds.get('trust_id'))
        self.assertEqual('atrustor123', load_creds.get('trustor_user_id'))

    def test_user_creds_none(self):
        self.ctx.username = None
        self.ctx.password = None
        self.ctx.trust_id = None
        self.ctx.region_name = None
        db_creds = db_api.user_creds_create(self.ctx)
        load_creds = db_api.user_creds_get(self.ctx, db_creds['id'])

        self.assertIsNone(load_creds.get('username'))
        self.assertIsNone(load_creds.get('password'))
        self.assertIsNone(load_creds.get('trust_id'))
        self.assertIsNone(load_creds.get('region_name'))

    def test_software_config_create(self):
        tenant_id = self.ctx.tenant_id
        config = db_api.software_config_create(
            self.ctx, {'name': 'config_mysql',
                       'tenant': tenant_id})
        self.assertIsNotNone(config)
        self.assertEqual('config_mysql', config.name)
        self.assertEqual(tenant_id, config.tenant)

    def test_software_config_get(self):
        self.assertRaises(
            exception.NotFound,
            db_api.software_config_get,
            self.ctx,
            str(uuid.uuid4()))
        conf = ('#!/bin/bash\n'
                'echo "$bar and $foo"\n')
        config = {
            'inputs': [{'name': 'foo'}, {'name': 'bar'}],
            'outputs': [{'name': 'result'}],
            'config': conf,
            'options': {}
        }
        tenant_id = self.ctx.tenant_id
        values = {'name': 'config_mysql',
                  'tenant': tenant_id,
                  'group': 'Heat::Shell',
                  'config': config}
        config = db_api.software_config_create(
            self.ctx, values)
        config_id = config.id
        config = db_api.software_config_get(self.ctx, config_id)
        self.assertIsNotNone(config)
        self.assertEqual('config_mysql', config.name)
        self.assertEqual(tenant_id, config.tenant)
        self.assertEqual('Heat::Shell', config.group)
        self.assertEqual(conf, config.config['config'])
        self.ctx.tenant = None
        self.assertRaises(
            exception.NotFound,
            db_api.software_config_get,
            self.ctx,
            config_id)
        # admin can get the software_config
        admin_ctx = utils.dummy_context(is_admin=True,
                                        tenant_id='admin_tenant')
        config = db_api.software_config_get(admin_ctx, config_id)
        self.assertIsNotNone(config)

    def _create_software_config_record(self):
        tenant_id = self.ctx.tenant_id
        software_config = db_api.software_config_create(
            self.ctx, {'name': 'config_mysql',
                       'tenant': tenant_id})
        self.assertIsNotNone(software_config)

        return software_config.id

    def _test_software_config_get_all(self, get_ctx=None):
        self.assertEqual([], db_api.software_config_get_all(self.ctx))
        scf_id = self._create_software_config_record()
        software_configs = db_api.software_config_get_all(get_ctx or self.ctx)
        self.assertEqual(1, len(software_configs))
        self.assertEqual(scf_id, software_configs[0].id)

    def test_software_config_get_all(self):
        self._test_software_config_get_all()

    def test_software_config_get_all_by_admin(self):
        admin_ctx = utils.dummy_context(is_admin=True,
                                        tenant_id='admin_tenant')
        self._test_software_config_get_all(get_ctx=admin_ctx)

    def test_software_config_delete(self):
        scf_id = self._create_software_config_record()

        cfg = db_api.software_config_get(self.ctx, scf_id)
        self.assertIsNotNone(cfg)

        db_api.software_config_delete(self.ctx, scf_id)
        err = self.assertRaises(
            exception.NotFound,
            db_api.software_config_get,
            self.ctx,
            scf_id)
        self.assertIn(scf_id, six.text_type(err))

        err = self.assertRaises(
            exception.NotFound, db_api.software_config_delete,
            self.ctx, scf_id)
        self.assertIn(scf_id, six.text_type(err))

    def test_software_config_delete_by_admin(self):
        scf_id = self._create_software_config_record()
        cfg = db_api.software_config_get(self.ctx, scf_id)
        self.assertIsNotNone(cfg)
        admin_ctx = utils.dummy_context(is_admin=True,
                                        tenant_id='admin_tenant')
        db_api.software_config_delete(admin_ctx, scf_id)

    def test_software_config_delete_not_allowed(self):
        tenant_id = self.ctx.tenant_id
        config = db_api.software_config_create(
            self.ctx, {'name': 'config_mysql',
                       'tenant': tenant_id})
        config_id = config.id
        values = {
            'tenant': tenant_id,
            'stack_user_project_id': str(uuid.uuid4()),
            'config_id': config_id,
            'server_id': str(uuid.uuid4()),
        }
        db_api.software_deployment_create(self.ctx, values)
        err = self.assertRaises(
            exception.InvalidRestrictedAction, db_api.software_config_delete,
            self.ctx, config_id)
        msg = ("Software config with id %s can not be deleted as it is "
               "referenced" % config_id)
        self.assertIn(msg, six.text_type(err))

    def _deployment_values(self):
        tenant_id = self.ctx.tenant_id
        stack_user_project_id = str(uuid.uuid4())
        config_id = db_api.software_config_create(
            self.ctx, {'name': 'config_mysql', 'tenant': tenant_id}).id
        server_id = str(uuid.uuid4())
        input_values = {'foo': 'fooooo', 'bar': 'baaaaa'}
        values = {
            'tenant': tenant_id,
            'stack_user_project_id': stack_user_project_id,
            'config_id': config_id,
            'server_id': server_id,
            'input_values': input_values
        }
        return values

    def test_software_deployment_create(self):
        values = self._deployment_values()
        deployment = db_api.software_deployment_create(self.ctx, values)
        self.assertIsNotNone(deployment)
        self.assertEqual(values['tenant'], deployment.tenant)

    def test_software_deployment_get(self):
        self.assertRaises(
            exception.NotFound,
            db_api.software_deployment_get,
            self.ctx,
            str(uuid.uuid4()))
        values = self._deployment_values()
        deployment = db_api.software_deployment_create(self.ctx, values)
        self.assertIsNotNone(deployment)
        deployment_id = deployment.id
        deployment = db_api.software_deployment_get(self.ctx, deployment_id)
        self.assertIsNotNone(deployment)
        self.assertEqual(values['tenant'], deployment.tenant)
        self.assertEqual(values['config_id'], deployment.config_id)
        self.assertEqual(values['server_id'], deployment.server_id)
        self.assertEqual(values['input_values'], deployment.input_values)
        self.assertEqual(
            values['stack_user_project_id'], deployment.stack_user_project_id)

        # assert not found with invalid context tenant
        self.ctx.tenant = str(uuid.uuid4())
        self.assertRaises(
            exception.NotFound,
            db_api.software_deployment_get,
            self.ctx,
            deployment_id)

        # assert found with stack_user_project_id context tenant
        self.ctx.tenant = deployment.stack_user_project_id
        deployment = db_api.software_deployment_get(self.ctx, deployment_id)
        self.assertIsNotNone(deployment)
        self.assertEqual(values['tenant'], deployment.tenant)

        # admin can get the deployments
        admin_ctx = utils.dummy_context(is_admin=True,
                                        tenant_id='admin_tenant')
        deployment = db_api.software_deployment_get(admin_ctx, deployment_id)
        self.assertIsNotNone(deployment)

    def test_software_deployment_get_all(self):
        self.assertEqual([], db_api.software_deployment_get_all(self.ctx))
        values = self._deployment_values()
        deployment = db_api.software_deployment_create(self.ctx, values)
        self.assertIsNotNone(deployment)
        deployments = db_api.software_deployment_get_all(self.ctx)
        self.assertEqual(1, len(deployments))
        self.assertEqual(deployment.id, deployments[0].id)
        deployments = db_api.software_deployment_get_all(
            self.ctx, server_id=values['server_id'])
        self.assertEqual(1, len(deployments))
        self.assertEqual(deployment.id, deployments[0].id)
        deployments = db_api.software_deployment_get_all(
            self.ctx, server_id=str(uuid.uuid4()))
        self.assertEqual([], deployments)
        # admin can get the deployments of other tenants
        admin_ctx = utils.dummy_context(is_admin=True,
                                        tenant_id='admin_tenant')
        deployments = db_api.software_deployment_get_all(admin_ctx)
        self.assertEqual(1, len(deployments))

    def test_software_deployment_update(self):
        deployment_id = str(uuid.uuid4())
        err = self.assertRaises(exception.NotFound,
                                db_api.software_deployment_update,
                                self.ctx, deployment_id, values={})
        self.assertIn(deployment_id, six.text_type(err))
        values = self._deployment_values()
        deployment = db_api.software_deployment_create(self.ctx, values)
        deployment_id = deployment.id
        values = {'status': 'COMPLETED'}
        deployment = db_api.software_deployment_update(
            self.ctx, deployment_id, values)
        self.assertIsNotNone(deployment)
        self.assertEqual(values['status'], deployment.status)
        admin_ctx = utils.dummy_context(is_admin=True,
                                        tenant_id='admin_tenant')
        values = {'status': 'FAILED'}
        deployment = db_api.software_deployment_update(
            admin_ctx, deployment_id, values)
        self.assertIsNotNone(deployment)
        self.assertEqual(values['status'], deployment.status)

    def _test_software_deployment_delete(self, test_ctx=None):
        deployment_id = str(uuid.uuid4())
        err = self.assertRaises(exception.NotFound,
                                db_api.software_deployment_delete,
                                self.ctx, deployment_id)
        self.assertIn(deployment_id, six.text_type(err))
        values = self._deployment_values()
        deployment = db_api.software_deployment_create(self.ctx, values)
        deployment_id = deployment.id
        test_ctx = test_ctx or self.ctx
        deployment = db_api.software_deployment_get(test_ctx, deployment_id)
        self.assertIsNotNone(deployment)
        db_api.software_deployment_delete(test_ctx, deployment_id)

        err = self.assertRaises(
            exception.NotFound,
            db_api.software_deployment_get,
            test_ctx,
            deployment_id)

        self.assertIn(deployment_id, six.text_type(err))

    def test_software_deployment_delete(self):
        self._test_software_deployment_delete()

    def test_software_deployment_delete_by_admin(self):
        admin_ctx = utils.dummy_context(is_admin=True,
                                        tenant_id='admin_tenant')

        self._test_software_deployment_delete(test_ctx=admin_ctx)

    def test_snapshot_create(self):
        template = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, template, user_creds)
        values = {'tenant': self.ctx.tenant_id, 'status': 'IN_PROGRESS',
                  'stack_id': stack.id}
        snapshot = db_api.snapshot_create(self.ctx, values)
        self.assertIsNotNone(snapshot)
        self.assertEqual(values['tenant'], snapshot.tenant)

    def test_snapshot_create_with_name(self):
        template = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, template, user_creds)
        values = {'tenant': self.ctx.tenant_id, 'status': 'IN_PROGRESS',
                  'stack_id': stack.id, 'name': 'snap1'}
        snapshot = db_api.snapshot_create(self.ctx, values)
        self.assertIsNotNone(snapshot)
        self.assertEqual(values['tenant'], snapshot.tenant)
        self.assertEqual('snap1', snapshot.name)

    def test_snapshot_get_not_found(self):
        self.assertRaises(
            exception.NotFound,
            db_api.snapshot_get,
            self.ctx,
            str(uuid.uuid4()))

    def test_snapshot_get(self):
        template = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, template, user_creds)
        values = {'tenant': self.ctx.tenant_id, 'status': 'IN_PROGRESS',
                  'stack_id': stack.id}
        snapshot = db_api.snapshot_create(self.ctx, values)
        self.assertIsNotNone(snapshot)
        snapshot_id = snapshot.id
        snapshot = db_api.snapshot_get(self.ctx, snapshot_id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(values['tenant'], snapshot.tenant)
        self.assertEqual(values['status'], snapshot.status)
        self.assertIsNotNone(snapshot.created_at)

    def test_snapshot_get_by_another_stack(self):
        template = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, template, user_creds)
        stack1 = create_stack(self.ctx, template, user_creds)
        values = {'tenant': self.ctx.tenant_id, 'status': 'IN_PROGRESS',
                  'stack_id': stack.id}
        snapshot = db_api.snapshot_create(self.ctx, values)
        self.assertIsNotNone(snapshot)
        snapshot_id = snapshot.id
        self.assertRaises(exception.SnapshotNotFound,
                          db_api.snapshot_get_by_stack,
                          self.ctx, snapshot_id, stack1)

    def test_snapshot_get_not_found_invalid_tenant(self):
        template = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, template, user_creds)
        values = {'tenant': self.ctx.tenant_id, 'status': 'IN_PROGRESS',
                  'stack_id': stack.id}
        snapshot = db_api.snapshot_create(self.ctx, values)
        self.ctx.tenant = str(uuid.uuid4())
        self.assertRaises(
            exception.NotFound,
            db_api.snapshot_get,
            self.ctx,
            snapshot.id)

    def test_snapshot_update_not_found(self):
        snapshot_id = str(uuid.uuid4())
        err = self.assertRaises(exception.NotFound,
                                db_api.snapshot_update,
                                self.ctx, snapshot_id, values={})
        self.assertIn(snapshot_id, six.text_type(err))

    def test_snapshot_update(self):
        template = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, template, user_creds)
        values = {'tenant': self.ctx.tenant_id, 'status': 'IN_PROGRESS',
                  'stack_id': stack.id}
        snapshot = db_api.snapshot_create(self.ctx, values)
        snapshot_id = snapshot.id
        values = {'status': 'COMPLETED'}
        snapshot = db_api.snapshot_update(self.ctx, snapshot_id, values)
        self.assertIsNotNone(snapshot)
        self.assertEqual(values['status'], snapshot.status)

    def test_snapshot_delete_not_found(self):
        snapshot_id = str(uuid.uuid4())
        err = self.assertRaises(exception.NotFound,
                                db_api.snapshot_delete,
                                self.ctx, snapshot_id)
        self.assertIn(snapshot_id, six.text_type(err))

    def test_snapshot_delete(self):
        template = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, template, user_creds)
        values = {'tenant': self.ctx.tenant_id, 'status': 'IN_PROGRESS',
                  'stack_id': stack.id}
        snapshot = db_api.snapshot_create(self.ctx, values)
        snapshot_id = snapshot.id
        snapshot = db_api.snapshot_get(self.ctx, snapshot_id)
        self.assertIsNotNone(snapshot)
        db_api.snapshot_delete(self.ctx, snapshot_id)

        err = self.assertRaises(
            exception.NotFound,
            db_api.snapshot_get,
            self.ctx,
            snapshot_id)

        self.assertIn(snapshot_id, six.text_type(err))

    def test_snapshot_get_all(self):
        template = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, template, user_creds)
        values = {'tenant': self.ctx.tenant_id, 'status': 'IN_PROGRESS',
                  'stack_id': stack.id}
        snapshot = db_api.snapshot_create(self.ctx, values)
        self.assertIsNotNone(snapshot)
        [snapshot] = db_api.snapshot_get_all(self.ctx, stack.id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(values['tenant'], snapshot.tenant)
        self.assertEqual(values['status'], snapshot.status)
        self.assertIsNotNone(snapshot.created_at)


def create_raw_template(context, **kwargs):
    t = template_format.parse(wp_template)
    template = {
        'template': t,
    }
    if 'files' not in kwargs and 'files_id' not in kwargs:
        # modern raw_templates have associated raw_template_files db obj
        tf = template_files.TemplateFiles({'foo': 'bar'})
        tf.store(context)
        kwargs['files_id'] = tf.files_id
    template.update(kwargs)
    return db_api.raw_template_create(context, template)


def create_user_creds(ctx, **kwargs):
    ctx_dict = ctx.to_dict()
    ctx_dict.update(kwargs)
    ctx = context.RequestContext.from_dict(ctx_dict)
    return db_api.user_creds_create(ctx)


def create_stack(ctx, template, user_creds, **kwargs):
    values = {
        'name': 'db_test_stack_name',
        'raw_template_id': template.id,
        'username': ctx.username,
        'tenant': ctx.tenant_id,
        'action': 'create',
        'status': 'complete',
        'status_reason': 'create_complete',
        'parameters': {},
        'user_creds_id': user_creds['id'],
        'owner_id': None,
        'backup': False,
        'timeout': '60',
        'disable_rollback': 0,
        'current_traversal': 'dummy-uuid',
        'prev_raw_template': None
    }
    values.update(kwargs)
    return db_api.stack_create(ctx, values)


def create_resource(ctx, stack, legacy_prop_data=False, **kwargs):
    phy_res_id = UUID1
    if 'phys_res_id' in kwargs:
        phy_res_id = kwargs.pop('phys_res_id')
    if not legacy_prop_data:
        rpd = db_api.resource_prop_data_create(ctx, {'data': {'foo1': 'bar1'},
                                                     'encrypted': False})
    values = {
        'name': 'test_resource_name',
        'physical_resource_id': phy_res_id,
        'action': 'create',
        'status': 'complete',
        'status_reason': 'create_complete',
        'rsrc_metadata': json.loads('{"foo": "123"}'),
        'stack_id': stack.id,
        'atomic_key': 1,
    }
    if not legacy_prop_data:
        values['rsrc_prop_data'] = rpd
    else:
        values['properties_data'] = {'foo1': 'bar1'}
    values.update(kwargs)
    return db_api.resource_create(ctx, values)


def create_resource_data(ctx, resource, **kwargs):
    values = {
        'key': 'test_resource_key',
        'value': 'test_value',
        'redact': 0,
    }
    values.update(kwargs)
    return db_api.resource_data_set(ctx, resource.id, **values)


def create_resource_prop_data(ctx, **kwargs):
    values = {
        'data': {'foo1': 'bar1'},
        'encrypted': False
    }
    values.update(kwargs)
    return db_api.resource_prop_data_create(ctx, **values)


def create_event(ctx, legacy_prop_data=False, **kwargs):
    if not legacy_prop_data:
        rpd = db_api.resource_prop_data_create(ctx,
                                               {'data': {'foo2': 'ev_bar'},
                                                'encrypted': False})
    values = {
        'stack_id': 'test_stack_id',
        'resource_action': 'create',
        'resource_status': 'complete',
        'resource_name': 'res',
        'physical_resource_id': UUID1,
        'resource_status_reason': "create_complete",
    }
    if not legacy_prop_data:
        values['rsrc_prop_data'] = rpd
    else:
        values['resource_properties'] = {'foo2': 'ev_bar'}
    values.update(kwargs)
    return db_api.event_create(ctx, values)


def create_service(ctx, **kwargs):
    values = {
        'id': '7079762f-c863-4954-ba61-9dccb68c57e2',
        'engine_id': 'f9aff81e-bc1f-4119-941d-ad1ea7f31d19',
        'host': 'engine-1',
        'hostname': 'host1.devstack.org',
        'binary': 'heat-engine',
        'topic': 'engine',
        'report_interval': 60}

    values.update(kwargs)
    return db_api.service_create(ctx, values)


def create_sync_point(ctx, **kwargs):
    values = {'entity_id': '0782c463-064a-468d-98fd-442efb638e3a',
              'is_update': True,
              'traversal_id': '899ff81e-fc1f-41f9-f41d-ad1ea7f31d19',
              'atomic_key': 0,
              'stack_id': 'f6359498-764b-49e7-a515-ad31cbef885b',
              'input_data': {}}
    values.update(kwargs)
    return db_api.sync_point_create(ctx, values)


class DBAPIRawTemplateTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIRawTemplateTest, self).setUp()
        self.ctx = utils.dummy_context()

    def test_raw_template_create(self):
        t = template_format.parse(wp_template)
        tp = create_raw_template(self.ctx, template=t)
        self.assertIsNotNone(tp.id)
        self.assertEqual(t, tp.template)

    def test_raw_template_get(self):
        t = template_format.parse(wp_template)
        tp = create_raw_template(self.ctx, template=t)
        template = db_api.raw_template_get(self.ctx, tp.id)
        self.assertEqual(tp.id, template.id)
        self.assertEqual(tp.template, template.template)

    def test_raw_template_update(self):
        another_wp_template = '''
        {
          "AWSTemplateFormatVersion" : "2010-09-09",
          "Description" : "WordPress",
          "Parameters" : {
            "KeyName" : {
              "Description" : "KeyName",
              "Type" : "String",
              "Default" : "test"
            }
          },
          "Resources" : {
            "WebServer": {
              "Type": "AWS::EC2::Instance",
              "Properties": {
                "ImageId" : "fedora-20.x86_64.qcow2",
                "InstanceType"   : "m1.xlarge",
                "KeyName"        : "test",
                "UserData"       : "wordpress"
              }
            }
          }
        }
        '''
        new_t = template_format.parse(another_wp_template)
        new_files = {
            'foo': 'bar',
            'myfile': 'file:///home/somefile'
        }
        new_values = {
            'template': new_t,
            'files': new_files
        }
        orig_tp = create_raw_template(self.ctx)
        updated_tp = db_api.raw_template_update(self.ctx,
                                                orig_tp.id, new_values)

        self.assertEqual(orig_tp.id, updated_tp.id)
        self.assertEqual(new_t, updated_tp.template)
        self.assertEqual(new_files, updated_tp.files)

    def test_raw_template_delete(self):
        t = template_format.parse(wp_template)
        tp = create_raw_template(self.ctx, template=t)
        db_api.raw_template_delete(self.ctx, tp.id)
        self.assertRaises(exception.NotFound, db_api.raw_template_get,
                          self.ctx, tp.id)


class DBAPIUserCredsTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIUserCredsTest, self).setUp()
        self.ctx = utils.dummy_context()

    def test_user_creds_create_trust(self):
        user_creds = create_user_creds(self.ctx, trust_id='test_trust_id',
                                       trustor_user_id='trustor_id')
        self.assertIsNotNone(user_creds['id'])
        self.assertEqual('test_trust_id', user_creds['trust_id'])
        self.assertEqual('trustor_id', user_creds['trustor_user_id'])
        self.assertIsNone(user_creds['username'])
        self.assertIsNone(user_creds['password'])
        self.assertEqual(self.ctx.project_name, user_creds['tenant'])
        self.assertEqual(self.ctx.tenant_id, user_creds['tenant_id'])

    def test_user_creds_create_password(self):
        user_creds = create_user_creds(self.ctx)
        self.assertIsNotNone(user_creds['id'])
        self.assertEqual(self.ctx.password, user_creds['password'])

    def test_user_creds_get(self):
        user_creds = create_user_creds(self.ctx)
        ret_user_creds = db_api.user_creds_get(self.ctx, user_creds['id'])
        self.assertEqual(user_creds['password'],
                         ret_user_creds['password'])

    def test_user_creds_get_noexist(self):
        self.assertIsNone(db_api.user_creds_get(self.ctx, 123456))

    def test_user_creds_delete(self):
        user_creds = create_user_creds(self.ctx)
        self.assertIsNotNone(user_creds['id'])
        db_api.user_creds_delete(self.ctx, user_creds['id'])
        creds = db_api.user_creds_get(self.ctx, user_creds['id'])
        self.assertIsNone(creds)
        mock_delete = self.patchobject(session.Session, 'delete')
        err = self.assertRaises(
            exception.NotFound, db_api.user_creds_delete,
            self.ctx, user_creds['id'])
        exp_msg = ('Attempt to delete user creds with id '
                   '%s that does not exist' % user_creds['id'])
        self.assertIn(exp_msg, six.text_type(err))
        self.assertEqual(0, mock_delete.call_count)

    def test_user_creds_delete_retries(self):
        mock_delete = self.patchobject(session.Session, 'delete')
        # returns StaleDataErrors, so we try delete 3 times
        mock_delete.side_effect = [exc.StaleDataError,
                                   exc.StaleDataError,
                                   None]
        user_creds = create_user_creds(self.ctx)
        self.assertIsNotNone(user_creds['id'])
        self.assertIsNone(
            db_api.user_creds_delete(self.ctx, user_creds['id']))
        self.assertEqual(3, mock_delete.call_count)

        # returns other errors, so we try delete once
        mock_delete.side_effect = [exc.UnmappedError]
        self.assertRaises(exc.UnmappedError, db_api.user_creds_delete,
                          self.ctx, user_creds['id'])
        self.assertEqual(4, mock_delete.call_count)


class DBAPIStackTagTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIStackTagTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)

    def test_stack_tags_set(self):
        tags = db_api.stack_tags_set(self.ctx, self.stack.id, ['tag1', 'tag2'])
        self.assertEqual(self.stack.id, tags[0].stack_id)
        self.assertEqual('tag1', tags[0].tag)

        tags = db_api.stack_tags_set(self.ctx, self.stack.id, [])
        self.assertIsNone(tags)

    def test_stack_tags_get(self):
        db_api.stack_tags_set(self.ctx, self.stack.id, ['tag1', 'tag2'])
        tags = db_api.stack_tags_get(self.ctx, self.stack.id)
        self.assertEqual(self.stack.id, tags[0].stack_id)
        self.assertEqual('tag1', tags[0].tag)

        tags = db_api.stack_tags_get(self.ctx, UUID1)
        self.assertIsNone(tags)

    def test_stack_tags_delete(self):
        db_api.stack_tags_set(self.ctx, self.stack.id, ['tag1', 'tag2'])
        db_api.stack_tags_delete(self.ctx, self.stack.id)
        tags = db_api.stack_tags_get(self.ctx, self.stack.id)
        self.assertIsNone(tags)


class DBAPIStackTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIStackTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)

    def test_stack_create(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        self.assertIsNotNone(stack.id)
        self.assertEqual('db_test_stack_name', stack.name)
        self.assertEqual(self.template.id, stack.raw_template_id)
        self.assertEqual(self.ctx.username, stack.username)
        self.assertEqual(self.ctx.tenant_id, stack.tenant)
        self.assertEqual('create', stack.action)
        self.assertEqual('complete', stack.status)
        self.assertEqual('create_complete', stack.status_reason)
        self.assertEqual({}, stack.parameters)
        self.assertEqual(self.user_creds['id'], stack.user_creds_id)
        self.assertIsNone(stack.owner_id)
        self.assertEqual('60', stack.timeout)
        self.assertFalse(stack.disable_rollback)

    def test_stack_delete(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        stack_id = stack.id
        resource = create_resource(self.ctx, stack)
        db_api.stack_delete(self.ctx, stack_id)
        self.assertIsNone(db_api.stack_get(self.ctx, stack_id,
                                           show_deleted=False))
        self.assertRaises(exception.NotFound, db_api.resource_get,
                          self.ctx, resource.id)

        self.assertRaises(exception.NotFound, db_api.stack_delete,
                          self.ctx, stack_id)

        # Testing soft delete
        ret_stack = db_api.stack_get(self.ctx, stack_id, show_deleted=True)
        self.assertIsNotNone(ret_stack)
        self.assertEqual(stack_id, ret_stack.id)
        self.assertEqual('db_test_stack_name', ret_stack.name)

        # Testing child resources deletion
        self.assertRaises(exception.NotFound, db_api.resource_get,
                          self.ctx, resource.id)

    def test_stack_update(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        values = {
            'name': 'db_test_stack_name2',
            'action': 'update',
            'status': 'failed',
            'status_reason': "update_failed",
            'timeout': '90',
            'current_traversal': 'another-dummy-uuid',
        }
        db_api.stack_update(self.ctx, stack.id, values)
        stack = db_api.stack_get(self.ctx, stack.id)
        self.assertEqual('db_test_stack_name2', stack.name)
        self.assertEqual('update', stack.action)
        self.assertEqual('failed', stack.status)
        self.assertEqual('update_failed', stack.status_reason)
        self.assertEqual(90, stack.timeout)
        self.assertEqual('another-dummy-uuid', stack.current_traversal)

        self.assertRaises(exception.NotFound, db_api.stack_update, self.ctx,
                          UUID2, values)

    def test_stack_update_matches_traversal_id(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        values = {
            'current_traversal': 'another-dummy-uuid',
        }
        updated = db_api.stack_update(self.ctx, stack.id, values,
                                      exp_trvsl='dummy-uuid')
        self.assertTrue(updated)
        stack = db_api.stack_get(self.ctx, stack.id)
        self.assertEqual('another-dummy-uuid', stack.current_traversal)

        # test update fails when expected traversal is not matched
        matching_uuid = 'another-dummy-uuid'
        updated = db_api.stack_update(self.ctx, stack.id, values,
                                      exp_trvsl=matching_uuid)
        self.assertTrue(updated)

        diff_uuid = 'some-other-dummy-uuid'
        updated = db_api.stack_update(self.ctx, stack.id, values,
                                      exp_trvsl=diff_uuid)
        self.assertFalse(updated)

    @mock.patch.object(time, 'sleep')
    def test_stack_update_retries_on_deadlock(self, sleep):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        with mock.patch('sqlalchemy.orm.query.Query.update',
                        side_effect=db_exception.DBDeadlock) as mock_update:
            self.assertRaises(db_exception.DBDeadlock,
                              db_api.stack_update, self.ctx, stack.id, {})
            self.assertEqual(4, mock_update.call_count)

    def test_stack_set_status_release_lock(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        values = {
            'name': 'db_test_stack_name2',
            'action': 'update',
            'status': 'failed',
            'status_reason': "update_failed",
            'timeout': '90',
            'current_traversal': 'another-dummy-uuid',
        }
        db_api.stack_lock_create(self.ctx, stack.id, UUID1)
        observed = db_api.persist_state_and_release_lock(self.ctx, stack.id,
                                                         UUID1, values)
        self.assertIsNone(observed)
        stack = db_api.stack_get(self.ctx, stack.id)
        self.assertEqual('db_test_stack_name2', stack.name)
        self.assertEqual('update', stack.action)
        self.assertEqual('failed', stack.status)
        self.assertEqual('update_failed', stack.status_reason)
        self.assertEqual(90, stack.timeout)
        self.assertEqual('another-dummy-uuid', stack.current_traversal)

    def test_stack_set_status_release_lock_failed(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        values = {
            'name': 'db_test_stack_name2',
            'action': 'update',
            'status': 'failed',
            'status_reason': "update_failed",
            'timeout': '90',
            'current_traversal': 'another-dummy-uuid',
        }
        db_api.stack_lock_create(self.ctx, stack.id, UUID2)
        observed = db_api.persist_state_and_release_lock(self.ctx, stack.id,
                                                         UUID1, values)
        self.assertTrue(observed)

    def test_stack_set_status_failed_release_lock(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        values = {
            'name': 'db_test_stack_name2',
            'action': 'update',
            'status': 'failed',
            'status_reason': "update_failed",
            'timeout': '90',
            'current_traversal': 'another-dummy-uuid',
        }
        db_api.stack_lock_create(self.ctx, stack.id, UUID1)
        observed = db_api.persist_state_and_release_lock(self.ctx, UUID2,
                                                         UUID1, values)
        self.assertTrue(observed)

    def test_stack_get_returns_a_stack(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        ret_stack = db_api.stack_get(self.ctx, stack.id, show_deleted=False)
        self.assertIsNotNone(ret_stack)
        self.assertEqual(stack.id, ret_stack.id)
        self.assertEqual('db_test_stack_name', ret_stack.name)

    def test_stack_get_returns_none_if_stack_does_not_exist(self):
        stack = db_api.stack_get(self.ctx, UUID1, show_deleted=False)
        self.assertIsNone(stack)

    def test_stack_get_returns_none_if_tenant_id_does_not_match(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        self.ctx.tenant = 'abc'
        stack = db_api.stack_get(self.ctx, UUID1, show_deleted=False)
        self.assertIsNone(stack)

    def test_stack_get_tenant_is_stack_user_project_id(self):
        stack = create_stack(self.ctx, self.template, self.user_creds,
                             stack_user_project_id='astackuserproject')
        self.ctx.tenant = 'astackuserproject'
        ret_stack = db_api.stack_get(self.ctx, stack.id, show_deleted=False)
        self.assertIsNotNone(ret_stack)
        self.assertEqual(stack.id, ret_stack.id)
        self.assertEqual('db_test_stack_name', ret_stack.name)

    def test_stack_get_can_return_a_stack_from_different_tenant(self):
        # create a stack with the common tenant
        stack = create_stack(self.ctx, self.template, self.user_creds)
        # admin context can get the stack
        admin_ctx = utils.dummy_context(user='admin_username',
                                        tenant_id='admin_tenant',
                                        is_admin=True)
        ret_stack = db_api.stack_get(admin_ctx, stack.id,
                                     show_deleted=False)
        self.assertEqual(stack.id, ret_stack.id)
        self.assertEqual('db_test_stack_name', ret_stack.name)

    def test_stack_get_by_name(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        ret_stack = db_api.stack_get_by_name(self.ctx, stack.name)
        self.assertIsNotNone(ret_stack)
        self.assertEqual(stack.id, ret_stack.id)
        self.assertEqual('db_test_stack_name', ret_stack.name)

        self.assertIsNone(db_api.stack_get_by_name(self.ctx, 'abc'))

        self.ctx.tenant = 'abc'
        self.assertIsNone(db_api.stack_get_by_name(self.ctx, 'abc'))

    def test_stack_get_all(self):
        values = [
            {'name': 'stack1'},
            {'name': 'stack2'},
            {'name': 'stack3'},
            {'name': 'stack4'}
        ]
        [create_stack(self.ctx, self.template, self.user_creds,
                      **val) for val in values]

        ret_stacks = db_api.stack_get_all(self.ctx)
        self.assertEqual(4, len(ret_stacks))
        names = [ret_stack.name for ret_stack in ret_stacks]
        [self.assertIn(val['name'], names) for val in values]

    def test_stack_get_all_by_owner_id(self):
        parent_stack1 = create_stack(self.ctx, self.template, self.user_creds)
        parent_stack2 = create_stack(self.ctx, self.template, self.user_creds)
        values = [
            {'owner_id': parent_stack1.id},
            {'owner_id': parent_stack1.id},
            {'owner_id': parent_stack2.id},
            {'owner_id': parent_stack2.id},
        ]
        [create_stack(self.ctx, self.template, self.user_creds,
                      **val) for val in values]

        stack1_children = db_api.stack_get_all_by_owner_id(self.ctx,
                                                           parent_stack1.id)
        self.assertEqual(2, len(stack1_children))
        stack2_children = db_api.stack_get_all_by_owner_id(self.ctx,
                                                           parent_stack2.id)
        self.assertEqual(2, len(stack2_children))

    def test_stack_get_all_by_root_owner_id(self):
        parent_stack1 = create_stack(self.ctx, self.template, self.user_creds)
        parent_stack2 = create_stack(self.ctx, self.template, self.user_creds)
        for i in range(3):
            lvl1_st = create_stack(self.ctx, self.template, self.user_creds,
                                   owner_id=parent_stack1.id)
            for j in range(2):
                create_stack(self.ctx, self.template, self.user_creds,
                             owner_id=lvl1_st.id)
        for i in range(2):
            lvl1_st = create_stack(self.ctx, self.template, self.user_creds,
                                   owner_id=parent_stack2.id)
            for j in range(4):
                lvl2_st = create_stack(self.ctx, self.template,
                                       self.user_creds, owner_id=lvl1_st.id)
                for k in range(3):
                    create_stack(self.ctx, self.template,
                                 self.user_creds, owner_id=lvl2_st.id)

        stack1_children = db_api.stack_get_all_by_root_owner_id(
            self.ctx,
            parent_stack1.id)
        # 3 stacks on the first level + 6 stack on the second
        self.assertEqual(9, len(list(stack1_children)))
        stack2_children = db_api.stack_get_all_by_root_owner_id(
            self.ctx,
            parent_stack2.id)
        # 2 + 8 + 24
        self.assertEqual(34, len(list(stack2_children)))

    def test_stack_get_all_with_regular_tenant(self):
        values = [
            {'tenant': UUID1},
            {'tenant': UUID1},
            {'tenant': UUID2},
            {'tenant': UUID2},
            {'tenant': UUID2},
        ]
        [create_stack(self.ctx, self.template, self.user_creds,
                      **val) for val in values]

        self.ctx.tenant = UUID1
        stacks = db_api.stack_get_all(self.ctx)
        self.assertEqual(2, len(stacks))

        self.ctx.tenant = UUID2
        stacks = db_api.stack_get_all(self.ctx)
        self.assertEqual(3, len(stacks))

        self.ctx.tenant = UUID3
        self.assertEqual([], db_api.stack_get_all(self.ctx))

    def test_stack_get_all_with_admin_context(self):
        values = [
            {'tenant': UUID1},
            {'tenant': UUID1},
            {'tenant': UUID2},
            {'tenant': UUID2},
            {'tenant': UUID2},
        ]
        [create_stack(self.ctx, self.template, self.user_creds,
                      **val) for val in values]

        admin_ctx = utils.dummy_context(user='admin_user',
                                        tenant_id='admin_tenant',
                                        is_admin=True)

        stacks = db_api.stack_get_all(admin_ctx)
        self.assertEqual(5, len(stacks))

    def test_stack_count_all_with_regular_tenant(self):
        values = [
            {'tenant': UUID1},
            {'tenant': UUID1},
            {'tenant': UUID2},
            {'tenant': UUID2},
            {'tenant': UUID2},
        ]
        [create_stack(self.ctx, self.template, self.user_creds,
                      **val) for val in values]

        self.ctx.tenant = UUID1
        self.assertEqual(2, db_api.stack_count_all(self.ctx))

        self.ctx.tenant = UUID2
        self.assertEqual(3, db_api.stack_count_all(self.ctx))

    def test_stack_count_all_with_admin_context(self):
        values = [
            {'tenant': UUID1},
            {'tenant': UUID1},
            {'tenant': UUID2},
            {'tenant': UUID2},
            {'tenant': UUID2},
        ]
        [create_stack(self.ctx, self.template, self.user_creds,
                      **val) for val in values]
        admin_ctx = utils.dummy_context(user='admin_user',
                                        tenant_id='admin_tenant',
                                        is_admin=True)
        self.assertEqual(5, db_api.stack_count_all(admin_ctx))

    def test_purge_deleted(self):
        now = timeutils.utcnow()
        delta = datetime.timedelta(seconds=3600 * 7)
        deleted = [now - delta * i for i in range(1, 6)]
        tmpl_files = [template_files.TemplateFiles(
            {'foo': 'file contents %d' % i}) for i in range(5)]
        [tmpl_file.store(self.ctx) for tmpl_file in tmpl_files]
        templates = [create_raw_template(self.ctx,
                                         files_id=tmpl_files[i].files_id
                                         ) for i in range(5)]
        creds = [create_user_creds(self.ctx) for i in range(5)]
        stacks = [create_stack(self.ctx, templates[i], creds[i],
                               deleted_at=deleted[i]) for i in range(5)]
        resources = [create_resource(self.ctx, stacks[i]) for i in range(5)]
        events = [create_event(self.ctx, stack_id=stacks[i].id)
                  for i in range(5)]

        db_api.purge_deleted(age=1, granularity='days')
        admin_ctx = utils.dummy_context(is_admin=True)
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (0, 1, 2), (3, 4))

        db_api.purge_deleted(age=22, granularity='hours')
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (0, 1, 2), (3, 4))

        db_api.purge_deleted(age=1100, granularity='minutes')
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (0, 1), (2, 3, 4))

        db_api.purge_deleted(age=3600, granularity='seconds')
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (), (0, 1, 2, 3, 4))

        # test wrong age
        self.assertRaises(exception.Error, db_api.purge_deleted, -1, 'seconds')

    def test_purge_project_deleted(self):
        now = timeutils.utcnow()
        delta = datetime.timedelta(seconds=3600 * 7)
        deleted = [now - delta * i for i in range(1, 6)]
        tmpl_files = [template_files.TemplateFiles(
            {'foo': 'file contents %d' % i}) for i in range(5)]
        [tmpl_file.store(self.ctx) for tmpl_file in tmpl_files]
        templates = [create_raw_template(self.ctx,
                                         files_id=tmpl_files[i].files_id
                                         ) for i in range(5)]
        values = [
            {'tenant': UUID1},
            {'tenant': UUID1},
            {'tenant': UUID1},
            {'tenant': UUID2},
            {'tenant': UUID2},
        ]
        creds = [create_user_creds(self.ctx) for i in range(5)]
        stacks = [create_stack(self.ctx, templates[i], creds[i],
                               deleted_at=deleted[i], **values[i]
                               ) for i in range(5)]
        resources = [create_resource(self.ctx, stacks[i]) for i in range(5)]
        events = [create_event(self.ctx, stack_id=stacks[i].id)
                  for i in range(5)]

        db_api.purge_deleted(age=1, granularity='days', project_id=UUID1)
        admin_ctx = utils.dummy_context(is_admin=True)
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (0, 1, 2, 3, 4), ())

        db_api.purge_deleted(age=22, granularity='hours', project_id=UUID1)
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (0, 1, 2, 3, 4), ())

        db_api.purge_deleted(age=1100, granularity='minutes', project_id=UUID1)
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (0, 1, 3, 4), (2,))

        db_api.purge_deleted(age=30, granularity='hours', project_id=UUID2)
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (0, 1, 3), (2, 4))

        db_api.purge_deleted(age=3600, granularity='seconds', project_id=UUID1)
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (3,), (0, 1, 2, 4))

        db_api.purge_deleted(age=3600, granularity='seconds', project_id=UUID2)
        self._deleted_stack_existance(admin_ctx, stacks, resources,
                                      events, tmpl_files, (), (0, 1, 2, 3, 4))

    def test_purge_deleted_prev_raw_template(self):
        now = timeutils.utcnow()
        templates = [create_raw_template(self.ctx) for i in range(2)]
        stacks = [create_stack(self.ctx, templates[0],
                               create_user_creds(self.ctx),
                               deleted_at=now - datetime.timedelta(seconds=10),
                               prev_raw_template=templates[1])]

        db_api.purge_deleted(age=3600, granularity='seconds')
        ctx = utils.dummy_context(is_admin=True)
        self.assertIsNotNone(db_api.stack_get(ctx, stacks[0].id,
                                              show_deleted=True))
        self.assertIsNotNone(db_api.raw_template_get(ctx, templates[1].id))

        stacks = [create_stack(self.ctx, templates[0],
                               create_user_creds(self.ctx),
                               deleted_at=now - datetime.timedelta(seconds=10),
                               prev_raw_template=templates[1],
                               tenant=UUID1)]

        db_api.purge_deleted(age=3600, granularity='seconds', project_id=UUID1)
        self.assertIsNotNone(db_api.stack_get(ctx, stacks[0].id,
                                              show_deleted=True))
        self.assertIsNotNone(db_api.raw_template_get(ctx, templates[1].id))

        db_api.purge_deleted(age=0, granularity='seconds', project_id=UUID2)
        self.assertIsNotNone(db_api.stack_get(ctx, stacks[0].id,
                                              show_deleted=True))
        self.assertIsNotNone(db_api.raw_template_get(ctx, templates[1].id))

    def test_dont_purge_shared_raw_template_files(self):
        now = timeutils.utcnow()
        delta = datetime.timedelta(seconds=3600 * 7)
        deleted = [now - delta * i for i in range(1, 6)]
        # the last two template_files are identical to first two
        # (so should not be purged)
        tmpl_files = [template_files.TemplateFiles(
            {'foo': 'more file contents'}) for i in range(3)]
        [tmpl_file.store(self.ctx) for tmpl_file in tmpl_files]
        templates = [create_raw_template(self.ctx,
                                         files_id=tmpl_files[i % 3].files_id
                                         ) for i in range(5)]
        creds = [create_user_creds(self.ctx) for i in range(5)]
        [create_stack(self.ctx, templates[i], creds[i],
                      deleted_at=deleted[i]) for i in range(5)]
        db_api.purge_deleted(age=15, granularity='hours')

        # The third raw_template_files object should be purged (along
        # with the last three stacks/templates). However, the other
        # two are shared with existing templates, so should not be
        # purged.
        self.assertIsNotNone(db_api.raw_template_files_get(
            self.ctx, tmpl_files[0].files_id))
        self.assertIsNotNone(db_api.raw_template_files_get(
            self.ctx, tmpl_files[1].files_id))
        self.assertRaises(exception.NotFound,
                          db_api.raw_template_files_get,
                          self.ctx, tmpl_files[2].files_id)

    def test_dont_purge_project_shared_raw_template_files(self):
        now = timeutils.utcnow()
        delta = datetime.timedelta(seconds=3600 * 7)
        deleted = [now - delta * i for i in range(1, 6)]
        # the last two template_files are identical to first two
        # (so should not be purged)
        tmpl_files = [template_files.TemplateFiles(
            {'foo': 'more file contents'}) for i in range(3)]
        [tmpl_file.store(self.ctx) for tmpl_file in tmpl_files]
        templates = [create_raw_template(self.ctx,
                                         files_id=tmpl_files[i % 3].files_id
                                         ) for i in range(5)]
        creds = [create_user_creds(self.ctx) for i in range(5)]
        [create_stack(self.ctx, templates[i], creds[i],
                      deleted_at=deleted[i], tenant=UUID1
                      ) for i in range(5)]

        db_api.purge_deleted(age=0, granularity='seconds', project_id=UUID3)
        self.assertIsNotNone(db_api.raw_template_files_get(
            self.ctx, tmpl_files[0].files_id))
        self.assertIsNotNone(db_api.raw_template_files_get(
            self.ctx, tmpl_files[1].files_id))
        self.assertIsNotNone(db_api.raw_template_files_get(
            self.ctx, tmpl_files[2].files_id))

        db_api.purge_deleted(age=15, granularity='hours', project_id=UUID1)
        self.assertIsNotNone(db_api.raw_template_files_get(
            self.ctx, tmpl_files[0].files_id))
        self.assertIsNotNone(db_api.raw_template_files_get(
            self.ctx, tmpl_files[1].files_id))
        self.assertRaises(exception.NotFound,
                          db_api.raw_template_files_get,
                          self.ctx, tmpl_files[2].files_id)

    def _deleted_stack_existance(self, ctx, stacks, resources, events,
                                 tmpl_files, existing, deleted):
        for s in existing:
            self.assertIsNotNone(db_api.stack_get(ctx, stacks[s].id,
                                                  show_deleted=True))
            self.assertIsNotNone(db_api.raw_template_files_get(
                ctx, tmpl_files[s].files_id))
            self.assertIsNotNone(db_api.resource_get(
                ctx, resources[s].id))
            self.assertIsNotNone(ctx.session.query(
                models.Event).get(events[s].id))
            self.assertIsNotNone(ctx.session.query(
                models.ResourcePropertiesData).filter_by(
                    id=resources[s].rsrc_prop_data.id).first())
            self.assertIsNotNone(ctx.session.query(
                models.ResourcePropertiesData).filter_by(
                    id=events[s].rsrc_prop_data.id).first())
        for s in deleted:
            self.assertIsNone(db_api.stack_get(ctx, stacks[s].id,
                                               show_deleted=True))
            rt_id = stacks[s].raw_template_id
            self.assertRaises(exception.NotFound,
                              db_api.raw_template_get, ctx, rt_id)
            self.assertEqual({}, db_api.resource_get_all_by_stack(
                ctx, stacks[s].id))
            self.assertRaises(exception.NotFound,
                              db_api.raw_template_files_get,
                              ctx, tmpl_files[s].files_id)
            self.assertEqual([],
                             db_api.event_get_all_by_stack(ctx,
                                                           stacks[s].id))
            self.assertIsNone(ctx.session.query(
                models.Event).get(events[s].id))
            self.assertIsNone(ctx.session.query(
                models.ResourcePropertiesData).filter_by(
                    id=resources[s].rsrc_prop_data.id).first())
            self.assertIsNone(ctx.session.query(
                models.ResourcePropertiesData).filter_by(
                    id=events[s].rsrc_prop_data.id).first())
            self.assertEqual([],
                             db_api.event_get_all_by_stack(ctx,
                                                           stacks[s].id))
            self.assertIsNone(db_api.user_creds_get(
                self.ctx, stacks[s].user_creds_id))

    def test_purge_deleted_batch_arg(self):
        now = timeutils.utcnow()
        delta = datetime.timedelta(seconds=3600)
        deleted = now - delta
        for i in range(7):
            create_stack(self.ctx, self.template, self.user_creds,
                         deleted_at=deleted)

        with mock.patch('heat.db.sqlalchemy.api._purge_stacks') as mock_ps:
            db_api.purge_deleted(age=0, batch_size=2)
            self.assertEqual(4, mock_ps.call_count)

    def test_stack_get_root_id(self):
        root = create_stack(self.ctx, self.template, self.user_creds,
                            name='root stack')
        child_1 = create_stack(self.ctx, self.template, self.user_creds,
                               name='child 1 stack', owner_id=root.id)
        child_2 = create_stack(self.ctx, self.template, self.user_creds,
                               name='child 2 stack', owner_id=child_1.id)
        child_3 = create_stack(self.ctx, self.template, self.user_creds,
                               name='child 3 stack', owner_id=child_2.id)

        self.assertEqual(root.id, db_api.stack_get_root_id(
            self.ctx, child_3.id))
        self.assertEqual(root.id, db_api.stack_get_root_id(
            self.ctx, child_2.id))
        self.assertEqual(root.id, db_api.stack_get_root_id(
            self.ctx, root.id))
        self.assertEqual(root.id, db_api.stack_get_root_id(
            self.ctx, child_1.id))
        self.assertIsNone(db_api.stack_get_root_id(
            self.ctx, 'non existent stack'))

    def test_stack_count_total_resources(self):

        def add_resources(stack, count, root_stack_id):
            for i in range(count):
                create_resource(
                    self.ctx,
                    stack,
                    False,
                    name='%s-%s' % (stack.name, i),
                    root_stack_id=root_stack_id
                )

        root = create_stack(self.ctx, self.template, self.user_creds,
                            name='root stack')

        # stack with 3 children
        s_1 = create_stack(self.ctx, self.template, self.user_creds,
                           name='s_1', owner_id=root.id)
        s_1_1 = create_stack(self.ctx, self.template, self.user_creds,
                             name='s_1_1', owner_id=s_1.id)
        s_1_2 = create_stack(self.ctx, self.template, self.user_creds,
                             name='s_1_2', owner_id=s_1.id)
        s_1_3 = create_stack(self.ctx, self.template, self.user_creds,
                             name='s_1_3', owner_id=s_1.id)

        # stacks 4 ancestors deep
        s_2 = create_stack(self.ctx, self.template, self.user_creds,
                           name='s_2', owner_id=root.id)
        s_2_1 = create_stack(self.ctx, self.template, self.user_creds,
                             name='s_2_1', owner_id=s_2.id)
        s_2_1_1 = create_stack(self.ctx, self.template, self.user_creds,
                               name='s_2_1_1', owner_id=s_2_1.id)
        s_2_1_1_1 = create_stack(self.ctx, self.template, self.user_creds,
                                 name='s_2_1_1_1', owner_id=s_2_1_1.id)

        s_3 = create_stack(self.ctx, self.template, self.user_creds,
                           name='s_3', owner_id=root.id)
        s_4 = create_stack(self.ctx, self.template, self.user_creds,
                           name='s_4', owner_id=root.id)

        add_resources(root, 3, root.id)
        add_resources(s_1, 2, root.id)
        add_resources(s_1_1, 4, root.id)
        add_resources(s_1_2, 5, root.id)
        add_resources(s_1_3, 6, root.id)

        add_resources(s_2, 1, root.id)
        add_resources(s_2_1_1_1, 1, root.id)
        add_resources(s_3, 4, root.id)

        self.assertEqual(26, db_api.stack_count_total_resources(
            self.ctx, root.id))

        self.assertEqual(0, db_api.stack_count_total_resources(
            self.ctx, s_4.id))
        self.assertEqual(0, db_api.stack_count_total_resources(
            self.ctx, 'asdf'))
        self.assertEqual(0, db_api.stack_count_total_resources(
            self.ctx, None))


class DBAPIResourceTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIResourceTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)

    def test_resource_create(self):
        res = create_resource(self.ctx, self.stack)
        ret_res = db_api.resource_get(self.ctx, res.id)
        self.assertIsNotNone(ret_res)
        self.assertEqual('test_resource_name', ret_res.name)
        self.assertEqual(UUID1, ret_res.physical_resource_id)
        self.assertEqual('create', ret_res.action)
        self.assertEqual('complete', ret_res.status)
        self.assertEqual('create_complete', ret_res.status_reason)
        self.assertEqual('{"foo": "123"}', json.dumps(ret_res.rsrc_metadata))
        self.assertEqual(self.stack.id, ret_res.stack_id)

    def test_resource_get(self):
        res = create_resource(self.ctx, self.stack)
        ret_res = db_api.resource_get(self.ctx, res.id)
        self.assertIsNotNone(ret_res)

        self.assertRaises(exception.NotFound, db_api.resource_get,
                          self.ctx, UUID2)

    def test_resource_get_by_name_and_stack(self):
        create_resource(self.ctx, self.stack)

        ret_res = db_api.resource_get_by_name_and_stack(self.ctx,
                                                        'test_resource_name',
                                                        self.stack.id)

        self.assertIsNotNone(ret_res)
        self.assertEqual('test_resource_name', ret_res.name)
        self.assertEqual(self.stack.id, ret_res.stack_id)

        self.assertIsNone(db_api.resource_get_by_name_and_stack(self.ctx,
                                                                'abc',
                                                                self.stack.id))

    def test_resource_get_by_physical_resource_id(self):
        create_resource(self.ctx, self.stack)

        ret_res = db_api.resource_get_by_physical_resource_id(self.ctx, UUID1)
        self.assertIsNotNone(ret_res)
        self.assertEqual(UUID1, ret_res.physical_resource_id)

        self.assertIsNone(db_api.resource_get_by_physical_resource_id(self.ctx,
                                                                      UUID2))

    def test_resource_get_all_by_physical_resource_id(self):
        create_resource(self.ctx, self.stack)
        create_resource(self.ctx, self.stack)

        ret_res = db_api.resource_get_all_by_physical_resource_id(self.ctx,
                                                                  UUID1)
        ret_list = list(ret_res)
        self.assertEqual(2, len(ret_list))
        for res in ret_list:
            self.assertEqual(UUID1, res.physical_resource_id)

        mt = db_api.resource_get_all_by_physical_resource_id(self.ctx, UUID2)
        self.assertFalse(list(mt))

    def test_resource_get_all_by_with_admin_context(self):
        admin_ctx = utils.dummy_context(is_admin=True,
                                        tenant_id='admin_tenant')
        create_resource(self.ctx, self.stack, phys_res_id=UUID1)
        create_resource(self.ctx, self.stack, phys_res_id=UUID2)

        ret_res = db_api.resource_get_all_by_physical_resource_id(admin_ctx,
                                                                  UUID1)
        ret_list = list(ret_res)
        self.assertEqual(1, len(ret_list))
        self.assertEqual(UUID1, ret_list[0].physical_resource_id)

        mt = db_api.resource_get_all_by_physical_resource_id(admin_ctx, UUID2)
        ret_list = list(mt)
        self.assertEqual(1, len(ret_list))
        self.assertEqual(UUID2, ret_list[0].physical_resource_id)

    def test_resource_get_all(self):
        values = [
            {'name': 'res1'},
            {'name': 'res2'},
            {'name': 'res3'},
        ]
        [create_resource(self.ctx, self.stack, False, **val)
         for val in values]

        resources = db_api.resource_get_all(self.ctx)
        self.assertEqual(3, len(resources))

        names = [resource.name for resource in resources]
        [self.assertIn(val['name'], names) for val in values]

    def test_resource_get_all_by_stack(self):
        self.stack1 = create_stack(self.ctx, self.template, self.user_creds)
        self.stack2 = create_stack(self.ctx, self.template, self.user_creds)
        values = [
            {'name': 'res1', 'stack_id': self.stack.id},
            {'name': 'res2', 'stack_id': self.stack.id},
            {'name': 'res3', 'stack_id': self.stack.id},
            {'name': 'res4', 'stack_id': self.stack1.id},
        ]
        [create_resource(self.ctx, self.stack, False, **val)
         for val in values]

        # Test for all resources in a stack
        resources = db_api.resource_get_all_by_stack(self.ctx, self.stack.id)
        self.assertEqual(3, len(resources))
        self.assertEqual('res1', resources.get('res1').name)
        self.assertEqual('res2', resources.get('res2').name)
        self.assertEqual('res3', resources.get('res3').name)

        # Test for resources matching single entry
        resources = db_api.resource_get_all_by_stack(self.ctx,
                                                     self.stack.id,
                                                     filters=dict(name='res1'))
        self.assertEqual(1, len(resources))
        self.assertEqual('res1', resources.get('res1').name)

        # Test for resources matching multi entry
        resources = db_api.resource_get_all_by_stack(self.ctx,
                                                     self.stack.id,
                                                     filters=dict(name=[
                                                         'res1',
                                                         'res2'
                                                     ]))
        self.assertEqual(2, len(resources))
        self.assertEqual('res1', resources.get('res1').name)
        self.assertEqual('res2', resources.get('res2').name)

        self.assertEqual({}, db_api.resource_get_all_by_stack(
            self.ctx, self.stack2.id))

    def test_resource_get_all_active_by_stack(self):
        values = [
            {'name': 'res1', 'action': rsrc.Resource.DELETE,
             'status': rsrc.Resource.COMPLETE},
            {'name': 'res2', 'action': rsrc.Resource.DELETE,
             'status': rsrc.Resource.IN_PROGRESS},
            {'name': 'res3', 'action': rsrc.Resource.UPDATE,
             'status': rsrc.Resource.IN_PROGRESS},
            {'name': 'res4', 'action': rsrc.Resource.UPDATE,
             'status': rsrc.Resource.COMPLETE},
            {'name': 'res5', 'action': rsrc.Resource.INIT,
             'status': rsrc.Resource.COMPLETE},
            {'name': 'res6'},
        ]
        [create_resource(self.ctx, self.stack, **val) for val in values]

        resources = db_api.resource_get_all_active_by_stack(self.ctx,
                                                            self.stack.id)
        self.assertEqual(5, len(resources))
        for rsrc_id, res in resources.items():
            self.assertIn(res.name, ['res2', 'res3', 'res4', 'res5', 'res6'])

    def test_resource_get_all_by_root_stack(self):
        self.stack1 = create_stack(self.ctx, self.template, self.user_creds)
        self.stack2 = create_stack(self.ctx, self.template, self.user_creds)

        create_resource(self.ctx, self.stack, name='res1',
                        root_stack_id=self.stack.id)
        create_resource(self.ctx, self.stack, name='res2',
                        root_stack_id=self.stack.id)
        create_resource(self.ctx, self.stack, name='res3',
                        root_stack_id=self.stack.id)
        create_resource(self.ctx, self.stack1, name='res4',
                        root_stack_id=self.stack.id)

        # Test for all resources in a stack
        resources = db_api.resource_get_all_by_root_stack(
            self.ctx, self.stack.id)
        self.assertEqual(4, len(resources))
        resource_names = [r.name for r in resources.values()]
        self.assertEqual(['res1', 'res2', 'res3', 'res4'],
                         sorted(resource_names))

        # Test for resources matching single entry
        resources = db_api.resource_get_all_by_root_stack(
            self.ctx, self.stack.id, filters=dict(name='res1'))
        self.assertEqual(1, len(resources))
        resource_names = [r.name for r in resources.values()]
        self.assertEqual(['res1'], resource_names)
        self.assertEqual(1, len(resources))

        # Test for resources matching multi entry
        resources = db_api.resource_get_all_by_root_stack(
            self.ctx, self.stack.id, filters=dict(name=[
                'res1',
                'res2'
            ])
        )
        self.assertEqual(2, len(resources))
        resource_names = [r.name for r in resources.values()]
        self.assertEqual(['res1', 'res2'],
                         sorted(resource_names))

        self.assertEqual({}, db_api.resource_get_all_by_root_stack(
            self.ctx, self.stack2.id))

    def test_resource_purge_deleted_by_stack(self):
        val = {'name': 'res1', 'action': rsrc.Resource.DELETE,
               'status': rsrc.Resource.COMPLETE}
        resource = create_resource(self.ctx, self.stack, **val)

        db_api.resource_purge_deleted(self.ctx, self.stack.id)
        self.assertRaises(exception.NotFound, db_api.resource_get,
                          self.ctx, resource.id)

    @mock.patch.object(time, 'sleep')
    def test_resource_purge_deleted_by_stack_retry_on_deadlock(self, m_sleep):
        val = {'name': 'res1', 'action': rsrc.Resource.DELETE,
               'status': rsrc.Resource.COMPLETE}
        create_resource(self.ctx, self.stack, **val)

        with mock.patch('sqlalchemy.orm.query.Query.delete',
                        side_effect=db_exception.DBDeadlock) as mock_delete:
            self.assertRaises(db_exception.DBDeadlock,
                              db_api.resource_purge_deleted,
                              self.ctx, self.stack.id)
            self.assertEqual(4, mock_delete.call_count)

    def test_engine_get_all_locked_by_stack(self):
        values = [
            {'name': 'res1', 'action': rsrc.Resource.DELETE,
             'root_stack_id': self.stack.id,
             'status': rsrc.Resource.COMPLETE},
            {'name': 'res2', 'action': rsrc.Resource.DELETE,
             'root_stack_id': self.stack.id,
             'status': rsrc.Resource.IN_PROGRESS, 'engine_id': 'engine-001'},
            {'name': 'res3', 'action': rsrc.Resource.UPDATE,
             'root_stack_id': self.stack.id,
             'status': rsrc.Resource.IN_PROGRESS, 'engine_id': 'engine-002'},
            {'name': 'res4', 'action': rsrc.Resource.CREATE,
             'root_stack_id': self.stack.id,
             'status': rsrc.Resource.COMPLETE},
            {'name': 'res5', 'action': rsrc.Resource.INIT,
             'root_stack_id': self.stack.id,
             'status': rsrc.Resource.COMPLETE},
            {'name': 'res6', 'action': rsrc.Resource.CREATE,
             'root_stack_id': self.stack.id,
             'status': rsrc.Resource.IN_PROGRESS, 'engine_id': 'engine-001'},
            {'name': 'res6'},
        ]
        for val in values:
            create_resource(self.ctx, self.stack, **val)

        engines = db_api.engine_get_all_locked_by_stack(self.ctx,
                                                        self.stack.id)
        self.assertEqual({'engine-001', 'engine-002'}, engines)


class DBAPIResourceReplacementTest(common.HeatTestCase):
    def setUp(self):
        self.useFixture(utils.ForeignKeyConstraintFixture())
        super(DBAPIResourceReplacementTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)

    def test_resource_create_replacement(self):
        orig = create_resource(self.ctx, self.stack)

        tmpl_id = create_raw_template(self.ctx).id

        repl = db_api.resource_create_replacement(
            self.ctx,
            orig.id,
            {'status_reason': 'test replacement'},
            {'name': orig.name, 'replaces': orig.id,
             'stack_id': orig.stack_id, 'current_template_id': tmpl_id},
            1, None)

        self.assertIsNotNone(repl)
        self.assertEqual(orig.name, repl.name)
        self.assertNotEqual(orig.id, repl.id)
        self.assertEqual(orig.id, repl.replaces)

    def test_resource_create_replacement_template_gone(self):
        orig = create_resource(self.ctx, self.stack)

        other_ctx = utils.dummy_context()
        tmpl_id = create_raw_template(self.ctx).id
        db_api.raw_template_delete(other_ctx, tmpl_id)

        repl = db_api.resource_create_replacement(
            self.ctx,
            orig.id,
            {'status_reason': 'test replacement'},
            {'name': orig.name, 'replaces': orig.id,
             'stack_id': orig.stack_id, 'current_template_id': tmpl_id},
            1, None)

        self.assertIsNone(repl)

    def test_resource_create_replacement_updated(self):
        orig = create_resource(self.ctx, self.stack)

        other_ctx = utils.dummy_context()
        tmpl_id = create_raw_template(self.ctx).id
        db_api.resource_update_and_save(other_ctx, orig.id, {'atomic_key': 2})

        self.assertRaises(exception.UpdateInProgress,
                          db_api.resource_create_replacement,
                          self.ctx,
                          orig.id,
                          {'status_reason': 'test replacement'},
                          {'name': orig.name, 'replaces': orig.id,
                           'stack_id': orig.stack_id,
                           'current_template_id': tmpl_id},
                          1, None)

    def test_resource_create_replacement_updated_concurrent(self):
        orig = create_resource(self.ctx, self.stack)

        other_ctx = utils.dummy_context()
        tmpl_id = create_raw_template(self.ctx).id

        def update_atomic_key(*args, **kwargs):
            db_api.resource_update_and_save(other_ctx, orig.id,
                                            {'atomic_key': 2})

        self.patchobject(db_api, 'resource_update',
                         new=mock.Mock(wraps=db_api.resource_update,
                                       side_effect=update_atomic_key))

        self.assertRaises(exception.UpdateInProgress,
                          db_api.resource_create_replacement,
                          self.ctx,
                          orig.id,
                          {'status_reason': 'test replacement'},
                          {'name': orig.name, 'replaces': orig.id,
                           'stack_id': orig.stack_id,
                           'current_template_id': tmpl_id},
                          1, None)

    def test_resource_create_replacement_locked(self):
        orig = create_resource(self.ctx, self.stack)

        other_ctx = utils.dummy_context()
        tmpl_id = create_raw_template(self.ctx).id
        db_api.resource_update_and_save(other_ctx, orig.id, {'engine_id': 'a',
                                                             'atomic_key': 2})

        self.assertRaises(exception.UpdateInProgress,
                          db_api.resource_create_replacement,
                          self.ctx,
                          orig.id,
                          {'status_reason': 'test replacement'},
                          {'name': orig.name, 'replaces': orig.id,
                           'stack_id': orig.stack_id,
                           'current_template_id': tmpl_id},
                          1, None)

    def test_resource_create_replacement_locked_concurrent(self):
        orig = create_resource(self.ctx, self.stack)

        other_ctx = utils.dummy_context()
        tmpl_id = create_raw_template(self.ctx).id

        def lock_resource(*args, **kwargs):
            db_api.resource_update_and_save(other_ctx, orig.id,
                                            {'engine_id': 'a',
                                             'atomic_key': 2})

        self.patchobject(db_api, 'resource_update',
                         new=mock.Mock(wraps=db_api.resource_update,
                                       side_effect=lock_resource))

        self.assertRaises(exception.UpdateInProgress,
                          db_api.resource_create_replacement,
                          self.ctx,
                          orig.id,
                          {'status_reason': 'test replacement'},
                          {'name': orig.name, 'replaces': orig.id,
                           'stack_id': orig.stack_id,
                           'current_template_id': tmpl_id},
                          1, None)


class DBAPIStackLockTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIStackLockTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)

    def test_stack_lock_create_success(self):
        observed = db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        self.assertIsNone(observed)

    def test_stack_lock_create_fail_double_same(self):
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        observed = db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        self.assertEqual(UUID1, observed)

    def test_stack_lock_create_fail_double_different(self):
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        observed = db_api.stack_lock_create(self.ctx, self.stack.id, UUID2)
        self.assertEqual(UUID1, observed)

    def test_stack_lock_get_id_success(self):
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        observed = db_api.stack_lock_get_engine_id(self.ctx, self.stack.id)
        self.assertEqual(UUID1, observed)

    def test_stack_lock_get_id_return_none(self):
        observed = db_api.stack_lock_get_engine_id(self.ctx, self.stack.id)
        self.assertIsNone(observed)

    def test_stack_lock_steal_success(self):
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        observed = db_api.stack_lock_steal(self.ctx, self.stack.id,
                                           UUID1, UUID2)
        self.assertIsNone(observed)

    def test_stack_lock_steal_fail_gone(self):
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        db_api.stack_lock_release(self.ctx, self.stack.id, UUID1)
        observed = db_api.stack_lock_steal(self.ctx, self.stack.id,
                                           UUID1, UUID2)
        self.assertTrue(observed)

    def test_stack_lock_steal_fail_stolen(self):
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)

        # Simulate stolen lock
        db_api.stack_lock_release(self.ctx, self.stack.id, UUID1)
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID2)

        observed = db_api.stack_lock_steal(self.ctx, self.stack.id,
                                           UUID3, UUID2)
        self.assertEqual(UUID2, observed)

    def test_stack_lock_release_success(self):
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        observed = db_api.stack_lock_release(self.ctx, self.stack.id, UUID1)
        self.assertIsNone(observed)

    def test_stack_lock_release_fail_double(self):
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        db_api.stack_lock_release(self.ctx, self.stack.id, UUID1)
        observed = db_api.stack_lock_release(self.ctx, self.stack.id, UUID1)
        self.assertTrue(observed)

    def test_stack_lock_release_fail_wrong_engine_id(self):
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        observed = db_api.stack_lock_release(self.ctx, self.stack.id, UUID2)
        self.assertTrue(observed)

    @mock.patch.object(time, 'sleep')
    def test_stack_lock_retry_on_deadlock(self, sleep):
        with mock.patch('sqlalchemy.orm.Session.add',
                        side_effect=db_exception.DBDeadlock) as mock_add:
            self.assertRaises(db_exception.DBDeadlock,
                              db_api.stack_lock_create, self.ctx,
                              self.stack.id, UUID1)
            self.assertEqual(4, mock_add.call_count)


class DBAPIResourceDataTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIResourceDataTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)
        self.resource = create_resource(self.ctx, self.stack)
        self.resource.context = self.ctx

    def test_resource_data_set_get(self):
        create_resource_data(self.ctx, self.resource)
        val = db_api.resource_data_get(
            self.ctx, self.resource.id, 'test_resource_key')
        self.assertEqual('test_value', val)

        # Updating existing resource data
        create_resource_data(self.ctx, self.resource, value='foo')
        val = db_api.resource_data_get(
            self.ctx, self.resource.id, 'test_resource_key')
        self.assertEqual('foo', val)

        # Testing with encrypted value
        create_resource_data(self.ctx, self.resource,
                             key='encryped_resource_key', redact=True)
        val = db_api.resource_data_get(
            self.ctx, self.resource.id, 'encryped_resource_key')
        self.assertEqual('test_value', val)

        # get all by querying for data
        vals = db_api.resource_data_get_all(self.resource.context,
                                            self.resource.id)
        self.assertEqual(2, len(vals))
        self.assertEqual('foo', vals.get('test_resource_key'))
        self.assertEqual('test_value', vals.get('encryped_resource_key'))

        # get all by using associated resource data
        self.resource = db_api.resource_get(self.ctx, self.resource.id)
        vals = db_api.resource_data_get_all(self.ctx, None, self.resource.data)
        self.assertEqual(2, len(vals))
        self.assertEqual('foo', vals.get('test_resource_key'))
        self.assertEqual('test_value', vals.get('encryped_resource_key'))

    def test_resource_data_delete(self):
        create_resource_data(self.ctx, self.resource)
        res_data = db_api.resource_data_get_by_key(self.ctx, self.resource.id,
                                                   'test_resource_key')
        self.assertIsNotNone(res_data)
        self.assertEqual('test_value', res_data.value)

        db_api.resource_data_delete(self.ctx, self.resource.id,
                                    'test_resource_key')
        self.assertRaises(exception.NotFound, db_api.resource_data_get_by_key,
                          self.ctx, self.resource.id, 'test_resource_key')
        self.assertIsNotNone(res_data)

        self.assertRaises(exception.NotFound, db_api.resource_data_get_all,
                          self.resource.context,
                          self.resource.id)


class DBAPIEventTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIEventTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)

    def test_event_create(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        event = create_event(self.ctx, stack_id=stack.id)
        ret_event = self.ctx.session.query(models.Event).get(event.id)
        self.assertIsNotNone(ret_event)
        self.assertEqual(stack.id, ret_event.stack_id)
        self.assertEqual('create', ret_event.resource_action)
        self.assertEqual('complete', ret_event.resource_status)
        self.assertEqual('res', ret_event.resource_name)
        self.assertEqual(UUID1, ret_event.physical_resource_id)
        self.assertEqual('create_complete', ret_event.resource_status_reason)
        self.assertEqual({'foo2': 'ev_bar'}, ret_event.rsrc_prop_data.data)

    def test_event_get_all_by_tenant(self):
        self.stack1 = create_stack(self.ctx, self.template, self.user_creds,
                                   tenant='tenant1')
        self.stack2 = create_stack(self.ctx, self.template, self.user_creds,
                                   tenant='tenant2')
        values = [
            {'stack_id': self.stack1.id, 'resource_name': 'res1'},
            {'stack_id': self.stack1.id, 'resource_name': 'res2'},
            {'stack_id': self.stack2.id, 'resource_name': 'res3'},
        ]
        [create_event(self.ctx, **val) for val in values]

        self.ctx.tenant = 'tenant1'
        events = db_api.event_get_all_by_tenant(self.ctx)
        self.assertEqual(2, len(events))
        marker = events[0].uuid
        expected = events[1].uuid
        events = db_api.event_get_all_by_tenant(self.ctx,
                                                marker=marker)
        self.assertEqual(1, len(events))
        self.assertEqual(expected, events[0].uuid)

        events = db_api.event_get_all_by_tenant(self.ctx, limit=1)
        self.assertEqual(1, len(events))

        filters = {'resource_name': 'res2'}
        events = db_api.event_get_all_by_tenant(self.ctx,
                                                filters=filters)
        self.assertEqual(1, len(events))
        self.assertEqual('res2', events[0].resource_name)

        sort_keys = 'resource_type'
        events = db_api.event_get_all_by_tenant(self.ctx,
                                                sort_keys=sort_keys)
        self.assertEqual(2, len(events))

        self.ctx.tenant = 'tenant2'
        events = db_api.event_get_all_by_tenant(self.ctx)
        self.assertEqual(1, len(events))

    def test_event_get_all_by_stack(self):
        self.stack1 = create_stack(self.ctx, self.template, self.user_creds)
        self.stack2 = create_stack(self.ctx, self.template, self.user_creds)
        values = [
            {'stack_id': self.stack1.id, 'resource_name': 'res1'},
            {'stack_id': self.stack1.id, 'resource_name': 'res2'},
            {'stack_id': self.stack2.id, 'resource_name': 'res3'},
        ]
        [create_event(self.ctx, **val) for val in values]

        self.ctx.tenant = 'tenant1'
        events = db_api.event_get_all_by_stack(self.ctx, self.stack1.id)
        self.assertEqual(2, len(events))

        self.ctx.tenant = 'tenant2'
        events = db_api.event_get_all_by_stack(self.ctx, self.stack2.id)
        self.assertEqual(1, len(events))

    def test_event_count_all_by_stack(self):
        self.stack1 = create_stack(self.ctx, self.template, self.user_creds)
        self.stack2 = create_stack(self.ctx, self.template, self.user_creds)
        values = [
            {'stack_id': self.stack1.id, 'resource_name': 'res1'},
            {'stack_id': self.stack1.id, 'resource_name': 'res2'},
            {'stack_id': self.stack2.id, 'resource_name': 'res3'},
        ]
        [create_event(self.ctx, **val) for val in values]

        self.assertEqual(2, db_api.event_count_all_by_stack(self.ctx,
                                                            self.stack1.id))

        self.assertEqual(1, db_api.event_count_all_by_stack(self.ctx,
                                                            self.stack2.id))


class DBAPIServiceTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIServiceTest, self).setUp()
        self.ctx = utils.dummy_context()

    def test_service_create_get(self):
        service = create_service(self.ctx)
        ret_service = db_api.service_get(self.ctx, service.id)
        self.assertIsNotNone(ret_service)
        self.assertEqual(service.id, ret_service.id)
        self.assertEqual(service.hostname, ret_service.hostname)
        self.assertEqual(service.binary, ret_service.binary)
        self.assertEqual(service.host, ret_service.host)
        self.assertEqual(service.topic, ret_service.topic)
        self.assertEqual(service.engine_id, ret_service.engine_id)
        self.assertEqual(service.report_interval, ret_service.report_interval)
        self.assertIsNotNone(service.created_at)
        self.assertIsNone(service.updated_at)
        self.assertIsNone(service.deleted_at)

    def test_service_get_all_by_args(self):
        # Host-1
        values = [{'id': str(uuid.uuid4()),
                   'hostname': 'host-1',
                   'host': 'engine-1'}]
        # Host-2
        for i in [0, 1, 2]:
            values.append({'id': str(uuid.uuid4()),
                           'hostname': 'host-2',
                           'host': 'engine-%s' % i})

        [create_service(self.ctx, **val) for val in values]

        services = db_api.service_get_all(self.ctx)
        self.assertEqual(4, len(services))

        services_by_args = db_api.service_get_all_by_args(self.ctx,
                                                          hostname='host-2',
                                                          binary='heat-engine',
                                                          host='engine-0')
        self.assertEqual(1, len(services_by_args))
        self.assertEqual('host-2', services_by_args[0].hostname)
        self.assertEqual('heat-engine', services_by_args[0].binary)
        self.assertEqual('engine-0', services_by_args[0].host)

    def test_service_update(self):
        service = create_service(self.ctx)
        values = {'hostname': 'host-updated',
                  'host': 'engine-updated',
                  'retry_interval': 120}
        service = db_api.service_update(self.ctx, service.id, values)
        self.assertEqual('host-updated', service.hostname)
        self.assertEqual(120, service.retry_interval)
        self.assertEqual('engine-updated', service.host)

        # simple update, expected the updated_at is updated
        old_updated_date = service.updated_at
        service = db_api.service_update(self.ctx, service.id, dict())
        self.assertGreater(service.updated_at, old_updated_date)

    def test_service_delete_soft_delete(self):
        service = create_service(self.ctx)

        # Soft delete
        db_api.service_delete(self.ctx, service.id)
        ret_service = db_api.service_get(self.ctx, service.id)
        self.assertEqual(ret_service.id, service.id)

        # Delete
        db_api.service_delete(self.ctx, service.id, False)
        ex = self.assertRaises(exception.EntityNotFound, db_api.service_get,
                               self.ctx, service.id)
        self.assertEqual('Service', ex.kwargs.get('entity'))


class DBAPIResourceUpdateTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIResourceUpdateTest, self).setUp()
        self.ctx = utils.dummy_context()
        template = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, template, user_creds)
        self.resource = create_resource(self.ctx, stack, False,
                                        atomic_key=0)

    def test_unlocked_resource_update(self):
        values = {'engine_id': 'engine-1',
                  'action': 'CREATE',
                  'status': 'IN_PROGRESS'}
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        ret = db_api.resource_update(self.ctx, self.resource.id,
                                     values, db_res.atomic_key, None)
        self.assertTrue(ret)
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        self.assertEqual('engine-1', db_res.engine_id)
        self.assertEqual('CREATE', db_res.action)
        self.assertEqual('IN_PROGRESS', db_res.status)
        self.assertEqual(1, db_res.atomic_key)

    def test_locked_resource_update_by_same_engine(self):
        values = {'engine_id': 'engine-1',
                  'action': 'CREATE',
                  'status': 'IN_PROGRESS'}
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        ret = db_api.resource_update(self.ctx, self.resource.id,
                                     values, db_res.atomic_key, None)
        self.assertTrue(ret)
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        self.assertEqual('engine-1', db_res.engine_id)
        self.assertEqual(1, db_res.atomic_key)
        values = {'engine_id': 'engine-1',
                  'action': 'CREATE',
                  'status': 'FAILED'}
        ret = db_api.resource_update(self.ctx, self.resource.id,
                                     values, db_res.atomic_key, 'engine-1')
        self.assertTrue(ret)
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        self.assertEqual('engine-1', db_res.engine_id)
        self.assertEqual('CREATE', db_res.action)
        self.assertEqual('FAILED', db_res.status)
        self.assertEqual(2, db_res.atomic_key)

    def test_locked_resource_update_by_other_engine(self):
        values = {'engine_id': 'engine-1',
                  'action': 'CREATE',
                  'status': 'IN_PROGRESS'}
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        ret = db_api.resource_update(self.ctx, self.resource.id,
                                     values, db_res.atomic_key, None)
        self.assertTrue(ret)
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        self.assertEqual('engine-1', db_res.engine_id)
        self.assertEqual(1, db_res.atomic_key)
        values = {'engine_id': 'engine-2',
                  'action': 'CREATE',
                  'status': 'FAILED'}
        ret = db_api.resource_update(self.ctx, self.resource.id,
                                     values, db_res.atomic_key, 'engine-2')
        self.assertFalse(ret)

    def test_release_resource_lock(self):
        values = {'engine_id': 'engine-1',
                  'action': 'CREATE',
                  'status': 'IN_PROGRESS'}
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        ret = db_api.resource_update(self.ctx, self.resource.id,
                                     values, db_res.atomic_key, None)
        self.assertTrue(ret)
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        self.assertEqual('engine-1', db_res.engine_id)
        self.assertEqual(1, db_res.atomic_key)
        # Set engine id as None to release the lock
        values = {'engine_id': None,
                  'action': 'CREATE',
                  'status': 'COMPLETE'}
        ret = db_api.resource_update(self.ctx, self.resource.id,
                                     values, db_res.atomic_key, 'engine-1')
        self.assertTrue(ret)
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        self.assertIsNone(db_res.engine_id)
        self.assertEqual('CREATE', db_res.action)
        self.assertEqual('COMPLETE', db_res.status)
        self.assertEqual(2, db_res.atomic_key)

    def test_steal_resource_lock(self):
        values = {'engine_id': 'engine-1',
                  'action': 'CREATE',
                  'status': 'IN_PROGRESS'}
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        ret = db_api.resource_update(self.ctx, self.resource.id,
                                     values, db_res.atomic_key, None)
        self.assertTrue(ret)
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        self.assertEqual('engine-1', db_res.engine_id)
        self.assertEqual(1, db_res.atomic_key)
        # Set engine id as engine-2 and pass expected engine id as old engine
        # i.e engine-1 in db api steal the lock
        values = {'engine_id': 'engine-2',
                  'action': 'DELETE',
                  'status': 'IN_PROGRESS'}
        ret = db_api.resource_update(self.ctx, self.resource.id,
                                     values, db_res.atomic_key, 'engine-1')
        self.assertTrue(ret)
        db_res = db_api.resource_get(self.ctx, self.resource.id)
        self.assertEqual('engine-2', db_res.engine_id)
        self.assertEqual('DELETE', db_res.action)
        self.assertEqual(2, db_res.atomic_key)


class DBAPISyncPointTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPISyncPointTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)
        self.resources = [create_resource(self.ctx, self.stack, name='res1'),
                          create_resource(self.ctx, self.stack, name='res2'),
                          create_resource(self.ctx, self.stack, name='res3')]

    def test_sync_point_create_get(self):
        for res in self.resources:
            # create sync_point for resources and verify
            sync_point_rsrc = create_sync_point(
                self.ctx, entity_id=str(res.id), stack_id=self.stack.id,
                traversal_id=self.stack.current_traversal
            )

            ret_sync_point_rsrc = db_api.sync_point_get(
                self.ctx, sync_point_rsrc.entity_id,
                sync_point_rsrc.traversal_id, sync_point_rsrc.is_update
            )

            self.assertIsNotNone(ret_sync_point_rsrc)
            self.assertEqual(sync_point_rsrc.entity_id,
                             ret_sync_point_rsrc.entity_id)
            self.assertEqual(sync_point_rsrc.traversal_id,
                             ret_sync_point_rsrc.traversal_id)
            self.assertEqual(sync_point_rsrc.is_update,
                             ret_sync_point_rsrc.is_update)
            self.assertEqual(sync_point_rsrc.atomic_key,
                             ret_sync_point_rsrc.atomic_key)
            self.assertEqual(sync_point_rsrc.stack_id,
                             ret_sync_point_rsrc.stack_id)
            self.assertEqual(sync_point_rsrc.input_data,
                             ret_sync_point_rsrc.input_data)

        # Finally create sync_point for stack and verify
        sync_point_stack = create_sync_point(
            self.ctx, entity_id=self.stack.id, stack_id=self.stack.id,
            traversal_id=self.stack.current_traversal
        )

        ret_sync_point_stack = db_api.sync_point_get(
            self.ctx, sync_point_stack.entity_id,
            sync_point_stack.traversal_id, sync_point_stack.is_update
        )

        self.assertIsNotNone(ret_sync_point_stack)
        self.assertEqual(sync_point_stack.entity_id,
                         ret_sync_point_stack.entity_id)
        self.assertEqual(sync_point_stack.traversal_id,
                         ret_sync_point_stack.traversal_id)
        self.assertEqual(sync_point_stack.is_update,
                         ret_sync_point_stack.is_update)
        self.assertEqual(sync_point_stack.atomic_key,
                         ret_sync_point_stack.atomic_key)
        self.assertEqual(sync_point_stack.stack_id,
                         ret_sync_point_stack.stack_id)
        self.assertEqual(sync_point_stack.input_data,
                         ret_sync_point_stack.input_data)

    def test_sync_point_update(self):
        sync_point = create_sync_point(
            self.ctx, entity_id=str(self.resources[0].id),
            stack_id=self.stack.id, traversal_id=self.stack.current_traversal
        )
        self.assertEqual({}, sync_point.input_data)
        self.assertEqual(0, sync_point.atomic_key)

        # first update
        rows_updated = db_api.sync_point_update_input_data(
            self.ctx, sync_point.entity_id, sync_point.traversal_id,
            sync_point.is_update, sync_point.atomic_key,
            {'input_data': '{key: value}'}
        )
        self.assertEqual(1, rows_updated)

        ret_sync_point = db_api.sync_point_get(self.ctx,
                                               sync_point.entity_id,
                                               sync_point.traversal_id,
                                               sync_point.is_update)
        self.assertIsNotNone(ret_sync_point)
        # check if atomic_key was incremented on write
        self.assertEqual(1, ret_sync_point.atomic_key)
        self.assertEqual({'input_data': '{key: value}'},
                         ret_sync_point.input_data)

        # second update
        rows_updated = db_api.sync_point_update_input_data(
            self.ctx, ret_sync_point.entity_id, ret_sync_point.traversal_id,
            ret_sync_point.is_update, ret_sync_point.atomic_key,
            {'input_data': '{key1: value1}'}
        )
        self.assertEqual(1, rows_updated)

        ret_sync_point = db_api.sync_point_get(self.ctx,
                                               sync_point.entity_id,
                                               sync_point.traversal_id,
                                               sync_point.is_update)
        self.assertIsNotNone(ret_sync_point)
        # check if atomic_key was incremented on write
        self.assertEqual(2, ret_sync_point.atomic_key)
        self.assertEqual({'input_data': '{key1: value1}'},
                         ret_sync_point.input_data)

    def test_sync_point_concurrent_update(self):
        sync_point = create_sync_point(
            self.ctx, entity_id=str(self.resources[0].id),
            stack_id=self.stack.id, traversal_id=self.stack.current_traversal
        )
        self.assertEqual({}, sync_point.input_data)
        self.assertEqual(0, sync_point.atomic_key)

        # update where atomic_key is 0 and succeeds.
        rows_updated = db_api.sync_point_update_input_data(
            self.ctx, sync_point.entity_id, sync_point.traversal_id,
            sync_point.is_update, 0, {'input_data': '{key: value}'}
        )
        self.assertEqual(1, rows_updated)

        # another update where atomic_key is 0 and does not update.
        rows_updated = db_api.sync_point_update_input_data(
            self.ctx, sync_point.entity_id, sync_point.traversal_id,
            sync_point.is_update, 0, {'input_data': '{key: value}'}
        )
        self.assertEqual(0, rows_updated)

    def test_sync_point_delete(self):
        for res in self.resources:
            sync_point_rsrc = create_sync_point(
                self.ctx, entity_id=str(res.id), stack_id=self.stack.id,
                traversal_id=self.stack.current_traversal
            )
            self.assertIsNotNone(sync_point_rsrc)

        sync_point_stack = create_sync_point(
            self.ctx, entity_id=self.stack.id,
            stack_id=self.stack.id,
            traversal_id=self.stack.current_traversal
        )
        self.assertIsNotNone(sync_point_stack)

        rows_deleted = db_api.sync_point_delete_all_by_stack_and_traversal(
            self.ctx, self.stack.id,
            self.stack.current_traversal
        )
        self.assertGreater(rows_deleted, 0)
        self.assertEqual(4, rows_deleted)

        # Additionally check if sync_point_get returns None.
        for res in self.resources:
            ret_sync_point_rsrc = db_api.sync_point_get(
                self.ctx, str(res.id), self.stack.current_traversal, True
            )
            self.assertIsNone(ret_sync_point_rsrc)

        ret_sync_point_stack = db_api.sync_point_get(
            self.ctx, self.stack.id, self.stack.current_traversal, True
        )
        self.assertIsNone(ret_sync_point_stack)

    @mock.patch.object(time, 'sleep')
    def test_syncpoint_create_deadlock(self, sleep):
        with mock.patch('sqlalchemy.orm.Session.add',
                        side_effect=db_exception.DBDeadlock) as add:
            for res in self.resources:
                self.assertRaises(db_exception.DBDeadlock,
                                  create_sync_point,
                                  self.ctx, entity_id=str(res.id),
                                  stack_id=self.stack.id,
                                  traversal_id=self.stack.current_traversal)
            self.assertEqual(len(self.resources) * 4, add.call_count)


class DBAPIMigratePropertiesDataTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPIMigratePropertiesDataTest, self).setUp()
        self.ctx = utils.dummy_context()
        templ = create_raw_template(self.ctx)
        user_creds = create_user_creds(self.ctx)
        stack = create_stack(self.ctx, templ, user_creds)
        stack2 = create_stack(self.ctx, templ, user_creds)
        create_resource(self.ctx, stack, True, name='res1')
        create_resource(self.ctx, stack2, True, name='res2')
        create_event(self.ctx, True)
        create_event(self.ctx, True)

    def _test_migrate_resource(self, batch_size=50):
        resources = self.ctx.session.query(models.Resource).all()
        self.assertEqual(2, len(resources))
        for resource in resources:
            self.assertEqual('bar1', resource.properties_data['foo1'])

        db_api.db_properties_data_migrate(self.ctx, batch_size=batch_size)
        for resource in resources:
            self.assertEqual('bar1', resource.rsrc_prop_data.data['foo1'])
            self.assertFalse(resource.rsrc_prop_data.encrypted)
            self.assertIsNone(resource.properties_data)
            self.assertIsNone(resource.properties_data_encrypted)

    def _test_migrate_event(self, batch_size=50):
        events = self.ctx.session.query(models.Event).all()
        self.assertEqual(2, len(events))
        for event in events:
            self.assertEqual('ev_bar', event.resource_properties['foo2'])

        db_api.db_properties_data_migrate(self.ctx, batch_size=batch_size)
        self.ctx.session.expire_all()
        events = self.ctx.session.query(models.Event).all()
        for event in events:
            self.assertEqual('ev_bar', event.rsrc_prop_data.data['foo2'])
            self.assertFalse(event.rsrc_prop_data.encrypted)
            self.assertIsNone(event.resource_properties)

    def test_migrate_event(self):
        self._test_migrate_event()

    def test_migrate_event_in_batches(self):
        self._test_migrate_event(batch_size=1)

    def test_migrate_resource(self):
        self._test_migrate_resource()

    def test_migrate_resource_in_batches(self):
        self._test_migrate_resource(batch_size=1)

    def test_migrate_encrypted_resource(self):
        resources = self.ctx.session.query(models.Resource).all()
        db_api.db_encrypt_parameters_and_properties(
            self.ctx, 'i have a key for you if you want')

        encrypted_data_pre_migration = resources[0].properties_data['foo1'][1]
        db_api.db_properties_data_migrate(self.ctx)
        resources = self.ctx.session.query(models.Resource).all()

        self.assertTrue(resources[0].rsrc_prop_data.encrypted)
        self.assertIsNone(resources[0].properties_data)
        self.assertIsNone(resources[0].properties_data_encrypted)
        self.assertEqual('cryptography_decrypt_v1',
                         resources[0].rsrc_prop_data.data['foo1'][0])
        self.assertEqual(encrypted_data_pre_migration,
                         resources[0].rsrc_prop_data.data['foo1'][1])

        db_api.db_decrypt_parameters_and_properties(
            self.ctx, 'i have a key for you if you want')
        self.ctx.session.expire_all()
        resources = self.ctx.session.query(models.Resource).all()

        self.assertEqual('bar1', resources[0].rsrc_prop_data.data['foo1'])
        self.assertFalse(resources[0].rsrc_prop_data.encrypted)
        self.assertIsNone(resources[0].properties_data)
        self.assertIsNone(resources[0].properties_data_encrypted)


class DBAPICryptParamsPropsTest(common.HeatTestCase):
    def setUp(self):
        super(DBAPICryptParamsPropsTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = self._create_template()
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)
        self.resources = [create_resource(self.ctx, self.stack, name='res1')]

    hidden_params_dict = {
        'param2': 'bar',
        'param_number': '456',
        'param_boolean': '1',
        'param_map': '{\"test\":\"json\"}',
        'param_comma_list': '[\"Hola\", \"Senor\"]'}

    def _create_template(self):
        """Initialize sample template."""
        self.t = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                description: value1.
            param2:
                type: string
                description: value2.
                hidden: true
            param3:
                type: string
                description: value3
                hidden: true
                default: "don't encrypt me! I'm not sensitive enough"
            param_string_default_int:
                type: string
                description: String parameter with integer default value
                default: 4353
                hidden: true
            param_number:
                type: number
                description: Number parameter
                default: 4353
                hidden: true
            param_boolean:
                type: boolean
                description: boolean parameter
                default: true
                hidden: true
            param_map:
                type: json
                description: json parameter
                default: {"fee": {"fi":"fo"}}
                hidden: true
            param_comma_list:
                type: comma_delimited_list
                description: cdl parameter
                default: ["hola", "senorita"]
                hidden: true
        resources:
            a_resource:
                type: GenericResourceType
        ''')
        template = {
            'template': self.t,
            'files': {'foo': 'bar'},
            'environment': {
                'parameters': {
                    'param1': 'foo',
                    'param2': 'bar',
                    'param_number': '456',
                    'param_boolean': '1',
                    'param_map': '{\"test\":\"json\"}',
                    'param_comma_list': '[\"Hola\", \"Senor\"]'}}}

        return db_api.raw_template_create(self.ctx, template)

    def encrypt(self, enc_key=None, batch_size=50,
                legacy_prop_data=False):
        session = self.ctx.session
        if enc_key is None:
            enc_key = cfg.CONF.auth_encryption_key
        self.assertEqual([], db_api.db_encrypt_parameters_and_properties(
            self.ctx, enc_key, batch_size=batch_size))
        for enc_tmpl in session.query(models.RawTemplate).all():
            for param_name in self.hidden_params_dict.keys():
                self.assertEqual(
                    'cryptography_decrypt_v1',
                    enc_tmpl.environment['parameters'][param_name][0])
            self.assertEqual(
                'foo', enc_tmpl.environment['parameters']['param1'])
            # test that decryption does not store (or encrypt) default
            # values in template's environment['parameters']
            self.assertIsNone(
                enc_tmpl.environment['parameters'].get('param3'))

        enc_resources = session.query(models.Resource).all()
        self.assertNotEqual([], enc_resources)
        for enc_resource in enc_resources:
            if legacy_prop_data:
                self.assertEqual(
                    'cryptography_decrypt_v1',
                    enc_resource.properties_data['foo1'][0])
            else:
                self.assertEqual(
                    'cryptography_decrypt_v1',
                    enc_resource.rsrc_prop_data.data['foo1'][0])

        ev = enc_tmpl.environment['parameters']['param2'][1]
        return ev

    def decrypt(self, encrypt_value, enc_key=None,
                batch_size=50, legacy_prop_data=False):
        session = self.ctx.session
        if enc_key is None:
            enc_key = cfg.CONF.auth_encryption_key

        self.assertEqual([], db_api.db_decrypt_parameters_and_properties(
            self.ctx, enc_key, batch_size=batch_size))

        for dec_tmpl in session.query(models.RawTemplate).all():
            self.assertNotEqual(
                encrypt_value,
                dec_tmpl.environment['parameters']['param2'][1])
            for param_name, param_value in self.hidden_params_dict.items():
                self.assertEqual(
                    param_value,
                    dec_tmpl.environment['parameters'][param_name])
            self.assertEqual(
                'foo', dec_tmpl.environment['parameters']['param1'])
            self.assertIsNone(
                dec_tmpl.environment['parameters'].get('param3'))

            # test that decryption does not store default
            # values in template's environment['parameters']
            self.assertIsNone(dec_tmpl.environment['parameters'].get(
                'param3'))

        decrypt_value = dec_tmpl.environment['parameters']['param2'][1]

        dec_resources = session.query(models.Resource).all()
        self.assertNotEqual([], dec_resources)
        for dec_resource in dec_resources:
            if legacy_prop_data:
                self.assertEqual(
                    'bar1', dec_resource.properties_data['foo1'])
            else:
                self.assertEqual(
                    'bar1', dec_resource.rsrc_prop_data.data['foo1'])

        return decrypt_value

    def _test_db_encrypt_decrypt(self, batch_size=50, legacy_prop_data=False):
        session = self.ctx.session
        raw_templates = session.query(models.RawTemplate).all()
        self.assertNotEqual([], raw_templates)
        for r_tmpl in raw_templates:
            for param_name, param_value in self.hidden_params_dict.items():
                self.assertEqual(param_value,
                                 r_tmpl.environment['parameters'][param_name])
                self.assertEqual('foo',
                                 r_tmpl.environment['parameters']['param1'])

        resources = session.query(models.Resource).all()
        self.assertNotEqual([], resources)
        self.assertEqual(len(resources), len(raw_templates))
        for resource in resources:
            resource = db_api.resource_get(self.ctx, resource.id)
            if legacy_prop_data:
                self.assertEqual(
                    'bar1', resource.properties_data['foo1'])
            else:
                self.assertEqual(
                    'bar1', resource.rsrc_prop_data.data['foo1'])

        # Test encryption
        encrypt_value = self.encrypt(batch_size=batch_size,
                                     legacy_prop_data=legacy_prop_data)

        # Test that encryption is idempotent
        encrypt_value2 = self.encrypt(batch_size=batch_size,
                                      legacy_prop_data=legacy_prop_data)
        self.assertEqual(encrypt_value, encrypt_value2)

        # Test decryption
        decrypt_value = self.decrypt(encrypt_value, batch_size=batch_size,
                                     legacy_prop_data=legacy_prop_data)

        # Test that decryption is idempotent
        decrypt_value2 = self.decrypt(encrypt_value, batch_size=batch_size,
                                      legacy_prop_data=legacy_prop_data)
        self.assertEqual(decrypt_value, decrypt_value2)

        # Test using a different encryption key to encrypt & decrypt
        encrypt_value3 = self.encrypt(
            enc_key='774c15be099ea74123a9b9592ff12680',
            batch_size=batch_size, legacy_prop_data=legacy_prop_data)
        decrypt_value3 = self.decrypt(
            encrypt_value3, enc_key='774c15be099ea74123a9b9592ff12680',
            batch_size=batch_size, legacy_prop_data=legacy_prop_data)
        self.assertEqual(decrypt_value, decrypt_value3)
        self.assertNotEqual(encrypt_value, decrypt_value)
        self.assertNotEqual(encrypt_value3, decrypt_value3)
        self.assertNotEqual(encrypt_value, encrypt_value3)

    def test_db_encrypt_decrypt(self):
        """Test encryption and decryption for single template and resource."""
        self._test_db_encrypt_decrypt()

    def test_db_encrypt_decrypt_legacy_prop_data(self):
        """Test encryption and decryption for res with legacy prop data."""
        # delete what setUp created
        [self.ctx.session.delete(r) for r in
         self.ctx.session.query(models.Resource).all()]
        [self.ctx.session.delete(s) for s in
         self.ctx.session.query(models.Stack).all()]
        [self.ctx.session.delete(t) for t in
         self.ctx.session.query(models.RawTemplate).all()]

        tmpl = self._create_template()
        stack = create_stack(self.ctx, tmpl, self.user_creds)
        create_resource(self.ctx, stack, True, name='res1')
        self._test_db_encrypt_decrypt(legacy_prop_data=True)

    def test_db_encrypt_decrypt_in_batches(self):
        """Test encryption and decryption in for several templates and resources.

        Test encryption and decryption with set batch size of
        templates and resources.
        """
        tmpl1 = self._create_template()
        tmpl2 = self._create_template()
        stack = create_stack(self.ctx, tmpl1, self.user_creds)
        create_resource(self.ctx, stack, False, name='res1')
        stack2 = create_stack(self.ctx, tmpl2, self.user_creds)
        create_resource(self.ctx, stack2, False, name='res2')

        self._test_db_encrypt_decrypt(batch_size=1)

    def test_db_encrypt_decrypt_exception_continue(self):
        """Test that encryption and decryption proceed after an exception"""
        def create_malformed_template():
            """Initialize a malformed template which should fail encryption."""
            t = template_format.parse('''
            heat_template_version: 2013-05-23
            parameters:
                param1:
                    type: string
                    description: value1.
                param2:
                    type: string
                    description: value2.
                    hidden: true
                param3:
                    type: string
                    description: value3
                    hidden: true
                    default: "don't encrypt me! I'm not sensitive enough"
            resources:
                a_resource:
                    type: GenericResourceType
            ''')
            template = {
                'template': t,
                'files': {'foo': 'bar'},
                'environment': ''}  # <- environment should be a dict

            return db_api.raw_template_create(self.ctx, template)

        create_malformed_template()
        self._create_template()

        # Test encryption
        enc_result = db_api.db_encrypt_parameters_and_properties(
            self.ctx, cfg.CONF.auth_encryption_key, batch_size=50)
        self.assertEqual(1, len(enc_result))
        self.assertIs(AttributeError, type(enc_result[0]))
        enc_tmpls = self.ctx.session.query(models.RawTemplate).all()
        self.assertEqual('', enc_tmpls[1].environment)
        self.assertEqual('cryptography_decrypt_v1',
                         enc_tmpls[2].environment['parameters']['param2'][0])

        # Test decryption
        dec_result = db_api.db_decrypt_parameters_and_properties(
            self.ctx, cfg.CONF.auth_encryption_key, batch_size=50)
        self.assertEqual(len(dec_result), 1)
        self.assertIs(AttributeError, type(dec_result[0]))
        dec_tmpls = self.ctx.session.query(models.RawTemplate).all()
        self.assertEqual('', dec_tmpls[1].environment)
        self.assertEqual('bar',
                         dec_tmpls[2].environment['parameters']['param2'])

    def test_db_encrypt_no_env(self):
        template = {
            'template': self.t,
            'files': {'foo': 'bar'},
            'environment': None}
        db_api.raw_template_create(self.ctx, template)
        self.assertEqual([], db_api.db_encrypt_parameters_and_properties(
            self.ctx, cfg.CONF.auth_encryption_key))

    def test_db_encrypt_no_env_parameters(self):
        template = {
            'template': self.t,
            'files': {'foo': 'bar'},
            'environment': {'encrypted_param_names': ['a']}}
        db_api.raw_template_create(self.ctx, template)
        self.assertEqual([], db_api.db_encrypt_parameters_and_properties(
            self.ctx, cfg.CONF.auth_encryption_key))

    def test_db_encrypt_no_properties_data(self):
        ctx = utils.dummy_context()
        template = self._create_template()
        user_creds = create_user_creds(ctx)
        stack = create_stack(ctx, template, user_creds)
        resources = [create_resource(ctx, stack, name='res1')]
        resources[0].properties_data = None
        self.assertEqual([], db_api.db_encrypt_parameters_and_properties(
            ctx, cfg.CONF.auth_encryption_key))

    def test_db_encrypt_decrypt_verbose_on(self):
        info_logger = self.useFixture(
            fixtures.FakeLogger(level=logging.INFO,
                                format="%(levelname)8s [%(name)s] "
                                       "%(message)s"))
        ctx = utils.dummy_context()
        template = self._create_template()
        user_creds = create_user_creds(ctx)
        stack = create_stack(ctx, template, user_creds)
        create_resource(ctx, stack, legacy_prop_data=True, name='res2')

        db_api.db_encrypt_parameters_and_properties(
            ctx, cfg.CONF.auth_encryption_key, verbose=True)
        self.assertIn("Processing raw_template 1", info_logger.output)
        self.assertIn("Finished encrypt processing of raw_template 1",
                      info_logger.output)
        self.assertIn("Processing resource_properties_data 1",
                      info_logger.output)
        self.assertIn("Finished processing resource_properties_data 1",
                      info_logger.output)
        # only the resource with legacy properties data is processed
        self.assertIn("Processing resource 2", info_logger.output)
        self.assertIn("Finished processing resource 2", info_logger.output)

        info_logger2 = self.useFixture(
            fixtures.FakeLogger(level=logging.INFO,
                                format="%(levelname)8s [%(name)s] "
                                       "%(message)s"))

        db_api.db_decrypt_parameters_and_properties(
            ctx, cfg.CONF.auth_encryption_key, verbose=True)
        self.assertIn("Processing raw_template 1", info_logger2.output)
        self.assertIn("Finished decrypt processing of raw_template 1",
                      info_logger2.output)
        self.assertIn("Processing resource_properties_data 1",
                      info_logger.output)
        self.assertIn("Finished processing resource_properties_data 1",
                      info_logger.output)
        # only the resource with legacy properties data is processed
        self.assertIn("Processing resource 2", info_logger2.output)
        self.assertIn("Finished processing resource 2", info_logger2.output)

    def test_db_encrypt_decrypt_verbose_off(self):
        info_logger = self.useFixture(
            fixtures.FakeLogger(level=logging.INFO,
                                format="%(levelname)8s [%(name)s] "
                                       "%(message)s"))
        ctx = utils.dummy_context()
        template = self._create_template()
        user_creds = create_user_creds(ctx)
        stack = create_stack(ctx, template, user_creds)
        create_resource(ctx, stack, name='res1')

        db_api.db_encrypt_parameters_and_properties(
            ctx, cfg.CONF.auth_encryption_key, verbose=False)
        self.assertNotIn("Processing raw_template 1", info_logger.output)
        self.assertNotIn("Processing resource 1", info_logger.output)
        self.assertNotIn("Successfully processed raw_template 1",
                         info_logger.output)
        self.assertNotIn("Successfully processed resource 1",
                         info_logger.output)

        info_logger2 = self.useFixture(
            fixtures.FakeLogger(level=logging.INFO,
                                format="%(levelname)8s [%(name)s] "
                                       "%(message)s"))

        db_api.db_decrypt_parameters_and_properties(
            ctx, cfg.CONF.auth_encryption_key, verbose=False)
        self.assertNotIn("Processing raw_template 1", info_logger2.output)
        self.assertNotIn("Processing resource 1", info_logger2.output)
        self.assertNotIn("Successfully processed raw_template 1",
                         info_logger2.output)
        self.assertNotIn("Successfully processed resource 1",
                         info_logger2.output)

    def test_db_encrypt_no_param_schema(self):
        t = copy.deepcopy(self.t)
        del(t['parameters']['param2'])
        template = {
            'template': t,
            'files': {'foo': 'bar'},
            'environment': {'encrypted_param_names': [],
                            'parameters': {'param2': 'foo'}}}
        db_api.raw_template_create(self.ctx, template)
        self.assertEqual([], db_api.db_encrypt_parameters_and_properties(
            self.ctx, cfg.CONF.auth_encryption_key))

    def test_db_encrypt_non_string_param_type(self):
        t = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                description: value1.
            param2:
                type: string
                description: value2.
                hidden: true
            param3:
                type: string
                description: value3
                hidden: true
                default: 1234
        resources:
            a_resource:
                type: GenericResourceType
        ''')
        template = {
            'template': t,
            'files': {},
            'environment': {'parameters': {
                'param1': 'foo',
                'param2': 'bar',
                'param3': 12345}}}
        tmpl = db_api.raw_template_create(self.ctx, template)
        self.assertEqual([], db_api.db_encrypt_parameters_and_properties(
            self.ctx, cfg.CONF.auth_encryption_key))
        tmpl = db_api.raw_template_get(self.ctx, tmpl.id)
        enc_params = copy.copy(tmpl.environment['parameters'])

        self.assertEqual([], db_api.db_decrypt_parameters_and_properties(
            self.ctx, cfg.CONF.auth_encryption_key, batch_size=50))
        tmpl = db_api.raw_template_get(self.ctx, tmpl.id)
        dec_params = tmpl.environment['parameters']

        self.assertNotEqual(enc_params['param3'], dec_params['param3'])
        self.assertEqual('bar', dec_params['param2'])
        self.assertEqual('12345', dec_params['param3'])


class ResetStackStatusTests(common.HeatTestCase):

    def setUp(self):
        super(ResetStackStatusTests, self).setUp()
        self.ctx = utils.dummy_context()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)

    def test_status_reset(self):
        db_api.stack_update(self.ctx, self.stack.id, {'status': 'IN_PROGRESS'})
        db_api.stack_lock_create(self.ctx, self.stack.id, UUID1)
        db_api.reset_stack_status(self.ctx, self.stack.id)

        stack = db_api.stack_get(self.ctx, self.stack.id)
        self.assertEqual('FAILED', stack.status)
        self.assertEqual('Stack status manually reset',
                         stack.status_reason)
        self.assertEqual(True, db_api.stack_lock_release(self.ctx,
                                                         self.stack.id,
                                                         UUID1))

    def test_resource_reset(self):
        resource_progress = create_resource(self.ctx, self.stack,
                                            status='IN_PROGRESS',
                                            engine_id=UUID2)
        resource_complete = create_resource(self.ctx, self.stack)
        db_api.reset_stack_status(self.ctx, self.stack.id)

        resource_complete = db_api.resource_get(self.ctx, resource_complete.id)
        resource_progress = db_api.resource_get(self.ctx, resource_progress.id)
        self.assertEqual('complete', resource_complete.status)
        self.assertEqual('FAILED', resource_progress.status)
        self.assertIsNone(resource_progress.engine_id)

    def test_hook_reset(self):
        resource = create_resource(self.ctx, self.stack)
        resource.context = self.ctx
        create_resource_data(self.ctx, resource, key="pre-create")
        create_resource_data(self.ctx, resource)
        db_api.reset_stack_status(self.ctx, self.stack.id)

        vals = db_api.resource_data_get_all(self.ctx, resource.id)
        self.assertEqual({'test_resource_key': 'test_value'}, vals)

    def test_nested_stack(self):
        db_api.stack_update(self.ctx, self.stack.id, {'status': 'IN_PROGRESS'})
        child = create_stack(self.ctx, self.template, self.user_creds,
                             owner_id=self.stack.id)
        grandchild = create_stack(self.ctx, self.template, self.user_creds,
                                  owner_id=child.id, status='IN_PROGRESS')
        resource = create_resource(self.ctx, grandchild, status='IN_PROGRESS',
                                   engine_id=UUID2)
        db_api.reset_stack_status(self.ctx, self.stack.id)

        grandchild = db_api.stack_get(self.ctx, grandchild.id)
        self.stack = db_api.stack_get(self.ctx, self.stack.id)
        resource = db_api.resource_get(self.ctx, resource.id)
        self.assertEqual('FAILED', grandchild.status)
        self.assertEqual('FAILED', resource.status)
        self.assertIsNone(resource.engine_id)
        self.assertEqual('FAILED', self.stack.status)
