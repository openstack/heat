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

from heat.engine.clients.os import zaqar

from heat.tests import common
from heat.tests import utils


class ZaqarClientPluginTest(common.HeatTestCase):

    def test_create(self):
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('zaqar')
        client = plugin.client()
        self.assertIsNotNone(client.queue)

    def test_create_for_tenant(self):
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('zaqar')
        client = plugin.create_for_tenant('other_tenant', 'token')
        self.assertEqual('other_tenant',
                         client.conf['auth_opts']['options']['os_project_id'])
        self.assertEqual('token',
                         client.conf['auth_opts']['options']['os_auth_token'])

    def test_event_sink(self):
        context = utils.dummy_context()
        client = context.clients.client('zaqar')
        fake_queue = mock.MagicMock()
        client.queue = lambda x, auto_create: fake_queue
        sink = zaqar.ZaqarEventSink('myqueue')
        sink.consume(context, {'hello': 'world'})
        fake_queue.post.assert_called_once_with(
            {'body': {'hello': 'world'}, 'ttl': 3600})
