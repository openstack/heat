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
from heat.engine.resources.openstack.neutron import qos
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
      name: test_policy
      description: a policy for test
      shared: true
      tenant_id: d66c74c01d6c41b9846088c1ad9634d0
'''


class NeutronQoSPolicyTest(common.HeatTestCase):
    def setUp(self):
        super(NeutronQoSPolicyTest, self).setUp()

        utils.setup_dummy_db()
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

    def test_resource_mapping(self):
        mapping = qos.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(qos.QoSPolicy, mapping['OS::Neutron::QoSPolicy'])
        self.assertIsInstance(self.my_qos_policy, qos.QoSPolicy)

    def test_qos_policy_handle_create(self):
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
            'name': 'new_name',
            'description': 'test',
            'shared': False
        }

        update_snippet = rsrc_defn.ResourceDefinition(
            self.my_qos_policy.name,
            self.my_qos_policy.type(),
            props)

        self.my_qos_policy.handle_update(json_snippet=update_snippet,
                                         tmpl_diff={},
                                         prop_diff=props)

        self.neutronclient.update_qos_policy.assert_called_once_with(
            policy_id, {'policy': props})

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
