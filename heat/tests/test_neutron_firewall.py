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

from testtools import skipIf

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine.resources.neutron import firewall
from heat.engine import scheduler
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils

neutronclient = try_import('neutronclient.v2_0.client')

firewall_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test neutron firewall resource",
  "Parameters" : {},
  "Resources" : {
    "firewall": {
      "Type": "OS::Neutron::Firewall",
      "Properties": {
        "name": "test-firewall",
        "firewall_policy_id": "policy-id",
        "admin_state_up": True,
      }
    }
  }
}
'''

firewall_policy_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test neutron firewall policy resource",
  "Parameters" : {},
  "Resources" : {
    "firewall_policy": {
      "Type": "OS::Neutron::FirewallPolicy",
      "Properties": {
        "name": "test-firewall-policy",
        "shared": True,
        "audited": True,
        "firewall_rules": ['rule-id-1', 'rule-id-2'],
      }
    }
  }
}
'''

firewall_rule_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test neutron firewall rule resource",
  "Parameters" : {},
  "Resources" : {
    "firewall_rule": {
      "Type": "OS::Neutron::FirewallRule",
      "Properties": {
        "name": "test-firewall-rule",
        "shared": True,
        "protocol": "tcp",
        "action": "allow",
        "enabled": True,
        "ip_version": "4",
      }
    }
  }
}
'''


@skipIf(neutronclient is None, 'neutronclient unavailable')
class FirewallTest(HeatTestCase):

    def setUp(self):
        super(FirewallTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_firewall')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_firewall')
        self.m.StubOutWithMock(neutronclient.Client, 'show_firewall')
        self.m.StubOutWithMock(neutronclient.Client, 'update_firewall')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_firewall(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_firewall({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'firewall_policy_id': 'policy-id'}}
        ).AndReturn({'firewall': {'id': '5678'}})

        snippet = template_format.parse(firewall_template)
        stack = utils.parse_stack(snippet)
        return firewall.Firewall(
            'firewall', snippet['Resources']['firewall'], stack)

    def test_create(self):
        rsrc = self.create_firewall()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_firewall({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'firewall_policy_id': 'policy-id'}}
        ).AndRaise(firewall.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(firewall_template)
        stack = utils.parse_stack(snippet)
        rsrc = firewall.Firewall(
            'firewall', snippet['Resources']['firewall'], stack)

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_firewall('5678')
        neutronclient.Client.show_firewall('5678').AndRaise(
            firewall.NeutronClientException(status_code=404))

        rsrc = self.create_firewall()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_firewall('5678').AndRaise(
            firewall.NeutronClientException(status_code=404))

        rsrc = self.create_firewall()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_firewall('5678').AndRaise(
            firewall.NeutronClientException(status_code=400))

        rsrc = self.create_firewall()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_firewall()
        neutronclient.Client.show_firewall('5678').MultipleTimes(
        ).AndReturn(
            {'firewall': {'admin_state_up': True,
                          'firewall_policy_id': 'policy-id'}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
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
            'incorrect.', str(error))
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


@skipIf(neutronclient is None, 'neutronclient unavailable')
class FirewallPolicyTest(HeatTestCase):

    def setUp(self):
        super(FirewallPolicyTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_firewall_policy')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_firewall_policy')
        self.m.StubOutWithMock(neutronclient.Client, 'show_firewall_policy')
        self.m.StubOutWithMock(neutronclient.Client, 'update_firewall_policy')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_firewall_policy(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_firewall_policy({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']}}
        ).AndReturn({'firewall_policy': {'id': '5678'}})

        snippet = template_format.parse(firewall_policy_template)
        stack = utils.parse_stack(snippet)
        return firewall.FirewallPolicy(
            'firewall_policy', snippet['Resources']['firewall_policy'], stack)

    def test_create(self):
        rsrc = self.create_firewall_policy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_firewall_policy({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']}}
        ).AndRaise(firewall.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(firewall_policy_template)
        stack = utils.parse_stack(snippet)
        rsrc = firewall.FirewallPolicy(
            'firewall_policy', snippet['Resources']['firewall_policy'], stack)

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_firewall_policy('5678')
        neutronclient.Client.show_firewall_policy('5678').AndRaise(
            firewall.NeutronClientException(status_code=404))

        rsrc = self.create_firewall_policy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_firewall_policy('5678').AndRaise(
            firewall.NeutronClientException(status_code=404))

        rsrc = self.create_firewall_policy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_firewall_policy('5678').AndRaise(
            firewall.NeutronClientException(status_code=400))

        rsrc = self.create_firewall_policy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
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
            'incorrect.', str(error))
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


@skipIf(neutronclient is None, 'neutronclient unavailable')
class FirewallRuleTest(HeatTestCase):

    def setUp(self):
        super(FirewallRuleTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_firewall_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_firewall_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'show_firewall_rule')
        self.m.StubOutWithMock(neutronclient.Client, 'update_firewall_rule')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_firewall_rule(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_firewall_rule({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"}}
        ).AndReturn({'firewall_rule': {'id': '5678'}})

        snippet = template_format.parse(firewall_rule_template)
        stack = utils.parse_stack(snippet)
        return firewall.FirewallRule(
            'firewall_rule', snippet['Resources']['firewall_rule'], stack)

    def test_create(self):
        rsrc = self.create_firewall_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_firewall_rule({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"}}
        ).AndRaise(firewall.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(firewall_rule_template)
        stack = utils.parse_stack(snippet)
        rsrc = firewall.FirewallRule(
            'firewall_rule', snippet['Resources']['firewall_rule'], stack)

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_firewall_rule('5678')
        neutronclient.Client.show_firewall_rule('5678').AndRaise(
            firewall.NeutronClientException(status_code=404))

        rsrc = self.create_firewall_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_firewall_rule('5678').AndRaise(
            firewall.NeutronClientException(status_code=404))

        rsrc = self.create_firewall_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_firewall_rule('5678').AndRaise(
            firewall.NeutronClientException(status_code=400))

        rsrc = self.create_firewall_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
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
            'incorrect.', str(error))
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
