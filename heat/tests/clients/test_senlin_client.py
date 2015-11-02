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

from heat.engine.clients.os import senlin as senlin_plugin
from heat.tests import common
from heat.tests import utils
from senlinclient.common import exc


class SenlinClientPluginTests(common.HeatTestCase):

    def test_cluster_get(self):
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('senlin')
        client = plugin.client()
        self.assertIsNotNone(client.clusters)


class ProfileConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(ProfileConstraintTest, self).setUp()
        self.senlin_client = mock.MagicMock()
        self.ctx = utils.dummy_context()
        self.mock_get_profile = mock.Mock()
        self.ctx.clients.client(
            'senlin').get_profile = self.mock_get_profile
        self.constraint = senlin_plugin.ProfileConstraint()

    def test_validate_true(self):
        self.mock_get_profile.return_value = None
        self.assertTrue(self.constraint.validate("PROFILE_ID", self.ctx))

    def test_validate_false(self):
        self.mock_get_profile.side_effect = exc.HTTPNotFound
        self.assertFalse(self.constraint.validate("PROFILE_ID", self.ctx))
