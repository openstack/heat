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

from heat.common import template_format
from heat.engine.resources import instance
from heat.engine import scheduler

from heat.tests import common
from heat.tests import utils


restarter_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test HARestarter",
  "Parameters" : {},
  "Resources" : {
    "restarter": {
      "Type": "OS::Heat::HARestarter",
      "Properties": {
        "InstanceId": "1234"
      }
    }
  }
}
'''


class RestarterTest(common.HeatTestCase):
    def setUp(self):
        super(RestarterTest, self).setUp()
        utils.setup_dummy_db()

    def create_restarter(self):
        snippet = template_format.parse(restarter_template)
        stack = utils.parse_stack(snippet)
        restarter = instance.Restarter(
            'restarter', snippet['Resources']['restarter'], stack)
        restarter.handle_create = mock.Mock(return_value=None)
        return restarter

    def create_mock_instance(self, stack):
        inst = mock.Mock(spec=instance.Instance)
        inst.resource_id = '1234'
        inst.name = 'instance'
        stack.resources['instance'] = inst

    def test_create(self):
        rsrc = self.create_restarter()
        scheduler.TaskRunner(rsrc.create)()

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.handle_create.assert_called_once_with()

    def test_handle_signal(self):
        rsrc = self.create_restarter()
        scheduler.TaskRunner(rsrc.create)()

        self.create_mock_instance(rsrc.stack)

        rsrc.stack.restart_resource = mock.Mock(return_value=None)

        self.assertIsNone(rsrc.handle_signal())
        rsrc.stack.restart_resource.assert_called_once_with('instance')

    def test_handle_signal_alarm(self):
        rsrc = self.create_restarter()
        scheduler.TaskRunner(rsrc.create)()

        self.create_mock_instance(rsrc.stack)

        rsrc.stack.restart_resource = mock.Mock(return_value=None)

        self.assertIsNone(rsrc.handle_signal({'state': 'Alarm'}))
        rsrc.stack.restart_resource.assert_called_once_with('instance')

    def test_handle_signal_not_alarm(self):
        rsrc = self.create_restarter()
        scheduler.TaskRunner(rsrc.create)()

        self.create_mock_instance(rsrc.stack)

        rsrc.stack.restart_resource = mock.Mock(return_value=None)

        self.assertIsNone(rsrc.handle_signal({'state': 'spam'}))
        self.assertEqual([], rsrc.stack.restart_resource.mock_calls)

    def test_handle_signal_no_instance(self):
        rsrc = self.create_restarter()
        scheduler.TaskRunner(rsrc.create)()

        rsrc.stack.restart_resource = mock.Mock(return_value=None)

        self.assertIsNone(rsrc.handle_signal())
        self.assertEqual([], rsrc.stack.restart_resource.mock_calls)
