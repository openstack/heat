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
from unittest import mock

from ironicclient.common.apiclient import exceptions as ic_exc
from oslo_config import cfg

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import ironic as ic
from heat.engine import resource
from heat.engine.resources.openstack.ironic import port
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils

cfg.CONF.import_opt('max_ironic_api_microversion', 'heat.common.config')

port_template = '''
    heat_template_version: rocky
    resources:
      test_port:
        type: OS::Ironic::Port
        properties:
          node: node_1
          address: 52:54:00:4d:e1:5e
          portgroup: pg1
          local_link_connection:
            switch_info: brbm
            port_id: ovs-node-1i1
            switch_id: 70:4d:7b:88:ff:3a
          pxe_enabled: true
          physical_network: fake_phy_net
          extra: {}
          is_smartnic: false
'''


min_port_template = '''
    heat_template_version: ocata
    resources:
      test_port:
        type: OS::Ironic::Port
        properties:
          node: node_2
          address: 54:54:00:4d:e1:5e
'''

RESOURCE_TYPE = 'OS::Ironic::Port'


class TestIronicPort(common.HeatTestCase):
    def setUp(self):
        super(TestIronicPort, self).setUp()
        cfg.CONF.set_override('max_ironic_api_microversion', 1.11)
        cfg.CONF.set_override('action_retry_limit', 0)
        self.fake_node_name = 'node_1'
        self.fake_portgroup_name = 'pg1'

        self.resource_id = '9cc6fd32-f711-4e1f-a82d-59e6ae074e95'
        self.fake_name = 'test_port'
        self.fake_address = u'52:54:00:4d:e1:5e'
        self.fake_node_uuid = u'22767a68-a7f2-45fe-bc08-335a83e2b919'
        self.fake_portgroup_uuid = '92972f88-a1e7-490f-866c-b6704d65c4de'
        self.fake_local_link_connection = {'switch_info': 'brbm',
                                           'port_id': 'ovs-node-1i1',
                                           'switch_id': '70:4d:7b:88:ff:3a'}
        self.fake_internal_info = {'foo': 'bar'}
        self.fake_pxe_enabled = True
        self.fake_physical_network = 'fake_phy_net'
        self.fake_internal_info = {}
        self.fake_extra = {}
        self.fake_is_smartnic = False
        resource._register_class(RESOURCE_TYPE, port.Port)
        t = template_format.parse(port_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns[self.fake_name]
        self.client = mock.Mock()
        self.patchobject(port.Port, 'client', return_value=self.client)
        self.m_fgn = self.patchobject(ic.IronicClientPlugin,
                                      'get_node')
        self.m_fgpg = self.patchobject(ic.IronicClientPlugin,
                                       'get_portgroup')
        self.m_fgn.return_value = self.fake_node_uuid
        self.m_fgpg.return_value = self.fake_portgroup_uuid
        self._mock_get_client()

    def _mock_get_client(self):
        value = mock.MagicMock(
            address=self.fake_address,
            node_uuid=self.fake_node_uuid,
            portgroup_uuid=self.fake_portgroup_uuid,
            local_link_connection=self.fake_local_link_connection,
            pxe_enabled=self.fake_pxe_enabled,
            physical_network=self.fake_physical_network,
            internal_info=self.fake_internal_info,
            extra=self.fake_extra,
            is_smartnic=self.fake_is_smartnic,
            uuid=self.resource_id,
        )
        value.to_dict.return_value = value.__dict__
        self.client.port.get.return_value = value

    def _create_resource(self, name, snippet, stack, get_exception=None):
        value = mock.MagicMock(uuid=self.resource_id)
        self.client.port.create.return_value = value
        get_rv = mock.MagicMock()
        if get_exception:
            self.client.port.get.side_effect = get_exception
        else:
            self.client.port.get.return_value = get_rv
        p = port.Port(name, snippet, stack)
        return p

    def test_port_create(self):
        b = self._create_resource('port', self.rsrc_defn, self.stack)
        # validate the properties
        self.assertEqual(
            self.fake_node_name,
            b.properties.get(port.Port.NODE))
        self.assertEqual(
            self.fake_address,
            b.properties.get(port.Port.ADDRESS))
        self.assertEqual(
            self.fake_portgroup_name,
            b.properties.get(port.Port.PORTGROUP))
        self.assertEqual(
            self.fake_local_link_connection,
            b.properties.get(port.Port.LOCAL_LINK_CONNECTION))
        self.assertEqual(
            self.fake_pxe_enabled,
            b.properties.get(port.Port.PXE_ENABLED))
        self.assertEqual(
            self.fake_physical_network,
            b.properties.get(port.Port.PHYSICAL_NETWORK))
        self.assertEqual(
            self.fake_extra,
            b.properties.get(port.Port.EXTRA))
        self.assertEqual(
            self.fake_is_smartnic,
            b.properties.get(port.Port.IS_SMARTNIC))
        scheduler.TaskRunner(b.create)()
        self.assertEqual(self.resource_id, b.resource_id)
        expected = [mock.call(self.fake_node_name),
                    mock.call(self.fake_node_uuid)]
        self.assertEqual(expected, self.m_fgn.call_args_list)
        expected = [mock.call(self.fake_portgroup_name),
                    mock.call(self.fake_portgroup_uuid)]
        self.assertEqual(expected, self.m_fgpg.call_args_list)
        self.client.port.create.assert_called_once_with(
            address=self.fake_address,
            extra=self.fake_extra,
            is_smartnic=self.fake_is_smartnic,
            local_link_connection=self.fake_local_link_connection,
            node_uuid=self.fake_node_uuid,
            physical_network=self.fake_physical_network,
            portgroup_uuid=self.fake_portgroup_uuid,
            pxe_enabled=self.fake_pxe_enabled)

    def _property_not_supported(self, property_name, version):
        t = template_format.parse(min_port_template)
        new_t = copy.deepcopy(t)
        new_t['resources'][self.fake_name]['properties'][
            property_name] = self.rsrc_defn._properties[property_name]
        rsrc_defns = template.Template(new_t).resource_definitions(
            self.stack)
        new_port = rsrc_defns[self.fake_name]
        p = self._create_resource('port-with-%s' % property_name,
                                  new_port, self.stack)

        p.client_plugin().max_microversion = version - 0.01

        feature = "OS::Ironic::Port with %s property" % property_name
        err = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(p.create))
        self.assertEqual("NotSupported: resources.port-with-%(key)s: "
                         "%(feature)s is not supported." % {
                             'feature': feature, 'key': property_name},
                         str(err))

    def test_port_create_with_pxe_enabled_not_supported(self):
        self._property_not_supported(port.Port.PXE_ENABLED, 1.19)

    def test_port_create_with_local_link_connection_not_supported(self):
        self._property_not_supported(port.Port.LOCAL_LINK_CONNECTION, 1.19)

    def test_port_create_with_portgroup_not_supported(self):
        self._property_not_supported(port.Port.PORTGROUP, 1.24)

    def test_port_create_with_physical_network_not_supported(self):
        self._property_not_supported(port.Port.PHYSICAL_NETWORK, 1.34)

    def test_port_create_with_is_smartnic_not_supported(self):
        self._property_not_supported(port.Port.IS_SMARTNIC, 1.53)

    def test_port_check_create_complete(self):
        b = self._create_resource('port', self.rsrc_defn, self.stack)
        self.assertTrue(b.check_create_complete(self.resource_id))

    def test_port_check_create_complete_with_not_found(self):
        b = self._create_resource('port', self.rsrc_defn, self.stack,
                                  get_exception=ic_exc.NotFound)
        self.assertFalse(b.check_create_complete(self.resource_id))

    def test_port_check_create_complete_with_non_not_found_exception(self):
        b = self._create_resource('port', self.rsrc_defn, self.stack,
                                  get_exception=ic_exc.Conflict())
        exc = self.assertRaises(ic_exc.Conflict, b.check_create_complete,
                                self.resource_id)
        self.assertIn('Conflict', str(exc))

    def _port_update(self, exc_msg=None):
        b = self._create_resource('port', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        if exc_msg:
            self.client.port.update.side_effect = ic_exc.Conflict(exc_msg)
        t = template_format.parse(port_template)
        new_t = copy.deepcopy(t)
        new_extra = {'foo': 'bar'}
        m_pg = mock.Mock(extra=new_extra)
        self.client.port.get.return_value = m_pg
        new_t['resources'][self.fake_name]['properties']['extra'] = new_extra
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_port = rsrc_defns[self.fake_name]
        if exc_msg:
            exc = self.assertRaises(
                exception.ResourceFailure,
                scheduler.TaskRunner(b.update, new_port))
            self.assertIn(exc_msg, str(exc))
        else:
            scheduler.TaskRunner(b.update, new_port)()
            self.client.port.update.assert_called_once_with(
                self.resource_id,
                [{'op': 'replace', 'path': '/extra', 'value': new_extra}])

    def test_port_update(self):
        self._port_update()

    def test_port_update_failed(self):
        exc_msg = ("Port 9cc6fd32-f711-4e1f-a82d-59e6ae074e95 can not have "
                   "any connectivity attributes (pxe_enabled, portgroup_id, "
                   "physical_network, local_link_connection) updated unless "
                   "node 9ccee9ec-92a5-4580-9242-82eb7f454d3f is in a enroll, "
                   "inspecting, inspect wait, manageable state or in "
                   "maintenance mode.")
        self._port_update(exc_msg)

    def test_port_check_delete_complete_with_no_id(self):
        b = self._create_resource('port', self.rsrc_defn, self.stack)
        self.assertTrue(b.check_delete_complete(None))

    def test_port_check_delete_complete_with_not_found(self):
        b = self._create_resource('port', self.rsrc_defn, self.stack,
                                  get_exception=ic_exc.NotFound)
        self.assertTrue(b.check_delete_complete(self.resource_id))

    def test_port_check_delete_complete_with_exception(self):
        b = self._create_resource('port', self.rsrc_defn, self.stack,
                                  get_exception=ic_exc.Conflict())
        exc = self.assertRaises(ic_exc.Conflict,
                                b.check_delete_complete, self.resource_id)
        self.assertIn('Conflict', str(exc))
