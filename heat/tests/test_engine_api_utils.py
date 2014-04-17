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

from datetime import datetime
import uuid

import mock

from heat.common.identifier import EventIdentifier
from heat.common import template_format
from heat.engine import api
from heat.engine.event import Event
from heat.engine import parameters
from heat.engine import parser
from heat.engine import resource
from heat.rpc import api as rpc_api
from heat.tests.common import HeatTestCase
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils


class FormatTest(HeatTestCase):
    def setUp(self):
        super(FormatTest, self).setUp()
        utils.setup_dummy_db()

        template = parser.Template({
            'Resources': {
                'generic1': {'Type': 'GenericResourceType'},
                'generic2': {
                    'Type': 'GenericResourceType',
                    'DependsOn': 'generic1'}
            }
        })
        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template, stack_id=str(uuid.uuid4()))

    def _dummy_event(self, event_id):
        resource = self.stack['generic1']
        return Event(utils.dummy_context(), self.stack, 'CREATE', 'COMPLETE',
                     'state changed', 'z3455xyc-9f88-404d-a85b-5315293e67de',
                     resource.properties, resource.name, resource.type(),
                     uuid='abc123yc-9f88-404d-a85b-531529456xyz',
                     id=event_id)

    def test_format_stack_resource(self):
        res = self.stack['generic1']

        resource_keys = set((
            rpc_api.RES_UPDATED_TIME,
            rpc_api.RES_NAME,
            rpc_api.RES_PHYSICAL_ID,
            rpc_api.RES_METADATA,
            rpc_api.RES_ACTION,
            rpc_api.RES_STATUS,
            rpc_api.RES_STATUS_DATA,
            rpc_api.RES_TYPE,
            rpc_api.RES_ID,
            rpc_api.RES_STACK_ID,
            rpc_api.RES_STACK_NAME,
            rpc_api.RES_REQUIRED_BY))

        resource_details_keys = resource_keys.union(set(
            (rpc_api.RES_DESCRIPTION, rpc_api.RES_METADATA)))

        formatted = api.format_stack_resource(res, True)
        self.assertEqual(resource_details_keys, set(formatted.keys()))

        formatted = api.format_stack_resource(res, False)
        self.assertEqual(resource_keys, set(formatted.keys()))

    def test_format_stack_resource_required_by(self):
        res1 = api.format_stack_resource(self.stack['generic1'])
        res2 = api.format_stack_resource(self.stack['generic2'])
        self.assertEqual(['generic2'], res1['required_by'])
        self.assertEqual([], res2['required_by'])

    def test_format_event_identifier_uuid(self):
        self._test_format_event('abc123yc-9f88-404d-a85b-531529456xyz')

    def _test_format_event(self, event_id):
        event = self._dummy_event(event_id)

        event_keys = set((
            rpc_api.EVENT_ID,
            rpc_api.EVENT_STACK_ID,
            rpc_api.EVENT_STACK_NAME,
            rpc_api.EVENT_TIMESTAMP,
            rpc_api.EVENT_RES_NAME,
            rpc_api.EVENT_RES_PHYSICAL_ID,
            rpc_api.EVENT_RES_ACTION,
            rpc_api.EVENT_RES_STATUS,
            rpc_api.EVENT_RES_STATUS_DATA,
            rpc_api.EVENT_RES_TYPE,
            rpc_api.EVENT_RES_PROPERTIES))

        formatted = api.format_event(event)
        self.assertEqual(event_keys, set(formatted.keys()))

        event_id_formatted = formatted[rpc_api.EVENT_ID]
        event_identifier = EventIdentifier(event_id_formatted['tenant'],
                                           event_id_formatted['stack_name'],
                                           event_id_formatted['stack_id'],
                                           event_id_formatted['path'])
        self.assertEqual(event_id, event_identifier.event_id)

    @mock.patch.object(api, 'format_stack_resource')
    def test_format_stack_preview(self, mock_fmt_resource):
        def mock_format_resources(res):
            return 'fmt%s' % res

        mock_fmt_resource.side_effect = mock_format_resources
        resources = [1, [2, [3]]]
        self.stack.preview_resources = mock.Mock(return_value=resources)

        stack = api.format_stack_preview(self.stack)
        self.assertIsInstance(stack, dict)
        self.assertEqual('test_stack', stack['stack_name'])
        self.assertIn('resources', stack)
        self.assertEqual(['fmt1', ['fmt2', ['fmt3']]], stack['resources'])

    def test_format_stack(self):
        self.stack.created_time = datetime(1970, 1, 1)
        info = api.format_stack(self.stack)

        aws_id = ('arn:openstack:heat::test_tenant_id:'
                  'stacks/test_stack/' + self.stack.id)
        expected_stack_info = {
            'capabilities': [],
            'creation_time': '1970-01-01T00:00:00Z',
            'description': 'No description',
            'disable_rollback': True,
            'notification_topics': [],
            'stack_action': '',
            'stack_name': 'test_stack',
            'stack_status': '',
            'stack_status_reason': '',
            'template_description': 'No description',
            'timeout_mins': None,
            'parameters': {
                'AWS::Region': 'ap-southeast-1',
                'AWS::StackId': aws_id,
                'AWS::StackName': 'test_stack'},
            'stack_identity': {
                'path': '',
                'stack_id': self.stack.id,
                'stack_name': 'test_stack',
                'tenant': 'test_tenant_id'},
            'updated_time': None}
        self.assertEqual(expected_stack_info, info)

    def test_format_stack_created_time(self):
        self.stack.created_time = None
        info = api.format_stack(self.stack)
        self.assertIsNotNone(info['creation_time'])

    def test_format_stack_updated_time(self):
        self.stack.updated_time = None
        info = api.format_stack(self.stack)
        self.assertIsNone(info['updated_time'])

        self.stack.updated_time = datetime(1970, 1, 1)
        info = api.format_stack(self.stack)
        self.assertEqual('1970-01-01T00:00:00Z', info['updated_time'])

    @mock.patch.object(api, 'format_stack_outputs')
    def test_format_stack_adds_outputs(self, mock_fmt_outputs):
        mock_fmt_outputs.return_value = 'foobar'
        self.stack.action = 'CREATE'
        self.stack.status = 'COMPLETE'
        info = api.format_stack(self.stack)
        self.assertEqual('foobar', info[rpc_api.STACK_OUTPUTS])


class FormatValidateParameterTest(HeatTestCase):

    base_template = '''
    {
        "AWSTemplateFormatVersion" : "2010-09-09",
        "Description" : "test",
        "Parameters" : {
            %s
        }
    }
    '''

    base_template_hot = '''
    {
        "heat_template_version" : "2013-05-23",
        "description" : "test",
        "parameters" : {
            %s
        }
    }
    '''

    scenarios = [
        ('simple',
         dict(template=base_template,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "Type": "String",
                        "Description": "Name of SSH key pair"
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('default',
         dict(template=base_template,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "Type": "String",
                        "Description": "Name of SSH key pair",
                        "Default": "dummy"
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'Default': 'dummy',
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('min_length_constraint',
         dict(template=base_template,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "Type": "String",
                        "Description": "Name of SSH key pair",
                        "MinLength": 4
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MinLength': 4,
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('max_length_constraint',
         dict(template=base_template,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "Type": "String",
                        "Description": "Name of SSH key pair",
                        "MaxLength": 10
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MaxLength': 10,
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('min_max_length_constraint',
         dict(template=base_template,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "Type": "String",
                        "Description": "Name of SSH key pair",
                        "MinLength": 4,
                        "MaxLength": 10
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MinLength': 4,
                  'MaxLength': 10,
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('min_value_constraint',
         dict(template=base_template,
              param_name='MyNumber',
              param='''
                    "MyNumber": {
                        "Type": "Number",
                        "Description": "A number",
                        "MinValue": 4
                    }
                    ''',
              expected={
                  'Type': 'Number',
                  'Description': 'A number',
                  'MinValue': 4,
                  'NoEcho': 'false',
                  'Label': 'MyNumber'
              })
         ),
        ('max_value_constraint',
         dict(template=base_template,
              param_name='MyNumber',
              param='''
                    "MyNumber": {
                        "Type": "Number",
                        "Description": "A number",
                        "MaxValue": 10
                    }
                    ''',
              expected={
                  'Type': 'Number',
                  'Description': 'A number',
                  'MaxValue': 10,
                  'NoEcho': 'false',
                  'Label': 'MyNumber'
              })
         ),
        ('min_max_value_constraint',
         dict(template=base_template,
              param_name='MyNumber',
              param='''
                    "MyNumber": {
                        "Type": "Number",
                        "Description": "A number",
                        "MinValue": 4,
                        "MaxValue": 10
                    }
                    ''',
              expected={
                  'Type': 'Number',
                  'Description': 'A number',
                  'MinValue': 4,
                  'MaxValue': 10,
                  'NoEcho': 'false',
                  'Label': 'MyNumber'
              })
         ),
        ('allowed_values_constraint',
         dict(template=base_template,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "Type": "String",
                        "Description": "Name of SSH key pair",
                        "AllowedValues": [ "foo", "bar", "blub" ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'AllowedValues': ['foo', 'bar', 'blub'],
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('allowed_pattern_constraint',
         dict(template=base_template,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "Type": "String",
                        "Description": "Name of SSH key pair",
                        "AllowedPattern": "[a-zA-Z0-9]+"
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'AllowedPattern': "[a-zA-Z0-9]+",
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('multiple_constraints',
         dict(template=base_template,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "Type": "String",
                        "Description": "Name of SSH key pair",
                        "MinLength": 4,
                        "MaxLength": 10,
                        "AllowedValues": [
                            "foo", "bar", "blub"
                        ],
                        "AllowedPattern": "[a-zA-Z0-9]+"
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MinLength': 4,
                  'MaxLength': 10,
                  'AllowedValues': ['foo', 'bar', 'blub'],
                  'AllowedPattern': "[a-zA-Z0-9]+",
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('simple_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair"
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('default_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair",
                        "default": "dummy"
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'Default': 'dummy',
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('min_length_constraint_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair",
                        "constraints": [
                            { "length": { "min": 4} }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MinLength': 4,
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('max_length_constraint_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair",
                        "constraints": [
                            { "length": { "max": 10} }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MaxLength': 10,
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('min_max_length_constraint_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair",
                        "constraints": [
                            { "length": { "min":4, "max": 10} }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MinLength': 4,
                  'MaxLength': 10,
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('min_value_constraint_hot',
         dict(template=base_template_hot,
              param_name='MyNumber',
              param='''
                    "MyNumber": {
                        "type": "number",
                        "description": "A number",
                        "constraints": [
                            { "range": { "min": 4} }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'Number',
                  'Description': 'A number',
                  'MinValue': 4,
                  'NoEcho': 'false',
                  'Label': 'MyNumber'
              })
         ),
        ('max_value_constraint_hot',
         dict(template=base_template_hot,
              param_name='MyNumber',
              param='''
                    "MyNumber": {
                        "type": "number",
                        "description": "A number",
                        "constraints": [
                            { "range": { "max": 10} }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'Number',
                  'Description': 'A number',
                  'MaxValue': 10,
                  'NoEcho': 'false',
                  'Label': 'MyNumber'
              })
         ),
        ('min_max_value_constraint_hot',
         dict(template=base_template_hot,
              param_name='MyNumber',
              param='''
                    "MyNumber": {
                        "type": "number",
                        "description": "A number",
                        "constraints": [
                            { "range": { "min": 4, "max": 10} }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'Number',
                  'Description': 'A number',
                  'MinValue': 4,
                  'MaxValue': 10,
                  'NoEcho': 'false',
                  'Label': 'MyNumber'
              })
         ),
        ('allowed_values_constraint_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair",
                        "constraints": [
                            { "allowed_values": [
                                "foo", "bar", "blub"
                              ]
                            }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'AllowedValues': ['foo', 'bar', 'blub'],
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('allowed_pattern_constraint_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair",
                        "constraints": [
                            { "allowed_pattern": "[a-zA-Z0-9]+" }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'AllowedPattern': "[a-zA-Z0-9]+",
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('multiple_constraints_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair",
                        "constraints": [
                            { "length": { "min": 4, "max": 10} },
                            { "allowed_values": [
                                "foo", "bar", "blub"
                              ]
                            },
                            { "allowed_pattern": "[a-zA-Z0-9]+" }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MinLength': 4,
                  'MaxLength': 10,
                  'AllowedValues': ['foo', 'bar', 'blub'],
                  'AllowedPattern': "[a-zA-Z0-9]+",
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('constraint_description_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair",
                        "constraints": [
                            { "length": { "min": 4},
                              "description": "Big enough" }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MinLength': 4,
                  'ConstraintDescription': 'Big enough',
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
        ('constraint_multiple_descriptions_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Name of SSH key pair",
                        "constraints": [
                            { "length": { "min": 4},
                              "description": "Big enough." },
                            { "allowed_pattern": "[a-zA-Z0-9]+",
                              "description": "Only letters." }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Name of SSH key pair',
                  'MinLength': 4,
                  'AllowedPattern': "[a-zA-Z0-9]+",
                  'ConstraintDescription': 'Big enough. Only letters.',
                  'NoEcho': 'false',
                  'Label': 'KeyName'
              })
         ),
    ]

    def test_format_validate_parameter(self):
        """
        Test format of a parameter.
        """

        t = template_format.parse(self.template % self.param)
        tmpl = parser.Template(t)

        tmpl_params = parameters.Parameters(None, tmpl, validate_value=False)
        param = tmpl_params.params[self.param_name]
        param_formated = api.format_validate_parameter(param)
        self.assertEqual(self.expected, param_formated)


class FormatSoftwareConfigDeploymentTest(HeatTestCase):

    def _dummy_software_config(self):
        config = mock.Mock()
        config.name = 'config_mysql'
        config.group = 'Heat::Shell'
        config.id = str(uuid.uuid4())
        config.config = {
            'inputs': [{'name': 'bar'}],
            'outputs': [{'name': 'result'}],
            'options': {},
            'config': '#!/bin/bash\n'
        }
        return config

    def _dummy_software_deployment(self):
        config = self._dummy_software_config()
        deployment = mock.Mock()
        deployment.config = config
        deployment.id = str(uuid.uuid4())
        deployment.server_id = str(uuid.uuid4())
        deployment.input_values = {'bar': 'baaaaa'}
        deployment.output_values = {'result': '0'}
        deployment.action = 'INIT'
        deployment.status = 'COMPLETE'
        deployment.status_reason = 'Because'
        return deployment

    def test_format_software_config(self):
        config = self._dummy_software_config()
        result = api.format_software_config(config)
        self.assertIsNotNone(result)
        self.assertEqual([{'name': 'bar'}], result['inputs'])
        self.assertEqual([{'name': 'result'}], result['outputs'])
        self.assertEqual({}, result['options'])

    def test_format_software_config_none(self):
        self.assertIsNone(api.format_software_config(None))

    def test_format_software_deployment(self):
        deployment = self._dummy_software_deployment()
        result = api.format_software_deployment(deployment)
        self.assertIsNotNone(result)
        self.assertEqual(deployment.id, result['id'])
        self.assertEqual(deployment.config.id, result['config_id'])
        self.assertEqual(deployment.server_id, result['server_id'])
        self.assertEqual(deployment.input_values, result['input_values'])
        self.assertEqual(deployment.output_values, result['output_values'])
        self.assertEqual(deployment.action, result['action'])
        self.assertEqual(deployment.status, result['status'])
        self.assertEqual(deployment.status_reason, result['status_reason'])

    def test_format_software_deployment_none(self):
        self.assertIsNone(api.format_software_deployment(None))
