
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

from oslo.config import cfg

from heat.engine import clients
from heat.tests.common import HeatTestCase

from .. import clients as rackspace_clients  # noqa


class ClientsTest(HeatTestCase):
    def setUp(self):
        super(ClientsTest, self).setUp()
        cfg.CONF.set_override('cloud_backend', 'rackspace.clients.Clients')
        self.backend = clients.ClientBackend('fake_context')

    def test_client_plugin_loads(self):
        self.assertIsInstance(self.backend, rackspace_clients.Clients)
