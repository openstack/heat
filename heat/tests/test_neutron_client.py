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
