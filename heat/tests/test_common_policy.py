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

from oslo.config import cfg

from heat.common import exception
from heat.common import policy
from heat.openstack.common import policy as base_policy
from heat.tests.common import HeatTestCase
from heat.tests import utils

policy_path = os.path.dirname(os.path.realpath(__file__)) + "/policy/"


class TestPolicyEnforcer(HeatTestCase):
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
        super(TestPolicyEnforcer, self).setUp()
        opts = [
            cfg.StrOpt('config_dir', default=policy_path),
            cfg.StrOpt('config_file', default='foo'),
            cfg.StrOpt('project', default='heat'),
        ]
        cfg.CONF.register_opts(opts)
        self.addCleanup(self.m.VerifyAll)

    def stub_policyfile(self, filename):
        pf = policy_path + filename
        self.m.StubOutWithMock(base_policy.Enforcer, '_get_policy_path')
        base_policy.Enforcer._get_policy_path().MultipleTimes().AndReturn(pf)
        self.m.ReplayAll()

    def test_policy_cfn_default(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer(scope='cloudformation')

        ctx = utils.dummy_context(roles=[])
        for action in self.cfn_actions:
            # Everything should be allowed
            enforcer.enforce(ctx, action)

    def test_policy_cfn_notallowed(self):
        self.stub_policyfile('notallowed.json')

        enforcer = policy.Enforcer(scope='cloudformation')

        ctx = utils.dummy_context(roles=[])
        for action in self.cfn_actions:
            # Everything should raise the default exception.Forbidden
            self.assertRaises(exception.Forbidden, enforcer.enforce, ctx,
                              action, {})

    def test_policy_cfn_deny_stack_user(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer(scope='cloudformation')

        ctx = utils.dummy_context(roles=['heat_stack_user'])
        for action in self.cfn_actions:
            # Everything apart from DescribeStackResource should be Forbidden
            if action == "DescribeStackResource":
                enforcer.enforce(ctx, action)
            else:
                self.assertRaises(exception.Forbidden, enforcer.enforce, ctx,
                                  action, {})

    def test_policy_cfn_allow_non_stack_user(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer(scope='cloudformation')

        ctx = utils.dummy_context(roles=['not_a_stack_user'])
        for action in self.cfn_actions:
            # Everything should be allowed
            enforcer.enforce(ctx, action)

    def test_policy_cw_deny_stack_user(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer(scope='cloudwatch')

        ctx = utils.dummy_context(roles=['heat_stack_user'])
        for action in self.cw_actions:
            # Everything apart from PutMetricData should be Forbidden
            if action == "PutMetricData":
                enforcer.enforce(ctx, action)
            else:
                self.assertRaises(exception.Forbidden, enforcer.enforce, ctx,
                                  action, {})

    def test_policy_cw_allow_non_stack_user(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer(scope='cloudwatch')

        ctx = utils.dummy_context(roles=['not_a_stack_user'])
        for action in self.cw_actions:
            # Everything should be allowed
            enforcer.enforce(ctx, action)

    def test_clear(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer()
        enforcer.load_rules(force_reload=True)
        enforcer.clear()
        self.assertEqual({}, enforcer.enforcer.rules)

    def test_set_rules_overwrite_true(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer()
        enforcer.load_rules(True)
        enforcer.set_rules({'test_heat_rule': 1}, True)
        self.assertEqual({'test_heat_rule': 1}, enforcer.enforcer.rules)

    def test_set_rules_overwrite_false(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer()
        enforcer.load_rules(True)
        enforcer.set_rules({'test_heat_rule': 1}, False)
        self.assertIn('test_heat_rule', enforcer.enforcer.rules)

    def test_load_rules_force_reload_true(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer()
        enforcer.set_rules({'test_heat_rule': 'test'})
        enforcer.load_rules(True)
        self.assertNotIn({'test_heat_rule': 'test'}, enforcer.enforcer.rules)

    def test_load_rules_force_reload_false(self):
        self.stub_policyfile('deny_stack_user.json')

        enforcer = policy.Enforcer()
        enforcer.load_rules(True)
        enforcer.set_rules({'test_heat_rule': 'test'})
        enforcer.load_rules(False)
        self.assertIn('test_heat_rule', enforcer.enforcer.rules)

    def test_default_rule(self):
        self.stub_policyfile('deny_stack_user.json')

        ctx = utils.dummy_context(roles=['not_a_stack_user'])
        default_rule = base_policy.FalseCheck()
        enforcer = policy.Enforcer(scope='cloudformation',
                                   exc=None, default_rule=default_rule)
        action = 'no_such_action'
        self.assertFalse(enforcer.enforce(ctx, action))

    def test_check_admin(self):
        self.stub_policyfile('check_admin.json')

        enforcer = policy.Enforcer()

        ctx = utils.dummy_context(roles=[])
        self.assertFalse(enforcer.check_is_admin(ctx))

        ctx = utils.dummy_context(roles=['not_admin'])
        self.assertFalse(enforcer.check_is_admin(ctx))

        ctx = utils.dummy_context(roles=['admin'])
        self.assertTrue(enforcer.check_is_admin(ctx))
