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

from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine import rsrc_defn
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

qos_policy_template = '''
heat_template_version: 2016-04-08
description: This template to define a neutron qos policy.
resources:
  my_qos_policy:
    type: OS::Neutron::QoSPolicy
    properties:
      description: a policy for test
      shared: true
      tenant_id: d66c74c01d6c41b9846088c1ad9634d0
'''

bandwidth_limit_rule_template = '''
heat_template_version: 2016-04-08
description: This template to define a neutron bandwidth limit rule.
resources:
  my_bandwidth_limit_rule:
    type: OS::Neutron::QoSBandwidthLimitRule
    properties:
      policy: 477e8273-60a7-4c41-b683-fdb0bc7cd151
      max_kbps: 1000
      max_burst_kbps: 1000
      tenant_id: d66c74c01d6c41b9846088c1ad9634d0
'''

dscp_marking_rule_template = '''
heat_template_version: 2016-04-08
description: This template to define a neutron DSCP marking rule.
resources:
  my_dscp_marking_rule:
    type: OS::Neutron::QoSDscpMarkingRule
    properties:
      policy: 477e8273-60a7-4c41-b683-fdb0bc7cd151
      dscp_mark: 16
      tenant_id: d66c74c01d6c41b9846088c1ad9634d0
'''


class NeutronQoSPolicyTest(common.HeatTestCase):
    def setUp(self):
        super(NeutronQoSPolicyTest, self).setUp()

        self.ctx = utils.dummy_context()
        tpl = template_format.parse(qos_policy_template)
        self.stack = stack.Stack(
            self.ctx,
            'neutron_qos_policy_test',
            template.Template(tpl)
        )

        self.neutronclient = mock.MagicMock()
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)
        self.my_qos_policy = self.stack['my_qos_policy']
        self.my_qos_policy.client = mock.MagicMock(
            return_value=self.neutronclient)
        self.patchobject(self.my_qos_policy, 'physical_resource_name',
                         return_value='test_policy')

    def test_qos_policy_handle_create(self):
        policy = {
            'policy': {
                'description': 'a policy for test',
                'id': '9c1eb3fe-7bba-479d-bd43-1d497e53c384',
                'rules': [],
                'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0',
                'shared': True
            }
        }
        create_props = {'name': 'test_policy',
                        'description': 'a policy for test',
                        'shared': True,
                        'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0'}

        self.neutronclient.create_qos_policy.return_value = policy
        self.my_qos_policy.handle_create()
        self.assertEqual('9c1eb3fe-7bba-479d-bd43-1d497e53c384',
                         self.my_qos_policy.resource_id)
        self.neutronclient.create_qos_policy.assert_called_once_with(
            {'policy': create_props}
        )

    def test_qos_policy_handle_delete(self):
        policy_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.my_qos_policy.resource_id = policy_id
        self.neutronclient.delete_qos_policy.return_value = None

        self.assertIsNone(self.my_qos_policy.handle_delete())
        self.neutronclient.delete_qos_policy.assert_called_once_with(
            self.my_qos_policy.resource_id)

    def test_qos_policy_handle_delete_not_found(self):
        policy_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.my_qos_policy.resource_id = policy_id
        not_found = self.neutronclient.NotFound
        self.neutronclient.delete_qos_policy.side_effect = not_found

        self.assertIsNone(self.my_qos_policy.handle_delete())
        self.neutronclient.delete_qos_policy.assert_called_once_with(
            self.my_qos_policy.resource_id)

    def test_qos_policy_handle_delete_resource_id_is_none(self):
        self.my_qos_policy.resource_id = None
        self.assertIsNone(self.my_qos_policy.handle_delete())
        self.assertEqual(0, self.neutronclient.delete_qos_policy.call_count)

    def test_qos_policy_handle_update(self):
        policy_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.my_qos_policy.resource_id = policy_id

        props = {
            'name': 'test_policy',
            'description': 'test',
            'shared': False
        }
        prop_dict = props.copy()
        update_snippet = rsrc_defn.ResourceDefinition(
            self.my_qos_policy.name,
            self.my_qos_policy.type(),
            props)

        # with name
        self.my_qos_policy.handle_update(json_snippet=update_snippet,
                                         tmpl_diff={},
                                         prop_diff=props)
        # without name
        props['name'] = None
        self.my_qos_policy.handle_update(json_snippet=update_snippet,
                                         tmpl_diff={},
                                         prop_diff=props)

        self.assertEqual(2, self.neutronclient.update_qos_policy.call_count)
        self.neutronclient.update_qos_policy.assert_called_with(
            policy_id, {'policy': prop_dict})

    def test_qos_policy_get_attr(self):
        self.my_qos_policy.resource_id = 'test policy'
        policy = {
            'policy': {
                'name': 'test_policy',
                'description': 'a policy for test',
                'id': '9c1eb3fe-7bba-479d-bd43-1d497e53c384',
                'rules': [],
                'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0',
                'shared': True
            }
        }
        self.neutronclient.show_qos_policy.return_value = policy

        self.assertEqual([], self.my_qos_policy.FnGetAtt('rules'))
        self.assertEqual(policy['policy'],
                         self.my_qos_policy.FnGetAtt('show'))
        self.neutronclient.show_qos_policy.assert_has_calls(
            [mock.call(self.my_qos_policy.resource_id)] * 2)


class NeutronQoSBandwidthLimitRuleTest(common.HeatTestCase):
    def setUp(self):
        super(NeutronQoSBandwidthLimitRuleTest, self).setUp()

        self.ctx = utils.dummy_context()
        tpl = template_format.parse(bandwidth_limit_rule_template)
        self.stack = stack.Stack(
            self.ctx,
            'neutron_bandwidth_limit_rule_test',
            template.Template(tpl)
        )

        self.neutronclient = mock.MagicMock()
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)
        self.bandwidth_limit_rule = self.stack['my_bandwidth_limit_rule']
        self.bandwidth_limit_rule.client = mock.MagicMock(
            return_value=self.neutronclient)
        self.find_mock = self.patchobject(
            neutron.neutronV20,
            'find_resourceid_by_name_or_id')
        self.policy_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.find_mock.return_value = self.policy_id

    def test_rule_handle_create(self):
        rule = {
            'bandwidth_limit_rule': {
                'id': 'cf0eab12-ef8b-4a62-98d0-70576583c17a',
                'max_kbps': 1000,
                'max_burst_kbps': 1000,
                'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0'
            }
        }

        create_props = {'max_kbps': 1000,
                        'max_burst_kbps': 1000,
                        'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0'}
        self.neutronclient.create_bandwidth_limit_rule.return_value = rule

        self.bandwidth_limit_rule.handle_create()
        self.assertEqual('cf0eab12-ef8b-4a62-98d0-70576583c17a',
                         self.bandwidth_limit_rule.resource_id)
        self.neutronclient.create_bandwidth_limit_rule.assert_called_once_with(
            self.policy_id,
            {'bandwidth_limit_rule': create_props})

    def test_rule_handle_delete(self):
        rule_id = 'cf0eab12-ef8b-4a62-98d0-70576583c17a'
        self.bandwidth_limit_rule.resource_id = rule_id
        self.neutronclient.delete_bandwidth_limit_rule.return_value = None

        self.assertIsNone(self.bandwidth_limit_rule.handle_delete())
        self.neutronclient.delete_bandwidth_limit_rule.assert_called_once_with(
            rule_id, self.policy_id)

    def test_rule_handle_delete_not_found(self):
        rule_id = 'cf0eab12-ef8b-4a62-98d0-70576583c17a'
        self.bandwidth_limit_rule.resource_id = rule_id
        not_found = self.neutronclient.NotFound
        self.neutronclient.delete_bandwidth_limit_rule.side_effect = not_found

        self.assertIsNone(self.bandwidth_limit_rule.handle_delete())
        self.neutronclient.delete_bandwidth_limit_rule.assert_called_once_with(
            rule_id, self.policy_id)

    def test_rule_handle_delete_resource_id_is_none(self):
        self.bandwidth_limit_rule.resource_id = None
        self.assertIsNone(self.bandwidth_limit_rule.handle_delete())
        self.assertEqual(0,
                         self.neutronclient.bandwidth_limit_rule.call_count)

    def test_rule_handle_update(self):
        rule_id = 'cf0eab12-ef8b-4a62-98d0-70576583c17a'
        self.bandwidth_limit_rule.resource_id = rule_id

        prop_diff = {
            'max_kbps': 500,
            'max_burst_kbps': 400
        }

        self.bandwidth_limit_rule.handle_update(
            json_snippet={},
            tmpl_diff={},
            prop_diff=prop_diff)

        self.neutronclient.update_bandwidth_limit_rule.assert_called_once_with(
            rule_id,
            self.policy_id,
            {'bandwidth_limit_rule': prop_diff})

    def test_rule_get_attr(self):
        self.bandwidth_limit_rule.resource_id = 'test rule'
        rule = {
            'bandwidth_limit_rule': {
                'id': 'cf0eab12-ef8b-4a62-98d0-70576583c17a',
                'max_kbps': 1000,
                'max_burst_kbps': 1000,
                'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0'
            }
        }
        self.neutronclient.show_bandwidth_limit_rule.return_value = rule

        self.assertEqual(rule['bandwidth_limit_rule'],
                         self.bandwidth_limit_rule.FnGetAtt('show'))

        self.neutronclient.show_bandwidth_limit_rule.assert_called_once_with(
            self.bandwidth_limit_rule.resource_id, self.policy_id)


class NeutronQoSDscpMarkingRuleTest(common.HeatTestCase):
    def setUp(self):
        super(NeutronQoSDscpMarkingRuleTest, self).setUp()

        self.ctx = utils.dummy_context()
        tpl = template_format.parse(dscp_marking_rule_template)
        self.stack = stack.Stack(
            self.ctx,
            'neutron_dscp_marking_rule_test',
            template.Template(tpl)
        )

        self.neutronclient = mock.MagicMock()
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)
        self.dscp_marking_rule = self.stack['my_dscp_marking_rule']
        self.dscp_marking_rule.client = mock.MagicMock(
            return_value=self.neutronclient)
        self.find_mock = self.patchobject(
            neutron.neutronV20,
            'find_resourceid_by_name_or_id')
        self.policy_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.find_mock.return_value = self.policy_id

    def test_rule_handle_create(self):
        rule = {
            'dscp_marking_rule': {
                'id': 'cf0eab12-ef8b-4a62-98d0-70576583c17a',
                'dscp_mark': 16,
                'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0'
            }
        }

        create_props = {'dscp_mark': 16,
                        'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0'}
        self.neutronclient.create_dscp_marking_rule.return_value = rule

        self.dscp_marking_rule.handle_create()
        self.assertEqual('cf0eab12-ef8b-4a62-98d0-70576583c17a',
                         self.dscp_marking_rule.resource_id)
        self.neutronclient.create_dscp_marking_rule.assert_called_once_with(
            self.policy_id,
            {'dscp_marking_rule': create_props})

    def test_rule_handle_delete(self):
        rule_id = 'cf0eab12-ef8b-4a62-98d0-70576583c17a'
        self.dscp_marking_rule.resource_id = rule_id
        self.neutronclient.delete_dscp_marking_rule.return_value = None

        self.assertIsNone(self.dscp_marking_rule.handle_delete())
        self.neutronclient.delete_dscp_marking_rule.assert_called_once_with(
            rule_id, self.policy_id)

    def test_rule_handle_delete_not_found(self):
        rule_id = 'cf0eab12-ef8b-4a62-98d0-70576583c17a'
        self.dscp_marking_rule.resource_id = rule_id
        not_found = self.neutronclient.NotFound
        self.neutronclient.delete_dscp_marking_rule.side_effect = not_found

        self.assertIsNone(self.dscp_marking_rule.handle_delete())
        self.neutronclient.delete_dscp_marking_rule.assert_called_once_with(
            rule_id, self.policy_id)

    def test_rule_handle_delete_resource_id_is_none(self):
        self.dscp_marking_rule.resource_id = None
        self.assertIsNone(self.dscp_marking_rule.handle_delete())
        self.assertEqual(0,
                         self.neutronclient.dscp_marking_rule.call_count)

    def test_rule_handle_update(self):
        rule_id = 'cf0eab12-ef8b-4a62-98d0-70576583c17a'
        self.dscp_marking_rule.resource_id = rule_id

        prop_diff = {
            'dscp_mark': 8
        }

        self.dscp_marking_rule.handle_update(
            json_snippet={},
            tmpl_diff={},
            prop_diff=prop_diff)

        self.neutronclient.update_dscp_marking_rule.assert_called_once_with(
            rule_id,
            self.policy_id,
            {'dscp_marking_rule': prop_diff})

    def test_rule_get_attr(self):
        self.dscp_marking_rule.resource_id = 'test rule'
        rule = {
            'dscp_marking_rule': {
                'id': 'cf0eab12-ef8b-4a62-98d0-70576583c17a',
                'dscp_mark': 8,
                'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0'
            }
        }
        self.neutronclient.show_dscp_marking_rule.return_value = rule

        self.assertEqual(rule['dscp_marking_rule'],
                         self.dscp_marking_rule.FnGetAtt('show'))

        self.neutronclient.show_dscp_marking_rule.assert_called_once_with(
            self.dscp_marking_rule.resource_id, self.policy_id)
