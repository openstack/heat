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

from mistralclient.auth import keystone
import mock

from heat.common import exception
from heat.engine.clients.os import mistral
from heat.tests import common
from heat.tests import utils


class MistralClientPluginTest(common.HeatTestCase):

    def test_create(self):
        self.patchobject(keystone.KeystoneAuthHandler, 'authenticate')
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('mistral')
        client = plugin.client()
        self.assertIsNotNone(client.workflows)


class WorkflowConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(WorkflowConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_workflow_by_identifier = mock.Mock()
        self.ctx.clients.client_plugin(
            'mistral'
        ).get_workflow_by_identifier = self.mock_get_workflow_by_identifier
        self.constraint = mistral.WorkflowConstraint()

    def test_validation(self):
        self.mock_get_workflow_by_identifier.return_value = {}
        self.assertTrue(self.constraint.validate("foo", self.ctx))
        self.mock_get_workflow_by_identifier.assert_called_once_with("foo")

    def test_validation_error(self):
        exc = exception.EntityNotFound(entity='Workflow', name='bar')
        self.mock_get_workflow_by_identifier.side_effect = exc
        self.assertFalse(self.constraint.validate("bar", self.ctx))
        self.mock_get_workflow_by_identifier.assert_called_once_with("bar")
