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

import mock
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception as heat_ex
from heat.common import short_id
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.clients.os import nova
from heat.engine import node_data
from heat.engine.resources.openstack.nova import floatingip
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


floating_ip_template = '''
{
    "heat_template_version": "2013-05-23",
    "resources": {
        "MyFloatingIP": {
            "type": "OS::Nova::FloatingIP",
            "properties": {
                "pool": "public"
            }
        }
    }
}
'''

floating_ip_template_with_assoc = '''
{
    "heat_template_version": "2013-05-23",
    "resources": {
        "MyFloatingIPAssociation": {
            "type": "OS::Nova::FloatingIPAssociation",
            "properties": {
                "server_id": "67dc62f9-efde-4c8b-94af-013e00f5dc57",
                "floating_ip": "fc68ea2c-b60b-4b4f-bd82-94ec81110766"
            }
        }
    }
}
'''


class NovaFloatingIPTest(common.HeatTestCase):
    def setUp(self):
        super(NovaFloatingIPTest, self).setUp()
        self.novaclient = fakes_nova.FakeClient()
        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.novaclient)
        self.mock_create_fip = self.patchobject(neutronclient.Client,
                                                'create_floatingip')
        self.mock_upd_fip = self.patchobject(neutronclient.Client,
                                             'update_floatingip')
        self.mock_del_fip = self.patchobject(neutronclient.Client,
                                             'delete_floatingip')
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='eeee')

    def mock_interface(self, port, ip):
        class MockIface(object):
            def __init__(self, port_id, fixed_ip):
                self.port_id = port_id
                self.fixed_ips = [{'ip_address': fixed_ip}]

        return MockIface(port, ip)

    def mock_create_floatingip(self):
        self.mock_create_fip.return_value = {'floatingip': {
            "status": "ACTIVE",
            "id": "fc68ea2c-b60b-4b4f-bd82-94ec81110766",
            'floating_network_id': 'eeee',
            "floating_ip_address": "11.0.0.1"
        }}

    def prepare_floating_ip(self):
        self.mock_create_floatingip()
        template = template_format.parse(floating_ip_template)
        self.stack = utils.parse_stack(template)
        defns = self.stack.t.resource_definitions(self.stack)

        return floatingip.NovaFloatingIp('MyFloatingIP',
                                         defns['MyFloatingIP'],
                                         self.stack)

    def prepare_floating_ip_assoc(self):
        return_server = self.novaclient.servers.list()[1]
        self.patchobject(self.novaclient.servers, 'get',
                         return_value=return_server)
        iface = self.mock_interface('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                                    '1.2.3.4')
        self.patchobject(return_server, 'interface_list', return_value=[iface])

        template = template_format.parse(floating_ip_template_with_assoc)
        self.stack = utils.parse_stack(template)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        floating_ip_assoc = resource_defns['MyFloatingIPAssociation']

        return floatingip.NovaFloatingIpAssociation(
            'MyFloatingIPAssociation', floating_ip_assoc, self.stack)

    def test_floating_ip_create(self):
        rsrc = self.prepare_floating_ip()
        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.mock_create_fip.assert_called_with(
            {'floatingip': {'floating_network_id': 'eeee'}})
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                         rsrc.FnGetRefId())
        self.assertEqual('11.0.0.1', rsrc.FnGetAtt('ip'))
        self.assertEqual('eeee', rsrc.FnGetAtt('pool'))

    def test_floating_ip_delete(self):
        rsrc = self.prepare_floating_ip()
        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.mock_del_fip.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766')

    def test_delete_floating_ip_assoc_successful_if_create_failed(self):
        rsrc = self.prepare_floating_ip_assoc()
        self.mock_upd_fip.side_effect = [fakes_nova.fake_exception(400)]

        rsrc.validate()
        self.assertRaises(heat_ex.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

    def test_floating_ip_assoc_create(self):
        rsrc = self.prepare_floating_ip_assoc()
        fip_request = {'floatingip': {
            'fixed_ip_address': '1.2.3.4',
            'port_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}
        }
        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mock_upd_fip.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766', fip_request)
        self.assertIsNotNone(rsrc.id)
        self.assertEqual(rsrc.id, rsrc.resource_id)

    def test_floating_ip_assoc_delete(self):
        rsrc = self.prepare_floating_ip_assoc()
        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        fip_request = {'floatingip': {
            'fixed_ip_address': None, 'port_id': None}}
        self.mock_upd_fip.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766', fip_request)

    def create_delete_assoc_with_exc(self, exc):
        rsrc = self.prepare_floating_ip_assoc()
        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.mock_upd_fip.side_effect = [exc]
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

    def test_floating_ip_assoc_delete_neutron_not_found(self):
        self.create_delete_assoc_with_exc(neutronclient.exceptions.NotFound())

    def test_floating_ip_assoc_delete_nova_not_found(self):
        self.create_delete_assoc_with_exc(fakes_nova.fake_exception(404))

    def test_floating_ip_assoc_update_server_id(self):
        rsrc = self.prepare_floating_ip_assoc()
        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # for update
        return_server = self.novaclient.servers.list()[2]
        self.patchobject(self.novaclient.servers, 'get',
                         return_value=return_server)
        iface = self.mock_interface('bbbbb-bbbb-bbbb-bbbbbbbbb',
                                    '4.5.6.7')
        self.patchobject(return_server, 'interface_list', return_value=[iface])

        # update with the new server_id
        props = copy.deepcopy(rsrc.properties.data)
        update_server_id = '2146dfbf-ba77-4083-8e86-d052f671ece5'
        props['server_id'] = update_server_id
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        fip_request = {'floatingip': {
            'fixed_ip_address': '1.2.3.4',
            'port_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}
        }
        fip_request_update = {'floatingip': {
            'fixed_ip_address': '4.5.6.7',
            'port_id': 'bbbbb-bbbb-bbbb-bbbbbbbbb'}
        }
        calls = [mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                           fip_request),
                 mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                           fip_request_update)]
        self.mock_upd_fip.assert_has_calls(calls)
        self.assertEqual(2, self.mock_upd_fip.call_count)

    def test_floating_ip_assoc_update_fl_ip(self):
        rsrc = self.prepare_floating_ip_assoc()
        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # update with the new floatingip
        props = copy.deepcopy(rsrc.properties.data)
        props['floating_ip'] = 'fc68ea2c-cccc-4b4f-bd82-94ec81110766'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        fip_request = {'floatingip': {
            'fixed_ip_address': '1.2.3.4',
            'port_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}
        }
        fip_request_none = {'floatingip': {
            'fixed_ip_address': None, 'port_id': None}}
        calls = [mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                           fip_request),
                 mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                           fip_request_none),
                 mock.call('fc68ea2c-cccc-4b4f-bd82-94ec81110766',
                           fip_request)]
        self.mock_upd_fip.assert_has_calls(calls)
        self.assertEqual(3, self.mock_upd_fip.call_count)

    def test_floating_ip_assoc_update_both(self):
        rsrc = self.prepare_floating_ip_assoc()
        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        # update with the new floatingip
        return_server = self.novaclient.servers.list()[2]
        self.patchobject(self.novaclient.servers, 'get',
                         return_value=return_server)
        iface = self.mock_interface('bbbbb-bbbb-bbbb-bbbbbbbbb',
                                    '4.5.6.7')
        self.patchobject(return_server, 'interface_list', return_value=[iface])
        props = copy.deepcopy(rsrc.properties.data)
        update_server_id = '2146dfbf-ba77-4083-8e86-d052f671ece5'
        props['server_id'] = update_server_id
        props['floating_ip'] = 'fc68ea2c-cccc-4b4f-bd82-94ec81110766'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        fip_request = {'floatingip': {
            'port_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            'fixed_ip_address': '1.2.3.4'}
        }
        fip_request_none = {'floatingip': {
            'port_id': None, 'fixed_ip_address': None}}
        fip_request_update = {'floatingip': {
            'port_id': 'bbbbb-bbbb-bbbb-bbbbbbbbb',
            'fixed_ip_address': '4.5.6.7'}
        }
        calls = [mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                           fip_request),
                 mock.call('fc68ea2c-b60b-4b4f-bd82-94ec81110766',
                           fip_request_none),
                 mock.call('fc68ea2c-cccc-4b4f-bd82-94ec81110766',
                           fip_request_update)]
        self.mock_upd_fip.assert_has_calls(calls)
        self.assertEqual(3, self.mock_upd_fip.call_count)

    def test_floating_ip_assoc_refid_rsrc_name(self):
        t = template_format.parse(floating_ip_template_with_assoc)
        stack = utils.parse_stack(t)
        rsrc = stack['MyFloatingIPAssociation']
        rsrc.id = '123'
        rsrc.uuid = '9bfb9456-3fe8-41f4-b318-9dba18eeef74'
        rsrc.action = 'CREATE'
        expected = '%s-%s-%s' % (rsrc.stack.name,
                                 rsrc.name,
                                 short_id.get_id(rsrc.uuid))
        self.assertEqual(expected, rsrc.FnGetRefId())

    def test_floating_ip_assoc_refid_rsrc_id(self):
        t = template_format.parse(floating_ip_template_with_assoc)
        stack = utils.parse_stack(t)
        rsrc = stack['MyFloatingIPAssociation']
        rsrc.resource_id = 'phy-rsrc-id'
        self.assertEqual('phy-rsrc-id', rsrc.FnGetRefId())

    def test_floating_ip_assoc_refid_convg_cache_data(self):
        t = template_format.parse(floating_ip_template_with_assoc)
        cache_data = {'MyFloatingIPAssociation': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        })}
        stack = utils.parse_stack(t, cache_data=cache_data)
        rsrc = stack.defn['MyFloatingIPAssociation']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())
