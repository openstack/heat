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
from neutronclient.common import exceptions
from neutronclient.v2_0 import client as neutronclient
from oslo_config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import firewall
from heat.engine import rsrc_defn
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
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_firewall(self, value_specs=True):
        snippet = template_format.parse(firewall_template)
        self.mockclient.create_firewall.return_value = {
            'firewall': {'id': '5678'}
        }
        if not value_specs:
            del snippet['resources']['firewall']['properties']['value_specs']

        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.fw_props = snippet['resources']['firewall']['properties']
        return firewall.Firewall(
            'firewall', resource_defns['firewall'], self.stack)

    def test_create(self):
        rsrc = self.create_firewall()
        self.mockclient.show_firewall.return_value = {
            'firewall': {'status': 'ACTIVE'}
        }
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.show_firewall.assert_called_once_with('5678')

    def test_create_failed_error_status(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        rsrc = self.create_firewall()
        self.mockclient.show_firewall.side_effect = [
            {'firewall': {'status': 'PENDING_CREATE'}},
            {'firewall': {'status': 'ERROR'}},
        ]

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'ResourceInError: resources.firewall: '
            'Went to status ERROR due to "Error in Firewall"',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.show_firewall.assert_called_with('5678')

    def test_create_failed(self):
        self.mockclient.create_firewall.side_effect = (
            exceptions.NeutronClientException())

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

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })

    def test_delete(self):
        rsrc = self.create_firewall()
        self.mockclient.show_firewall.side_effect = [
            {'firewall': {'status': 'ACTIVE'}},
            exceptions.NeutronClientException(status_code=404),
        ]
        self.mockclient.delete_firewall.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.delete_firewall.assert_called_once_with('5678')
        self.mockclient.show_firewall.assert_called_with('5678')

    def test_delete_already_gone(self):
        rsrc = self.create_firewall()
        self.mockclient.show_firewall.return_value = {
            'firewall': {'status': 'ACTIVE'}
        }
        self.mockclient.delete_firewall.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.delete_firewall.assert_called_once_with('5678')
        self.mockclient.show_firewall.assert_called_once_with('5678')

    def test_delete_failed(self):
        rsrc = self.create_firewall()
        self.mockclient.show_firewall.return_value = {
            'firewall': {'status': 'ACTIVE'}
        }
        self.mockclient.delete_firewall.side_effect = (
            exceptions.NeutronClientException(status_code=400))

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.firewall: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.delete_firewall.assert_called_once_with('5678')
        self.mockclient.show_firewall.assert_called_once_with('5678')

    def test_attribute(self):
        rsrc = self.create_firewall()
        self.mockclient.show_firewall.return_value = {
            'firewall': {
                'status': 'ACTIVE',
                'admin_state_up': True,
                'firewall_policy_id': 'policy-id',
                'shared': True,
            }
        }

        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual('This attribute is currently unsupported in neutron '
                         'firewall resource.', rsrc.FnGetAtt('shared'))
        self.assertEqual('policy-id', rsrc.FnGetAtt('firewall_policy_id'))

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.show_firewall.assert_called_with('5678')

    def test_attribute_failed(self):
        rsrc = self.create_firewall()
        self.mockclient.show_firewall.return_value = {
            'firewall': {'status': 'ACTIVE'}
        }

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'subnet_id')
        self.assertEqual(
            'The Referenced Attribute (firewall subnet_id) is '
            'incorrect.', six.text_type(error))

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.show_firewall.assert_called_once_with('5678')

    def test_update(self):
        rsrc = self.create_firewall()
        self.mockclient.show_firewall.return_value = {
            'firewall': {'status': 'ACTIVE'}
        }
        self.mockclient.update_firewall.return_value = None

        scheduler.TaskRunner(rsrc.create)()

        props = self.fw_props.copy()
        props['admin_state_up'] = False
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.show_firewall.assert_called_once_with('5678')
        self.mockclient.update_firewall.assert_called_once_with(
            '5678', {'firewall': {'admin_state_up': False}})

    def test_update_with_value_specs(self):
        rsrc = self.create_firewall(value_specs=False)
        self.mockclient.show_firewall.return_value = {
            'firewall': {'status': 'ACTIVE'}
        }

        scheduler.TaskRunner(rsrc.create)()
        prop_diff = {
            'value_specs': {
                'router_ids': ['router_1', 'router_2']
            }
        }
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      prop_diff)
        rsrc.handle_update(update_snippet, {}, prop_diff)

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.show_firewall.assert_called_once_with('5678')
        self.mockclient.update_firewall.assert_called_once_with(
            '5678', {'firewall': {'router_ids': ['router_1',
                                                 'router_2']}})

    def test_get_live_state(self):
        rsrc = self.create_firewall(value_specs=True)
        self.mockclient.show_firewall.return_value = {
            'firewall': {
                'status': 'ACTIVE',
                'router_ids': ['router_1', 'router_2'],
                'name': 'firewall-firewall-pwakkqdrcl7z',
                'admin_state_up': True,
                'tenant_id': 'df49ea64e87c43a792a510698364f03e',
                'firewall_policy_id': '680eb26d-3eea-40be-b484-1476e4c7c1b3',
                'id': '11425cd4-41b6-4fd4-97aa-17629c63de61',
                'description': ''
            }
        }

        scheduler.TaskRunner(rsrc.create)()

        reality = rsrc.get_live_state(rsrc.properties)
        expected = {
            'value_specs': {
                'router_ids': ['router_1', 'router_2']
            },
            'name': 'firewall-firewall-pwakkqdrcl7z',
            'admin_state_up': True,
            'firewall_policy_id': '680eb26d-3eea-40be-b484-1476e4c7c1b3',
            'description': ''
        }

        self.assertEqual(expected, reality)

        self.mockclient.create_firewall.assert_called_once_with({
            'firewall': {
                'name': 'test-firewall', 'admin_state_up': True,
                'router_ids': ['router_1', 'router_2'],
                'firewall_policy_id': 'policy-id', 'shared': True
            }
        })
        self.mockclient.show_firewall.assert_called_with('5678')


class FirewallPolicyTest(common.HeatTestCase):

    def setUp(self):
        super(FirewallPolicyTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_firewall_policy(self):
        self.mockclient.create_firewall_policy.return_value = {
            'firewall_policy': {'id': '5678'}
        }

        snippet = template_format.parse(firewall_policy_template)
        self.stack = utils.parse_stack(snippet)
        self.tmpl = snippet
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return firewall.FirewallPolicy(
            'firewall_policy', resource_defns['firewall_policy'], self.stack)

    def test_create(self):
        rsrc = self.create_firewall_policy()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall_policy.assert_called_once_with({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']
            }
        })

    def test_create_failed(self):
        self.mockclient.create_firewall_policy.side_effect = (
            exceptions.NeutronClientException())

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

        self.mockclient.create_firewall_policy.assert_called_once_with({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']
            }
        })

    def test_delete(self):
        rsrc = self.create_firewall_policy()
        self.mockclient.delete_firewall_policy.return_value = None
        self.mockclient.show_firewall_policy.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall_policy.assert_called_once_with({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']
            }
        })
        self.mockclient.delete_firewall_policy.assert_called_once_with('5678')
        self.mockclient.show_firewall_policy.assert_called_once_with('5678')

    def test_delete_already_gone(self):
        rsrc = self.create_firewall_policy()
        self.mockclient.delete_firewall_policy.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall_policy.assert_called_once_with({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']
            }
        })
        self.mockclient.delete_firewall_policy.assert_called_once_with('5678')
        self.mockclient.show_firewall_policy.assert_not_called()

    def test_delete_failed(self):
        rsrc = self.create_firewall_policy()
        self.mockclient.delete_firewall_policy.side_effect = (
            exceptions.NeutronClientException(status_code=400))

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.firewall_policy: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_firewall_policy.assert_called_once_with({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']
            }
        })
        self.mockclient.delete_firewall_policy.assert_called_once_with('5678')
        self.mockclient.show_firewall_policy.assert_not_called()

    def test_attribute(self):
        rsrc = self.create_firewall_policy()
        self.mockclient.show_firewall_policy.return_value = {
            'firewall_policy': {'audited': True, 'shared': True}
        }

        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('audited'))
        self.assertIs(True, rsrc.FnGetAtt('shared'))

        self.mockclient.create_firewall_policy.assert_called_once_with({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']
            }
        })
        self.mockclient.show_firewall_policy.assert_called_with('5678')

    def test_attribute_failed(self):
        rsrc = self.create_firewall_policy()

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'subnet_id')
        self.assertEqual(
            'The Referenced Attribute (firewall_policy subnet_id) is '
            'incorrect.', six.text_type(error))

        self.mockclient.create_firewall_policy.assert_called_once_with({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']
            }
        })
        self.mockclient.show_firewall_policy.assert_not_called()

    def test_update(self):
        rsrc = self.create_firewall_policy()
        self.mockclient.update_firewall_policy.return_value = None

        scheduler.TaskRunner(rsrc.create)()

        props = self.tmpl['resources']['firewall_policy']['properties'].copy()
        props['firewall_rules'] = ['3', '4']
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.mockclient.create_firewall_policy.assert_called_once_with({
            'firewall_policy': {
                'name': 'test-firewall-policy', 'shared': True,
                'audited': True, 'firewall_rules': ['rule-id-1', 'rule-id-2']
            }
        })
        self.mockclient.update_firewall_policy.assert_called_once_with(
            '5678', {'firewall_policy': {'firewall_rules': ['3', '4']}})


class FirewallRuleTest(common.HeatTestCase):

    def setUp(self):
        super(FirewallRuleTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_firewall_rule(self):
        self.mockclient.create_firewall_rule.return_value = {
            'firewall_rule': {'id': '5678'}
        }

        snippet = template_format.parse(firewall_rule_template)
        self.stack = utils.parse_stack(snippet)
        self.tmpl = snippet
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return firewall.FirewallRule(
            'firewall_rule', resource_defns['firewall_rule'], self.stack)

    def test_create(self):
        rsrc = self.create_firewall_rule()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"
            }
        })

    def test_validate_failed_with_string_None_protocol(self):
        snippet = template_format.parse(firewall_rule_template)
        stack = utils.parse_stack(snippet)
        rsrc = stack['firewall_rule']
        props = dict(rsrc.properties)
        props['protocol'] = 'None'
        rsrc.t = rsrc.t.freeze(properties=props)
        rsrc.reparse()
        self.assertRaises(exception.StackValidationFailed, rsrc.validate)

    def test_create_with_protocol_any(self):
        self.mockclient.create_firewall_rule.return_value = {
            'firewall_rule': {'id': '5678'}
        }

        snippet = template_format.parse(firewall_rule_template)
        snippet['resources']['firewall_rule']['properties']['protocol'] = 'any'
        stack = utils.parse_stack(snippet)
        rsrc = stack['firewall_rule']

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': None, 'enabled': True,
                'ip_version': "4"
            }
        })

    def test_create_failed(self):
        self.mockclient.create_firewall_rule.side_effect = (
            exceptions.NeutronClientException())

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

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"
            }
        })

    def test_delete(self):
        rsrc = self.create_firewall_rule()
        self.mockclient.delete_firewall_rule.return_value = None
        self.mockclient.show_firewall_rule.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"
            }
        })
        self.mockclient.delete_firewall_rule.assert_called_once_with('5678')
        self.mockclient.show_firewall_rule.assert_called_once_with('5678')

    def test_delete_already_gone(self):
        rsrc = self.create_firewall_rule()
        self.mockclient.delete_firewall_rule.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"
            }
        })
        self.mockclient.delete_firewall_rule.assert_called_once_with('5678')
        self.mockclient.show_firewall_rule.assert_not_called()

    def test_delete_failed(self):
        rsrc = self.create_firewall_rule()
        self.mockclient.delete_firewall_rule.side_effect = (
            exceptions.NeutronClientException(status_code=400))

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.firewall_rule: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"
            }
        })
        self.mockclient.delete_firewall_rule.assert_called_once_with('5678')
        self.mockclient.show_firewall_rule.assert_not_called()

    def test_attribute(self):
        rsrc = self.create_firewall_rule()
        self.mockclient.show_firewall_rule.return_value = {
            'firewall_rule': {'protocol': 'tcp', 'shared': True}
        }

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual('tcp', rsrc.FnGetAtt('protocol'))
        self.assertIs(True, rsrc.FnGetAtt('shared'))

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"
            }
        })
        self.mockclient.show_firewall_rule.assert_called_with('5678')

    def test_attribute_failed(self):
        rsrc = self.create_firewall_rule()

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'subnet_id')
        self.assertEqual(
            'The Referenced Attribute (firewall_rule subnet_id) is '
            'incorrect.', six.text_type(error))

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"
            }
        })
        self.mockclient.show_firewall_rule.assert_not_called()

    def test_update(self):
        rsrc = self.create_firewall_rule()
        self.mockclient.update_firewall_rule.return_value = None

        scheduler.TaskRunner(rsrc.create)()

        props = self.tmpl['resources']['firewall_rule']['properties'].copy()
        props['protocol'] = 'icmp'
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"
            }
        })
        self.mockclient.update_firewall_rule.assert_called_once_with(
            '5678', {'firewall_rule': {'protocol': 'icmp'}})

    def test_update_protocol_to_any(self):
        rsrc = self.create_firewall_rule()
        self.mockclient.update_firewall_rule.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        # update to 'any' protocol
        props = self.tmpl['resources']['firewall_rule']['properties'].copy()
        props['protocol'] = 'any'
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.mockclient.create_firewall_rule.assert_called_once_with({
            'firewall_rule': {
                'name': 'test-firewall-rule', 'shared': True,
                'action': 'allow', 'protocol': 'tcp', 'enabled': True,
                'ip_version': "4"
            }
        })
        self.mockclient.update_firewall_rule.assert_called_once_with(
            '5678', {'firewall_rule': {'protocol': None}})
