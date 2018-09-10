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

from heat.tests import common
from heat.tests import utils


class ZunClientPluginTest(common.HeatTestCase):

    def setUp(self):
        super(ZunClientPluginTest, self).setUp()
        self.client = mock.Mock()
        context = utils.dummy_context()
        self.plugin = context.clients.client_plugin('zun')
        self.plugin.client = lambda **kw: self.client
        self.resource_id = '123456'

    def test_create(self):
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('zun')
        client = plugin.client()
        self.assertEqual('http://server.test:5000/v3',
                         client.containers.api.session.auth.endpoint)
        self.assertEqual('1.12',
                         client.api_version.get_string())

    def test_container_update(self):
        prop_diff = {'cpu': 10, 'memory': 10, 'name': 'fake-container'}
        self.plugin.update_container(self.resource_id, **prop_diff)
        self.client.containers.update.assert_called_once_with(
            self.resource_id, cpu=10, memory=10, name='fake-container')
