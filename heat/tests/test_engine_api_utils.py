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
import heat.engine.api as api
from heat.engine import parser
from heat.engine import resource
from heat.openstack.common import uuidutils
from heat.rpc import api as rpc_api
from heat.tests.common import HeatTestCase
from heat.tests import generic_resource as generic_rsrc
from heat.tests.utils import setup_dummy_db


class EngineApiTest(HeatTestCase):
    def test_timeout_extract(self):
        p = {'timeout_mins': '5'}
        args = api.extract_args(p)
        self.assertEqual(args['timeout_mins'], 5)

    def test_timeout_extract_zero(self):
        p = {'timeout_mins': '0'}
        args = api.extract_args(p)
        self.assertTrue('timeout_mins' not in args)

    def test_timeout_extract_garbage(self):
        p = {'timeout_mins': 'wibble'}
        args = api.extract_args(p)
        self.assertTrue('timeout_mins' not in args)

    def test_timeout_extract_none(self):
        p = {'timeout_mins': None}
        args = api.extract_args(p)
        self.assertTrue('timeout_mins' not in args)

    def test_timeout_extract_not_present(self):
        args = api.extract_args({})
        self.assertTrue('timeout_mins' not in args)

    def test_disable_rollback_extract_true(self):
        args = api.extract_args({'disable_rollback': True})
        self.assertTrue('disable_rollback' in args)
        self.assertTrue(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'True'})
        self.assertTrue('disable_rollback' in args)
        self.assertTrue(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'true'})
        self.assertTrue('disable_rollback' in args)
        self.assertTrue(args.get('disable_rollback'))

    def test_disable_rollback_extract_false(self):
        args = api.extract_args({'disable_rollback': False})
        self.assertTrue('disable_rollback' in args)
        self.assertFalse(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'False'})
        self.assertTrue('disable_rollback' in args)
        self.assertFalse(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'false'})
        self.assertTrue('disable_rollback' in args)
        self.assertFalse(args.get('disable_rollback'))

    def test_disable_rollback_extract_bad(self):
        self.assertRaises(ValueError, api.extract_args,
                          {'disable_rollback': 'bad'})


class FormatTest(HeatTestCase):

    def setUp(self):
        super(FormatTest, self).setUp()
        setup_dummy_db()
        ctx = context.get_admin_context()
        self.m.StubOutWithMock(ctx, 'user')
        ctx.user = 'test_user'
        ctx.tenant_id = 'test_tenant'

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
        self.stack = parser.Stack(ctx, 'test_stack', template,
                                  stack_id=uuidutils.generate_uuid())

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
