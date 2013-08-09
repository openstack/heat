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

import mox

from heat.db.sqlalchemy import api as db_api
from heat.engine import environment
from heat.tests.v1_1 import fakes
from heat.engine.resource import Resource
from heat.common import template_format
from heat.engine.resources import instance as instances
from heat.engine import parser
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

UUIDs = (UUID1, UUID2) = sorted([uuidutils.generate_uuid() for x in range(2)])


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
        rs = db_api.resource_get_by_name_and_stack(None,
                                                   'cs_encryption',
                                                   stack.id)
        encrypted_key = rs.data[0]['value']
        self.assertNotEqual(encrypted_key, "fake secret")
        decrypted_key = cs.my_secret
        self.assertEqual(decrypted_key, "fake secret")
        cs.destroy()

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
        self.assertEqual(2, len(st_db))

        stacks[0].delete()
        st_db = db_api.stack_get_all(self.ctx)
        self.assertEqual(1, len(st_db))

        stacks[1].delete()
        st_db = db_api.stack_get_all(self.ctx)
        self.assertEqual(0, len(st_db))

    def test_stack_get_all_by_tenant(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        st_db = db_api.stack_get_all_by_tenant(self.ctx)
        self.assertEqual(2, len(st_db))

        stacks[0].delete()
        st_db = db_api.stack_get_all_by_tenant(self.ctx)
        self.assertEqual(1, len(st_db))

        stacks[1].delete()
        st_db = db_api.stack_get_all_by_tenant(self.ctx)
        self.assertEqual(0, len(st_db))

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

    def test_event_get_all_by_tenant(self):
        stacks = [self._setup_test_stack('stack', x)[1] for x in UUIDs]

        self._mock_create(self.m)
        self.m.ReplayAll()
        [s.create() for s in stacks]
        self.m.UnsetStubs()

        events = db_api.event_get_all_by_tenant(self.ctx)
        self.assertEqual(4, len(events))

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
        self.assertEqual(4, len(events))

        self._mock_delete(self.m)
        self.m.ReplayAll()
        stacks[0].delete()

        events = db_api.event_get_all(self.ctx)
        self.assertEqual(2, len(events))

        self.m.VerifyAll()
