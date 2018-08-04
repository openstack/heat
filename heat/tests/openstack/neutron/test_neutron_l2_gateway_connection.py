# Copyright 2018 Ericsson
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
from neutronclient.v2_0 import client as neutronclient

from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


class NeutronL2GatewayConnectionTest(common.HeatTestCase):
    test_template = '''
    heat_template_version: queens
    description: Template to test L2GatewayConnection Neutron resource
    resources:
      l2gw_conn:
        type: OS::Neutron::L2GatewayConnection
        properties:
          network_id: j29n3678-c012-p008-3975-93584a65a18a
          segmentation_id: 501
          l2_gateway_id: d3590f37-b072-4358-9719-71964d84a31c
    '''

    mock_create_req = {
        "l2_gateway_connection": {
            "network_id": "j29n3678-c012-p008-3975-93584a65a18a",
            "segmentation_id": "501",
            "l2_gateway_id": "d3590f37-b072-4358-9719-71964d84a31c"
        }}
    mock_create_reply = {
        "l2_gateway_connection": {
            "id": "e491171c-3458-4d85-b3a3-68a7c4a1cacd",
            "tenant_id": "7ea656c7c9b8447494f33b0bc741d9e6",
            "network_id": "j29n3678-c012-p008-3975-93584a65a18a",
            "segmentation_id": "501",
            "l2_gateway_id": "d3590f37-b072-4358-9719-71964d84a31c"
        }}

    def setUp(self):
        super(NeutronL2GatewayConnectionTest, self).setUp()
        self.mockclient = mock.MagicMock()
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def _create_l2_gateway_connection(self):
        # stack create
        self.mockclient.create_l2_gateway_connection.return_value = (
            self.mock_create_reply)
        self.mockclient.show_l2_gateway_connection.return_value = (
            self.mock_create_reply)
        orig_template = template_format.parse(self.test_template)
        self.stack = utils.parse_stack(orig_template)
        scheduler.TaskRunner(self.stack.create)()
        self.l2gwconn_resource = self.stack['l2gw_conn']

    def test_l2_gateway_connection_create(self):
        self._create_l2_gateway_connection()
        self.assertIsNone(self.l2gwconn_resource.validate())
        self.assertEqual((self.l2gwconn_resource.CREATE,
                         self.l2gwconn_resource.COMPLETE),
                         self.l2gwconn_resource.state)
        self.assertEqual('e491171c-3458-4d85-b3a3-68a7c4a1cacd',
                         self.l2gwconn_resource.FnGetRefId())
        self.mockclient.create_l2_gateway_connection.assert_called_once_with(
            self.mock_create_req)

    def test_l2_gateway_connection_delete(self):
        self._create_l2_gateway_connection()
        self.stack.delete()
        self.mockclient.delete_l2_gateway_connection.assert_called_with(
            'e491171c-3458-4d85-b3a3-68a7c4a1cacd')
