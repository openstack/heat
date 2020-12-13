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

import ddt

from oslo_config import fixture as config_fixture
from oslo_policy import policy as base_policy

from heat.common import exception
from heat.common import policy
from heat.tests import common
from heat.tests import utils

policy_path = os.path.dirname(os.path.realpath(__file__)) + "/policy/"


@ddt.ddt
class TestPolicyEnforcer(common.HeatTestCase):

    def setUp(self):
        super(TestPolicyEnforcer, self).setUp(
            mock_resource_policy=False, mock_find_file=False)
        self.fixture = self.useFixture(config_fixture.Config())
        self.fixture.conf(args=['--config-dir', policy_path])

    def get_policy_file(self, filename):
        return policy_path + filename

    def _get_context(self, persona):
        if persona == "system_admin":
            ctx = utils.dummy_system_admin_context()
        elif persona == "system_reader":
            ctx = utils.dummy_system_reader_context()
        elif persona == "project_admin":
            ctx = utils.dummy_context(roles=['admin', 'member', 'reader'])
        elif persona == "project_member":
            ctx = utils.dummy_context(roles=['member', 'reader'])
        elif persona == "project_reader":
            ctx = utils.dummy_context(roles=['reader'])
        elif persona == "stack_user":
            ctx = utils.dummy_context(roles=['heat_stack_user'])
        elif persona == "anyone":
            ctx = utils.dummy_context(roles=['foobar'])
        else:
            self.fail("Persona [{}] not found".format(persona))
        return ctx

    def _test_legacy_rbac_policies(self, **kwargs):
        scope = kwargs.get("scope")
        actions = kwargs.get("actions")
        allowed_personas = kwargs.get("allowed", [])
        denied_personas = kwargs.get("denied", [])
        self._test_policy_allowed(scope, actions, allowed_personas)
        self._test_policy_notallowed(scope, actions, denied_personas)

    @ddt.file_data('policy/test_acl_personas.yaml')
    @ddt.unpack
    def test_legacy_rbac_policies(self, **kwargs):
        self._test_legacy_rbac_policies(**kwargs)

    @ddt.file_data('policy/test_deprecated_access.yaml')
    @ddt.unpack
    def test_deprecated_policies(self, **kwargs):
        self._test_legacy_rbac_policies(**kwargs)

    @ddt.file_data('policy/test_acl_personas.yaml')
    @ddt.unpack
    def test_secure_rbac_policies(self, **kwargs):
        self.fixture.config(group='oslo_policy', enforce_scope=True)
        self.fixture.config(group='oslo_policy', enforce_new_defaults=True)
        scope = kwargs.get("scope")
        actions = kwargs.get("actions")
        allowed_personas = kwargs.get("allowed", [])
        denied_personas = kwargs.get("denied", [])
        self._test_policy_allowed(scope, actions, allowed_personas)
        self._test_policy_notallowed(scope, actions, denied_personas)

    def _test_policy_allowed(self, scope, actions, personas):
        enforcer = policy.Enforcer(scope=scope)
        for persona in personas:
            ctx = self._get_context(persona)
            for action in actions:
                # Everything should be allowed
                enforcer.enforce(
                    ctx,
                    action,
                    target={"project_id": "test_tenant_id"},
                    is_registered_policy=True
                )

    def _test_policy_notallowed(self, scope, actions, personas):
        enforcer = policy.Enforcer(scope=scope)
        for persona in personas:
            ctx = self._get_context(persona)
            for action in actions:
                # Everything should raise the default exception.Forbidden
                self.assertRaises(
                    exception.Forbidden,
                    enforcer.enforce, ctx,
                    action,
                    target={"project_id": "test_tenant_id"},
                    is_registered_policy=True)

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
