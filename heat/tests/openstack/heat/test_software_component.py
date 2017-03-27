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

import contextlib
import mock
import six

from heat.common import exception as exc
from heat.common import template_format
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


class SoftwareComponentTest(common.HeatTestCase):

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
        self.rpc_client = mock.MagicMock()
        self.component._rpc_client = self.rpc_client

        @contextlib.contextmanager
        def exc_filter(*args):
            try:
                yield
            except exc.NotFound:
                pass

        self.rpc_client.ignore_error_by_name.side_effect = exc_filter

    def test_handle_create(self):
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        value = {'id': config_id}
        self.rpc_client.create_software_config.return_value = value
        props = dict(self.component.properties)
        self.component.handle_create()
        self.rpc_client.create_software_config.assert_called_with(
            self.ctx,
            group='component',
            name=None,
            inputs=props['inputs'],
            outputs=props['outputs'],
            config={'configs': props['configs']},
            options=None)
        self.assertEqual(config_id, self.component.resource_id)

    def test_handle_delete(self):
        self.resource_id = None
        self.assertIsNone(self.component.handle_delete())
        config_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        self.component.resource_id = config_id
        self.rpc_client.delete_software_config.return_value = None
        self.assertIsNone(self.component.handle_delete())
        self.rpc_client.delete_software_config.side_effect = exc.NotFound
        self.assertIsNone(self.component.handle_delete())

    def test_resolve_attribute(self):
        self.assertIsNone(self.component._resolve_attribute('others'))
        self.component.resource_id = None
        self.assertIsNone(self.component._resolve_attribute('configs'))
        self.component.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        configs = self.template['resources']['mysql_component'
                                             ]['properties']['configs']
        # configs list is stored in 'config' property of SoftwareConfig
        value = {'config': {'configs': configs}}
        self.rpc_client.show_software_config.return_value = value
        self.assertEqual(configs, self.component._resolve_attribute('configs'))
        self.rpc_client.show_software_config.side_effect = exc.NotFound
        self.assertIsNone(self.component._resolve_attribute('configs'))


class SoftwareComponentValidationTest(common.HeatTestCase):

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
                 err=exc.StackValidationFailed,
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
                 err=exc.StackValidationFailed,
                 err_msg='Property configs not assigned')
        ),
        (
            'empty_configs',
            dict(snippet='''
                 component:
                   type: OS::Heat::SoftwareComponent
                   properties:
                     configs:
                 ''',
                 err=exc.StackValidationFailed,
                 err_msg='resources.component.properties.configs: '
                         'length (0) is out of range (min: 1, max: None)')
        ),
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
                 err=exc.StackValidationFailed,
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
                 err=exc.StackValidationFailed,
                 err_msg='component.properties.configs[0].actions: '
                         'length (0) is out of range (min: 1, max: None)')
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
                 err=exc.StackValidationFailed,
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
                 err=exc.StackValidationFailed,
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
        self.component._rpc_client = mock.MagicMock()

    def test_properties_schema(self):
        if self.err:
            err = self.assertRaises(self.err, self.stack.validate)
            if self.err_msg:
                self.assertIn(self.err_msg, six.text_type(err))
        else:
            self.assertIsNone(self.stack.validate())
