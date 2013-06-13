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


from heat.common import context
import heat.db.api as db_api
from heat.engine import parser
from heat.engine import resource
from heat.engine import template
from heat.engine import event

from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db
from heat.tests import generic_resource as generic_rsrc


tmpl = {
    'Resources': {
        'EventTestResource': {
            'Type': 'GenericResourceType',
            'Properties': {'foo': True}
        }
    }
}


class EventTest(HeatTestCase):

    def setUp(self):
        super(EventTest, self).setUp()
        self.username = 'event_test_user'

        setup_dummy_db()
        self.ctx = context.get_admin_context()
        self.m.StubOutWithMock(self.ctx, 'username')
        self.ctx.username = self.username

        self.m.ReplayAll()

        # patch in a dummy property schema for GenericResource
        dummy_schema = {'foo': {'Type': 'Boolean', 'Required': True}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)

        self.stack = parser.Stack(self.ctx, 'event_load_test_stack',
                                  template.Template(tmpl))
        self.stack.store()

        self.resource = self.stack['EventTestResource']
        self.resource._store()
        self.addCleanup(db_api.stack_delete, self.ctx, self.stack.id)

    def test_load(self):
        self.resource.resource_id_set('resource_physical_id')

        e = event.Event(self.ctx, self.stack, self.resource,
                        'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', self.resource.properties)

        e.store()
        self.assertNotEqual(e.id, None)

        loaded_e = event.Event.load(self.ctx, e.id)

        self.assertEqual(loaded_e.stack.id, self.stack.id)
        self.assertEqual(loaded_e.resource.name, self.resource.name)
        self.assertEqual(loaded_e.resource.id, self.resource.id)
        self.assertEqual(loaded_e.physical_resource_id, 'wibble')
        self.assertEqual(loaded_e.action, 'TEST')
        self.assertEqual(loaded_e.status, 'IN_PROGRESS')
        self.assertEqual(loaded_e.reason, 'Testing')
        self.assertNotEqual(loaded_e.timestamp, None)
        self.assertEqual(loaded_e.resource_properties, {'foo': True})

    def test_identifier(self):
        e = event.Event(self.ctx, self.stack, self.resource,
                        'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', self.resource.properties)

        eid = e.store()
        expected_identifier = {
            'stack_name': self.stack.name,
            'stack_id': self.stack.id,
            'tenant': self.ctx.tenant_id,
            'path': '/resources/EventTestResource/events/%s' % str(eid)
        }
        self.assertEqual(e.identifier(), expected_identifier)

    def test_badprop(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'foo': 'abc'}}
        rname = 'bad_resource'
        res = generic_rsrc.GenericResource(rname, tmpl, self.stack)
        e = event.Event(self.ctx, self.stack, res,
                        'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', res.properties)
        self.assertTrue('Error' in e.resource_properties)
