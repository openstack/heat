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
import uuid

from heat.db.sqlalchemy import models
from heat.engine import event
from heat.engine import stack
from heat.engine import template
from heat.objects import event as event_object
from heat.objects import resource_properties_data as rpd_object
from heat.objects import stack as stack_object
from heat.tests import common
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


class EventCommon(common.HeatTestCase):

    def _setup_stack(self, the_tmpl, encrypted=False):
        if encrypted:
            cfg.CONF.set_override('encrypt_parameters_and_properties', True)

        self.username = 'event_test_user'

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(self.ctx, 'event_load_test_stack',
                                 template.Template(the_tmpl))
        self.stack.store()

        self.resource = self.stack['EventTestResource']
        self.resource._update_stored_properties()
        self.resource.store()
        self.addCleanup(stack_object.Stack.delete, self.ctx, self.stack.id)


class EventTest(EventCommon):

    def setUp(self):
        super(EventTest, self).setUp()
        self._setup_stack(tmpl)

    def test_store_caps_events(self):
        cfg.CONF.set_override('event_purge_batch_size', 1)
        cfg.CONF.set_override('max_events_per_stack', 1)
        self.resource.resource_id_set('resource_physical_id')

        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'alabama', self.resource._rsrc_prop_data_id,
                        self.resource._stored_properties_data,
                        self.resource.name, self.resource.type())
        e.store()
        self.assertEqual(1, len(event_object.Event.get_all_by_stack(
            self.ctx,
            self.stack.id)))
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'arizona', self.resource._rsrc_prop_data_id,
                        self.resource._stored_properties_data,
                        self.resource.name, self.resource.type())
        e.store()
        events = event_object.Event.get_all_by_stack(self.ctx, self.stack.id)
        self.assertEqual(1, len(events))
        self.assertEqual('arizona', events[0].physical_resource_id)

    def test_store_caps_events_random_purge(self):
        cfg.CONF.set_override('event_purge_batch_size', 100)
        cfg.CONF.set_override('max_events_per_stack', 1)
        self.resource.resource_id_set('resource_physical_id')

        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'arkansas', None, None,
                        self.resource.name, self.resource.type())
        e.store()

        # purge happens
        with mock.patch("random.uniform") as mock_random_uniform:
            mock_random_uniform.return_value = 2.0 / 100 - .0001
            e = event.Event(self.ctx, self.stack, 'TEST',
                            'IN_PROGRESS', 'Testing',
                            'alaska', None, None,
                            self.resource.name, self.resource.type())
            e.store()
        events = event_object.Event.get_all_by_stack(self.ctx, self.stack.id)
        self.assertEqual(1, len(events))
        self.assertEqual('alaska', events[0].physical_resource_id)

        # no purge happens
        with mock.patch("random.uniform") as mock_random_uniform:
            mock_random_uniform.return_value = 2.0 / 100 + .0001
            e = event.Event(self.ctx, self.stack, 'TEST',
                            'IN_PROGRESS', 'Testing',
                            'aardvark', None, None,
                            self.resource.name, self.resource.type())
            e.store()
        events = event_object.Event.get_all_by_stack(self.ctx, self.stack.id)
        self.assertEqual(2, len(events))

    def test_store_caps_resource_props_data(self):
        cfg.CONF.set_override('event_purge_batch_size', 2)
        cfg.CONF.set_override('max_events_per_stack', 3)
        self.resource.resource_id_set('resource_physical_id')

        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'alabama', self.resource._rsrc_prop_data_id,
                        self.resource._stored_properties_data,
                        self.resource.name, self.resource.type())
        e.store()
        rpd1_id = self.resource._rsrc_prop_data_id

        rpd2 = rpd_object.ResourcePropertiesData.create(
            self.ctx, {'encrypted': False, 'data': {'foo': 'bar'}})
        rpd2_id = rpd2.id
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'arizona', rpd2_id, rpd2.data,
                        self.resource.name, self.resource.type())
        e.store()

        rpd3 = rpd_object.ResourcePropertiesData.create(
            self.ctx, {'encrypted': False, 'data': {'foo': 'bar'}})
        rpd3_id = rpd3.id
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'arkansas', rpd3_id, rpd3.data,
                        self.resource.name, self.resource.type())
        e.store()

        rpd4 = rpd_object.ResourcePropertiesData.create(
            self.ctx, {'encrypted': False, 'data': {'foo': 'bar'}})
        rpd4_id = rpd4.id
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'arkansas', rpd4_id, rpd4.data,
                        self.resource.name, self.resource.type())
        e.store()

        events = event_object.Event.get_all_by_stack(self.ctx, self.stack.id)
        self.assertEqual(2, len(events))
        self.assertEqual('arkansas', events[0].physical_resource_id)
        # rpd1 should still exist since that is still referred to by
        # the resource. rpd2 shoud have been deleted along with the
        # 2nd event.
        self.assertIsNotNone(self.ctx.session.query(
            models.ResourcePropertiesData).get(rpd1_id))
        self.assertIsNone(self.ctx.session.query(
            models.ResourcePropertiesData).get(rpd2_id))
        # We didn't purge the last two events, so we ought to have
        # kept rsrc_prop_data for both.
        self.assertIsNotNone(self.ctx.session.query(
            models.ResourcePropertiesData).get(rpd3_id))
        self.assertIsNotNone(self.ctx.session.query(
            models.ResourcePropertiesData).get(rpd4_id))

    def test_identifier(self):
        event_uuid = 'abc123yc-9f88-404d-a85b-531529456xyz'
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', self.resource._rsrc_prop_data_id,
                        self.resource._stored_properties_data,
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
                        'wibble', None, None,
                        self.resource.name, self.resource.type())

        self.assertIsNone(e.identifier())
        e.store()
        self.assertIsNotNone(e.identifier())

    def test_as_dict(self):
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', self.resource._rsrc_prop_data_id,
                        self.resource._stored_properties_data,
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

    def test_load_deprecated_prop_data(self):
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', self.resource._rsrc_prop_data_id,
                        self.resource._stored_properties_data,
                        self.resource.name, self.resource.type())
        e.store()

        # for test purposes, dress up the event to have the deprecated
        # properties_data field populated
        e_obj = self.ctx.session.query(models.Event).get(e.id)
        with self.ctx.session.begin():
            e_obj['resource_properties'] = {'Time': 'not enough'}
            e_obj['rsrc_prop_data'] = None

        # verify the deprecated data gets loaded
        ev = event_object.Event.get_all_by_stack(self.ctx, self.stack.id)[0]
        self.assertEqual({'Time': 'not enough'}, ev.resource_properties)

    def test_event_object_resource_properties_data(self):
        cfg.CONF.set_override('encrypt_parameters_and_properties', True)
        data = {'p1': 'hello',
                'p2': 'too soon?'}
        rpd_obj = rpd_object.ResourcePropertiesData().create_or_update(
            self.ctx, data)
        e_obj = event_object.Event().create(
            self.ctx,
            {'stack_id': self.stack.id,
             'uuid': str(uuid.uuid4()),
             'rsrc_prop_data_id': rpd_obj.id})
        e_obj = event_object.Event.get_all_by_stack(utils.dummy_context(),
                                                    self.stack.id)[0]
        # properties data appears unencrypted to event object
        self.assertEqual(data, e_obj.resource_properties)


class EventEncryptedTest(EventCommon):

    def setUp(self):
        super(EventEncryptedTest, self).setUp()
        self._setup_stack(tmpl, encrypted=True)

    def test_props_encrypted(self):
        e = event.Event(self.ctx, self.stack, 'TEST', 'IN_PROGRESS', 'Testing',
                        'wibble', self.resource._rsrc_prop_data_id,
                        self.resource._stored_properties_data,
                        self.resource.name, self.resource.type())
        e.store()

        # verify the resource_properties_data db data is encrypted
        e_obj = event_object.Event.get_all_by_stack(self.resource.context,
                                                    self.stack.id)[0]
        rpd_id = e_obj['rsrc_prop_data_id']
        results = self.resource.context.session.query(
            models.ResourcePropertiesData).filter_by(
                id=rpd_id)
        self.assertNotEqual('goo',
                            results[0]['data']['Foo'])
        self.assertTrue(results[0]['encrypted'])

        ev = event_object.Event.get_all_by_stack(self.ctx,
                                                 self.stack.id)[0]
        # verify not eager loaded
        self.assertIsNone(ev._resource_properties)
        # verify encrypted data is decrypted when retrieved through
        # heat object layer (normally it would be eager loaded)
        self.assertEqual({'Foo': 'goo'}, ev.resource_properties)

        # verify eager load case (uuid is specified)
        filters = {'uuid': ev.uuid}
        ev = event_object.Event.get_all_by_stack(self.ctx,
                                                 self.stack.id,
                                                 filters=filters)[0]
        # verify eager loaded
        self.assertIsNotNone(ev._resource_properties)
        self.assertEqual({'Foo': 'goo'}, ev.resource_properties)
