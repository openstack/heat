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

import datetime as dt
import json
import uuid

import mock
from oslo_utils import timeutils
import six

from heat.common import exception
from heat.common import template_format
from heat.common import timeutils as heat_timeutils
from heat.db.sqlalchemy import models
from heat.engine import api
from heat.engine.cfn import parameters as cfn_param
from heat.engine import event
from heat.engine import parent_rsrc
from heat.engine import stack as parser
from heat.engine import template
from heat.objects import event as event_object
from heat.rpc import api as rpc_api
from heat.tests import common
from heat.tests import utils

datetime = dt.datetime


class FormatTest(common.HeatTestCase):
    def setUp(self):
        super(FormatTest, self).setUp()

        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'generic1': {'Type': 'GenericResourceType',
                             'Properties': {'k1': 'v1'}},
                'generic2': {
                    'Type': 'GenericResourceType',
                    'DependsOn': 'generic1'},
                'generic3': {'Type': 'ResWithShowAttrType'},
                'generic4': {'Type': 'StackResourceType'}
            }
        })
        self.context = utils.dummy_context()
        self.stack = parser.Stack(self.context, 'test_stack',
                                  tmpl, stack_id=str(uuid.uuid4()))

    def _dummy_event(self, res_properties=None):
        resource = self.stack['generic1']
        ev_uuid = 'abc123yc-9f88-404d-a85b-531529456xyz'
        ev = event.Event(self.context, self.stack, 'CREATE',
                         'COMPLETE', 'state changed',
                         'z3455xyc-9f88-404d-a85b-5315293e67de',
                         resource._rsrc_prop_data_id,
                         resource._stored_properties_data,
                         resource.name, resource.type(),
                         uuid=ev_uuid)
        ev.store()
        return event_object.Event.get_all_by_stack(
            self.context, self.stack.id, filters={'uuid': ev_uuid})[0]

    def test_format_stack_resource(self):
        self.stack.created_time = datetime(2015, 8, 3, 17, 5, 1)
        self.stack.updated_time = datetime(2015, 8, 3, 17, 6, 2)
        res = self.stack['generic1']

        resource_keys = set((
            rpc_api.RES_CREATION_TIME,
            rpc_api.RES_UPDATED_TIME,
            rpc_api.RES_NAME,
            rpc_api.RES_PHYSICAL_ID,
            rpc_api.RES_ACTION,
            rpc_api.RES_STATUS,
            rpc_api.RES_STATUS_DATA,
            rpc_api.RES_TYPE,
            rpc_api.RES_ID,
            rpc_api.RES_STACK_ID,
            rpc_api.RES_STACK_NAME,
            rpc_api.RES_REQUIRED_BY,
        ))

        resource_details_keys = resource_keys.union(set((
            rpc_api.RES_DESCRIPTION,
            rpc_api.RES_METADATA,
            rpc_api.RES_ATTRIBUTES,
        )))

        formatted = api.format_stack_resource(res, True)
        self.assertEqual(resource_details_keys, set(formatted.keys()))

        formatted = api.format_stack_resource(res, False)
        self.assertEqual(resource_keys, set(formatted.keys()))
        self.assertEqual(heat_timeutils.isotime(self.stack.created_time),
                         formatted[rpc_api.RES_CREATION_TIME])
        self.assertEqual(heat_timeutils.isotime(self.stack.updated_time),
                         formatted[rpc_api.RES_UPDATED_TIME])
        self.assertEqual(res.INIT, formatted[rpc_api.RES_ACTION])

    def test_format_stack_resource_no_attrs(self):
        res = self.stack['generic1']
        formatted = api.format_stack_resource(res, True, with_attr=False)
        self.assertNotIn(rpc_api.RES_ATTRIBUTES, formatted)
        self.assertIn(rpc_api.RES_METADATA, formatted)

    def test_format_stack_resource_has_been_deleted(self):
        # assume the stack and resource have been deleted,
        # to test the resource's action inherit from stack
        self.stack.state_set(self.stack.DELETE, self.stack.COMPLETE,
                             'test_delete')
        res = self.stack['generic1']
        formatted = api.format_stack_resource(res, False)
        self.assertEqual(res.DELETE, formatted[rpc_api.RES_ACTION])

    def test_format_stack_resource_has_been_rollback(self):
        # Rollback a stack, the resources perhaps have not been
        # created yet or have been deleted when rollback.
        # To test the resource's action inherit from stack
        self.stack.state_set(self.stack.ROLLBACK, self.stack.COMPLETE,
                             'test_rollback')
        res = self.stack['generic1']
        formatted = api.format_stack_resource(res, False)
        self.assertEqual(res.ROLLBACK, formatted[rpc_api.RES_ACTION])

    @mock.patch.object(api, 'format_resource_properties')
    def test_format_stack_resource_with_props(self, mock_format_props):
        mock_format_props.return_value = 'formatted_res_props'
        res = self.stack['generic1']

        formatted = api.format_stack_resource(res, True, with_props=True)
        formatted_props = formatted[rpc_api.RES_PROPERTIES]
        self.assertEqual('formatted_res_props', formatted_props)

    @mock.patch.object(api, 'format_resource_attributes')
    def test_format_stack_resource_with_attributes(self, mock_format_attrs):
        mock_format_attrs.return_value = 'formatted_resource_attrs'
        res = self.stack['generic1']

        formatted = api.format_stack_resource(res, True, with_attr=['a', 'b'])
        formatted_attrs = formatted[rpc_api.RES_ATTRIBUTES]
        self.assertEqual('formatted_resource_attrs', formatted_attrs)

    def test_format_resource_attributes(self):
        res = self.stack['generic1']
        # the _resolve_attribute method of  'generic1' returns map with all
        # attributes except 'show' (because it's None in this test)
        formatted_attributes = api.format_resource_attributes(res)
        expected = {'foo': 'generic1', 'Foo': 'generic1'}
        self.assertEqual(expected, formatted_attributes)

    def test_format_resource_attributes_show_attribute(self):
        res = self.stack['generic3']
        res.resource_id = 'generic3_id'
        formatted_attributes = api.format_resource_attributes(res)
        self.assertEqual(3, len(formatted_attributes))
        self.assertIn('foo', formatted_attributes)
        self.assertIn('Foo', formatted_attributes)
        self.assertIn('Another', formatted_attributes)

    def test_format_resource_attributes_show_attribute_with_attr(self):
        res = self.stack['generic3']
        res.resource_id = 'generic3_id'
        formatted_attributes = api.format_resource_attributes(
            res, with_attr=['c'])
        self.assertEqual(4, len(formatted_attributes))
        self.assertIn('foo', formatted_attributes)
        self.assertIn('Foo', formatted_attributes)
        self.assertIn('Another', formatted_attributes)
        self.assertIn('c', formatted_attributes)

    def _get_formatted_resource_properties(self, res_name):
        tmpl = template.Template(template_format.parse('''
            heat_template_version: 2013-05-23
            resources:
              resource1:
                type: ResWithComplexPropsAndAttrs
              resource2:
                type: ResWithComplexPropsAndAttrs
                properties:
                  a_string: foobar
              resource3:
                type: ResWithComplexPropsAndAttrs
                properties:
                  a_string: { get_attr: [ resource2, string] }
        '''))
        stack = parser.Stack(utils.dummy_context(), 'test_stack_for_preview',
                             tmpl, stack_id=str(uuid.uuid4()))
        res = stack[res_name]
        return api.format_resource_properties(res)

    def test_format_resource_properties_empty(self):
        props = self._get_formatted_resource_properties('resource1')
        self.assertIsNone(props['a_string'])
        self.assertIsNone(props['a_list'])
        self.assertIsNone(props['a_map'])

    def test_format_resource_properties_direct_props(self):
        props = self._get_formatted_resource_properties('resource2')
        self.assertEqual('foobar', props['a_string'])

    def test_format_resource_properties_get_attr(self):
        props = self._get_formatted_resource_properties('resource3')
        self.assertEqual('', props['a_string'])

    def test_format_stack_resource_with_nested_stack(self):
        res = self.stack['generic4']
        nested_id = {'foo': 'bar'}
        res.has_nested = mock.Mock()
        res.has_nested.return_value = True
        res.nested_identifier = mock.Mock()
        res.nested_identifier.return_value = nested_id

        formatted = api.format_stack_resource(res, False)
        self.assertEqual(nested_id, formatted[rpc_api.RES_NESTED_STACK_ID])

    def test_format_stack_resource_with_nested_stack_none(self):
        res = self.stack['generic4']

        resource_keys = set((
            rpc_api.RES_CREATION_TIME,
            rpc_api.RES_UPDATED_TIME,
            rpc_api.RES_NAME,
            rpc_api.RES_PHYSICAL_ID,
            rpc_api.RES_ACTION,
            rpc_api.RES_STATUS,
            rpc_api.RES_STATUS_DATA,
            rpc_api.RES_TYPE,
            rpc_api.RES_ID,
            rpc_api.RES_STACK_ID,
            rpc_api.RES_STACK_NAME,
            rpc_api.RES_REQUIRED_BY))

        formatted = api.format_stack_resource(res, False)
        self.assertEqual(resource_keys, set(formatted.keys()))

    def test_format_stack_resource_with_nested_stack_not_found(self):
        res = self.stack['generic4']
        self.patchobject(parser.Stack, 'load',
                         side_effect=exception.NotFound())

        resource_keys = set((
            rpc_api.RES_CREATION_TIME,
            rpc_api.RES_UPDATED_TIME,
            rpc_api.RES_NAME,
            rpc_api.RES_PHYSICAL_ID,
            rpc_api.RES_ACTION,
            rpc_api.RES_STATUS,
            rpc_api.RES_STATUS_DATA,
            rpc_api.RES_TYPE,
            rpc_api.RES_ID,
            rpc_api.RES_STACK_ID,
            rpc_api.RES_STACK_NAME,
            rpc_api.RES_REQUIRED_BY))

        formatted = api.format_stack_resource(res, False)
        # 'nested_stack_id' is not in formatted
        self.assertEqual(resource_keys, set(formatted.keys()))

    def test_format_stack_resource_with_nested_stack_empty(self):
        res = self.stack['generic4']
        nested_id = {'foo': 'bar'}

        res.has_nested = mock.Mock()
        res.has_nested.return_value = True
        res.nested_identifier = mock.Mock()
        res.nested_identifier.return_value = nested_id

        formatted = api.format_stack_resource(res, False)
        self.assertEqual(nested_id, formatted[rpc_api.RES_NESTED_STACK_ID])

    def test_format_stack_resource_required_by(self):
        res1 = api.format_stack_resource(self.stack['generic1'])
        res2 = api.format_stack_resource(self.stack['generic2'])
        self.assertEqual(['generic2'], res1['required_by'])
        self.assertEqual([], res2['required_by'])

    def test_format_stack_resource_with_parent_stack(self):
        res = self.stack['generic1']
        res.stack.defn._parent_info = parent_rsrc.ParentResourceProxy(
            self.stack.context, 'foobar', None)

        formatted = api.format_stack_resource(res, False)
        self.assertEqual('foobar', formatted[rpc_api.RES_PARENT_RESOURCE])

    def test_format_event_identifier_uuid(self):
        event = self._dummy_event()

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

        formatted = api.format_event(event, self.stack.identifier())
        self.assertEqual(event_keys, set(formatted.keys()))

        event_id_formatted = formatted[rpc_api.EVENT_ID]
        self.assertEqual({
            'path': '/resources/generic1/events/%s' % event.uuid,
            'stack_id': self.stack.id,
            'stack_name': 'test_stack',
            'tenant': 'test_tenant_id'
        }, event_id_formatted)

    def test_format_event_prop_data(self):
        resource = self.stack['generic1']
        resource._update_stored_properties()
        resource.store()
        event = self._dummy_event(
            res_properties=resource._stored_properties_data)
        formatted = api.format_event(event, self.stack.identifier(),
                                     include_rsrc_prop_data=True)
        self.assertEqual({'k1': 'v1'}, formatted[rpc_api.EVENT_RES_PROPERTIES])

    def test_format_event_legacy_prop_data(self):
        event = self._dummy_event(res_properties=None)
        # legacy location
        db_obj = self.stack.context.session.query(
            models.Event).filter_by(id=event.id).first()
        db_obj.update({'resource_properties': {'legacy_k1': 'legacy_v1'}})
        db_obj.save(self.stack.context.session)
        event_legacy = event_object.Event.get_all_by_stack(self.context,
                                                           self.stack.id)[0]
        formatted = api.format_event(event_legacy, self.stack.identifier())
        self.assertEqual({'legacy_k1': 'legacy_v1'},
                         formatted[rpc_api.EVENT_RES_PROPERTIES])

    def test_format_event_empty_prop_data(self):
        event = self._dummy_event(res_properties=None)
        formatted = api.format_event(event, self.stack.identifier())
        self.assertEqual({}, formatted[rpc_api.EVENT_RES_PROPERTIES])

    @mock.patch.object(api, 'format_stack_resource')
    def test_format_stack_preview(self, mock_fmt_resource):
        def mock_format_resources(res, **kwargs):
            return 'fmt%s' % res

        mock_fmt_resource.side_effect = mock_format_resources
        resources = [1, [2, [3]]]
        self.stack.preview_resources = mock.Mock(return_value=resources)

        stack = api.format_stack_preview(self.stack)
        self.assertIsInstance(stack, dict)
        self.assertIsNone(stack.get('status'))
        self.assertIsNone(stack.get('action'))
        self.assertIsNone(stack.get('status_reason'))
        self.assertEqual('test_stack', stack['stack_name'])
        self.assertIn('resources', stack)
        resources = list(stack['resources'])
        self.assertEqual('fmt1', resources[0])

        resources = list(resources[1])
        self.assertEqual('fmt2', resources[0])

        resources = list(resources[1])
        self.assertEqual('fmt3', resources[0])

        kwargs = mock_fmt_resource.call_args[1]
        self.assertTrue(kwargs['with_props'])

    def test_format_stack(self):
        self.stack.created_time = datetime(1970, 1, 1)
        info = api.format_stack(self.stack)

        aws_id = ('arn:openstack:heat::test_tenant_id:'
                  'stacks/test_stack/' + self.stack.id)
        expected_stack_info = {
            'capabilities': [],
            'creation_time': '1970-01-01T00:00:00Z',
            'deletion_time': None,
            'description': 'No description',
            'disable_rollback': True,
            'notification_topics': [],
            'stack_action': 'CREATE',
            'stack_name': 'test_stack',
            'stack_owner': 'test_username',
            'stack_status': 'IN_PROGRESS',
            'stack_status_reason': '',
            'stack_user_project_id': None,
            'outputs': [],
            'template_description': 'No description',
            'timeout_mins': None,
            'tags': None,
            'parameters': {
                'AWS::Region': 'ap-southeast-1',
                'AWS::StackId': aws_id,
                'AWS::StackName': 'test_stack'},
            'stack_identity': {
                'path': '',
                'stack_id': self.stack.id,
                'stack_name': 'test_stack',
                'tenant': 'test_tenant_id'},
            'updated_time': None,
            'parent': None}
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

    @mock.patch.object(api, 'format_stack_outputs')
    def test_format_stack_without_resolving_outputs(self, mock_fmt_outputs):
        mock_fmt_outputs.return_value = 'foobar'
        self.stack.action = 'CREATE'
        self.stack.status = 'COMPLETE'
        info = api.format_stack(self.stack, resolve_outputs=False)
        self.assertIsNone(info.get(rpc_api.STACK_OUTPUTS))

    def test_format_stack_outputs(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'generic': {'Type': 'GenericResourceType'}
            },
            'Outputs': {
                'correct_output': {
                    'Description': 'Good output',
                    'Value': {'Fn::GetAtt': ['generic', 'Foo']}
                },
                'incorrect_output': {
                    'Value': {'Fn::GetAtt': ['generic', 'Bar']}
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             tmpl, stack_id=str(uuid.uuid4()))
        stack.action = 'CREATE'
        stack.status = 'COMPLETE'
        stack['generic'].action = 'CREATE'
        stack['generic'].status = 'COMPLETE'
        stack._update_all_resource_data(False, True)
        info = api.format_stack_outputs(stack.outputs, resolve_value=True)
        expected = [{'description': 'No description given',
                     'output_error': 'The Referenced Attribute (generic Bar) '
                                     'is incorrect.',
                     'output_key': 'incorrect_output',
                     'output_value': None},
                    {'description': 'Good output',
                     'output_key': 'correct_output',
                     'output_value': 'generic'}]

        self.assertEqual(expected, sorted(info, key=lambda k: k['output_key'],
                                          reverse=True))

    def test_format_stack_outputs_unresolved(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'generic': {'Type': 'GenericResourceType'}
            },
            'Outputs': {
                'correct_output': {
                    'Description': 'Good output',
                    'Value': {'Fn::GetAtt': ['generic', 'Foo']}
                },
                'incorrect_output': {
                    'Value': {'Fn::GetAtt': ['generic', 'Bar']}
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             tmpl, stack_id=str(uuid.uuid4()))
        stack.action = 'CREATE'
        stack.status = 'COMPLETE'
        stack['generic'].action = 'CREATE'
        stack['generic'].status = 'COMPLETE'
        info = api.format_stack_outputs(stack.outputs)
        expected = [{'description': 'No description given',
                     'output_key': 'incorrect_output'},
                    {'description': 'Good output',
                     'output_key': 'correct_output'}]

        self.assertEqual(expected, sorted(info, key=lambda k: k['output_key'],
                                          reverse=True))

    def test_format_stack_params_csv(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'parameters': {
                'foo': {
                    'type': 'comma_delimited_list',
                    'default': ['bar', 'baz']
                },
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             tmpl, stack_id=str(uuid.uuid4()))
        info = api.format_stack(stack)

        # Should be 'bar,baz' NOT "[u'bar', u'baz']"
        self.assertEqual('bar,baz', info['parameters']['foo'])

    def test_format_stack_params_json(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'parameters': {
                'foo': {
                    'type': 'json',
                    'default': {'bar': 'baz'}
                },
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             tmpl, stack_id=str(uuid.uuid4()))
        info = api.format_stack(stack)

        # Should be '{"bar": "baz"}' NOT "{u'bar': u'baz'}"
        self.assertEqual('{"bar": "baz"}', info['parameters']['foo'])


class FormatValidateParameterTest(common.HeatTestCase):

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
        ('constraint_custom_hot',
         dict(template=base_template_hot,
              param_name='KeyName',
              param='''
                    "KeyName": {
                        "type": "string",
                        "description": "Public Network",
                        "constraints": [
                            { "custom_constraint": "neutron.network" }
                        ]
                    }
                    ''',
              expected={
                  'Type': 'String',
                  'Description': 'Public Network',
                  'NoEcho': 'false',
                  'Label': 'KeyName',
                  'CustomConstraint': 'neutron.network'
              })
         )
    ]

    def test_format_validate_parameter(self):
        """Test format of a parameter."""

        t = template_format.parse(self.template % self.param)
        tmpl = template.Template(t)

        tmpl_params = cfn_param.CfnParameters(None, tmpl)
        tmpl_params.validate(validate_value=False)
        param = tmpl_params.params[self.param_name]
        param_formated = api.format_validate_parameter(param)
        self.assertEqual(self.expected, param_formated)


class FormatSoftwareConfigDeploymentTest(common.HeatTestCase):

    def _dummy_software_config(self):
        config = mock.Mock()
        self.now = timeutils.utcnow()
        config.name = 'config_mysql'
        config.group = 'Heat::Shell'
        config.id = str(uuid.uuid4())
        config.created_at = self.now
        config.config = {
            'inputs': [{'name': 'bar'}],
            'outputs': [{'name': 'result'}],
            'options': {},
            'config': '#!/bin/bash\n'
        }
        config.tenant = str(uuid.uuid4())
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
        deployment.created_at = config.created_at
        deployment.updated_at = config.created_at
        return deployment

    def test_format_software_config(self):
        config = self._dummy_software_config()
        result = api.format_software_config(config)
        self.assertIsNotNone(result)
        self.assertEqual([{'name': 'bar'}], result['inputs'])
        self.assertEqual([{'name': 'result'}], result['outputs'])
        self.assertEqual([{'name': 'result'}], result['outputs'])
        self.assertEqual({}, result['options'])
        self.assertEqual(heat_timeutils.isotime(self.now),
                         result['creation_time'])
        self.assertNotIn('project', result)

        result = api.format_software_config(config, include_project=True)
        self.assertIsNotNone(result)
        self.assertEqual([{'name': 'bar'}], result['inputs'])
        self.assertEqual([{'name': 'result'}], result['outputs'])
        self.assertEqual([{'name': 'result'}], result['outputs'])
        self.assertEqual({}, result['options'])
        self.assertEqual(heat_timeutils.isotime(self.now),
                         result['creation_time'])
        self.assertIn('project', result)

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
        self.assertEqual(heat_timeutils.isotime(self.now),
                         result['creation_time'])
        self.assertEqual(heat_timeutils.isotime(self.now),
                         result['updated_time'])

    def test_format_software_deployment_none(self):
        self.assertIsNone(api.format_software_deployment(None))


class TestExtractArgs(common.HeatTestCase):
    def test_timeout_extract(self):
        p = {'timeout_mins': '5'}
        args = api.extract_args(p)
        self.assertEqual(5, args['timeout_mins'])

    def test_timeout_extract_zero(self):
        p = {'timeout_mins': '0'}
        args = api.extract_args(p)
        self.assertNotIn('timeout_mins', args)

    def test_timeout_extract_garbage(self):
        p = {'timeout_mins': 'wibble'}
        args = api.extract_args(p)
        self.assertNotIn('timeout_mins', args)

    def test_timeout_extract_none(self):
        p = {'timeout_mins': None}
        args = api.extract_args(p)
        self.assertNotIn('timeout_mins', args)

    def test_timeout_extract_negative(self):
        p = {'timeout_mins': '-100'}
        error = self.assertRaises(ValueError, api.extract_args, p)
        self.assertIn('Invalid timeout value', six.text_type(error))

    def test_timeout_extract_not_present(self):
        args = api.extract_args({})
        self.assertNotIn('timeout_mins', args)

    def test_adopt_stack_data_extract_present(self):
        p = {'adopt_stack_data': json.dumps({'Resources': {}})}
        args = api.extract_args(p)
        self.assertTrue(args.get('adopt_stack_data'))

    def test_invalid_adopt_stack_data(self):
        params = {'adopt_stack_data': json.dumps("foo")}
        exc = self.assertRaises(ValueError, api.extract_args, params)
        self.assertIn('Invalid adopt data', six.text_type(exc))

    def test_adopt_stack_data_extract_not_present(self):
        args = api.extract_args({})
        self.assertNotIn('adopt_stack_data', args)

    def test_disable_rollback_extract_true(self):
        args = api.extract_args({'disable_rollback': True})
        self.assertIn('disable_rollback', args)
        self.assertTrue(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'True'})
        self.assertIn('disable_rollback', args)
        self.assertTrue(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'true'})
        self.assertIn('disable_rollback', args)
        self.assertTrue(args.get('disable_rollback'))

    def test_disable_rollback_extract_false(self):
        args = api.extract_args({'disable_rollback': False})
        self.assertIn('disable_rollback', args)
        self.assertFalse(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'False'})
        self.assertIn('disable_rollback', args)
        self.assertFalse(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'false'})
        self.assertIn('disable_rollback', args)
        self.assertFalse(args.get('disable_rollback'))

    def test_disable_rollback_extract_bad(self):
        self.assertRaises(ValueError, api.extract_args,
                          {'disable_rollback': 'bad'})

    def test_tags_extract(self):
        p = {'tags': ["tag1", "tag2"]}
        args = api.extract_args(p)
        self.assertEqual(['tag1', 'tag2'], args['tags'])

    def test_tags_extract_not_present(self):
        args = api.extract_args({})
        self.assertNotIn('tags', args)

    def test_tags_extract_not_map(self):
        p = {'tags': {"foo": "bar"}}
        exc = self.assertRaises(ValueError, api.extract_args, p)
        self.assertIn('Invalid tags, not a list: ', six.text_type(exc))

    def test_tags_extract_not_string(self):
        p = {'tags': ["tag1", 2]}
        exc = self.assertRaises(ValueError, api.extract_args, p)
        self.assertIn('Invalid tag, "2" is not a string', six.text_type(exc))

    def test_tags_extract_over_limit(self):
        p = {'tags': ["tag1", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                      "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}
        exc = self.assertRaises(ValueError, api.extract_args, p)
        self.assertIn('Invalid tag, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
                      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" is longer '
                      'than 80 characters', six.text_type(exc))

    def test_tags_extract_comma(self):
        p = {'tags': ["tag1", 'tag2,']}
        exc = self.assertRaises(ValueError, api.extract_args, p)
        self.assertIn('Invalid tag, "tag2," contains a comma',
                      six.text_type(exc))


class TranslateFilterTest(common.HeatTestCase):
    scenarios = [
        (
            'single+single',
            dict(inputs={'stack_status': 'COMPLETE', 'status': 'FAILED'},
                 expected={'status': ['COMPLETE', 'FAILED']})
        ), (
            'none+single',
            dict(inputs={'name': 'n1'},
                 expected={'name': 'n1'})
        ), (
            'single+none',
            dict(inputs={'stack_name': 'n1'},
                 expected={'name': 'n1'})
        ), (
            'none+list',
            dict(inputs={'action': ['a1', 'a2']},
                 expected={'action': ['a1', 'a2']})
        ), (
            'list+none',
            dict(inputs={'stack_action': ['a1', 'a2']},
                 expected={'action': ['a1', 'a2']})
        ), (
            'single+list',
            dict(inputs={'stack_owner': 'u1', 'username': ['u2', 'u3']},
                 expected={'username': ['u1', 'u2', 'u3']})
        ), (
            'list+single',
            dict(inputs={'parent': ['s1', 's2'], 'owner_id': 's3'},
                 expected={'owner_id': ['s1', 's2', 's3']})
        ), (
            'list+list',
            dict(inputs={'stack_name': ['n1', 'n2'], 'name': ['n3', 'n4']},
                 expected={'name': ['n1', 'n2', 'n3', 'n4']})
        ), (
            'full_status_split',
            dict(inputs={'stack_status': 'CREATE_COMPLETE'},
                 expected={'action': 'CREATE', 'status': 'COMPLETE'})
        ), (
            'full_status_split_merge',
            dict(inputs={'stack_status': 'CREATE_COMPLETE',
                         'status': 'CREATE_FAILED'},
                 expected={'action': 'CREATE',
                           'status': ['COMPLETE', 'FAILED']})
        ), (
            'action_status_merge',
            dict(inputs={'action': ['UPDATE', 'CREATE'],
                         'status': 'CREATE_FAILED'},
                 expected={'action': ['CREATE', 'UPDATE'],
                           'status': 'FAILED'})
        )
    ]

    def test_stack_filter_translate(self):
        actual = api.translate_filters(self.inputs)
        self.assertEqual(self.expected, actual)


class ParseStatusTest(common.HeatTestCase):
    scenarios = [
        (
            'single_bogus',
            dict(inputs='bogus status',
                 expected=(set(), set()))
        ), (
            'list_bogus',
            dict(inputs=['foo', 'bar'],
                 expected=(set(), set()))
        ), (
            'single_partial',
            dict(inputs='COMPLETE',
                 expected=(set(), set(['COMPLETE'])))
        ), (
            'multi_partial',
            dict(inputs=['FAILED', 'COMPLETE'],
                 expected=(set(), set(['FAILED', 'COMPLETE'])))
        ), (
            'multi_partial_dup',
            dict(inputs=['FAILED', 'FAILED'],
                 expected=(set(), set(['FAILED'])))
        ), (
            'single_full',
            dict(inputs=['DELETE_FAILED'],
                 expected=(set(['DELETE']), set(['FAILED'])))
        ), (
            'multi_full',
            dict(inputs=['DELETE_FAILED', 'CREATE_COMPLETE'],
                 expected=(set(['CREATE', 'DELETE']),
                           set(['COMPLETE', 'FAILED'])))
        ), (
            'mix_bogus_partial',
            dict(inputs=['delete_failed', 'COMPLETE'],
                 expected=(set(), set(['COMPLETE'])))
        ), (
            'mix_bogus_full',
            dict(inputs=['delete_failed', 'action_COMPLETE'],
                 expected=(set(['action']), set(['COMPLETE'])))
        ), (
            'mix_bogus_full_incomplete',
            dict(inputs=['delete_failed', '_COMPLETE'],
                 expected=(set(), set(['COMPLETE'])))
        ), (
            'mix_partial_full',
            dict(inputs=['FAILED', 'b_COMPLETE'],
                 expected=(set(['b']),
                           set(['COMPLETE', 'FAILED'])))
        ), (
            'mix_full_dup',
            dict(inputs=['a_FAILED', 'a_COMPLETE'],
                 expected=(set(['a']),
                           set(['COMPLETE', 'FAILED'])))
        ), (
            'mix_full_dup_2',
            dict(inputs=['a_FAILED', 'b_FAILED'],
                 expected=(set(['a', 'b']), set(['FAILED'])))
        )
    ]

    def test_stack_parse_status(self):
        actual = api._parse_object_status(self.inputs)
        self.assertEqual(self.expected, actual)
