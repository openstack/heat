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

from barbicanclient import exceptions
import mock

from heat.common import exception
from heat.engine.clients.os import barbican
from heat.tests import common
from heat.tests import utils


class BarbicanClientPluginTest(common.HeatTestCase):

    def setUp(self):
        super(BarbicanClientPluginTest, self).setUp()
        self.barbican_client = mock.MagicMock()
        con = utils.dummy_context()
        c = con.clients
        self.barbican_plugin = c.client_plugin('barbican')
        self.barbican_plugin._client = self.barbican_client

    def test_create(self):
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('barbican')
        client = plugin.client()
        self.assertIsNotNone(client.orders)

    def test_get_secret_by_ref(self):
        self.barbican_client.secrets.get(
        )._get_formatted_entity.return_value = {}
        self.assertEqual({}, self.barbican_plugin.get_secret_by_ref("secret"))

    def test_get_secret_by_ref_not_found(self):
        self.barbican_client.secrets.get(
        )._get_formatted_entity.side_effect = exceptions.HTTPClientError(
            message="Not Found")
        self.assertRaises(
            exception.EntityNotFound,
            self.barbican_plugin.get_secret_by_ref,
            "secret")


class SecretConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(SecretConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_secret_by_ref = mock.Mock()
        self.ctx.clients.client_plugin(
            'barbican').get_secret_by_ref = self.mock_get_secret_by_ref
        self.constraint = barbican.SecretConstraint()

    def test_validation(self):
        self.mock_get_secret_by_ref.return_value = {}
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        self.mock_get_secret_by_ref.side_effect = exception.EntityNotFound(
            entity='Secret', name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))


class ContainerConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(ContainerConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_container_by_ref = mock.Mock()
        self.ctx.clients.client_plugin(
            'barbican').get_container_by_ref = self.mock_get_container_by_ref
        self.constraint = barbican.ContainerConstraint()

    def test_validation(self):
        self.mock_get_container_by_ref.return_value = {}
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        self.mock_get_container_by_ref.side_effect = exception.EntityNotFound(
            entity='Container', name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))
