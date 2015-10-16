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

import copy

from neutronclient.common import exceptions
from neutronclient.v2_0 import client as neutronclient
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import firewall
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


firewall_template = '''
heat_template_version: 2015-04-30
description: Template to test neutron firewall resource
resources:
  firewall:
    type: OS::Neutron::Firewall
    properties:
      name: test-firewall
      firewall_policy_id: policy-id
      admin_state_up: True
      shared: True
      value_specs:
         router_ids:
           - router_1
           - router_2
'''

firewall_policy_template = '''
heat_template_version: 2015-04-30
description: Template to test neutron firewall policy resource
resources:
  firewall_policy:
    type: OS::Neutron::FirewallPolicy
    properties:
      name: test-firewall-policy
      shared: True
      audited: True
      firewall_rules:
        - rule-id-1
        - rule-id-2
'''

firewall_rule_template = '''
heat_template_version: 2015-04-30
description: Template to test neutron firewall rule resource
resources:
  firewall_rule:
    type: OS::Neutron::FirewallRule
    properties:
      name: test-firewall-rule
      shared: True
      protocol: tcp
      action: allow
      enabled: True
      ip_version: 4
'''


class FirewallTest(common.HeatTestCase):

    def setUp(self):
        super(FirewallTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_firewall')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_firewall')
        self.m.StubOutWithMock(neutronclient.Client, 'show_firewall')
        self.m.StubOutWithMock(neutronclient.Client, 'update_firewall')
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_firewall(self):
        neutronclient.Client.create_firewall({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True}}
        ).AndReturn({'firewall': {'id': '5678'}})

        snippet = template_format.parse(firewall_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return firewall.Firewall(
            'firewall', resource_defns['firewall'], self.stack)

    def test_create(self):
        rsrc = self.create_firewall()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        neutronclient.Client.create_firewall({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True}}
        ).AndRaise(exceptions.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(firewall_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = firewall.Firewall(
            'firewall', resource_defns['firewall'], stack)

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.firewall: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_firewall('5678')
        neutronclient.Client.show_firewall('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_firewall()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_firewall('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_firewall()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_firewall('5678').AndRaise(
            exceptions.NeutronClientException(status_code=400))

        rsrc = self.create_firewall()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.firewall: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_firewall()
        neutronclient.Client.show_firewall('5678').MultipleTimes(
        ).AndReturn(
            {'firewall': {'admin_state_up': True,
                          'firewall_policy_id': 'policy-id',
                          'shared': True}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertIs(True, rsrc.FnGetAtt('shared'))
        self.assertEqual('policy-id', rsrc.FnGetAtt('firewall_policy_id'))
        self.m.VerifyAll()

    def test_attribute_failed(self):
        rsrc = self.create_firewall()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'subnet_id')
        self.assertEqual(
            'The Referenced Attribute (firewall subnet_id) is '
            'incorrect.', six.text_type(error))
        self.m.VerifyAll()

    def test_update(self):
        rsrc = self.create_firewall()
        neutronclient.Client.update_firewall(
            '5678', {'firewall': {'admin_state_up': False}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['admin_state_up'] = False
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.m.VerifyAll()


class FirewallPolicyTest(common.HeatTestCase):

    def setUp(self):
        super(FirewallPolicyTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_firewall_policy')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_firewall_policy')
        self.m.StubOutWithMock(neutronclient.Client, 'show_firewall_policy')
        self.m.StubOutWithMock(neutronclient.Client, 'update_firewall_policy')
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_firewall_policy(self):
        neutronclient.Client.create_firewall_policy({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']}}
        ).AndReturn({'firewall_policy': {'id': '5678'}})

        snippet = template_format.parse(firewall_policy_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return firewall.FirewallPolicy(
            'firewall_policy', resource_defns['firewall_policy'], self.stack)

    def test_create(self):
        rsrc = self.create_firewall_policy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        neutronclient.Client.create_firewall_policy({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']}}
        ).AndRaise(exceptions.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(firewall_policy_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = firewall.FirewallPolicy(
            'firewall_policy', resource_defns['firewall_policy'], stack)

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.firewall_policy: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_firewall_policy('5678')
        neutronclient.Client.show_firewall_policy('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_firewall_policy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_firewall_policy('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_firewall_policy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_firewall_policy('5678').AndRaise(
            exceptions.NeutronClientException(status_code=400))

        rsrc = self.create_firewall_policy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.firewall_policy: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_firewall_policy()
        neutronclient.Client.show_firewall_policy('5678').MultipleTimes(
        ).AndReturn(
            {'firewall_policy': {'audited': True, 'shared': True}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('audited'))
        self.assertIs(True, rsrc.FnGetAtt('shared'))
        self.m.VerifyAll()

    def test_attribute_failed(self):
        rsrc = self.create_firewall_policy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'subnet_id')
        self.assertEqual(
            'The Referenced Attribute (firewall_policy subnet_id) is '
            'incorrect.', six.text_type(error))
        self.m.VerifyAll()

    def test_update(self):
        rsrc = self.create_firewall_policy()
        neutronclient.Client.update_firewall_policy(
            '5678', {'firewall_policy': {'firewall_rules': ['3', '4']}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['firewall_rules'] = ['3', '4']
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.m.VerifyAll()


class FirewallRuleTest(common.HeatTestCase):

    def setUp(self):
        super(FirewallRuleTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_firewall_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_firewall_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'show_firewall_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'update_firewall_rule')
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_firewall_rule(self):
        neutronclient.Client.create_firewall_rule({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"}}
        ).AndReturn({'firewall_rule': {'id': '5678'}})

        snippet = template_format.parse(firewall_rule_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return firewall.FirewallRule(
            'firewall_rule', resource_defns['firewall_rule'], self.stack)

    def test_create(self):
        rsrc = self.create_firewall_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_validate_failed_with_string_None_protocol(self):
        snippet = template_format.parse(firewall_rule_template)
        stack = utils.parse_stack(snippet)
        rsrc = stack['firewall_rule']
        rsrc.t['Properties']['protocol'] = 'None'
        self.assertRaises(exception.StackValidationFailed, rsrc.validate)

    def test_create_with_protocol_any(self):
        neutronclient.Client.create_firewall_rule({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': None, 'enabled': True,
                'ip_version': "4"}}
        ).AndReturn({'firewall_rule': {'id': '5678'}})
        self.m.ReplayAll()

        snippet = template_format.parse(firewall_rule_template)
        stack = utils.parse_stack(snippet)
        rsrc = stack['firewall_rule']
        rsrc.t['Properties']['protocol'] = 'any'

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        neutronclient.Client.create_firewall_rule({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"}}
        ).AndRaise(exceptions.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(firewall_rule_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = firewall.FirewallRule(
            'firewall_rule', resource_defns['firewall_rule'], stack)

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.firewall_rule: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_firewall_rule('5678')
        neutronclient.Client.show_firewall_rule('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_firewall_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_firewall_rule('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_firewall_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_firewall_rule('5678').AndRaise(
            exceptions.NeutronClientException(status_code=400))

        rsrc = self.create_firewall_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.firewall_rule: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_firewall_rule()
        neutronclient.Client.show_firewall_rule('5678').MultipleTimes(
        ).AndReturn(
            {'firewall_rule': {'protocol': 'tcp', 'shared': True}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual('tcp', rsrc.FnGetAtt('protocol'))
        self.assertIs(True, rsrc.FnGetAtt('shared'))
        self.m.VerifyAll()

    def test_attribute_failed(self):
        rsrc = self.create_firewall_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'subnet_id')
        self.assertEqual(
            'The Referenced Attribute (firewall_rule subnet_id) is '
            'incorrect.', six.text_type(error))
        self.m.VerifyAll()

    def test_update(self):
        rsrc = self.create_firewall_rule()
        neutronclient.Client.update_firewall_rule(
            '5678', {'firewall_rule': {'protocol': 'icmp'}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['protocol'] = 'icmp'
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.m.VerifyAll()

    def test_update_protocol_to_any(self):
        rsrc = self.create_firewall_rule()
        neutronclient.Client.update_firewall_rule(
            '5678', {'firewall_rule': {'protocol': None}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        # update to 'any' protocol
        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['protocol'] = 'any'
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.m.VerifyAll()
