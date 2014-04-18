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

from datetime import datetime
from datetime import timedelta
import uuid

import fixtures
from json import dumps
from json import loads
import mock
import mox

from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.db.sqlalchemy import api as db_api
from heat.engine import clients
from heat.engine.clients import novaclient
from heat.engine import environment
from heat.engine import parser
from heat.engine.resource import Resource
from heat.engine.resources import instance as instances
from heat.engine import scheduler
from heat.openstack.common import timeutils
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes


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


class MyResource(Resource):
    properties_schema = {
        'ServerName': {'Type': 'String', 'Required': True},
        'Flavor': {'Type': 'String', 'Required': True},
        'ImageName': {'Type': 'String', 'Required': True},
        'UserData': {'Type': 'String'},
        'PublicKey': {'Type': 'String'}
    }

    @property
    def my_secret(self):
        return db_api.resource_data_get(self, 'my_secret')

    @my_secret.setter
    def my_secret(self, my_secret):
        db_api.resource_data_set(self, 'my_secret', my_secret, True)


class SqlAlchemyTest(HeatTestCase):
    def setUp(self):
        super(SqlAlchemyTest, self).setUp()
        self.fc = fakes.FakeClient()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.ctx = utils.dummy_context()

    def tearDown(self):
        super(SqlAlchemyTest, self).tearDown()

    def _setup_test_stack(self, stack_name, stack_id=None, owner_id=None,
                          stack_user_project_id=None):
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        stack_id = stack_id or str(uuid.uuid4())
        stack = parser.Stack(self.ctx, stack_name, template,
                             environment.Environment({'KeyName': 'test'}),
                             owner_id=owner_id,
                             stack_user_project_id=stack_user_project_id)
        with utils.UUIDStub(stack_id):
            stack.store()
        return (t, stack)

    def _mock_create(self, mocks):
        fc = fakes.FakeClient()
        mocks.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        mocks.StubOutWithMock(fc.servers, 'create')
        fc.servers.create(image=744, flavor=3, key_name='test',
                          name=mox.IgnoreArg(),
                          security_groups=None,
                          userdata=mox.IgnoreArg(), scheduler_hints=None,
                          meta=None, nics=None,
                          availability_zone=None).MultipleTimes().AndReturn(
                              fc.servers.list()[4])
        return fc

    def _mock_delete(self, mocks):
        fc = fakes.FakeClient()
        mocks.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        mocks.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().MultipleTimes().AndRaise(novaclient.exceptions.NotFound(404))

    @mock.patch.object(db_api, '_paginate_query')
    def test_filter_and_page_query_paginates_query(self, mock_paginate_query):
        query = mock.Mock()
        db_api._filter_and_page_query(self.ctx, query)

        assert mock_paginate_query.called

    @mock.patch.object(db_api.db_filters, 'exact_filter')
    def test_filter_and_page_query_handles_no_filters(self, mock_db_filter):
        query = mock.Mock()
        db_api._filter_and_page_query(self.ctx, query)

        mock_db_filter.assert_called_once_with(mock.ANY, mock.ANY, {})

    @mock.patch.object(db_api.db_filters, 'exact_filter')
    def test_filter_and_page_query_applies_filters(self, mock_db_filter):
        query = mock.Mock()
        filters = {'foo': 'bar'}
        db_api._filter_and_page_query(self.ctx, query, filters=filters)

        assert mock_db_filter.called

    @mock.patch.object(db_api, '_paginate_query')
    def test_filter_and_page_query_whitelists_sort_keys(self,
                                                        mock_paginate_query):
        query = mock.Mock()
        sort_keys = ['name', 'foo']
        db_api._filter_and_page_query(self.ctx, query, sort_keys=sort_keys)

        args, _ = mock_paginate_query.call_args
        self.assertIn(['name'], args)

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
    @mock.patch.object(db_api, 'model_query')
    def test_paginate_query_gets_model_marker(self, mock_query,
                                              mock_paginate_query):
        query = mock.Mock()
        model = mock.Mock()
        marker = mock.Mock()

        mock_query_object = mock.Mock()
        mock_query_object.get.return_value = 'real_marker'
        mock_query.return_value = mock_query_object

        db_api._paginate_query(self.ctx, query, model, marker=marker)
        mock_query_object.get.assert_called_once_with(marker)
        args, _ = mock_paginate_query.call_args
        self.assertIn('real_marker', args)

    @mock.patch.object(db_api.utils, 'paginate_query')
    def test_paginate_query_raises_invalid_sort_key(self, mock_paginate_query):
        query = mock.Mock()
        model = mock.Mock()

        mock_paginate_query.side_effect = db_api.utils.InvalidSortKey()
        self.assertRaises(exception.Invalid, db_api._paginate_query,
                          self.ctx, query, model, sort_keys=['foo'])

    def test_filter_sort_keys_returns_empty_list_if_no_keys(self):
        sort_keys = None
        whitelist = None

        filtered_keys = db_api._filter_sort_keys(sort_keys, whitelist)
        self.assertEqual([], filtered_keys)

    def test_filter_sort_keys_whitelists_single_key(self):
        sort_key = 'foo'
        whitelist = ['foo']

        filtered_keys = db_api._filter_sort_keys(sort_key, whitelist)
        self.assertEqual(['foo'], filtered_keys)

    def test_filter_sort_keys_whitelists_multiple_keys(self):
        sort_keys = ['foo', 'bar', 'nope']
        whitelist = ['foo', 'bar']

        filtered_keys = db_api._filter_sort_keys(sort_keys, whitelist)
        self.assertIn('foo', filtered_keys)
        self.assertIn('bar', filtered_keys)
        self.assertNotIn('nope', filtered_keys)

    def test_encryption(self):
        stack_name = 'test_encryption'
        (t, stack) = self._setup_test_stack(stack_name)
        cs = MyResource('cs_encryption',
                        t['Resources']['WebServer'],
                        stack)

        # This gives the fake cloud server an id and created_time attribute
        cs._store_or_update(cs.CREATE, cs.IN_PROGRESS, 'test_store')

        cs.my_secret = 'fake secret'
        rs = db_api.resource_get_by_name_and_stack(self.ctx,
                                                   'cs_encryption',
                                                   stack.id)
        encrypted_key = rs.data[0]['value']
        self.assertNotEqual(encrypted_key, "fake secret")
        # Test private_key property returns decrypted value
        self.assertEqual("fake secret", cs.my_secret)

        #do this twice to verify that the orm does not commit the unencrypted
        #value.
        self.assertEqual("fake secret", cs.my_secret)
        scheduler.TaskRunner(cs.destroy)()

    def test_resource_data_delete(self):
        stack = self._setup_test_stack('stack', UUID1)[1]
        self._mock_create(self.m)
        self.m.ReplayAll()
        stack.create()
        rsrc = stack['WebServer']
        db_api.resource_data_set(rsrc, 'test', 'test_data')
        self.assertEqual('test_data', db_api.resource_data_get(rsrc, 'test'))
        db_api.resource_data_delete(rsrc, 'test')
        self.assertRaises(exception.NotFound,
                          db_api.resource_data_get, rsrc, 'test')

    def test_stack_get_by_name(self):
        stack = self._setup_test_stack('stack', UUID1,
                                       stack_user_project_id=UUID2)[1]

        st = db_api.stack_get_by_name(self.ctx, 'stack')
        self.assertEqual(UUID1, st.id)

        self.ctx.tenant_id = UUID3
        st = db_api.stack_get_by_name(self.ctx, 'stack')
        self.assertIsNone(st)

        self.ctx.tenant_id = UUID2
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

        self.ctx.tenant_id = str(uuid.uuid4())
        result = db_api.stack_get_by_name_and_owner_id(self.ctx, 'stack2',
                                                       None)
        self.assertIsNone(result)

        self.ctx.tenant_id = UUID3
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
                                     sort_keys='created_at')
        self.assertEqual(3, len(st_db))
        self.assertEqual(stacks[0].id, st_db[0].id)
        self.assertEqual(stacks[1].id, st_db[1].id)
        self.assertEqual(stacks[2].id, st_db[2].id)

    @mock.patch.object(db_api.utils, 'paginate_query')
    def test_stack_get_all_filters_sort_keys(self, mock_paginate):
        sort_keys = ['name', 'status', 'created_at', 'updated_at', 'username']
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

        uuid = 'this stack doesnt exist'
        st_db = db_api.stack_get_all(self.ctx, marker=uuid)
        self.assertEqual(3, len(st_db))

    def test_stack_get_all_doesnt_mutate_sort_keys(self):
        [self._setup_test_stack('stack', x)[1] for x in UUIDs]
        sort_keys = ['id']

        db_api.stack_get_all(self.ctx, sort_keys=sort_keys)
        self.assertEqual(['id'], sort_keys)

    def test_stack_count_all(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_count_all(self.ctx)
        self.assertEqual(3, st_db)

        stacks[0].delete()
        st_db = db_api.stack_count_all(self.ctx)
        self.assertEqual(2, st_db)

        stacks[1].delete()
        st_db = db_api.stack_count_all(self.ctx)
        self.assertEqual(1, st_db)

    def test_stack_count_all_with_filters(self):
        self._setup_test_stack('foo', UUID1)
        self._setup_test_stack('bar', UUID2)
        self._setup_test_stack('bar', UUID3)
        filters = {'name': 'bar'}

        st_db = db_api.stack_count_all(self.ctx, filters=filters)
        self.assertEqual(2, st_db)

    def test_event_get_all_by_stack(self):
        stack = self._setup_test_stack('stack', UUID1)[1]

        self._mock_create(self.m)
        self.m.ReplayAll()
        stack.create()
        self.m.UnsetStubs()

        events = db_api.event_get_all_by_stack(self.ctx, UUID1)
        self.assertEqual(2, len(events))

        self._mock_delete(self.m)
        self.m.ReplayAll()
        stack.delete()

        events = db_api.event_get_all_by_stack(self.ctx, UUID1)
        self.assertEqual(4, len(events))

        self.m.VerifyAll()

    def test_event_count_all_by_stack(self):
        stack = self._setup_test_stack('stack', UUID1)[1]

        self._mock_create(self.m)
        self.m.ReplayAll()
        stack.create()
        self.m.UnsetStubs()

        num_events = db_api.event_count_all_by_stack(self.ctx, UUID1)
        self.assertEqual(2, num_events)

        self._mock_delete(self.m)
        self.m.ReplayAll()
        stack.delete()

        num_events = db_api.event_count_all_by_stack(self.ctx, UUID1)
        self.assertEqual(4, num_events)

        self.m.VerifyAll()

    def test_event_get_all_by_tenant(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        self._mock_create(self.m)
        self.m.ReplayAll()
        [s.create() for s in stacks]
        self.m.UnsetStubs()

        events = db_api.event_get_all_by_tenant(self.ctx)
        self.assertEqual(6, len(events))

        self._mock_delete(self.m)
        self.m.ReplayAll()
        [s.delete() for s in stacks]

        events = db_api.event_get_all_by_tenant(self.ctx)
        self.assertEqual(0, len(events))

        self.m.VerifyAll()

    def test_event_get_all(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        self._mock_create(self.m)
        self.m.ReplayAll()
        [s.create() for s in stacks]
        self.m.UnsetStubs()

        events = db_api.event_get_all(self.ctx)
        self.assertEqual(6, len(events))

        self._mock_delete(self.m)
        self.m.ReplayAll()
        stacks[0].delete()

        events = db_api.event_get_all(self.ctx)
        self.assertEqual(4, len(events))

        self.m.VerifyAll()

    def test_user_creds_password(self):
        self.ctx.trust_id = None
        db_creds = db_api.user_creds_create(self.ctx)
        load_creds = db_api.user_creds_get(db_creds.id)

        self.assertEqual('test_username', load_creds.get('username'))
        self.assertEqual('password', load_creds.get('password'))
        self.assertEqual('test_tenant', load_creds.get('tenant'))
        self.assertEqual('test_tenant_id', load_creds.get('tenant_id'))
        self.assertIsNotNone(load_creds.get('created_at'))
        self.assertIsNone(load_creds.get('updated_at'))
        self.assertEqual('http://server.test:5000/v2.0',
                         load_creds.get('auth_url'))
        self.assertIsNone(load_creds.get('trust_id'))
        self.assertIsNone(load_creds.get('trustor_user_id'))

    def test_user_creds_trust(self):
        self.ctx.username = None
        self.ctx.password = None
        self.ctx.trust_id = 'atrust123'
        self.ctx.trustor_user_id = 'atrustor123'
        self.ctx.tenant_id = 'atenant123'
        self.ctx.tenant = 'atenant'
        db_creds = db_api.user_creds_create(self.ctx)
        load_creds = db_api.user_creds_get(db_creds.id)

        self.assertIsNone(load_creds.get('username'))
        self.assertIsNone(load_creds.get('password'))
        self.assertIsNotNone(load_creds.get('created_at'))
        self.assertIsNone(load_creds.get('updated_at'))
        self.assertIsNone(load_creds.get('auth_url'))
        self.assertEqual('atenant123', load_creds.get('tenant_id'))
        self.assertEqual('atenant', load_creds.get('tenant'))
        self.assertEqual('atrust123', load_creds.get('trust_id'))
        self.assertEqual('atrustor123', load_creds.get('trustor_user_id'))

    def test_user_creds_none(self):
        self.ctx.username = None
        self.ctx.password = None
        self.ctx.trust_id = None
        db_creds = db_api.user_creds_create(self.ctx)
        load_creds = db_api.user_creds_get(db_creds.id)

        self.assertIsNone(load_creds.get('username'))
        self.assertIsNone(load_creds.get('password'))
        self.assertIsNone(load_creds.get('trust_id'))

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
        self.ctx.tenant_id = None
        self.assertRaises(
            exception.NotFound,
            db_api.software_config_get,
            self.ctx,
            config_id)

    def test_software_config_delete(self):
        tenant_id = self.ctx.tenant_id
        config = db_api.software_config_create(
            self.ctx, {'name': 'config_mysql',
                       'tenant': tenant_id})
        config_id = config.id
        db_api.software_config_delete(self.ctx, config_id)
        err = self.assertRaises(
            exception.NotFound,
            db_api.software_config_get,
            self.ctx,
            config_id)
        self.assertIn(config_id, str(err))

        err = self.assertRaises(
            exception.NotFound, db_api.software_config_delete,
            self.ctx, config_id)
        self.assertIn(config_id, str(err))

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
        self.ctx.tenant_id = str(uuid.uuid4())
        self.assertRaises(
            exception.NotFound,
            db_api.software_deployment_get,
            self.ctx,
            deployment_id)

        # assert found with stack_user_project_id context tenant
        self.ctx.tenant_id = deployment.stack_user_project_id
        deployment = db_api.software_deployment_get(self.ctx, deployment_id)
        self.assertIsNotNone(deployment)
        self.assertEqual(values['tenant'], deployment.tenant)

    def test_software_deployment_get_all(self):
        self.assertEqual([], db_api.software_deployment_get_all(self.ctx))
        values = self._deployment_values()
        deployment = db_api.software_deployment_create(self.ctx, values)
        self.assertIsNotNone(deployment)
        all = db_api.software_deployment_get_all(self.ctx)
        self.assertEqual(1, len(all))
        self.assertEqual(deployment, all[0])
        all = db_api.software_deployment_get_all(
            self.ctx, server_id=values['server_id'])
        self.assertEqual(1, len(all))
        self.assertEqual(deployment, all[0])
        all = db_api.software_deployment_get_all(
            self.ctx, server_id=str(uuid.uuid4()))
        self.assertEqual([], all)

    def test_software_deployment_update(self):
        deployment_id = str(uuid.uuid4())
        err = self.assertRaises(exception.NotFound,
                                db_api.software_deployment_update,
                                self.ctx, deployment_id, values={})
        self.assertIn(deployment_id, str(err))
        values = self._deployment_values()
        deployment = db_api.software_deployment_create(self.ctx, values)
        deployment_id = deployment.id
        values = {'status': 'COMPLETED'}
        deployment = db_api.software_deployment_update(
            self.ctx, deployment_id, values)
        self.assertIsNotNone(deployment)
        self.assertEqual(values['status'], deployment.status)

    def test_software_deployment_delete(self):
        deployment_id = str(uuid.uuid4())
        err = self.assertRaises(exception.NotFound,
                                db_api.software_deployment_delete,
                                self.ctx, deployment_id)
        self.assertIn(deployment_id, str(err))
        values = self._deployment_values()
        deployment = db_api.software_deployment_create(self.ctx, values)
        deployment_id = deployment.id
        deployment = db_api.software_deployment_get(self.ctx, deployment_id)
        self.assertIsNotNone(deployment)
        db_api.software_deployment_delete(self.ctx, deployment_id)

        err = self.assertRaises(
            exception.NotFound,
            db_api.software_deployment_get,
            self.ctx,
            deployment_id)

        self.assertIn(deployment_id, str(err))


def create_raw_template(context, **kwargs):
    t = template_format.parse(wp_template)
    template = {
        'template': t,
        'files': {'foo': 'bar'}
    }
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
        'user_creds_id': user_creds.id,
        'owner_id': None,
        'timeout': '60',
        'disable_rollback': 0
    }
    values.update(kwargs)
    return db_api.stack_create(ctx, values)


def create_resource(ctx, stack, **kwargs):
    values = {
        'name': 'test_resource_name',
        'nova_instance': UUID1,
        'action': 'create',
        'status': 'complete',
        'status_reason': 'create_complete',
        'rsrc_metadata': loads('{"foo": "123"}'),
        'stack_id': stack.id
    }
    values.update(kwargs)
    return db_api.resource_create(ctx, values)


def create_resource_data(ctx, resource, **kwargs):
    values = {
        'key': 'test_resource_key',
        'value': 'test_value',
        'redact': 0,
    }
    values.update(kwargs)
    return db_api.resource_data_set(resource, **values)


def create_event(ctx, **kwargs):
    values = {
        'stack_id': 'test_stack_id',
        'resource_action': 'create',
        'resource_status': 'complete',
        'resource_name': 'res',
        'physical_resource_id': UUID1,
        'resource_status_reason': "create_complete",
        'resource_properties': {'name': 'foo'}
    }
    values.update(kwargs)
    return db_api.event_create(ctx, values)


def create_watch_rule(ctx, stack, **kwargs):
    values = {
        'name': 'test_rule',
        'rule': loads('{"foo": "123"}'),
        'state': 'normal',
        'last_evaluated': timeutils.utcnow(),
        'stack_id': stack.id,
    }
    values.update(kwargs)
    return db_api.watch_rule_create(ctx, values)


def create_watch_data(ctx, watch_rule, **kwargs):
    values = {
        'data': loads('{"foo": "bar"}'),
        'watch_rule_id': watch_rule.id
    }
    values.update(kwargs)
    return db_api.watch_data_create(ctx, values)


class DBAPIRawTemplateTest(HeatTestCase):
    def setUp(self):
        super(DBAPIRawTemplateTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()

    def test_raw_template_create(self):
        t = template_format.parse(wp_template)
        tp = create_raw_template(self.ctx, template=t)
        self.assertIsNotNone(tp.id)
        self.assertEqual(t, tp.template)
        self.assertEqual({'foo': 'bar'}, tp.files)

    def test_raw_template_get(self):
        t = template_format.parse(wp_template)
        tp = create_raw_template(self.ctx, template=t)
        template = db_api.raw_template_get(self.ctx, tp.id)
        self.assertEqual(tp.id, template.id)
        self.assertEqual(tp.template, template.template)


class DBAPIUserCredsTest(HeatTestCase):
    def setUp(self):
        super(DBAPIUserCredsTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()

    def test_user_creds_create_trust(self):
        user_creds = create_user_creds(self.ctx, trust_id='test_trust_id',
                                       trustor_user_id='trustor_id')
        self.assertIsNotNone(user_creds.id)
        self.assertEqual('test_trust_id',
                         db_api._decrypt(user_creds.trust_id,
                                         user_creds.decrypt_method))
        self.assertEqual('trustor_id', user_creds.trustor_user_id)
        self.assertIsNone(user_creds.username)
        self.assertIsNone(user_creds.password)
        self.assertEqual(self.ctx.tenant, user_creds.tenant)
        self.assertEqual(self.ctx.tenant_id, user_creds.tenant_id)

    def test_user_creds_create_password(self):
        user_creds = create_user_creds(self.ctx)
        self.assertIsNotNone(user_creds.id)
        self.assertEqual(self.ctx.password,
                         db_api._decrypt(user_creds.password,
                                         user_creds.decrypt_method))

    def test_user_creds_get(self):
        user_creds = create_user_creds(self.ctx)
        ret_user_creds = db_api.user_creds_get(user_creds.id)
        self.assertEqual(db_api._decrypt(user_creds.password,
                                         user_creds.decrypt_method),
                         ret_user_creds['password'])

    def test_user_creds_get_noexist(self):
        self.assertIsNone(db_api.user_creds_get(123456))

    def test_user_creds_delete(self):
        user_creds = create_user_creds(self.ctx)
        self.assertIsNotNone(user_creds.id)
        db_api.user_creds_delete(self.ctx, user_creds.id)
        creds = db_api.user_creds_get(user_creds.id)
        self.assertIsNone(creds)
        err = self.assertRaises(
            exception.NotFound, db_api.user_creds_delete,
            self.ctx, user_creds.id)
        exp_msg = ('Attempt to delete user creds with id '
                   '%s that does not exist' % user_creds.id)
        self.assertIn(exp_msg, str(err))


class DBAPIStackTest(HeatTestCase):
    def setUp(self):
        super(DBAPIStackTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
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
        self.assertEqual(self.user_creds.id, stack.user_creds_id)
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

        #Testing soft delete
        ret_stack = db_api.stack_get(self.ctx, stack_id, show_deleted=True)
        self.assertIsNotNone(ret_stack)
        self.assertEqual(stack_id, ret_stack.id)
        self.assertEqual('db_test_stack_name', ret_stack.name)

        #Testing child resources deletion
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
        }
        db_api.stack_update(self.ctx, stack.id, values)
        stack = db_api.stack_get(self.ctx, stack.id)
        self.assertEqual('db_test_stack_name2', stack.name)
        self.assertEqual('update', stack.action)
        self.assertEqual('failed', stack.status)
        self.assertEqual('update_failed', stack.status_reason)
        self.assertEqual('90', stack.timeout)

        self.assertRaises(exception.NotFound, db_api.stack_update, self.ctx,
                          UUID2, values)

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
        self.ctx.tenant_id = 'abc'
        stack = db_api.stack_get(self.ctx, UUID1, show_deleted=False)
        self.assertIsNone(stack)

    def test_stack_get_tenant_is_stack_user_project_id(self):
        stack = create_stack(self.ctx, self.template, self.user_creds,
                             stack_user_project_id='astackuserproject')
        self.ctx.tenant_id = 'astackuserproject'
        ret_stack = db_api.stack_get(self.ctx, stack.id, show_deleted=False)
        self.assertIsNotNone(ret_stack)
        self.assertEqual(stack.id, ret_stack.id)
        self.assertEqual('db_test_stack_name', ret_stack.name)

    def test_stack_get_can_return_a_stack_from_different_tenant(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        self.ctx.tenant_id = 'abc'
        ret_stack = db_api.stack_get(self.ctx, stack.id,
                                     show_deleted=False, tenant_safe=False)
        self.assertEqual(stack.id, ret_stack.id)
        self.assertEqual('db_test_stack_name', ret_stack.name)

    def test_stack_get_by_name(self):
        stack = create_stack(self.ctx, self.template, self.user_creds)
        ret_stack = db_api.stack_get_by_name(self.ctx, stack.name)
        self.assertIsNotNone(ret_stack)
        self.assertEqual(stack.id, ret_stack.id)
        self.assertEqual('db_test_stack_name', ret_stack.name)

        self.assertIsNone(db_api.stack_get_by_name(self.ctx, 'abc'))

        self.ctx.tenant_id = 'abc'
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

        self.ctx.tenant_id = UUID1
        stacks = db_api.stack_get_all(self.ctx)
        self.assertEqual(2, len(stacks))

        self.ctx.tenant_id = UUID2
        stacks = db_api.stack_get_all(self.ctx)
        self.assertEqual(3, len(stacks))

        self.ctx.tenant_id = UUID3
        self.assertEqual([], db_api.stack_get_all(self.ctx))

    def test_stack_get_all_with_tenant_safe_false(self):
        values = [
            {'tenant': UUID1},
            {'tenant': UUID1},
            {'tenant': UUID2},
            {'tenant': UUID2},
            {'tenant': UUID2},
        ]
        [create_stack(self.ctx, self.template, self.user_creds,
                      **val) for val in values]

        stacks = db_api.stack_get_all(self.ctx, tenant_safe=False)
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

        self.ctx.tenant_id = UUID1
        self.assertEqual(2, db_api.stack_count_all(self.ctx))

        self.ctx.tenant_id = UUID2
        self.assertEqual(3, db_api.stack_count_all(self.ctx))

    def test_stack_count_all_with_tenant_safe_false(self):
        values = [
            {'tenant': UUID1},
            {'tenant': UUID1},
            {'tenant': UUID2},
            {'tenant': UUID2},
            {'tenant': UUID2},
        ]
        [create_stack(self.ctx, self.template, self.user_creds,
                      **val) for val in values]

        self.assertEqual(5,
                         db_api.stack_count_all(self.ctx, tenant_safe=False))

    def test_purge_deleted(self):
        now = datetime.now()
        delta = timedelta(seconds=3600 * 7)
        deleted = [now - delta * i for i in range(1, 6)]
        templates = [create_raw_template(self.ctx) for i in range(5)]
        creds = [create_user_creds(self.ctx) for i in range(5)]
        stacks = [create_stack(self.ctx, templates[i], creds[i],
                               deleted_at=deleted[i]) for i in range(5)]

        class MyDatetime():
            def now(self):
                return now
        self.useFixture(fixtures.MonkeyPatch('heat.db.sqlalchemy.api.datetime',
                                             MyDatetime()))

        db_api.purge_deleted(age=1, granularity='days')
        self._deleted_stack_existance(utils.dummy_context(), stacks,
                                      (0, 1, 2), (3, 4))

        db_api.purge_deleted(age=22, granularity='hours')
        self._deleted_stack_existance(utils.dummy_context(), stacks,
                                      (0, 1, 2), (3, 4))

        db_api.purge_deleted(age=1100, granularity='minutes')
        self._deleted_stack_existance(utils.dummy_context(), stacks,
                                      (0, 1), (2, 3, 4))

        db_api.purge_deleted(age=3600, granularity='seconds')
        self._deleted_stack_existance(utils.dummy_context(), stacks,
                                      (), (0, 1, 2, 3, 4))

    def _deleted_stack_existance(self, ctx, stacks, existing, deleted):
        for s in existing:
            self.assertIsNotNone(db_api.stack_get(ctx, stacks[s].id,
                                                  show_deleted=True))
        for s in deleted:
            self.assertIsNone(db_api.stack_get(ctx, stacks[s].id,
                                               show_deleted=True))


class DBAPIResourceTest(HeatTestCase):
    def setUp(self):
        super(DBAPIResourceTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)

    def test_resource_create(self):
        res = create_resource(self.ctx, self.stack)
        ret_res = db_api.resource_get(self.ctx, res.id)
        self.assertIsNotNone(ret_res)
        self.assertEqual('test_resource_name', ret_res.name)
        self.assertEqual(UUID1, ret_res.nova_instance)
        self.assertEqual('create', ret_res.action)
        self.assertEqual('complete', ret_res.status)
        self.assertEqual('create_complete', ret_res.status_reason)
        self.assertEqual('{"foo": "123"}', dumps(ret_res.rsrc_metadata))
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
        self.assertEqual(UUID1, ret_res.nova_instance)

        self.assertIsNone(db_api.resource_get_by_physical_resource_id(self.ctx,
                                                                      UUID2))

    def test_resource_get_all(self):
        values = [
            {'name': 'res1'},
            {'name': 'res2'},
            {'name': 'res3'},
        ]
        [create_resource(self.ctx, self.stack, **val) for val in values]

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
            {'name': 'res3', 'stack_id': self.stack1.id},
        ]
        [create_resource(self.ctx, self.stack, **val) for val in values]

        stacks = db_api.resource_get_all_by_stack(self.ctx, self.stack.id)
        self.assertEqual(2, len(stacks))

        self.assertRaises(exception.NotFound, db_api.resource_get_all_by_stack,
                          self.ctx, self.stack2.id)


class DBAPIStackLockTest(HeatTestCase):
    def setUp(self):
        super(DBAPIStackLockTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)

    def test_stack_lock_create_success(self):
        observed = db_api.stack_lock_create(self.stack.id, UUID1)
        self.assertIsNone(observed)

    def test_stack_lock_create_fail_double_same(self):
        db_api.stack_lock_create(self.stack.id, UUID1)
        observed = db_api.stack_lock_create(self.stack.id, UUID1)
        self.assertEqual(UUID1, observed)

    def test_stack_lock_create_fail_double_different(self):
        db_api.stack_lock_create(self.stack.id, UUID1)
        observed = db_api.stack_lock_create(self.stack.id, UUID2)
        self.assertEqual(UUID1, observed)

    def test_stack_lock_steal_success(self):
        db_api.stack_lock_create(self.stack.id, UUID1)
        observed = db_api.stack_lock_steal(self.stack.id, UUID1, UUID2)
        self.assertIsNone(observed)

    def test_stack_lock_steal_fail_gone(self):
        db_api.stack_lock_create(self.stack.id, UUID1)
        db_api.stack_lock_release(self.stack.id, UUID1)
        observed = db_api.stack_lock_steal(self.stack.id, UUID1, UUID2)
        self.assertTrue(observed)

    def test_stack_lock_steal_fail_stolen(self):
        db_api.stack_lock_create(self.stack.id, UUID1)

        # Simulate stolen lock
        db_api.stack_lock_release(self.stack.id, UUID1)
        db_api.stack_lock_create(self.stack.id, UUID2)

        observed = db_api.stack_lock_steal(self.stack.id, UUID3, UUID2)
        self.assertEqual(UUID2, observed)

    def test_stack_lock_release_success(self):
        db_api.stack_lock_create(self.stack.id, UUID1)
        observed = db_api.stack_lock_release(self.stack.id, UUID1)
        self.assertIsNone(observed)

    def test_stack_lock_release_fail_double(self):
        db_api.stack_lock_create(self.stack.id, UUID1)
        db_api.stack_lock_release(self.stack.id, UUID1)
        observed = db_api.stack_lock_release(self.stack.id, UUID1)
        self.assertTrue(observed)

    def test_stack_lock_release_fail_wrong_engine_id(self):
        db_api.stack_lock_create(self.stack.id, UUID1)
        observed = db_api.stack_lock_release(self.stack.id, UUID2)
        self.assertTrue(observed)


class DBAPIResourceDataTest(HeatTestCase):
    def setUp(self):
        super(DBAPIResourceDataTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)
        self.resource = create_resource(self.ctx, self.stack)
        self.resource.context = self.ctx

    def test_resource_data_set_get(self):
        create_resource_data(self.ctx, self.resource)
        val = db_api.resource_data_get(self.resource, 'test_resource_key')
        self.assertEqual('test_value', val)

        #Updating existing resource data
        create_resource_data(self.ctx, self.resource, value='foo')
        val = db_api.resource_data_get(self.resource, 'test_resource_key')
        self.assertEqual('foo', val)

        #Testing with encrypted value
        create_resource_data(self.ctx, self.resource,
                             key='encryped_resource_key', redact=True)
        val = db_api.resource_data_get(self.resource, 'encryped_resource_key')
        self.assertEqual('test_value', val)

        vals = db_api.resource_data_get_all(self.resource)
        self.assertEqual(2, len(vals))
        self.assertEqual('foo', vals.get('test_resource_key'))
        self.assertEqual('test_value', vals.get('encryped_resource_key'))

    def test_resource_data_delete(self):
        create_resource_data(self.ctx, self.resource)
        res_data = db_api.resource_data_get_by_key(self.ctx, self.resource.id,
                                                   'test_resource_key')
        self.assertIsNotNone(res_data)
        self.assertEqual('test_value', res_data.value)

        db_api.resource_data_delete(self.resource, 'test_resource_key')
        self.assertRaises(exception.NotFound, db_api.resource_data_get_by_key,
                          self.ctx, self.resource.id, 'test_resource_key')
        self.assertIsNotNone(res_data)


class DBAPIEventTest(HeatTestCase):
    def setUp(self):
        super(DBAPIEventTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)

    def test_event_create_get(self):
        event = create_event(self.ctx)
        ret_event = db_api.event_get(self.ctx, event.id)
        self.assertIsNotNone(ret_event)
        self.assertEqual('test_stack_id', ret_event.stack_id)
        self.assertEqual('create', ret_event.resource_action)
        self.assertEqual('complete', ret_event.resource_status)
        self.assertEqual('res', ret_event.resource_name)
        self.assertEqual(UUID1, ret_event.physical_resource_id)
        self.assertEqual('create_complete', ret_event.resource_status_reason)
        self.assertEqual({'name': 'foo'}, ret_event.resource_properties)

    def test_event_get_all(self):
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

        events = db_api.event_get_all(self.ctx)
        self.assertEqual(3, len(events))

        stack_ids = [event.stack_id for event in events]
        res_names = [event.resource_name for event in events]
        [(self.assertIn(val['stack_id'], stack_ids),
          self.assertIn(val['resource_name'], res_names)) for val in values]

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

        self.ctx.tenant_id = 'tenant1'
        events = db_api.event_get_all_by_tenant(self.ctx)
        self.assertEqual(2, len(events))

        self.ctx.tenant_id = 'tenant2'
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

        self.ctx.tenant_id = 'tenant1'
        events = db_api.event_get_all_by_stack(self.ctx, self.stack1.id)
        self.assertEqual(2, len(events))

        self.ctx.tenant_id = 'tenant2'
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


class DBAPIWatchRuleTest(HeatTestCase):
    def setUp(self):
        super(DBAPIWatchRuleTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)

    def test_watch_rule_create_get(self):
        watch_rule = create_watch_rule(self.ctx, self.stack)
        ret_wr = db_api.watch_rule_get(self.ctx, watch_rule.id)
        self.assertIsNotNone(ret_wr)
        self.assertEqual('test_rule', ret_wr.name)
        self.assertEqual('{"foo": "123"}', dumps(ret_wr.rule))
        self.assertEqual('normal', ret_wr.state)
        self.assertEqual(self.stack.id, ret_wr.stack_id)

    def test_watch_rule_get_by_name(self):
        watch_rule = create_watch_rule(self.ctx, self.stack)
        ret_wr = db_api.watch_rule_get_by_name(self.ctx, watch_rule.name)
        self.assertIsNotNone(ret_wr)
        self.assertEqual('test_rule', ret_wr.name)

    def test_watch_rule_get_all(self):
        values = [
            {'name': 'rule1'},
            {'name': 'rule2'},
            {'name': 'rule3'},
        ]
        [create_watch_rule(self.ctx, self.stack, **val) for val in values]

        wrs = db_api.watch_rule_get_all(self.ctx)
        self.assertEqual(3, len(wrs))

        names = [wr.name for wr in wrs]
        [self.assertIn(val['name'], names) for val in values]

    def test_watch_rule_get_all_by_stack(self):
        self.stack1 = create_stack(self.ctx, self.template, self.user_creds)

        values = [
            {'name': 'rule1', 'stack_id': self.stack.id},
            {'name': 'rule2', 'stack_id': self.stack1.id},
            {'name': 'rule3', 'stack_id': self.stack1.id},
        ]
        [create_watch_rule(self.ctx, self.stack, **val) for val in values]

        wrs = db_api.watch_rule_get_all_by_stack(self.ctx, self.stack.id)
        self.assertEqual(1, len(wrs))
        wrs = db_api.watch_rule_get_all_by_stack(self.ctx, self.stack1.id)
        self.assertEqual(2, len(wrs))

    def test_watch_rule_update(self):
        watch_rule = create_watch_rule(self.ctx, self.stack)
        values = {
            'name': 'test_rule_1',
            'rule': loads('{"foo": "bar"}'),
            'state': 'nodata',
        }
        db_api.watch_rule_update(self.ctx, watch_rule.id, values)
        watch_rule = db_api.watch_rule_get(self.ctx, watch_rule.id)
        self.assertEqual('test_rule_1', watch_rule.name)
        self.assertEqual('{"foo": "bar"}', dumps(watch_rule.rule))
        self.assertEqual('nodata', watch_rule.state)

        self.assertRaises(exception.NotFound, db_api.watch_rule_update,
                          self.ctx, UUID2, values)

    def test_watch_rule_delete(self):
        watch_rule = create_watch_rule(self.ctx, self.stack)
        create_watch_data(self.ctx, watch_rule)
        db_api.watch_rule_delete(self.ctx, watch_rule.id)
        self.assertIsNone(db_api.watch_rule_get(self.ctx, watch_rule.id))
        self.assertRaises(exception.NotFound, db_api.watch_rule_delete,
                          self.ctx, UUID2)

        #Testing associated watch data deletion
        self.assertEqual([], db_api.watch_data_get_all(self.ctx))


class DBAPIWatchDataTest(HeatTestCase):
    def setUp(self):
        super(DBAPIWatchDataTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.template = create_raw_template(self.ctx)
        self.user_creds = create_user_creds(self.ctx)
        self.stack = create_stack(self.ctx, self.template, self.user_creds)
        self.watch_rule = create_watch_rule(self.ctx, self.stack)

    def test_watch_data_create(self):
        create_watch_data(self.ctx, self.watch_rule)
        ret_data = db_api.watch_data_get_all(self.ctx)
        self.assertEqual(1, len(ret_data))

        self.assertEqual('{"foo": "bar"}', dumps(ret_data[0].data))
        self.assertEqual(self.watch_rule.id, ret_data[0].watch_rule_id)

    def test_watch_data_get_all(self):
        values = [
            {'data': loads('{"foo": "d1"}')},
            {'data': loads('{"foo": "d2"}')},
            {'data': loads('{"foo": "d3"}')}
        ]
        [create_watch_data(self.ctx, self.watch_rule, **val) for val in values]
        watch_data = db_api.watch_data_get_all(self.ctx)
        self.assertEqual(3, len(watch_data))

        data = [wd.data for wd in watch_data]
        [self.assertIn(val['data'], data) for val in values]
