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

import fixtures
from json import loads
from json import dumps
import mox
from testtools import matchers


from heat.db.sqlalchemy import api as db_api
from heat.engine import environment
from heat.tests.v1_1 import fakes
from heat.engine.resource import Resource
from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.engine.resources import instance as instances
from heat.engine import parser
from heat.engine import scheduler
from heat.openstack.common import timeutils
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
from heat.tests import utils


from heat.engine.clients import novaclient

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

UUIDs = (UUID1, UUID2, UUID3) = sorted([uuidutils.generate_uuid()
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

    def _setup_test_stack(self, stack_name, stack_id=None):
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        stack_id = stack_id or uuidutils.generate_uuid()
        stack = parser.Stack(self.ctx, stack_name, template,
                             environment.Environment({'KeyName': 'test'}))
        with utils.UUIDStub(stack_id):
            stack.store()
        return (t, stack)

    def _mock_create(self, mocks):
        fc = fakes.FakeClient()
        mocks.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(fc)

        mocks.StubOutWithMock(fc.servers, 'create')
        fc.servers.create(image=744, flavor=3, key_name='test',
                          name=mox.IgnoreArg(),
                          security_groups=None,
                          userdata=mox.IgnoreArg(), scheduler_hints=None,
                          meta=None, nics=None,
                          availability_zone=None).MultipleTimes().AndReturn(
                              fc.servers.list()[-1])
        return fc

    def _mock_delete(self, mocks):
        fc = fakes.FakeClient()
        mocks.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(fc)

        mocks.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().MultipleTimes().AndRaise(novaclient.exceptions.NotFound(404))

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
        decrypted_key = cs.my_secret
        self.assertEqual(decrypted_key, "fake secret")

        #do this twice to verify that the orm does not commit the unencrypted
        #value.
        self.assertEqual(cs.my_secret, "fake secret")
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
        stack = self._setup_test_stack('stack', UUID1)[1]

        st = db_api.stack_get_by_name(self.ctx, 'stack')
        self.assertEqual(UUID1, st.id)

        stack.delete()

        st = db_api.stack_get_by_name(self.ctx, 'stack')
        self.assertIsNone(st)

    def test_stack_get(self):
        stack = self._setup_test_stack('stack', UUID1)[1]

        st = db_api.stack_get(self.ctx, UUID1, show_deleted=False)
        self.assertEqual(UUID1, st.id)

        stack.delete()
        st = db_api.stack_get(self.ctx, UUID1, show_deleted=False)
        self.assertIsNone(st)

        st = db_api.stack_get(self.ctx, UUID1, show_deleted=True)
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

    def test_stack_get_all_by_tenant(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_get_all_by_tenant(self.ctx)
        self.assertEqual(3, len(st_db))

        stacks[0].delete()
        st_db = db_api.stack_get_all_by_tenant(self.ctx)
        self.assertEqual(2, len(st_db))

        stacks[1].delete()
        st_db = db_api.stack_get_all_by_tenant(self.ctx)
        self.assertEqual(1, len(st_db))

    def test_stack_count_all_by_tenant(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_count_all_by_tenant(self.ctx)
        self.assertEqual(3, st_db)

        stacks[0].delete()
        st_db = db_api.stack_count_all_by_tenant(self.ctx)
        self.assertEqual(2, st_db)

        stacks[1].delete()
        st_db = db_api.stack_count_all_by_tenant(self.ctx)
        self.assertEqual(1, st_db)

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

        self.assertEqual(load_creds.get('username'), 'test_username')
        self.assertEqual(load_creds.get('password'), 'password')
        self.assertEqual(load_creds.get('tenant'), 'test_tenant')
        self.assertEqual(load_creds.get('tenant_id'), 'test_tenant_id')
        self.assertIsNotNone(load_creds.get('created_at'))
        self.assertIsNone(load_creds.get('updated_at'))
        self.assertEqual(load_creds.get('auth_url'),
                         'http://server.test:5000/v2.0')
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
        self.assertEqual(load_creds.get('tenant_id'), 'atenant123')
        self.assertEqual(load_creds.get('tenant'), 'atenant')
        self.assertEqual(load_creds.get('trust_id'), 'atrust123')
        self.assertEqual(load_creds.get('trustor_user_id'), 'atrustor123')

    def test_user_creds_none(self):
        self.ctx.username = None
        self.ctx.password = None
        self.ctx.trust_id = None
        db_creds = db_api.user_creds_create(self.ctx)
        load_creds = db_api.user_creds_get(db_creds.id)

        self.assertIsNone(load_creds.get('username'))
        self.assertIsNone(load_creds.get('password'))
        self.assertIsNone(load_creds.get('trust_id'))


def create_raw_template(context, **kwargs):
    t = template_format.parse(wp_template)
    template = {
        'template': t,
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


def create_stack_lock(ctx, stack_id, engine_id):
    return db_api.stack_lock_create(ctx, stack_id, engine_id)


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
        self.assertEqual('test_trust_id', db_api._decrypt(user_creds.trust_id))
        self.assertEqual('trustor_id', user_creds.trustor_user_id)
        self.assertIsNone(user_creds.username)
        self.assertIsNone(user_creds.password)
        self.assertEqual(self.ctx.tenant, user_creds.tenant)
        self.assertEqual(self.ctx.tenant_id, user_creds.tenant_id)

    def test_user_creds_create_password(self):
        user_creds = create_user_creds(self.ctx)
        self.assertIsNotNone(user_creds.id)
        self.assertEqual(self.ctx.password,
                         db_api._decrypt(user_creds.password))

    def test_user_creds_get(self):
        user_creds = create_user_creds(self.ctx)
        ret_user_creds = db_api.user_creds_get(user_creds.id)
        self.assertEqual(db_api._decrypt(user_creds.password),
                         ret_user_creds['password'])


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
        self.assertEqual(False, stack.disable_rollback)

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

    def test_stack_get_all_by_tenant(self):
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
        stacks = db_api.stack_get_all_by_tenant(self.ctx)
        self.assertEqual(2, len(stacks))

        self.ctx.tenant_id = UUID2
        stacks = db_api.stack_get_all_by_tenant(self.ctx)
        self.assertEqual(3, len(stacks))

        self.ctx.tenant_id = UUID3
        self.assertEqual([], db_api.stack_get_all_by_tenant(self.ctx))

    def test_stack_count_all_by_tenant(self):
        values = [
            {'tenant': self.ctx.tenant_id},
            {'tenant': self.ctx.tenant_id},
        ]
        [create_stack(self.ctx, self.template, self.user_creds,
                      **val) for val in values]

        self.assertEqual(2, db_api.stack_count_all_by_tenant(self.ctx))

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

    def test_stack_lock_create_get(self):
        create_stack_lock(self.ctx, self.stack.id, UUID1)
        lock = db_api.stack_lock_get(self.ctx, self.stack.id)
        self.assertEqual(UUID1, lock['engine_id'])

    def test_stack_lock_steal(self):
        create_stack_lock(self.ctx, self.stack.id, UUID1)
        db_api.stack_lock_steal(self.ctx, self.stack.id, UUID2)
        lock = db_api.stack_lock_get(self.ctx, self.stack.id)
        self.assertEqual(UUID2, lock['engine_id'])

    def test_stack_lock_release(self):
        create_stack_lock(self.ctx, self.stack.id, UUID1)
        db_api.stack_lock_release(self.ctx, self.stack.id)
        lock = db_api.stack_lock_get(self.ctx, self.stack.id)
        self.assertIsNone(lock)


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


class DBAPIUtilTest(HeatTestCase):
    def setUp(self):
        super(DBAPIUtilTest, self).setUp()
        self.ctx = utils.dummy_context()
        utils.setup_dummy_db()
        utils.reset_dummy_db()

    def test_current_timestamp(self):
        current_timestamp = db_api.current_timestamp()
        self.assertThat(current_timestamp, matchers.IsInstance(datetime))
