# Copyright 2017 Ericsson
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
import six

from oslo_log import log as logging

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import trunk
from heat.engine import scheduler
from heat.engine import stk_defn
from heat.tests import common
from heat.tests import utils
from neutronclient.common import exceptions as ncex
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient


LOG = logging.getLogger(__name__)

create_template = '''
heat_template_version: 2017-09-01
description: Template to test Neutron Trunk resource
resources:
  parent_port:
    type: OS::Neutron::Port
    properties:
      network: parent_port_net
  subport_1:
    type: OS::Neutron::Port
    properties:
      network: subport_1_net
  subport_2:
    type: OS::Neutron::Port
    properties:
      network: subport_2_net
  trunk:
    type: OS::Neutron::Trunk
    properties:
      name: trunk name
      description: trunk description
      port: { get_resource: parent_port }
      sub_ports:
        - { port: { get_resource: subport_1 },
            segmentation_type: vlan,
            segmentation_id: 101 }
        - { port: { get_resource: subport_2 },
            segmentation_type: vlan,
            segmentation_id: 102 }
'''

update_template = '''
heat_template_version: 2017-09-01
description: Template to test Neutron Trunk resource
resources:
  trunk:
    type: OS::Neutron::Trunk
    properties:
      name: trunk name
      description: trunk description
      port: parent_port_id
      sub_ports:
        - { port: subport_1_id,
            segmentation_type: vlan,
            segmentation_id: 101 }
        - { port: subport_2_id,
            segmentation_type: vlan,
            segmentation_id: 102 }
'''


class NeutronTrunkTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronTrunkTest, self).setUp()

        self.patchobject(
            neutron.NeutronClientPlugin, 'has_extension', return_value=True)
        self.create_trunk_mock = self.patchobject(
            neutronclient.Client, 'create_trunk')
        self.delete_trunk_mock = self.patchobject(
            neutronclient.Client, 'delete_trunk')
        self.show_trunk_mock = self.patchobject(
            neutronclient.Client, 'show_trunk')
        self.update_trunk_mock = self.patchobject(
            neutronclient.Client, 'update_trunk')
        self.trunk_remove_subports_mock = self.patchobject(
            neutronclient.Client, 'trunk_remove_subports')
        self.trunk_add_subports_mock = self.patchobject(
            neutronclient.Client, 'trunk_add_subports')
        self.find_resource_mock = self.patchobject(
            neutronV20, 'find_resourceid_by_name_or_id')

        rv = {
            'trunk': {
                'id': 'trunk id',
                'status': 'DOWN',
            }
        }
        self.create_trunk_mock.return_value = rv
        self.show_trunk_mock.return_value = rv

        def find_resourceid_by_name_or_id(
                _client, _resource, name_or_id, **_kwargs):
            return name_or_id
        self.find_resource_mock.side_effect = find_resourceid_by_name_or_id

    def _create_trunk(self, stack):
        trunk = stack['trunk']
        scheduler.TaskRunner(trunk.create)()
        stk_defn.update_resource_data(stack.defn, trunk.name,
                                      trunk.node_data())

        self.assertEqual((trunk.CREATE, trunk.COMPLETE), trunk.state)

    def _delete_trunk(self, stack):
        trunk = stack['trunk']
        scheduler.TaskRunner(trunk.delete)()

        self.assertEqual((trunk.DELETE, trunk.COMPLETE), trunk.state)

    def test_create_missing_port_property(self):
        t = template_format.parse(create_template)
        del t['resources']['trunk']['properties']['port']
        stack = utils.parse_stack(t)

        self.assertRaises(
            exception.StackValidationFailed,
            stack.validate)

    def test_create_no_subport(self):
        t = template_format.parse(create_template)
        del t['resources']['trunk']['properties']['sub_ports']
        del t['resources']['subport_1']
        del t['resources']['subport_2']
        stack = utils.parse_stack(t)

        parent_port = stack['parent_port']
        self.patchobject(parent_port, 'get_reference_id',
                         return_value='parent port id')
        self.find_resource_mock.return_value = 'parent port id'
        stk_defn.update_resource_data(stack.defn, parent_port.name,
                                      parent_port.node_data())

        self._create_trunk(stack)

        self.create_trunk_mock.assert_called_once_with({
            'trunk': {
                'description': 'trunk description',
                'name': 'trunk name',
                'port_id': 'parent port id',
            }}
        )

    def test_create_one_subport(self):
        t = template_format.parse(create_template)
        del t['resources']['trunk']['properties']['sub_ports'][1:]
        del t['resources']['subport_2']
        stack = utils.parse_stack(t)

        parent_port = stack['parent_port']
        self.patchobject(parent_port, 'get_reference_id',
                         return_value='parent port id')
        stk_defn.update_resource_data(stack.defn, parent_port.name,
                                      parent_port.node_data())

        subport_1 = stack['subport_1']
        self.patchobject(subport_1, 'get_reference_id',
                         return_value='subport id')
        stk_defn.update_resource_data(stack.defn, subport_1.name,
                                      subport_1.node_data())

        self._create_trunk(stack)

        self.create_trunk_mock.assert_called_once_with({
            'trunk': {
                'description': 'trunk description',
                'name': 'trunk name',
                'port_id': 'parent port id',
                'sub_ports': [
                    {'port_id': 'subport id',
                     'segmentation_type': 'vlan',
                     'segmentation_id': 101},
                ],
            }}
        )

    def test_create_two_subports(self):
        t = template_format.parse(create_template)
        del t['resources']['trunk']['properties']['sub_ports'][2:]
        stack = utils.parse_stack(t)

        parent_port = stack['parent_port']
        self.patchobject(parent_port, 'get_reference_id',
                         return_value='parent_port_id')
        stk_defn.update_resource_data(stack.defn, parent_port.name,
                                      parent_port.node_data())

        subport_1 = stack['subport_1']
        self.patchobject(subport_1, 'get_reference_id',
                         return_value='subport_1_id')
        stk_defn.update_resource_data(stack.defn, subport_1.name,
                                      subport_1.node_data())

        subport_2 = stack['subport_2']
        self.patchobject(subport_2, 'get_reference_id',
                         return_value='subport_2_id')
        stk_defn.update_resource_data(stack.defn, subport_2.name,
                                      subport_2.node_data())

        self._create_trunk(stack)

        self.create_trunk_mock.assert_called_once_with({
            'trunk': {
                'description': 'trunk description',
                'name': 'trunk name',
                'port_id': 'parent_port_id',
                'sub_ports': [
                    {'port_id': 'subport_1_id',
                     'segmentation_type': 'vlan',
                     'segmentation_id': 101},
                    {'port_id': 'subport_2_id',
                     'segmentation_type': 'vlan',
                     'segmentation_id': 102},
                ],
            }}
        )

    def test_create_degraded(self):
        t = template_format.parse(create_template)
        stack = utils.parse_stack(t)

        rv = {
            'trunk': {
                'id': 'trunk id',
                'status': 'DEGRADED',
            }
        }
        self.create_trunk_mock.return_value = rv
        self.show_trunk_mock.return_value = rv

        trunk = stack['trunk']
        e = self.assertRaises(
            exception.ResourceInError,
            trunk.check_create_complete,
            trunk.resource_id)

        self.assertIn(
            'Went to status DEGRADED due to',
            six.text_type(e))

    def test_create_parent_port_by_name(self):
        t = template_format.parse(create_template)
        t['resources']['parent_port'][
            'properties']['name'] = 'parent port name'
        t['resources']['trunk'][
            'properties']['port'] = 'parent port name'
        del t['resources']['trunk']['properties']['sub_ports']
        stack = utils.parse_stack(t)

        parent_port = stack['parent_port']
        self.patchobject(parent_port, 'get_reference_id',
                         return_value='parent port id')
        stk_defn.update_resource_data(stack.defn, parent_port.name,
                                      parent_port.node_data())

        def find_resourceid_by_name_or_id(
                _client, _resource, name_or_id, **_kwargs):
            name_to_id = {
                'parent port name': 'parent port id',
                'parent port id': 'parent port id',
            }
            return name_to_id[name_or_id]
        self.find_resource_mock.side_effect = find_resourceid_by_name_or_id

        self._create_trunk(stack)

        self.create_trunk_mock.assert_called_once_with({
            'trunk': {
                'description': 'trunk description',
                'name': 'trunk name',
                'port_id': 'parent port id',
            }}
        )

    def test_create_subport_by_name(self):
        t = template_format.parse(create_template)
        del t['resources']['trunk']['properties']['sub_ports'][1:]
        del t['resources']['subport_2']
        t['resources']['subport_1'][
            'properties']['name'] = 'subport name'
        t['resources']['trunk'][
            'properties']['sub_ports'][0]['port'] = 'subport name'
        stack = utils.parse_stack(t)

        parent_port = stack['parent_port']
        self.patchobject(parent_port, 'get_reference_id',
                         return_value='parent port id')
        stk_defn.update_resource_data(stack.defn, parent_port.name,
                                      parent_port.node_data())

        subport_1 = stack['subport_1']
        self.patchobject(subport_1, 'get_reference_id',
                         return_value='subport id')
        stk_defn.update_resource_data(stack.defn, subport_1.name,
                                      subport_1.node_data())

        def find_resourceid_by_name_or_id(
                _client, _resource, name_or_id, **_kwargs):
            name_to_id = {
                'subport name': 'subport id',
                'subport id': 'subport id',
                'parent port name': 'parent port id',
                'parent port id': 'parent port id',
            }
            return name_to_id[name_or_id]
        self.find_resource_mock.side_effect = find_resourceid_by_name_or_id

        self._create_trunk(stack)

        self.create_trunk_mock.assert_called_once_with({
            'trunk': {
                'description': 'trunk description',
                'name': 'trunk name',
                'port_id': 'parent port id',
                'sub_ports': [
                    {'port_id': 'subport id',
                     'segmentation_type': 'vlan',
                     'segmentation_id': 101},
                ],
            }}
        )

    def test_delete_proper(self):
        t = template_format.parse(create_template)
        stack = utils.parse_stack(t)

        self._create_trunk(stack)
        self._delete_trunk(stack)

        self.delete_trunk_mock.assert_called_once_with('trunk id')

    def test_delete_already_gone(self):
        t = template_format.parse(create_template)
        stack = utils.parse_stack(t)

        self._create_trunk(stack)
        self.delete_trunk_mock.side_effect = ncex.NeutronClientException(
            status_code=404)
        self._delete_trunk(stack)

        self.delete_trunk_mock.assert_called_once_with('trunk id')

    def test_update_basic_properties(self):
        t = template_format.parse(update_template)
        stack = utils.parse_stack(t)

        rsrc_defn = stack.defn.resource_definition('trunk')
        rsrc = trunk.Trunk('trunk', rsrc_defn, stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        props = copy.deepcopy(t['resources']['trunk']['properties'])
        props['name'] = 'new trunk name'
        rsrc_defn = rsrc_defn.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, rsrc_defn)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.update_trunk_mock.assert_called_once_with(
            'trunk id', {'trunk': {'name': 'new trunk name'}}
        )
        self.trunk_remove_subports_mock.assert_not_called()
        self.trunk_add_subports_mock.assert_not_called()

    def test_update_subport_delete(self):
        t = template_format.parse(update_template)
        stack = utils.parse_stack(t)

        rsrc_defn = stack.defn.resource_definition('trunk')
        rsrc = trunk.Trunk('trunk', rsrc_defn, stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        props = copy.deepcopy(t['resources']['trunk']['properties'])
        del props['sub_ports'][1]
        rsrc_defn = rsrc_defn.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, rsrc_defn)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.update_trunk_mock.assert_not_called()
        self.trunk_remove_subports_mock.assert_called_once_with(
            'trunk id', {'sub_ports': [{'port_id': u'subport_2_id'}]}
        )
        self.trunk_add_subports_mock.assert_not_called()

    def test_update_subport_add(self):
        t = template_format.parse(update_template)
        stack = utils.parse_stack(t)

        rsrc_defn = stack.defn.resource_definition('trunk')
        rsrc = trunk.Trunk('trunk', rsrc_defn, stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        props = copy.deepcopy(t['resources']['trunk']['properties'])
        props['sub_ports'].append(
            {'port': 'subport_3_id',
             'segmentation_type': 'vlan',
             'segmentation_id': 103})
        rsrc_defn = rsrc_defn.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, rsrc_defn)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.update_trunk_mock.assert_not_called()
        self.trunk_remove_subports_mock.assert_not_called()
        self.trunk_add_subports_mock.assert_called_once_with(
            'trunk id',
            {'sub_ports': [
                {'port_id': 'subport_3_id',
                 'segmentation_id': 103,
                 'segmentation_type': 'vlan'}
            ]}
        )

    def test_update_subport_change(self):
        t = template_format.parse(update_template)
        stack = utils.parse_stack(t)

        rsrc_defn = stack.defn.resource_definition('trunk')
        rsrc = trunk.Trunk('trunk', rsrc_defn, stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        props = copy.deepcopy(t['resources']['trunk']['properties'])
        props['sub_ports'][1]['segmentation_id'] = 103
        rsrc_defn = rsrc_defn.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, rsrc_defn)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.update_trunk_mock.assert_not_called()
        self.trunk_remove_subports_mock.assert_called_once_with(
            'trunk id', {'sub_ports': [{'port_id': u'subport_2_id'}]}
        )
        self.trunk_add_subports_mock.assert_called_once_with(
            'trunk id',
            {'sub_ports': [
                {'port_id': 'subport_2_id',
                 'segmentation_id': 103,
                 'segmentation_type': 'vlan'}
            ]}
        )
