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
import collections

from manilaclient import exceptions
import mock

from heat.common import exception as heat_exception
from heat.tests import common
from heat.tests import utils


class ManilaClientPluginTest(common.HeatTestCase):
    scenarios = [
        ('share_type',
            dict(manager_name="share_types",
                 method_name="get_share_type")),
        ('share_network',
            dict(manager_name="share_networks",
                 method_name="get_share_network")),
        ('share_snapshot',
            dict(manager_name="share_snapshots",
                 method_name="get_share_snapshot")),
        ('security_service',
            dict(manager_name="security_services",
                 method_name="get_security_service")),
    ]

    def setUp(self):
        super(ManilaClientPluginTest, self).setUp()
        # mock client and plugin
        self.manila_client = mock.MagicMock()
        con = utils.dummy_context()
        c = con.clients
        self.manila_plugin = c.client_plugin('manila')
        self.manila_plugin.client = lambda: self.manila_client
        # prepare list of items to test search
        Item = collections.namedtuple('Item', ['id', 'name'])
        self.item_list = [
            Item(name="unique_name", id="unique_id"),
            Item(name="unique_id", id="i_am_checking_that_id_prior"),
            Item(name="duplicated_name", id="duplicate_test_one"),
            Item(name="duplicated_name", id="duplicate_test_second")]

    def test_create(self):
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('manila')
        client = plugin.client()
        self.assertIsNotNone(client.security_services)
        self.assertEqual('http://server.test:5000/v3',
                         client.client.endpoint_url)

    def test_manila_get_method(self):
        # set item list as client output
        manager = getattr(self.manila_client, self.manager_name)
        manager.list.return_value = self.item_list
        # test that get_<method_name> is searching correctly
        get_method = getattr(self.manila_plugin, self.method_name)
        self.assertEqual(get_method("unique_id").name, "unique_name")
        self.assertRaises(heat_exception.EntityNotFound,
                          get_method, "non_exist")
        self.assertRaises(exceptions.NoUniqueMatch, get_method,
                          "duplicated_name")
