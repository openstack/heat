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

from heat.engine.resources.openstack.neutron.taas import tap_flow
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

sample_template = {
    'heat_template_version': '2016-04-08',
    'resources': {
        'test_resource': {
            'type': 'OS::Neutron::TaaS::TapFlow',
            'properties': {
                'name': 'test_tap_flow',
                'description': 'desc',
                'port':  '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'tap_service':  '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'direction': 'BOTH',
                'vlan_filter': '1-5,9,18,27-30,99-108,4000-4095'
            }
        }
    }
}

RESOURCE_TYPE = 'OS::Neutron::TaaS::TapFlow'


class TapFlowTest(common.HeatTestCase):

    def setUp(self):
        super(TapFlowTest, self).setUp()

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

    def test_resource_mapping(self):
        mapping = tap_flow.resource_mapping()
        self.assertEqual(
            tap_flow.TapFlow,
            mapping['OS::Neutron::TaaS::TapFlow'])

    def _get_mock_resource(self):
        value = mock.MagicMock()
        value.id = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
        return value

    def test_resource_handle_create(self):
        mock_tap_flow_create = self.test_client_plugin.create_ext_resource
        mock_resource = self._get_mock_resource()
        mock_tap_flow_create.return_value = mock_resource

    # validate the properties
        self.assertEqual(
            'test_tap_flow',
            self.test_resource.properties.get(
                tap_flow.TapFlow.NAME))
        self.assertEqual(
            'desc',
            self.test_resource.properties.get(
                tap_flow.TapFlow.DESCRIPTION))
        self.assertEqual(
            '6af055d3-26f6-48dd-a597-7611d7e58d35',
            self.test_resource.properties.get(
                tap_flow.TapFlow.PORT))
        self.assertEqual(
            '6af055d3-26f6-48dd-a597-7611d7e58d35',
            self.test_resource.properties.get(
                tap_flow.TapFlow.TAP_SERVICE))
        self.assertEqual(
            'BOTH',
            self.test_resource.properties.get(
                tap_flow.TapFlow.DIRECTION))
        self.assertEqual(
            '1-5,9,18,27-30,99-108,4000-4095',
            self.test_resource.properties.get(
                tap_flow.TapFlow.VLAN_FILTER))

        self.test_resource.data_set = mock.Mock()
        self.test_resource.handle_create()
        mock_tap_flow_create.assert_called_once_with(
            'tap_flow',
            {
                'name': 'test_tap_flow',
                'description': 'desc',
                'port': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'tap_service': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'direction': 'BOTH',
                'vlan_filter': '1-5,9,18,27-30,99-108,4000-4095',
            }
        )

    def test_resource_handle_delete(self):
        mock_tap_flow_delete = self.test_client_plugin.delete_ext_resource
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_tap_flow_delete.return_value = None
        self.assertIsNone(self.test_resource.handle_delete())
        mock_tap_flow_delete.assert_called_once_with(
            'tap_flow', self.test_resource.resource_id)

    def test_resource_handle_delete_resource_id_is_none(self):
        self.test_resource.resource_id = None
        self.assertIsNone(self.test_resource.handle_delete())
        self.assertEqual(0, self.test_client_plugin.
                         delete_ext_resource.call_count)

    def test_resource_handle_delete_not_found(self):
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_tap_flow_delete = self.test_client_plugin.delete_ext_resource
        mock_tap_flow_delete.side_effect = self.test_client_plugin.NotFound
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resource_show_resource(self):
        mock_tap_flow_get = self.test_client_plugin.show_ext_resource
        mock_tap_flow_get.return_value = {}
        self.assertEqual({},
                         self.test_resource._show_resource(),
                         'Failed to show resource')

    def test_resource_handle_update(self):
        mock_tap_flow_patch = self.test_client_plugin.update_ext_resource
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {
            tap_flow.TapFlow.NAME:
                'name-updated',
            tap_flow.TapFlow.DESCRIPTION:
                'description-updated',
            tap_flow.TapFlow.PORT:
                '6af055d3-26f6-48dd-a597-7611d7e58d35',
            tap_flow.TapFlow.TAP_SERVICE:
                '6af055d3-26f6-48dd-a597-7611d7e58d35',
            tap_flow.TapFlow.DIRECTION:
                'BOTH',
            tap_flow.TapFlow.VLAN_FILTER:
                '1-5,9,18,27-30,99-108,4000-4095'
            }
        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        mock_tap_flow_patch.assert_called_once_with(
            'tap_flow',
            {
                'name': 'name-updated',
                'description': 'description-updated',
                'port': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'tap_service': '6af055d3-26f6-48dd-a597-7611d7e58d35',
                'direction': 'BOTH',
                'vlan_filter': '1-5,9,18,27-30,99-108,4000-4095',
            },  self.test_resource.resource_id)
