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
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.software_config import software_component as sc
from heat.engine import stack
from heat.engine import template
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heatclient.exc import HTTPNotFound


class SoftwareComponentTest(HeatTestCase):

    def setUp(self):
        super(SoftwareComponentTest, self).setUp()
        self.ctx = utils.dummy_context()

        tpl = '''
        heat_template_version: 2013-05-23
        resources:
          mysql_component:
            type: OS::Heat::SoftwareComponent
            properties:
              configs:
                - actions: [CREATE]
                  config: |
                    #!/bin/bash
                    echo "Create MySQL"
                  tool: script
                - actions: [UPDATE]
                  config: |
                    #!/bin/bash
                    echo "Update MySQL"
                  tool: script
              inputs:
                - name: mysql_port
              outputs:
                - name: root_password
        '''

        self.template = template_format.parse(tpl)
        self.stack = stack.Stack(
            self.ctx, 'software_component_test_stack',
            template.Template(self.template))
        self.component = self.stack['mysql_component']
        heat = mock.MagicMock()
        self.heatclient = mock.MagicMock()
        self.component.heat = heat
        heat.return_value = self.heatclient
        self.software_configs = self.heatclient.software_configs

    def test_resource_mapping(self):
        mapping = sc.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(sc.SoftwareComponent,
                         mapping['OS::Heat::SoftwareComponent'])
        self.assertIsInstance(self.component, sc.SoftwareComponent)

    def test_handle_create(self):
        value = mock.MagicMock()
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        value.id = config_id
        self.software_configs.create.return_value = value
        self.component.handle_create()
        self.assertEqual(config_id, self.component.resource_id)

    def test_handle_delete(self):
        self.resource_id = None
        self.assertIsNone(self.component.handle_delete())
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        self.component.resource_id = config_id
        self.software_configs.delete.return_value = None
        self.assertIsNone(self.component.handle_delete())
        self.software_configs.delete.side_effect = HTTPNotFound()
        self.assertIsNone(self.component.handle_delete())

    def test_resolve_attribute(self):
        self.assertIsNone(self.component._resolve_attribute('others'))
        self.component.resource_id = None
        self.assertIsNone(self.component._resolve_attribute('configs'))
        self.component.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        value = mock.MagicMock()
        configs = self.\
            template['resources']['mysql_component']['properties']['configs']
        # configs list is stored in 'config' property of SoftwareConfig
        value.config = {'configs': configs}
        self.software_configs.get.return_value = value
        self.assertEqual(configs, self.component._resolve_attribute('configs'))
        self.software_configs.get.side_effect = HTTPNotFound()
        self.assertIsNone(self.component._resolve_attribute('configs'))


class SoftwareComponentValidationTest(HeatTestCase):

    scenarios = [
        (
            'component_full',
            dict(snippet='''
                 component:
                   type: OS::Heat::SoftwareComponent
                   properties:
                     configs:
                       - actions: [CREATE]
                         config: |
                           #!/bin/bash
                           echo CREATE $foo
                         tool: script
                     inputs:
                       - name: foo
                     outputs:
                       - name: bar
                     options:
                       opt1: blah
                 ''',
                 err=None,
                 err_msg=None)
        ),
        (
            'no_input_output_options',
            dict(snippet='''
                 component:
                   type: OS::Heat::SoftwareComponent
                   properties:
                     configs:
                       - actions: [CREATE]
                         config: |
                           #!/bin/bash
                           echo CREATE $foo
                         tool: script
                 ''',
                 err=None,
                 err_msg=None)
        ),
        (
            'wrong_property_config',
            dict(snippet='''
                 component:
                   type: OS::Heat::SoftwareComponent
                   properties:
                     config: #!/bin/bash
                     configs:
                       - actions: [CREATE]
                         config: |
                           #!/bin/bash
                           echo CREATE $foo
                         tool: script
                 ''',
                 err=exception.StackValidationFailed,
                 err_msg='Unknown Property config')
        ),
        (
            'missing_configs',
            dict(snippet='''
                 component:
                   type: OS::Heat::SoftwareComponent
                   properties:
                     inputs:
                       - name: foo
                 ''',
                 err=exception.StackValidationFailed,
                 err_msg='Property configs not assigned')
        ),
        # do not test until bug #1350840
#         (
#             'empty_configs',
#             dict(snippet='''
#                  component:
#                    type: OS::Heat::SoftwareComponent
#                    properties:
#                      configs:
#                  ''',
#                  err=exception.StackValidationFailed,
#                  err_msg='configs length (0) is out of range '
#                                     '(min: 1, max: None)')
#         ),
        (
            'invalid_configs',
            dict(snippet='''
                 component:
                   type: OS::Heat::SoftwareComponent
                   properties:
                     configs:
                       actions: [CREATE]
                       config: #!/bin/bash
                       tool: script
                 ''',
                 err=exception.StackValidationFailed,
                 err_msg='is not a list')
        ),
        (
            'config_empty_actions',
            dict(snippet='''
                 component:
                   type: OS::Heat::SoftwareComponent
                   properties:
                     configs:
                       - actions: []
                         config: #!/bin/bash
                         tool: script
                 ''',
                 err=exception.StackValidationFailed,
                 err_msg='actions length (0) is out of range '
                         '(min: 1, max: None)')
        ),
        (
            'multiple_configs_per_action_single',
            dict(snippet='''
                 component:
                   type: OS::Heat::SoftwareComponent
                   properties:
                     configs:
                       - actions: [CREATE]
                         config: #!/bin/bash
                         tool: script
                       - actions: [CREATE]
                         config: #!/bin/bash
                         tool: script
                 ''',
                 err=exception.StackValidationFailed,
                 err_msg='Defining more than one configuration for the same '
                         'action in SoftwareComponent "component" is not '
                         'allowed.')
        ),
        (
            'multiple_configs_per_action_overlapping_list',
            dict(snippet='''
                 component:
                   type: OS::Heat::SoftwareComponent
                   properties:
                     configs:
                       - actions: [CREATE, UPDATE, RESUME]
                         config: #!/bin/bash
                         tool: script
                       - actions: [UPDATE]
                         config: #!/bin/bash
                         tool: script
                 ''',
                 err=exception.StackValidationFailed,
                 err_msg='Defining more than one configuration for the same '
                         'action in SoftwareComponent "component" is not '
                         'allowed.')
        ),
    ]

    def setUp(self):
        super(SoftwareComponentValidationTest, self).setUp()
        self.ctx = utils.dummy_context()

        tpl = '''
        heat_template_version: 2013-05-23
        resources:
          %s
        ''' % self.snippet

        self.template = template_format.parse(tpl)
        self.stack = stack.Stack(
            self.ctx, 'software_component_test_stack',
            template.Template(self.template))
        self.component = self.stack['component']
        heat = mock.MagicMock()
        self.heatclient = mock.MagicMock()
        self.component.heat = heat
        heat.return_value = self.heatclient
        self.software_configs = self.heatclient.software_configs

    def test_properties_schema(self):
        if self.err:
            err = self.assertRaises(self.err, self.stack.validate)
            if self.err_msg:
                self.assertIn(self.err_msg, six.text_type(err))
        else:
            self.assertIsNone(self.stack.validate())
