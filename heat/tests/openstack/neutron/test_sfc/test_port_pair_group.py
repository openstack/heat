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
from heat.engine.resources.openstack.neutron.sfc import port_pair_group
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

sample_template = {
    'heat_template_version': '2016-04-08',
    'resources': {
        'test_resource': {
            'type': 'OS::Neutron::PortPairGroup',
            'properties': {
                'name': 'test_port_pair_group',
                'description': 'desc',
                'port_pairs':  ['port1']
                }
            }
        }
    }


class PortPairGroupTest(common.HeatTestCase):

    def setUp(self):
        super(PortPairGroupTest, self).setUp()

        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack',
            template.Template(sample_template)
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

        self.patchobject(self.test_client_plugin,
                         'resolve_ext_resource').return_value = ('port1')

    def test_resource_mapping(self):
        mapping = port_pair_group.resource_mapping()
        self.assertEqual(port_pair_group.PortPairGroup,
                         mapping['OS::Neutron::PortPairGroup'])

    def _get_mock_resource(self):
        value = mock.MagicMock()
        value.id = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
        return value

    def _resolve_ext_resource(self):
        value = mock.MagicMock()
        value.id = '[port1]'
        return value.id

    def test_resource_handle_create(self):
        mock_ppg_create = self.test_client_plugin.create_ext_resource
        mock_resource = self._get_mock_resource()
        mock_ppg_create.return_value = mock_resource

    # validate the properties
        self.assertEqual(
            'test_port_pair_group',
            self.test_resource.properties.get(
                port_pair_group.PortPairGroup.NAME))
        self.assertEqual(
            'desc',
            self.test_resource.properties.get(
                port_pair_group.PortPairGroup.DESCRIPTION))
        self.assertEqual(
            ['port1'],
            self.test_resource.properties.get(
                port_pair_group.PortPairGroup.PORT_PAIRS))

        self.test_resource.data_set = mock.Mock()
        self.test_resource.handle_create()

        mock_ppg_create.assert_called_once_with(
            'port_pair_group',
            {
                'name': 'test_port_pair_group',
                'description': 'desc',
                'port_pairs': ['port1'],
            }
        )

    def test_resource_handle_delete(self):
        mock_ppg_delete = self.test_client_plugin.delete_ext_resource
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_ppg_delete.return_value = None
        self.assertIsNone(self.test_resource.handle_delete())
        mock_ppg_delete.assert_called_once_with(
            'port_pair_group', self.test_resource.resource_id)

    def test_resource_handle_delete_resource_id_is_none(self):
        self.test_resource.resource_id = None
        self.assertIsNone(self.test_resource.handle_delete())
        self.assertEqual(0, self.test_client_plugin.
                         delete_ext_resource.call_count)

    def test_resource_handle_delete_not_found(self):
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_ppg_delete = self.test_client_plugin.delete_ext_resource
        mock_ppg_delete.side_effect = self.test_client_plugin.NotFound
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resource_show_resource(self):
        mock_ppg_get = self.test_client_plugin.show_ext_resource
        mock_ppg_get.return_value = {}
        self.assertEqual({},
                         self.test_resource._show_resource(),
                         'Failed to show resource')

    def test_resource_handle_update(self):
        mock_ppg_patch = self.test_client_plugin.update_ext_resource
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        prop_diff = {
            'name': 'name-updated',
            'description': 'description-updated',
        }
        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        mock_ppg_patch.assert_called_once_with(
            'port_pair_group',
            {
                'name': 'name-updated',
                'description': 'description-updated',
            },  self.test_resource.resource_id)

    def test_resource_handle_update_port_pairs(self):
        self.patchobject(self.test_client_plugin,
                         'resolve_ext_resource').return_value = ('port2')
        mock_ppg_patch = self.test_client_plugin.update_ext_resource
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {
            port_pair_group.PortPairGroup.NAME:
                'name',
            port_pair_group.PortPairGroup.DESCRIPTION:
                'description',
            port_pair_group.PortPairGroup.PORT_PAIRS:
                ['port2'],
            }
        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        mock_ppg_patch.assert_called_once_with(
            'port_pair_group',
            {
                'name': 'name',
                'description': 'description',
                'port_pairs': ['port2'],
            },  self.test_resource.resource_id)
