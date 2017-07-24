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

from heat.common import template_format
from heat.engine.clients.os import nova
from heat.tests import common
from heat.tests import utils


restarter_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test HARestarter",
  "Parameters" : {},
  "Resources" : {
    "instance": {
      "Type": "OS::Heat::None"
    },
    "restarter": {
      "Type": "OS::Heat::HARestarter",
      "Properties": {
        "InstanceId": {"Ref": "instance"}
      }
    }
  }
}
'''

bogus_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test HARestarter",
  "Parameters" : {},
  "Resources" : {
    "restarter": {
      "Type": "OS::Heat::HARestarter",
      "Properties": {
        "InstanceId": "instance"
      }
    }
  }
}
'''


class RestarterTest(common.HeatTestCase):
    def create_restarter(self, template=restarter_template):
        snippet = template_format.parse(template)
        self.stack = utils.parse_stack(snippet)
        restarter = self.stack['restarter']
        self.patchobject(nova.NovaClientPlugin, 'get_server',
                         return_value=mock.MagicMock())
        restarter.handle_create = mock.Mock(return_value=None)
        self.stack.create()
        return restarter

    def test_create(self):
        rsrc = self.create_restarter()

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.handle_create.assert_called_once_with()

    def test_handle_signal(self):
        rsrc = self.create_restarter()

        with mock.patch.object(rsrc.stack, 'restart_resource') as rr:
            self.assertIsNone(rsrc.handle_signal())
            rr.assert_called_once_with('instance')

    def test_handle_signal_alarm(self):
        rsrc = self.create_restarter()

        with mock.patch.object(rsrc.stack, 'restart_resource') as rr:
            self.assertIsNone(rsrc.handle_signal({'state': 'Alarm'}))
            rr.assert_called_once_with('instance')

    def test_handle_signal_not_alarm(self):
        rsrc = self.create_restarter()

        with mock.patch.object(rsrc.stack, 'restart_resource') as rr:
            self.assertIsNone(rsrc.handle_signal({'state': 'spam'}))
            self.assertEqual([], rr.mock_calls)

    def test_handle_signal_no_instance(self):
        rsrc = self.create_restarter(bogus_template)

        with mock.patch.object(rsrc.stack, 'restart_resource') as rr:
            self.assertIsNone(rsrc.handle_signal())
            self.assertEqual([], rr.mock_calls)
