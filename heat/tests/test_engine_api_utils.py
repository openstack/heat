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

import uuid

import heat.engine.api as api

from heat.engine import parser
from heat.engine import resource
from heat.engine.event import Event
from heat.common.identifier import EventIdentifier
from heat.rpc import api as rpc_api
from heat.tests.common import HeatTestCase
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils


class EngineApiTest(HeatTestCase):
    def test_timeout_extract(self):
        p = {'timeout_mins': '5'}
        args = api.extract_args(p)
        self.assertEqual(args['timeout_mins'], 5)

    def test_timeout_extract_zero(self):
        p = {'timeout_mins': '0'}
        args = api.extract_args(p)
        self.assertNotIn('timeout_mins', args)

    def test_timeout_extract_garbage(self):
        p = {'timeout_mins': 'wibble'}
        args = api.extract_args(p)
        self.assertNotIn('timeout_mins', args)

    def test_timeout_extract_none(self):
        p = {'timeout_mins': None}
        args = api.extract_args(p)
        self.assertNotIn('timeout_mins', args)

    def test_timeout_extract_not_present(self):
        args = api.extract_args({})
        self.assertNotIn('timeout_mins', args)

    def test_disable_rollback_extract_true(self):
        args = api.extract_args({'disable_rollback': True})
        self.assertIn('disable_rollback', args)
        self.assertTrue(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'True'})
        self.assertIn('disable_rollback', args)
        self.assertTrue(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'true'})
        self.assertIn('disable_rollback', args)
        self.assertTrue(args.get('disable_rollback'))

    def test_disable_rollback_extract_false(self):
        args = api.extract_args({'disable_rollback': False})
        self.assertIn('disable_rollback', args)
        self.assertFalse(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'False'})
        self.assertIn('disable_rollback', args)
        self.assertFalse(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'false'})
        self.assertIn('disable_rollback', args)
        self.assertFalse(args.get('disable_rollback'))

    def test_disable_rollback_extract_bad(self):
        self.assertRaises(ValueError, api.extract_args,
                          {'disable_rollback': 'bad'})


class FormatTest(HeatTestCase):
    def setUp(self):
        super(FormatTest, self).setUp()
        utils.setup_dummy_db()

        template = parser.Template({
            'Resources': {
                'generic1': {'Type': 'GenericResourceType'},
                'generic2': {
                    'Type': 'GenericResourceType',
                    'DependsOn': 'generic1'}
            }
        })
        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template, stack_id=str(uuid.uuid4()))

    def _dummy_event(self, event_id):
        resource = self.stack['generic1']
        return Event(utils.dummy_context(), self.stack, 'CREATE', 'COMPLETE',
                     'state changed', 'z3455xyc-9f88-404d-a85b-5315293e67de',
                     resource.properties, resource.name, resource.type(),
                     id=event_id)

    def test_format_stack_resource(self):
        res = self.stack['generic1']

        resource_keys = set((
            rpc_api.RES_UPDATED_TIME,
            rpc_api.RES_NAME,
            rpc_api.RES_PHYSICAL_ID,
            rpc_api.RES_METADATA,
            rpc_api.RES_ACTION,
            rpc_api.RES_STATUS,
            rpc_api.RES_STATUS_DATA,
            rpc_api.RES_TYPE,
            rpc_api.RES_ID,
            rpc_api.RES_STACK_ID,
            rpc_api.RES_STACK_NAME,
            rpc_api.RES_REQUIRED_BY))

        resource_details_keys = resource_keys.union(set(
            (rpc_api.RES_DESCRIPTION, rpc_api.RES_METADATA)))

        formatted = api.format_stack_resource(res, True)
        self.assertEqual(resource_details_keys, set(formatted.keys()))

        formatted = api.format_stack_resource(res, False)
        self.assertEqual(resource_keys, set(formatted.keys()))

    def test_format_stack_resource_required_by(self):
        res1 = api.format_stack_resource(self.stack['generic1'])
        res2 = api.format_stack_resource(self.stack['generic2'])
        self.assertEqual(res1['required_by'], ['generic2'])
        self.assertEqual(res2['required_by'], [])

    def test_format_event_id_integer(self):
        self._test_format_event('42')

    def test_format_event_id_uuid(self):
        self._test_format_event('a3455d8c-9f88-404d-a85b-5315293e67de')

    def _test_format_event(self, event_id):
        event = self._dummy_event(event_id)

        event_keys = set((
            rpc_api.EVENT_ID,
            rpc_api.EVENT_STACK_ID,
            rpc_api.EVENT_STACK_NAME,
            rpc_api.EVENT_TIMESTAMP,
            rpc_api.EVENT_RES_NAME,
            rpc_api.EVENT_RES_PHYSICAL_ID,
            rpc_api.EVENT_RES_ACTION,
            rpc_api.EVENT_RES_STATUS,
            rpc_api.EVENT_RES_STATUS_DATA,
            rpc_api.EVENT_RES_TYPE,
            rpc_api.EVENT_RES_PROPERTIES))

        formatted = api.format_event(event)
        self.assertEqual(event_keys, set(formatted.keys()))

        event_id_formatted = formatted[rpc_api.EVENT_ID]
        event_identifier = EventIdentifier(event_id_formatted['tenant'],
                                           event_id_formatted['stack_name'],
                                           event_id_formatted['stack_id'],
                                           event_id_formatted['path'])
        self.assertEqual(event_id, event_identifier.event_id)
