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

from heat.common import exception
from heat.engine.clients.os import neutron
from heat.tests.common import HeatTestCase
from heat.tests import utils


class NeutronClientPluginTestCase(HeatTestCase):
    def setUp(self):
        super(NeutronClientPluginTestCase, self).setUp()
        self.neutron_client = mock.MagicMock()

        con = utils.dummy_context()
        c = con.clients
        self.neutron_plugin = c.client_plugin('neutron')
        self.neutron_plugin._client = self.neutron_client


class NeutronClientPluginTests(NeutronClientPluginTestCase):
    def setUp(self):
        super(NeutronClientPluginTests, self).setUp()
        self.mock_find = self.patchobject(neutron.neutronV20,
                                          'find_resourceid_by_name_or_id')
        self.mock_find.return_value = 42

    def test_find_neutron_resource(self):
        props = {'net': 'test_network'}

        res = self.neutron_plugin.find_neutron_resource(props, 'net',
                                                        'network')
        self.assertEqual(42, res)
        self.mock_find.assert_called_once_with(self.neutron_client, 'network',
                                               'test_network')

    def test_resolve_network(self):
        props = {'net': 'test_network'}

        res = self.neutron_plugin.resolve_network(props, 'net', 'net_id')
        self.assertEqual(42, res)
        self.mock_find.assert_called_once_with(self.neutron_client, 'network',
                                               'test_network')

        # check resolve if was send id instead of name
        props = {'net_id': 77}
        res = self.neutron_plugin.resolve_network(props, 'net', 'net_id')
        self.assertEqual(77, res)
        # in this case find_resourceid_by_name_or_id is not called
        self.mock_find.assert_called_once_with(self.neutron_client, 'network',
                                               'test_network')

    def test_resolve_subnet(self):
        props = {'snet': 'test_subnet'}

        res = self.neutron_plugin.resolve_subnet(props, 'snet', 'snet_id')
        self.assertEqual(42, res)
        self.mock_find.assert_called_once_with(self.neutron_client, 'subnet',
                                               'test_subnet')

        # check resolve if was send id instead of name
        props = {'snet_id': 77}
        res = self.neutron_plugin.resolve_subnet(props, 'snet', 'snet_id')
        self.assertEqual(77, res)
        # in this case find_resourceid_by_name_or_id is not called
        self.mock_find.assert_called_once_with(self.neutron_client, 'subnet',
                                               'test_subnet')

    def test_get_secgroup_uuids(self):
        # test get from uuids
        sgs_uuid = ['b62c3079-6946-44f5-a67b-6b9091884d4f',
                    '9887157c-d092-40f5-b547-6361915fce7d']

        sgs_list = self.neutron_plugin.get_secgroup_uuids(sgs_uuid)
        self.assertEqual(sgs_list, sgs_uuid)
        # test get from name, return only one
        sgs_non_uuid = ['security_group_1']
        expected_groups = ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        fake_list = {
            'security_groups': [
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }
        self.neutron_client.list_security_groups.return_value = fake_list
        self.assertEqual(expected_groups,
                         self.neutron_plugin.get_secgroup_uuids(sgs_non_uuid))
        # test only one belong to the tenant
        fake_list = {
            'security_groups': [
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'tenant_id': 'not_test_tenant_id',
                    'id': '384ccd91-447c-4d83-832c-06974a7d3d05',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }
        self.neutron_client.list_security_groups.return_value = fake_list
        self.assertEqual(expected_groups,
                         self.neutron_plugin.get_secgroup_uuids(sgs_non_uuid))
        # test there are two securityGroups with same name, and the two
        # all belong to the tenant
        fake_list = {
            'security_groups': [
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '384ccd91-447c-4d83-832c-06974a7d3d05',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }
        self.neutron_client.list_security_groups.return_value = fake_list
        self.assertRaises(exception.PhysicalResourceNameAmbiguity,
                          self.neutron_plugin.get_secgroup_uuids,
                          sgs_non_uuid)
