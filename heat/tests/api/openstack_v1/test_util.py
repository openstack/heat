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

from unittest import mock

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
        self.param_types = {'foo': util.PARAM_TYPE_SINGLE}

    def test_returns_empty_dict(self):
        self.param_types = {}

        result = util.get_allowed_params(self.params, self.param_types)
        self.assertEqual({}, result)

    def test_only_adds_allowed_param_if_param_exists(self):
        self.param_types = {'foo': util.PARAM_TYPE_SINGLE}
        self.params.clear()

        result = util.get_allowed_params(self.params, self.param_types)
        self.assertNotIn('foo', result)

    def test_returns_only_allowed_params(self):
        self.params.add('bar', 'bar value')

        result = util.get_allowed_params(self.params, self.param_types)
        self.assertIn('foo', result)
        self.assertNotIn('bar', result)

    def test_handles_single_value_params(self):
        result = util.get_allowed_params(self.params, self.param_types)
        self.assertEqual('foo value', result['foo'])

    def test_handles_multiple_value_params(self):
        self.param_types = {'foo': util.PARAM_TYPE_MULTI}
        self.params.add('foo', 'foo value 2')

        result = util.get_allowed_params(self.params, self.param_types)
        self.assertEqual(2, len(result['foo']))
        self.assertIn('foo value', result['foo'])
        self.assertIn('foo value 2', result['foo'])

    def test_handles_mixed_value_param_with_multiple_entries(self):
        self.param_types = {'foo': util.PARAM_TYPE_MIXED}
        self.params.add('foo', 'foo value 2')

        result = util.get_allowed_params(self.params, self.param_types)
        self.assertEqual(2, len(result['foo']))
        self.assertIn('foo value', result['foo'])
        self.assertIn('foo value 2', result['foo'])

    def test_handles_mixed_value_param_with_single_entry(self):
        self.param_types = {'foo': util.PARAM_TYPE_MIXED}

        result = util.get_allowed_params(self.params, self.param_types)
        self.assertEqual('foo value', result['foo'])

    def test_bogus_param_type(self):
        self.param_types = {'foo': 'blah'}
        self.assertRaises(AssertionError, util.get_allowed_params,
                          self.params, self.param_types)


class TestPolicyEnforce(common.HeatTestCase):
    def setUp(self):
        super(TestPolicyEnforce, self).setUp()
        self.req = wsgi.Request({})
        self.req.context = context.RequestContext(tenant='foo',
                                                  is_admin=False)

        class DummyController(object):
            REQUEST_SCOPE = 'test'

            @util.registered_policy_enforce
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
