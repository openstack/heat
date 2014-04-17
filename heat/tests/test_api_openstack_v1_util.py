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

import json
import mock

from webob import exc
import six

from heat.api.openstack.v1 import util
from heat.common import context
from heat.common import policy
from heat.common.wsgi import Request
from heat.tests.common import HeatTestCase


class TestGetAllowedParams(HeatTestCase):
    def setUp(self):
        super(TestGetAllowedParams, self).setUp()
        req = Request({})
        self.params = req.params.copy()
        self.params.add('foo', 'foo value')
        self.whitelist = {'foo': 'single'}

    def test_returns_empty_dict(self):
        self.whitelist = {}

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertEqual({}, result)

    def test_only_adds_whitelisted_params_if_param_exists(self):
        self.whitelist = {'foo': 'single'}
        self.params.clear()

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertNotIn('foo', result)

    def test_returns_only_whitelisted_params(self):
        self.params.add('bar', 'bar value')

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertIn('foo', result)
        self.assertNotIn('bar', result)

    def test_handles_single_value_params(self):
        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertEqual('foo value', result['foo'])

    def test_handles_multiple_value_params(self):
        self.whitelist = {'foo': 'multi'}
        self.params.add('foo', 'foo value 2')

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertEqual(2, len(result['foo']))
        self.assertIn('foo value', result['foo'])
        self.assertIn('foo value 2', result['foo'])

    def test_handles_mixed_value_param_with_multiple_entries(self):
        self.whitelist = {'foo': 'mixed'}
        self.params.add('foo', 'foo value 2')

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertEqual(2, len(result['foo']))
        self.assertIn('foo value', result['foo'])
        self.assertIn('foo value 2', result['foo'])

    def test_handles_mixed_value_param_with_single_entry(self):
        self.whitelist = {'foo': 'mixed'}

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertEqual('foo value', result['foo'])

    def test_ignores_bogus_whitelist_items(self):
        self.whitelist = {'foo': 'blah'}
        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertNotIn('foo', result)


class TestPolicyEnforce(HeatTestCase):
    def setUp(self):
        super(TestPolicyEnforce, self).setUp()
        self.req = Request({})
        self.req.context = context.RequestContext(tenant_id='foo',
                                                  is_admin=False)

        class DummyController(object):
            REQUEST_SCOPE = 'test'

            @util.policy_enforce
            def an_action(self, req):
                return 'woot'

        self.controller = DummyController()

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_policy_enforce_tenant_mismatch(self, mock_enforce):
        mock_enforce.return_value = True

        self.assertEqual('woot',
                         self.controller.an_action(self.req, 'foo'))

        self.assertRaises(exc.HTTPForbidden,
                          self.controller.an_action,
                          self.req, tenant_id='bar')

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_policy_enforce_policy_deny(self, mock_enforce):
        mock_enforce.return_value = False

        self.assertRaises(exc.HTTPForbidden,
                          self.controller.an_action,
                          self.req, tenant_id='foo')


class TestExtractArgs(HeatTestCase):
    def test_timeout_extract(self):
        p = {'timeout_mins': '5'}
        args = util.extract_args(p)
        self.assertEqual(5, args['timeout_mins'])

    def test_timeout_extract_zero(self):
        p = {'timeout_mins': '0'}
        args = util.extract_args(p)
        self.assertNotIn('timeout_mins', args)

    def test_timeout_extract_garbage(self):
        p = {'timeout_mins': 'wibble'}
        args = util.extract_args(p)
        self.assertNotIn('timeout_mins', args)

    def test_timeout_extract_none(self):
        p = {'timeout_mins': None}
        args = util.extract_args(p)
        self.assertNotIn('timeout_mins', args)

    def test_timeout_extract_negative(self):
        p = {'timeout_mins': '-100'}
        error = self.assertRaises(ValueError, util.extract_args, p)
        self.assertIn('Invalid timeout value', six.text_type(error))

    def test_timeout_extract_not_present(self):
        args = util.extract_args({})
        self.assertNotIn('timeout_mins', args)

    def test_adopt_stack_data_extract_present(self):
        p = {'adopt_stack_data': json.dumps({'Resources': {}})}
        args = util.extract_args(p)
        self.assertTrue(args.get('adopt_stack_data'))

    def test_invalid_adopt_stack_data(self):
        p = {'adopt_stack_data': json.dumps("foo")}
        error = self.assertRaises(ValueError, util.extract_args, p)
        self.assertEqual(
            'Unexpected adopt data "foo". Adopt data must be a dict.',
            six.text_type(error))

    def test_adopt_stack_data_extract_not_present(self):
        args = util.extract_args({})
        self.assertNotIn('adopt_stack_data', args)

    def test_disable_rollback_extract_true(self):
        args = util.extract_args({'disable_rollback': True})
        self.assertIn('disable_rollback', args)
        self.assertTrue(args.get('disable_rollback'))

        args = util.extract_args({'disable_rollback': 'True'})
        self.assertIn('disable_rollback', args)
        self.assertTrue(args.get('disable_rollback'))

        args = util.extract_args({'disable_rollback': 'true'})
        self.assertIn('disable_rollback', args)
        self.assertTrue(args.get('disable_rollback'))

    def test_disable_rollback_extract_false(self):
        args = util.extract_args({'disable_rollback': False})
        self.assertIn('disable_rollback', args)
        self.assertFalse(args.get('disable_rollback'))

        args = util.extract_args({'disable_rollback': 'False'})
        self.assertIn('disable_rollback', args)
        self.assertFalse(args.get('disable_rollback'))

        args = util.extract_args({'disable_rollback': 'false'})
        self.assertIn('disable_rollback', args)
        self.assertFalse(args.get('disable_rollback'))

    def test_disable_rollback_extract_bad(self):
        self.assertRaises(ValueError, util.extract_args,
                          {'disable_rollback': 'bad'})
