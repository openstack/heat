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

import uuid

import mock

from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


class CloudConfigTest(common.HeatTestCase):

    def setUp(self):
        super(CloudConfigTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.properties = {
            'cloud_config': {'foo': 'bar'}
        }
        self.stack = stack.Stack(
            self.ctx, 'software_config_test_stack',
            template.Template({
                'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'config_mysql': {
                        'Type': 'OS::Heat::CloudConfig',
                        'Properties': self.properties
                    }}}))
        self.config = self.stack['config_mysql']
        self.rpc_client = mock.MagicMock()
        self.config._rpc_client = self.rpc_client

    def test_handle_create(self):
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        value = {'id': config_id}
        self.rpc_client.create_software_config.return_value = value
        self.config.id = 5
        self.config.uuid = uuid.uuid4().hex
        self.config.handle_create()
        self.assertEqual(config_id, self.config.resource_id)
        kwargs = self.rpc_client.create_software_config.call_args[1]
        self.assertEqual({
            'name': self.config.physical_resource_name(),
            'config': '#cloud-config\n{foo: bar}\n',
            'group': 'Heat::Ungrouped'
        }, kwargs)
