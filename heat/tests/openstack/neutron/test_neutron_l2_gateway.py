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
from neutronclient.common import exceptions
from neutronclient.v2_0 import client as neutronclient
import six

from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

try:
    from networking_l2gw.services.l2gateway.exceptions import (
        L2GatewaySegmentationRequired)  # noqa
except ImportError:
    class L2GatewaySegmentationRequired(exceptions.NeutronException):
        message = ("L2 gateway segmentation id must be consistent for all "
                   "the interfaces")


class NeutronL2GatewayTest(common.HeatTestCase):
    test_template = '''
    heat_template_version: queens
    description: Template to test L2Gateway Neutron resource
    resources:
      l2gw:
        type: OS::Neutron::L2Gateway
        properties:
          name: L2GW01
          devices:
            - device_name: switch01
              interfaces:
                - name: eth0
                - name: eth1
    '''

    test_template_update = '''
    heat_template_version: queens
    description: Template to test L2Gateway Neutron resource
    resources:
      l2gw:
        type: OS::Neutron::L2Gateway
        properties:
          name: L2GW01
          devices:
            - device_name: switch01
              interfaces:
                - name: eth0
                - name: eth1
            - device_name: switch02
              interfaces:
                - name: eth5
                - name: eth6
    '''

    test_template_with_seg = '''
    heat_template_version: queens
    description: Template to test L2Gateway Neutron resource
    resources:
      l2gw:
        type: OS::Neutron::L2Gateway
        properties:
          name: L2GW01
          devices:
            - device_name: switch01
              interfaces:
                - name: eth0
                  segmentation_id:
                    - 101
                    - 102
                    - 103
                - name: eth1
                  segmentation_id:
                    - 101
                    - 102
                    - 103
    '''

    test_template_invalid_seg = '''
    heat_template_version: queens
    description: Template to test L2Gateway Neutron resource
    resources:
      l2gw:
        type: OS::Neutron::L2Gateway
        properties:
          name: L2GW01
          devices:
            - device_name: switch01
              interfaces:
                - name: eth0
                  segmentation_id:
                    - 101
                    - 102
                    - 103
                - name: eth1
    '''

    mock_create_req = {
        "l2_gateway": {
            "name": "L2GW01",
            "devices": [{
                "device_name": "switch01",
                "interfaces": [
                    {"name": "eth0"},
                    {"name": "eth1"}
                ]
            }]
        }}
    mock_create_reply = {
        "l2_gateway": {
            "name": "L2GW01",
            "id": "d3590f37-b072-4358-9719-71964d84a31c",
            "tenant_id": "7ea656c7c9b8447494f33b0bc741d9e6",
            "devices": [{
                "device_name": "switch01",
                "interfaces": [
                    {"name": "eth0"},
                    {"name": "eth1"}
                ]
            }]
        }}

    mock_update_req = {
        "l2_gateway": {
            "devices": [{
                "device_name": "switch01",
                "interfaces": [
                    {"name": "eth0"},
                    {"name": "eth1"}
                    ]
            }, {
                "device_name": "switch02",
                "interfaces": [
                    {"name": "eth5"},
                    {"name": "eth6"}]
                }]
        }}

    mock_update_reply = {
        "l2_gateway": {
            "name": "L2GW01",
            "id": "d3590f37-b072-4358-9719-71964d84a31c",
            "tenant_id": "7ea656c7c9b8447494f33b0bc741d9e6",
            "devices": [{
                "device_name": "switch01",
                "interfaces": [
                    {"name": "eth0"},
                    {"name": "eth1"}]
            }, {
                "device_name": "switch02",
                "interfaces": [
                    {"name": "eth5"},
                    {"name": "eth6"}]
                }]
        }}

    mock_create_with_seg_req = {
        "l2_gateway": {
            "name": "L2GW01",
            "devices": [{
                "device_name": "switch01",
                "interfaces": [
                    {"name": "eth0",
                     "segmentation_id": [101, 102, 103]},
                    {"name": "eth1",
                     "segmentation_id": [101, 102, 103]}
                ]
            }]
        }}
    mock_create_with_seg_reply = {
        "l2_gateway": {
            "name": "L2GW01",
            "id": "d3590f37-b072-4358-9719-71964d84a31c",
            "tenant_id": "7ea656c7c9b8447494f33b0bc741d9e6",
            "devices": [{
                "device_name": "switch01",
                "interfaces": [
                    {"name": "eth0",
                     "segmentation_id": ["101", "102", "103"]},
                    {"name": "eth1",
                     "segmentation_id": ["101", "102", "103"]}
                ]
            }]
        }}

    mock_create_invalid_seg_req = {
        "l2_gateway": {
            "name": "L2GW01",
            "devices": [{
                "device_name": "switch01",
                "interfaces": [
                    {"name": "eth0",
                     "segmentation_id": [101, 102, 103]},
                    {"name": "eth1"}
                ]
            }]
        }}
    mock_create_invalid_seg_reply = {
        "l2_gateway": {
            "name": "L2GW01",
            "id": "d3590f37-b072-4358-9719-71964d84a31c",
            "tenant_id": "7ea656c7c9b8447494f33b0bc741d9e6",
            "devices": [{
                "device_name": "switch01",
                "interfaces": [
                    {"name": "eth0",
                     "segmentation_id": ["101", "102", "103"]},
                    {"name": "eth1"}
                ]
            }]
        }}

    def setUp(self):
        super(NeutronL2GatewayTest, self).setUp()
        self.mockclient = mock.MagicMock()
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def _create_l2_gateway(self, hot, reply):
        # stack create
        self.mockclient.create_l2_gateway.return_value = reply
        self.mockclient.show_l2_gateway.return_value = reply
        template = template_format.parse(hot)
        self.stack = utils.parse_stack(template)
        scheduler.TaskRunner(self.stack.create)()
        self.l2gw_resource = self.stack['l2gw']

    def test_l2_gateway_create(self):
        self._create_l2_gateway(self.test_template, self.mock_create_reply)
        self.assertIsNone(self.l2gw_resource.validate())
        self.assertEqual((self.l2gw_resource.CREATE,
                         self.l2gw_resource.COMPLETE),
                         self.l2gw_resource.state)
        self.assertEqual('d3590f37-b072-4358-9719-71964d84a31c',
                         self.l2gw_resource.FnGetRefId())
        self.mockclient.create_l2_gateway.assert_called_once_with(
            self.mock_create_req)

    def test_l2_gateway_update(self):
        self._create_l2_gateway(self.test_template, self.mock_create_reply)
        # update l2_gateway with 2nd device
        self.mockclient.update_l2_gateway.return_value = self.mock_update_reply
        self.mockclient.show_l2_gateway.return_value = self.mock_update_reply
        updated_tmpl = template_format.parse(self.test_template_update)
        updated_stack = utils.parse_stack(updated_tmpl)
        self.stack.update(updated_stack)
        ud_l2gw_resource = self.stack['l2gw']
        self.assertIsNone(ud_l2gw_resource.validate())
        self.assertEqual((ud_l2gw_resource.UPDATE, ud_l2gw_resource.COMPLETE),
                         ud_l2gw_resource.state)
        self.assertEqual('d3590f37-b072-4358-9719-71964d84a31c',
                         ud_l2gw_resource.FnGetRefId())
        self.mockclient.update_l2_gateway.assert_called_once_with(
            'd3590f37-b072-4358-9719-71964d84a31c',
            self.mock_update_req)

    def test_l2_gateway_create_with_seg(self):
        # test with segmentation_id in template
        self._create_l2_gateway(self.test_template_with_seg,
                                self.mock_create_with_seg_reply)
        self.assertIsNone(self.l2gw_resource.validate())
        self.assertEqual((self.l2gw_resource.CREATE,
                         self.l2gw_resource.COMPLETE),
                         self.l2gw_resource.state)
        self.assertEqual('d3590f37-b072-4358-9719-71964d84a31c',
                         self.l2gw_resource.FnGetRefId())
        self.mockclient.create_l2_gateway.assert_called_once_with(
            self.mock_create_with_seg_req)

    def test_l2_gateway_create_invalid_seg(self):
        # test failure when segmentation_id is not consistent across
        # all interfaces
        self.mockclient.create_l2_gateway.side_effect = (
            L2GatewaySegmentationRequired())
        template = template_format.parse(self.test_template_invalid_seg)
        self.stack = utils.parse_stack(template)
        scheduler.TaskRunner(self.stack.create)()
        self.l2gw_resource = self.stack['l2gw']
        self.assertIsNone(self.l2gw_resource.validate())
        self.assertEqual(
            six.text_type('Resource CREATE failed: '
                          'L2GatewaySegmentationRequired: resources.l2gw: '
                          'L2 gateway segmentation id must be consistent for '
                          'all the interfaces'),
            self.stack.status_reason)
        self.assertEqual((self.l2gw_resource.CREATE,
                         self.l2gw_resource.FAILED),
                         self.l2gw_resource.state)
        self.mockclient.create_l2_gateway.assert_called_once_with(
            self.mock_create_invalid_seg_req)

    def test_l2_gateway_delete(self):
        self._create_l2_gateway(self.test_template, self.mock_create_reply)
        self.stack.delete()
        self.mockclient.delete_l2_gateway.assert_called_with(
            'd3590f37-b072-4358-9719-71964d84a31c')
