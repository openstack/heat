# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


from nose.plugins.attrib import attr
import mox
import unittest

from heat.common import context
import heat.db as db_api
from heat.engine import parser
from heat.engine import template
from heat.engine.resources import event
from heat.engine.resources import resource


tmpl = {
    'Resources': {
        'EventTestResource': {
            'Type': 'GenericResourceType',
        }
    }
}


@attr(tag=['unit', 'event'])
@attr(speed='fast')
class EventTest(unittest.TestCase):

    def setUp(self):
        self.username = 'event_test_user'

        self.m = mox.Mox()

        self.ctx = context.get_admin_context()
        self.m.StubOutWithMock(self.ctx, 'username')
        self.ctx.username = self.username

        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'event_load_test_stack',
                                  template.Template(tmpl))
        self.stack.store()

        self.resource = self.stack['EventTestResource']
        self.resource._store()

    def tearDown(self):
        db_api.stack_delete(self.ctx, self.stack.id)
        self.m.UnsetStubs()

    def test_load(self):
        self.resource.resource_id_set('resource_physical_id')

        e = event.Event(self.ctx, self.stack, self.resource,
                        'TEST_IN_PROGRESS', 'Testing',
                        'wibble', {'foo': 'bar'})

        e.store()
        self.assertNotEqual(e.id, None)

        loaded_e = event.Event.load(self.ctx, e.id)

        self.assertEqual(loaded_e.stack.id, self.stack.id)
        self.assertEqual(loaded_e.resource.name, self.resource.name)
        self.assertEqual(loaded_e.resource.id, self.resource.id)
        self.assertEqual(loaded_e.physical_resource_id, 'wibble')
        self.assertEqual(loaded_e.new_state, 'TEST_IN_PROGRESS')
        self.assertEqual(loaded_e.reason, 'Testing')
        self.assertNotEqual(loaded_e.timestamp, None)
        self.assertEqual(loaded_e.resource_properties, {'foo': 'bar'})

    def test_identifier(self):
        e = event.Event(self.ctx, self.stack, self.resource,
                        'TEST_IN_PROGRESS', 'Testing',
                        'wibble', {'foo': 'bar'})

        eid = e.store()
        expected_identifier = {
            'stack_name': self.stack.name,
            'stack_id': self.stack.id,
            'tenant': self.ctx.tenant_id,
            'path': '/resources/EventTestResource/events/%s' % str(eid)
        }
        self.assertEqual(e.identifier(), expected_identifier)
