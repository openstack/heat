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

from heat.common import exception
from heat.engine import parser
from heat.engine import template

import heat.engine.resources.software_config.software_config as sc
from heatclient.exc import HTTPNotFound

from heat.tests.common import HeatTestCase
from heat.tests import utils


class SoftwareConfigTest(HeatTestCase):

    def setUp(self):
        super(SoftwareConfigTest, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()
        self.properties = {
            'group': 'Heat::Shell',
            'inputs': [],
            'outputs': [],
            'options': {},
            'config': '#!/bin/bash'
        }
        self.stack = parser.Stack(
            self.ctx, 'software_config_test_stack',
            template.Template({
                'Resources': {
                    'config_mysql': {
                        'Type': 'OS::Heat::SoftwareConfig',
                        'Properties': self.properties
                    }}}))
        self.config = self.stack['config_mysql']
        heat = mock.MagicMock()
        self.heatclient = mock.MagicMock()
        self.config.heat = heat
        heat.return_value = self.heatclient
        self.software_configs = self.heatclient.software_configs

    def test_resource_mapping(self):
        mapping = sc.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(sc.SoftwareConfig,
                         mapping['OS::Heat::SoftwareConfig'])
        self.assertIsInstance(self.config, sc.SoftwareConfig)

    def test_handle_create(self):
        value = mock.MagicMock()
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        value.id = config_id
        self.software_configs.create.return_value = value
        self.config.handle_create()
        self.assertEqual(config_id, self.config.resource_id)

    def test_handle_delete(self):
        self.resource_id = None
        self.assertIsNone(self.config.handle_delete())
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        self.config.resource_id = config_id
        self.software_configs.delete.return_value = None
        self.assertIsNone(self.config.handle_delete())
        self.software_configs.delete.side_effect = HTTPNotFound()
        self.assertIsNone(self.config.handle_delete())

    def test_get_software_config(self):
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        value = mock.MagicMock()
        value.config = '#!/bin/bash'
        self.software_configs.get.return_value = value
        heatclient = self.heatclient
        config = sc.SoftwareConfig.get_software_config(heatclient, config_id)
        self.assertEqual('#!/bin/bash', config)

        self.software_configs.get.side_effect = HTTPNotFound()
        err = self.assertRaises(
            exception.SoftwareConfigMissing,
            self.config.get_software_config,
            heatclient, config_id)
        self.assertEqual(
            ('The config (c8a19429-7fde-47ea-a42f-40045488226c) '
             'could not be found.'), str(err))

    def test_resolve_attribute(self):
        self.assertIsNone(self.config._resolve_attribute('others'))
        self.config.resource_id = None
        self.assertIsNone(self.config._resolve_attribute('config'))
        self.config.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        value = mock.MagicMock()
        value.config = '#!/bin/bash'
        self.software_configs.get.return_value = value
        self.assertEqual(
            '#!/bin/bash', self.config._resolve_attribute('config'))
        self.software_configs.get.side_effect = HTTPNotFound()
        self.assertEqual('', self.config._resolve_attribute('config'))
