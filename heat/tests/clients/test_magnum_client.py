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

from magnumclient import exceptions as mc_exc
import mock

from heat.engine.clients.os import magnum as mc
from heat.tests import common
from heat.tests import utils


class MagnumClientPluginTest(common.HeatTestCase):

    def test_create(self):
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('magnum')
        client = plugin.client()
        self.assertEqual('http://server.test:5000/v3',
                         client.cluster_templates.api.session.auth.endpoint)


class fake_cluster_template(object):
    def __init__(self, id=None, name=None):
        self.uuid = id
        self.name = name


class ClusterTemplateConstraintTest(common.HeatTestCase):
    def setUp(self):
        super(ClusterTemplateConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_cluster_template_get = mock.Mock()
        self.ctx.clients.client_plugin(
            'magnum').client().cluster_templates.get = \
            self.mock_cluster_template_get
        self.constraint = mc.ClusterTemplateConstraint()

    def test_validate(self):
        self.mock_cluster_template_get.return_value = fake_cluster_template(
            id='my_cluster_template')
        self.assertTrue(self.constraint.validate(
            'my_cluster_template', self.ctx))

    def test_validate_fail(self):
        self.mock_cluster_template_get.side_effect = mc_exc.NotFound()
        self.assertFalse(self.constraint.validate(
            "bad_cluster_template", self.ctx))


class BaymodelConstraintTest(common.HeatTestCase):
    def setUp(self):
        super(BaymodelConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_baymodel_get = mock.Mock()
        self.ctx.clients.client_plugin(
            'magnum').client().baymodels.get = self.mock_baymodel_get
        self.constraint = mc.BaymodelConstraint()

    def test_validate(self):
        self.mock_baymodel_get.return_value = fake_cluster_template(
            id='badbaymodel')
        self.assertTrue(self.constraint.validate("mybaymodel", self.ctx))

    def test_validate_fail(self):
        self.mock_baymodel_get.side_effect = mc_exc.NotFound()
        self.assertFalse(self.constraint.validate("badbaymodel", self.ctx))
