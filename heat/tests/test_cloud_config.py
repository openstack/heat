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

from heat.engine import parser
from heat.engine import template

import heat.engine.resources.software_config.cloud_config as cc

from heat.tests.common import HeatTestCase
from heat.tests import utils


class CloudConfigTest(HeatTestCase):

    def setUp(self):
        super(CloudConfigTest, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()
        self.properties = {
            'cloud_config': {'foo': 'bar'}
        }
        self.stack = parser.Stack(
            self.ctx, 'software_config_test_stack',
            template.Template({
                'Resources': {
                    'config_mysql': {
                        'Type': 'OS::Heat::CloudConfig',
                        'Properties': self.properties
                    }}}))
        self.config = self.stack['config_mysql']
        heat = mock.MagicMock()
        self.config.heat = heat
        self.software_configs = heat.return_value.software_configs

    def test_resource_mapping(self):
        mapping = cc.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(cc.CloudConfig,
                         mapping['OS::Heat::CloudConfig'])
        self.assertIsInstance(self.config, cc.CloudConfig)

    def test_handle_create(self):
        sc = mock.MagicMock()
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        sc.id = config_id
        self.software_configs.create.return_value = sc
        self.config.handle_create()
        self.assertEqual(config_id, self.config.resource_id)
        kwargs = self.software_configs.create.call_args[1]
        self.assertEqual('#cloud-config\n{foo: bar}\n', kwargs['config'])
