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
from webob import exc

from heat.api.openstack.v1 import util
from heat.common import context
from heat.common import policy
from heat.common import wsgi
from heat.tests import common


class TestGetAllowedParams(common.HeatTestCase):
    def setUp(self):
        super(TestGetAllowedParams, self).setUp()
        req = wsgi.Request({})
        self.params = req.params.copy()
        self.params.add('foo', 'foo value')
        self.whitelist = {'foo': util.PARAM_TYPE_SINGLE}

    def test_returns_empty_dict(self):
        self.whitelist = {}

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertEqual({}, result)

    def test_only_adds_whitelisted_params_if_param_exists(self):
        self.whitelist = {'foo': util.PARAM_TYPE_SINGLE}
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
        self.whitelist = {'foo': util.PARAM_TYPE_MULTI}
        self.params.add('foo', 'foo value 2')

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertEqual(2, len(result['foo']))
        self.assertIn('foo value', result['foo'])
        self.assertIn('foo value 2', result['foo'])

    def test_handles_mixed_value_param_with_multiple_entries(self):
        self.whitelist = {'foo': util.PARAM_TYPE_MIXED}
        self.params.add('foo', 'foo value 2')

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertEqual(2, len(result['foo']))
        self.assertIn('foo value', result['foo'])
        self.assertIn('foo value 2', result['foo'])

    def test_handles_mixed_value_param_with_single_entry(self):
        self.whitelist = {'foo': util.PARAM_TYPE_MIXED}

        result = util.get_allowed_params(self.params, self.whitelist)
        self.assertEqual('foo value', result['foo'])

    def test_bogus_whitelist_items(self):
        self.whitelist = {'foo': 'blah'}
        self.assertRaises(AssertionError, util.get_allowed_params,
                          self.params, self.whitelist)


class TestPolicyEnforce(common.HeatTestCase):
    def setUp(self):
        super(TestPolicyEnforce, self).setUp()
        self.req = wsgi.Request({})
        self.req.context = context.RequestContext(tenant='foo',
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
    def test_policy_enforce_tenant_mismatch_is_admin(self, mock_enforce):
        self.req.context = context.RequestContext(tenant='foo',
                                                  is_admin=True)
        mock_enforce.return_value = True

        self.assertEqual('woot',
                         self.controller.an_action(self.req, 'foo'))

        self.assertEqual('woot',
                         self.controller.an_action(self.req, 'bar'))

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_policy_enforce_policy_deny(self, mock_enforce):
        mock_enforce.return_value = False

        self.assertRaises(exc.HTTPForbidden,
                          self.controller.an_action,
                          self.req, tenant_id='foo')
