#
# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
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

import os.path

from oslo_config import fixture as config_fixture
from oslo_policy import policy as base_policy

from heat.common import exception
from heat.common import policy
from heat.tests import common
from heat.tests import utils

policy_path = os.path.dirname(os.path.realpath(__file__)) + "/policy/"


class TestPolicyEnforcer(common.HeatTestCase):
    cfn_actions = ("ListStacks", "CreateStack", "DescribeStacks",
                   "DeleteStack", "UpdateStack", "DescribeStackEvents",
                   "ValidateTemplate", "GetTemplate",
                   "EstimateTemplateCost", "DescribeStackResource",
                   "DescribeStackResources")

    cw_actions = ("DeleteAlarms", "DescribeAlarmHistory", "DescribeAlarms",
                  "DescribeAlarmsForMetric", "DisableAlarmActions",
                  "EnableAlarmActions", "GetMetricStatistics", "ListMetrics",
                  "PutMetricAlarm", "PutMetricData", "SetAlarmState")

    def setUp(self):
        super(TestPolicyEnforcer, self).setUp(mock_resource_policy=False)
        self.fixture = self.useFixture(config_fixture.Config())
        self.fixture.conf(args=['--config-dir', policy_path])

    def get_policy_file(self, filename):
        return policy_path + filename

    def test_policy_cfn_default(self):
        enforcer = policy.Enforcer(scope='cloudformation')

        ctx = utils.dummy_context(roles=[])
        for action in self.cfn_actions:
            # Everything should be allowed
            enforcer.enforce(ctx, action, is_registered_policy=True)

    def test_policy_cfn_notallowed(self):
        enforcer = policy.Enforcer(
            scope='cloudformation',
            policy_file=self.get_policy_file('notallowed.json'))

        ctx = utils.dummy_context(roles=[])
        for action in self.cfn_actions:
            # Everything should raise the default exception.Forbidden
            self.assertRaises(exception.Forbidden, enforcer.enforce, ctx,
                              action, {}, is_registered_policy=True)

    def test_policy_cfn_deny_stack_user(self):
        enforcer = policy.Enforcer(scope='cloudformation')

        ctx = utils.dummy_context(roles=['heat_stack_user'])
        for action in self.cfn_actions:
            # Everything apart from DescribeStackResource should be Forbidden
            if action == "DescribeStackResource":
                enforcer.enforce(ctx, action, is_registered_policy=True)
            else:
                self.assertRaises(exception.Forbidden, enforcer.enforce, ctx,
                                  action, {}, is_registered_policy=True)

    def test_policy_cfn_allow_non_stack_user(self):
        enforcer = policy.Enforcer(scope='cloudformation')

        ctx = utils.dummy_context(roles=['not_a_stack_user'])
        for action in self.cfn_actions:
            # Everything should be allowed
            enforcer.enforce(ctx, action, is_registered_policy=True)

    def test_set_rules_overwrite_true(self):
        enforcer = policy.Enforcer()
        enforcer.load_rules(True)
        enforcer.set_rules({'test_heat_rule': 1}, True)
        self.assertEqual({'test_heat_rule': 1}, enforcer.enforcer.rules)

    def test_set_rules_overwrite_false(self):
        enforcer = policy.Enforcer()
        enforcer.load_rules(True)
        enforcer.load_rules(True)
        enforcer.set_rules({'test_heat_rule': 1}, False)
        self.assertIn('test_heat_rule', enforcer.enforcer.rules)

    def test_load_rules_force_reload_true(self):
        enforcer = policy.Enforcer()
        enforcer.load_rules(True)
        enforcer.set_rules({'test_heat_rule': 'test'})
        enforcer.load_rules(True)
        self.assertNotIn({'test_heat_rule': 'test'}, enforcer.enforcer.rules)

    def test_load_rules_force_reload_false(self):
        enforcer = policy.Enforcer()
        enforcer.load_rules(True)
        enforcer.load_rules(True)
        enforcer.set_rules({'test_heat_rule': 'test'})
        enforcer.load_rules(False)
        self.assertIn('test_heat_rule', enforcer.enforcer.rules)

    def test_no_such_action(self):
        ctx = utils.dummy_context(roles=['not_a_stack_user'])
        enforcer = policy.Enforcer(scope='cloudformation')
        action = 'no_such_action'
        msg = 'cloudformation:no_such_action has not been registered'
        self.assertRaisesRegex(base_policy.PolicyNotRegistered,
                               msg,
                               enforcer.enforce,
                               ctx, action,
                               None, None,
                               True)

    def test_check_admin(self):
        enforcer = policy.Enforcer()

        ctx = utils.dummy_context(roles=[])
        self.assertFalse(enforcer.check_is_admin(ctx))

        ctx = utils.dummy_context(roles=['not_admin'])
        self.assertFalse(enforcer.check_is_admin(ctx))

        ctx = utils.dummy_context(roles=['admin'])
        self.assertTrue(enforcer.check_is_admin(ctx))

    def test_enforce_creds(self):
        enforcer = policy.Enforcer()
        ctx = utils.dummy_context(roles=['admin'])
        self.assertTrue(enforcer.check_is_admin(ctx))

    def test_resource_default_rule(self):
        context = utils.dummy_context(roles=['non-admin'])
        enforcer = policy.ResourceEnforcer()
        res_type = "OS::Test::NotInPolicy"
        self.assertTrue(enforcer.enforce(context, res_type,
                                         is_registered_policy=True))

    def test_resource_enforce_success(self):
        context = utils.dummy_context(roles=['admin'])
        enforcer = policy.ResourceEnforcer()
        res_type = "OS::Keystone::User"
        self.assertTrue(enforcer.enforce(context, res_type,
                                         is_registered_policy=True))

    def test_resource_enforce_fail(self):
        context = utils.dummy_context(roles=['non-admin'])
        enforcer = policy.ResourceEnforcer()
        res_type = "OS::Nova::Quota"
        ex = self.assertRaises(exception.Forbidden,
                               enforcer.enforce,
                               context, res_type,
                               None, None,
                               True)
        self.assertIn(res_type, ex.message)

    def test_resource_wildcard_enforce_fail(self):
        context = utils.dummy_context(roles=['non-admin'])
        enforcer = policy.ResourceEnforcer()
        res_type = "OS::Keystone::User"
        ex = self.assertRaises(exception.Forbidden,
                               enforcer.enforce,
                               context, res_type,
                               None, None,
                               True)

        self.assertIn(res_type.split("::", 1)[0], ex.message)

    def test_resource_enforce_returns_false(self):
        context = utils.dummy_context(roles=['non-admin'])
        enforcer = policy.ResourceEnforcer(exc=None)
        res_type = "OS::Keystone::User"
        self.assertFalse(enforcer.enforce(context, res_type,
                                          is_registered_policy=True))
        self.assertIsNotNone(enforcer.enforce(context, res_type,
                                              is_registered_policy=True))

    def test_resource_enforce_exc_on_false(self):
        context = utils.dummy_context(roles=['non-admin'])
        enforcer = policy.ResourceEnforcer()
        res_type = "OS::Keystone::User"
        ex = self.assertRaises(exception.Forbidden,
                               enforcer.enforce,
                               context, res_type,
                               None, None,
                               True)

        self.assertIn(res_type, ex.message)

    def test_resource_enforce_override_deny_admin(self):
        context = utils.dummy_context(roles=['admin'])
        enforcer = policy.ResourceEnforcer(
            policy_file=self.get_policy_file('resources.json'))
        res_type = "OS::Cinder::Quota"
        ex = self.assertRaises(exception.Forbidden,
                               enforcer.enforce,
                               context, res_type,
                               None, None,
                               True)
        self.assertIn(res_type, ex.message)
