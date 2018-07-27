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

from heat.tests import common
from heat.tests import utils
import mock


class BlazarClientPluginTest(common.HeatTestCase):

    def setUp(self):
        super(BlazarClientPluginTest, self).setUp()
        self.blazar_client = mock.MagicMock()
        context = utils.dummy_context()
        self.blazar_client_plugin = context.clients.client_plugin('blazar')

    def _stub_client(self):
        self.blazar_client_plugin.client = lambda: self.blazar_client

    def test_create(self):
        client = self.blazar_client_plugin.client()
        self.assertEqual(None, client.blazar_url)

    def test_has_host_pass(self):
        self._stub_client()
        self.blazar_client.host.list.return_value = ['hosta']
        self.assertEqual(True, self.blazar_client_plugin.has_host())

    def test_has_host_fail(self):
        self._stub_client()
        self.blazar_client.host.list.return_value = []
        self.assertEqual(False, self.blazar_client_plugin.has_host())
