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
import oslo_db.exception

from heat.engine import event
from heat.engine import rsrc_defn
from heat.engine import stack
from heat.engine import template
from heat.objects import event as event_object
from heat.objects import stack as stack_object
from heat.tests import common
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils

cfg.CONF.import_opt('event_purge_batch_size', 'heat.common.config')
cfg.CONF.import_opt('max_events_per_stack', 'heat.common.config')

tmpl = {
    'HeatTemplateFormatVersion': '2012-12-12',
    'Resources': {
        'EventTestResource': {
            'Type': 'ResourceWithRequiredProps',
            'Properties': {'Foo': 'goo'}
        }
    }
}

tmpl_multiple = {
    'HeatTemplateFormatVersion': '2012-12-12',
    'Resources': {
        'EventTestResource': {
            'Type': 'ResourceWithMultipleRequiredProps',
            'Properties': {'Foo1': 'zoo',
                           'Foo2': 'A0000000000',
                           'Foo3': '99999'}
        }
    }
}

tmpl_multiple_too_large = {
    'HeatTemplateFormatVersion': '2012-12-12',
    'Resources': {
        'EventTestResource': {
            'Type': 'ResourceWithMultipleRequiredProps',
            'Properties': {'Foo1': 'zoo',
                           'Foo2': 'A' * (1 << 16),
                           'Foo3': '99999'}
        }
    }
}

tmpl_multiple_srsly_too_large = {
    'HeatTemplateFormatVersion': '2012-12-12',
    'Resources': {
        'EventTestResource': {
            'Type': 'ResourceWithMultipleRequiredProps',
            'Properties': {'Foo1': 'Z' * (1 << 16),
                           'Foo2': 'A' * (1 << 16),
                           'Foo3': '99999'}
        }
    }
}


class EventCommon(common.HeatTestCase):

    def setUp(self):
        super(EventCommon, self).setUp()

    def _setup_stack(self, the_tmpl):
        self.username = 'event_test_user'

        self.ctx = utils.dummy_context()

        self.m.ReplayAll()

        self.stack = stack.Stack(self.ctx, 'event_load_test_stack',
                                 template.Template(the_tmpl))
        self.stack.store()

        self.resource = self.stack['EventTestResource']
        self.resource._store()
        self.addCleanup(stack_object.Stack.delete, self.ctx, self.stack.id)


class EventTest(EventCommon):

    def setUp(self):
        super(EventTest, self).setUp()
        self._setup_stack(tmpl)

    def test_store_caps_events(self):
        cfg.CONF.set_override('event_purge_batch_size', 1, enforce_type=True)
        cfg.CONF.set_override('max_events_per_stack', 1, enforce_type=True)
        self.resource.resource_id_set('resource_physical_id')

        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'alabama', self.resource.properties,
                        self.resource.name, self.resource.type())
        e.store()
        self.assertEqual(1, len(event_object.Event.get_all_by_stack(
            self.ctx,
            self.stack.id)))
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'arizona', self.resource.properties,
                        self.resource.name, self.resource.type())
        e.store()
        events = event_object.Event.get_all_by_stack(self.ctx, self.stack.id)
        self.assertEqual(1, len(events))
        self.assertEqual('arizona', events[0].physical_resource_id)

    def test_identifier(self):
        event_uuid = 'abc123yc-9f88-404d-a85b-531529456xyz'
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', self.resource.properties,
                        self.resource.name, self.resource.type(),
                        uuid=event_uuid)

        e.store()
        expected_identifier = {
            'stack_name': self.stack.name,
            'stack_id': self.stack.id,
            'tenant': self.ctx.tenant_id,
            'path': '/resources/EventTestResource/events/%s' % str(event_uuid)
        }
        self.assertEqual(expected_identifier, e.identifier())

    def test_identifier_is_none(self):
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', self.resource.properties,
                        self.resource.name, self.resource.type())

        self.assertIsNone(e.identifier())
        e.store()
        self.assertIsNotNone(e.identifier())

    def test_badprop(self):
        rname = 'bad_resource'
        defn = rsrc_defn.ResourceDefinition(rname,
                                            'ResourceWithRequiredProps',
                                            {'IntFoo': False})

        res = generic_rsrc.ResourceWithRequiredProps(rname, defn, self.stack)
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', res.properties, res.name, res.type())
        self.assertIn('Error', e.resource_properties)

    def test_as_dict(self):
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', self.resource.properties,
                        self.resource.name, self.resource.type())

        e.store()
        expected = {
            'id': e.uuid,
            'timestamp': e.timestamp.isoformat(),
            'type': 'os.heat.event',
            'version': '0.1',
            'payload': {'physical_resource_id': 'wibble',
                        'resource_action': 'TEST',
                        'resource_name': 'EventTestResource',
                        'resource_properties': {'Foo': 'goo'},
                        'resource_status': 'IN_PROGRESS',
                        'resource_status_reason': 'Testing',
                        'resource_type': 'ResourceWithRequiredProps',
                        'stack_id': self.stack.id,
                        'version': '0.1'}}
        self.assertEqual(expected, e.as_dict())


class EventTestSingleLargeProp(EventCommon):

    def setUp(self):
        super(EventTestSingleLargeProp, self).setUp()
        self._setup_stack(tmpl_multiple_too_large)

    def test_too_large_single_prop(self):
        self.resource.resource_id_set('resource_physical_id')

        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'alabama', self.resource.properties,
                        self.resource.name, self.resource.type())
        e.store()
        self.assertIsNotNone(e.id)
        ev = event_object.Event.get_by_id(self.ctx, e.id)

        self.assertEqual(
            {'Foo1': 'zoo',
             'Foo2': '<Deleted, too large>',
             'Foo3': '99999',
             'Error': 'Resource properties are too large to store fully'},
            ev['resource_properties'])


class EventTestMultipleLargeProp(EventCommon):

    def setUp(self):
        super(EventTestMultipleLargeProp, self).setUp()
        self._setup_stack(tmpl_multiple_srsly_too_large)

    def test_too_large_multiple_prop(self):
        self.resource.resource_id_set('resource_physical_id')

        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'alabama', self.resource.properties,
                        self.resource.name, self.resource.type())
        e.store()
        self.assertIsNotNone(e.id)
        ev = event_object.Event.get_by_id(self.ctx, e.id)

        self.assertEqual(
            {'Error': 'Resource properties are too large to attempt to store'},
            ev['resource_properties'])


class EventTestStoreProps(EventCommon):

    def setUp(self):
        super(EventTestStoreProps, self).setUp()
        self._setup_stack(tmpl_multiple)

    def test_store_fail_all_props(self):
        self.resource.resource_id_set('resource_physical_id')

        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'alabama', self.resource.properties,
                        self.resource.name, self.resource.type())
        e.store()
        self.assertIsNotNone(e.id)
        ev = event_object.Event.get_by_id(self.ctx, e.id)

        errors = [oslo_db.exception.DBError]

        def side_effect(*args):
            try:
                raise errors.pop()
            except IndexError:
                self.assertEqual(
                    {'Error': 'Resource properties are too large to store'},
                    args[1]['resource_properties'])
                return ev

        with mock.patch("heat.objects.event.Event") as mock_event:
            mock_event.create.side_effect = side_effect
            e.store()
