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

from heat.engine.resources.openstack.neutron.sfc import flow_classifier
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


sample_template = {
    'heat_template_version': '2016-04-08',
    'resources': {
        'test_resource': {
            'type': 'OS::Neutron::FlowClassifier',
            'properties': {
                'name': 'test_flow_classifier',
                'description': 'flow_classifier_desc',
                'protocol': 'tcp',
                'ethertype': 'IPv4',
                'source_ip_prefix': '10.0.3.21',
                'destination_ip_prefix': '10.0.3.22',
                'source_port_range_min': 1,
                'source_port_range_max': 10,
                'destination_port_range_min': 80,
                'destination_port_range_max': 100,
                'logical_source_port': 'port-id1',
                'logical_destination_port': 'port-id2',
                'l7_parameters': {"url": 'http://local'}
                }
            }
        }
    }


class FlowClassifierTest(common.HeatTestCase):

    def setUp(self):
        super(FlowClassifierTest, self).setUp()
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
        mapping = flow_classifier.resource_mapping()
        self.assertEqual(flow_classifier.FlowClassifier,
                         mapping['OS::Neutron::FlowClassifier'])

    def _get_mock_resource(self):
        value = mock.MagicMock()
        value.id = '2a046ff4-cd7b-4500-b8f0-b60d96ce3e0c'
        return value

    def test_resource_handle_create(self):
        mock_fc_create = self.test_client_plugin.create_ext_resource
        mock_resource = self._get_mock_resource()
        mock_fc_create.return_value = mock_resource
        # validate the properties
        self.assertEqual(
            'test_flow_classifier',
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.NAME))
        self.assertEqual(
            'flow_classifier_desc',
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.DESCRIPTION))
        self.assertEqual(
            'tcp',
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.PROTOCOL))
        self.assertEqual(
            'IPv4',
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.ETHERTYPE))
        self.assertEqual(
            '10.0.3.21',
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.SOURCE_IP_PREFIX))
        self.assertEqual(
            '10.0.3.22',
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.DESTINATION_IP_PREFIX))
        self.assertEqual(
            1,
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.SOURCE_PORT_RANGE_MIN))
        self.assertEqual(
            10,
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.SOURCE_PORT_RANGE_MAX))
        self.assertEqual(
            80,
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.DESTINATION_PORT_RANGE_MIN))
        self.assertEqual(
            100,
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.DESTINATION_PORT_RANGE_MAX))
        self.assertEqual(
            'port-id1',
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.LOGICAL_SOURCE_PORT))
        self.assertEqual(
            'port-id2',
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.LOGICAL_DESTINATION_PORT))
        self.assertEqual(
            {"url": 'http://local'},
            self.test_resource.properties.get(
                flow_classifier.FlowClassifier.L7_PARAMETERS))

        self.test_resource.data_set = mock.Mock()
        self.test_resource.handle_create()

        mock_fc_create.assert_called_once_with(
            'flow_classifier',
            {
                'name': 'test_flow_classifier',
                'description': 'flow_classifier_desc',
                'protocol': 'tcp',
                'ethertype': 'IPv4',
                'source_ip_prefix': '10.0.3.21',
                'destination_ip_prefix': '10.0.3.22',
                'source_port_range_min': 1,
                'source_port_range_max': 10,
                'destination_port_range_min': 80,
                'destination_port_range_max': 100,
                'logical_source_port': 'port-id1',
                'logical_destination_port': 'port-id2',
                'l7_parameters': {"url": 'http://local'}
            }
        )

    def test_resource_handle_delete(self):
        mock_fc_delete = self.test_client_plugin.delete_ext_resource
        self.test_resource.resource_id = '2a046ff4-cd7b-4500-b8f0-b60d96ce3e0c'
        mock_fc_delete.return_value = None
        self.assertIsNone(self.test_resource.handle_delete())
        mock_fc_delete.assert_called_once_with(
            'flow_classifier', self.test_resource.resource_id)

    def test_resource_handle_delete_resource_id_is_none(self):
        self.test_resource.resource_id = None
        self.assertIsNone(self.test_resource.handle_delete())
        self.assertEqual(0, self.test_client_plugin.
                         delete_ext_resource.call_count)

    def test_resource_handle_delete_not_found(self):
        self.test_resource.resource_id = '2a046ff4-cd7b-4500-b8f0-b60d96ce3e0c'
        mock_fc_delete = self.test_client_plugin.delete_ext_resource
        mock_fc_delete.side_effect = self.test_client_plugin.NotFound
        self.assertIsNone(self.test_resource.handle_delete())

    def test_resource_show_resource(self):
        mock_fc_get = self.test_client_plugin.show_ext_resource
        mock_fc_get.return_value = {}
        self.assertEqual({},
                         self.test_resource._show_resource(),
                         'Failed to show resource')

    def test_resource_handle_update(self):
        mock_fc_patch = self.test_client_plugin.update_ext_resource
        self.test_resource.resource_id = '2a046ff4-cd7b-4500-b8f0-b60d96ce3e0c'

        prop_diff = {
            flow_classifier.FlowClassifier.NAME:
                'name-updated',
            flow_classifier.FlowClassifier.DESCRIPTION:
                'description-updated',
            }
        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)
        mock_fc_patch.assert_called_once_with(
            'flow_classifier',
            {
                'name': 'name-updated',
                'description': 'description-updated',
            },  self.test_resource.resource_id)
