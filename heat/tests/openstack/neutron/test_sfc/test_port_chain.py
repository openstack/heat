#
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

import mock

from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron.sfc import port_chain
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

port_chain_template = {
    'heat_template_version': '2015-04-30',
    'resources': {
        'test_resource': {
            'type': 'OS::Neutron::PortChain',
            'properties': {
                'name': 'test_port_chain',
                'description': 'port_chain_desc',
                'port_pair_groups': ['port_pair_group_1'],
                'flow_classifiers': ['flow_classifier1'],
                'chain_parameters': {"correlation": 'mpls'}
                }
            }
        }
    }


class PortChainTest(common.HeatTestCase):

    def setUp(self):
        super(PortChainTest, self).setUp()
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack',
            template.Template(port_chain_template)
        )
        self.test_resource = self.stack['test_resource']

        self.test_client_plugin = mock.MagicMock()

        self.test_resource.client_plugin = mock.MagicMock(
            return_value=self.test_client_plugin)

        self.test_client = mock.MagicMock()
        self.test_resource.client = mock.MagicMock(
            return_value=self.test_client)

        self.test_client_plugin.get_notification = mock.MagicMock(
            return_value='sample_notification')

        self.patchobject(self.test_client_plugin, 'resolve_ext_resource'
                         ).return_value = ('port_pair_group_1')

        self.patchobject(self.test_client_plugin, 'resolve_ext_resource'
                         ).return_value = ('flow_classifier1')

    def test_resource_mapping(self):
        mapping = port_chain.resource_mapping()
        self.assertEqual(port_chain.PortChain,
                         mapping['OS::Neutron::PortChain'])

    def _get_mock_resource(self):
        value = mock.MagicMock()
        value.id = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
        return value

    def test_resource_handle_create(self):
        mock_pc_create = self.test_client_plugin.create_ext_resource
        mock_resource = self._get_mock_resource()
        mock_pc_create.return_value = mock_resource

    # validate the properties
        self.assertEqual(
            'test_port_chain',
            self.test_resource.properties.get(
                port_chain.PortChain.NAME))
        self.assertEqual(
            'port_chain_desc',
            self.test_resource.properties.get(
                port_chain.PortChain.DESCRIPTION))
        self.assertEqual(
            ['port_pair_group_1'],
            self.test_resource.properties.get(
                port_chain.PortChain.PORT_PAIR_GROUPS))
        self.assertEqual(
            ['flow_classifier1'],
            self.test_resource.properties.get(
                port_chain.PortChain.FLOW_CLASSIFIERS))
        self.assertEqual(
            {"correlation": 'mpls'},
            self.test_resource.properties.get(
                port_chain.PortChain.CHAIN_PARAMETERS))

        self.test_resource.data_set = mock.Mock()
        self.test_resource.handle_create()

        mock_pc_create.assert_called_once_with(
            'port_chain',
            {
                'name': 'test_port_chain',
                'description': 'port_chain_desc',
                'port_pair_groups': ['port_pair_group_1'],
                'flow_classifiers': ['flow_classifier1'],
                'chain_parameters': {"correlation": 'mpls'}}
        )

    def delete_portchain(self):
        mock_pc_delete = self.test_client_plugin.delete_ext_resource
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_pc_delete.return_value = None
        self.assertIsNone(self.test_resource.handle_delete())
        mock_pc_delete.assert_called_once_with(
            'port_chain', self.test_resource.resource_id)

    def delete_portchain_resource_id_is_none(self):
        self.test_resource.resource_id = None
        self.assertIsNone(self.test_resource.handle_delete())
        self.assertEqual(0, self.test_client_plugin.
                         delete_ext_resource.call_count)

    def test_resource_handle_delete_not_found(self):
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_pc_delete = self.test_client_plugin.delete_ext_resource
        mock_pc_delete.side_effect = self.test_client_plugin.NotFound
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resource_show_resource(self):
        mock_pc_get = self.test_client_plugin.show_ext_resource
        mock_pc_get.return_value = None
        self.assertIsNone(self.test_resource._show_resource(),
                          'Failed to show resource')

    def test_resource_handle_update(self):
        mock_ppg_patch = self.test_client_plugin.update_ext_resource
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        prop_diff = {
            'name': 'name-updated',
            'description': 'description-updated',
            'port_pair_groups': ['port_pair_group_2'],
            'flow_classifiers': ['flow_classifier2'],
        }
        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        mock_ppg_patch.assert_called_once_with(
            'port_chain',
            {
                'name': 'name-updated',
                'description': 'description-updated',
                'port_pair_groups': ['port_pair_group_2'],
                'flow_classifiers': ['flow_classifier2'],
            },  self.test_resource.resource_id)
