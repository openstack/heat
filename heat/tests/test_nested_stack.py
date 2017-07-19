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
from oslo_config import cfg
from requests import exceptions
import six
import yaml

from heat.common import exception
from heat.common import identifier
from heat.common import template_format
from heat.common import urlfetch
from heat.engine import api
from heat.engine import node_data
from heat.engine import resource
from heat.engine.resources.aws.cfn import stack as stack_res
from heat.engine import rsrc_defn
from heat.engine import stack as parser
from heat.engine import template
from heat.objects import resource_data as resource_data_object
from heat.tests import common
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils


class NestedStackTest(common.HeatTestCase):
    test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_nested:
    Type: AWS::CloudFormation::Stack
    Properties:
      TemplateURL: https://server.test/the.template
      Parameters:
        KeyName: foo
'''

    nested_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Outputs:
  Foo:
    Value: bar
'''

    update_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Outputs:
  Bar:
    Value: foo
'''

    def setUp(self):
        super(NestedStackTest, self).setUp()
        self.patchobject(urlfetch, 'get')

    def validate_stack(self, template):
        t = template_format.parse(template)
        stack = self.parse_stack(t)
        res = stack.validate()
        self.assertIsNone(res)
        return stack

    def parse_stack(self, t, data=None):
        ctx = utils.dummy_context('test_username', 'aaaa', 'password')
        stack_name = 'test_stack'
        tmpl = template.Template(t)
        stack = parser.Stack(ctx, stack_name, tmpl, adopt_stack_data=data)
        stack.store()
        return stack

    @mock.patch.object(parser.Stack, 'total_resources')
    def test_nested_stack_three_deep(self, tr):
        root_template = '''
HeatTemplateFormatVersion: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth1.template'
'''
        depth1_template = '''
HeatTemplateFormatVersion: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth2.template'
'''
        depth2_template = '''
HeatTemplateFormatVersion: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth3.template'
            Parameters:
                KeyName: foo
'''
        urlfetch.get.side_effect = [
            depth1_template,
            depth2_template,
            self.nested_template]

        tr.return_value = 2

        self.validate_stack(root_template)
        calls = [mock.call('https://server.test/depth1.template'),
                 mock.call('https://server.test/depth2.template'),
                 mock.call('https://server.test/depth3.template')]
        urlfetch.get.assert_has_calls(calls)

    @mock.patch.object(parser.Stack, 'total_resources')
    def test_nested_stack_six_deep(self, tr):
        tmpl = '''
HeatTemplateFormatVersion: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth%i.template'
'''
        root_template = tmpl % 1
        depth1_template = tmpl % 2
        depth2_template = tmpl % 3
        depth3_template = tmpl % 4
        depth4_template = tmpl % 5
        depth5_template = tmpl % 6
        depth5_template += '''
            Parameters:
                KeyName: foo
'''

        urlfetch.get.side_effect = [
            depth1_template,
            depth2_template,
            depth3_template,
            depth4_template,
            depth5_template,
            self.nested_template]

        tr.return_value = 5

        t = template_format.parse(root_template)
        stack = self.parse_stack(t)
        stack['Nested'].root_stack_id = '1234'

        res = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('Recursion depth exceeds', six.text_type(res))

        calls = [mock.call('https://server.test/depth1.template'),
                 mock.call('https://server.test/depth2.template'),
                 mock.call('https://server.test/depth3.template'),
                 mock.call('https://server.test/depth4.template'),
                 mock.call('https://server.test/depth5.template'),
                 mock.call('https://server.test/depth6.template')]
        urlfetch.get.assert_has_calls(calls)

    def test_nested_stack_four_wide(self):
        root_template = '''
HeatTemplateFormatVersion: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth1.template'
            Parameters:
                KeyName: foo
    Nested2:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth2.template'
            Parameters:
                KeyName: foo
    Nested3:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth3.template'
            Parameters:
                KeyName: foo
    Nested4:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth4.template'
            Parameters:
                KeyName: foo
'''
        urlfetch.get.return_value = self.nested_template

        self.validate_stack(root_template)
        calls = [mock.call('https://server.test/depth1.template'),
                 mock.call('https://server.test/depth2.template'),
                 mock.call('https://server.test/depth3.template'),
                 mock.call('https://server.test/depth4.template')]
        urlfetch.get.assert_has_calls(calls, any_order=True)

    @mock.patch.object(parser.Stack, 'total_resources')
    def test_nested_stack_infinite_recursion(self, tr):
        tmpl = '''
HeatTemplateFormatVersion: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/the.template'
'''
        urlfetch.get.return_value = tmpl
        t = template_format.parse(tmpl)
        stack = self.parse_stack(t)
        stack['Nested'].root_stack_id = '1234'
        tr.return_value = 2
        res = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('Recursion depth exceeds', six.text_type(res))
        expected_count = cfg.CONF.get('max_nested_stack_depth') + 1
        self.assertEqual(expected_count, urlfetch.get.call_count)

    def test_child_params(self):
        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        nested_stack = stack['the_nested']
        nested_stack.properties.data[nested_stack.PARAMETERS] = {'foo': 'bar'}

        self.assertEqual({'foo': 'bar'}, nested_stack.child_params())

    def test_child_template_when_file_is_fetched(self):
        urlfetch.get.return_value = 'template_file'
        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        nested_stack = stack['the_nested']

        with mock.patch('heat.common.template_format.parse') as mock_parse:
            mock_parse.return_value = 'child_template'
            self.assertEqual('child_template', nested_stack.child_template())
            mock_parse.assert_called_once_with(
                'template_file', 'https://server.test/the.template')

    def test_child_template_when_fetching_file_fails(self):
        urlfetch.get.side_effect = exceptions.RequestException()
        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        nested_stack = stack['the_nested']
        self.assertRaises(ValueError, nested_stack.child_template)

    def test_child_template_when_io_error(self):
        msg = 'Failed to retrieve template'
        urlfetch.get.side_effect = urlfetch.URLFetchError(msg)
        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        nested_stack = stack['the_nested']
        self.assertRaises(ValueError, nested_stack.child_template)

    def test_refid(self):
        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        nested_stack = stack['the_nested']
        self.assertEqual('the_nested', nested_stack.FnGetRefId())

    def test_refid_convergence_cache_data(self):
        t = template_format.parse(self.test_template)
        tmpl = template.Template(t)
        ctx = utils.dummy_context()
        cache_data = {'the_nested': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'the_nested_convg_mock'
        })}
        stack = parser.Stack(ctx, 'test_stack', tmpl, cache_data=cache_data)
        nested_stack = stack.defn['the_nested']
        self.assertEqual('the_nested_convg_mock', nested_stack.FnGetRefId())

    def test_get_attribute(self):
        tmpl = template_format.parse(self.test_template)
        ctx = utils.dummy_context('test_username', 'aaaa', 'password')
        stack = parser.Stack(ctx, 'test',
                             template.Template(tmpl))
        stack.store()

        stack_res = stack['the_nested']
        stack_res.store()

        nested_t = template_format.parse(self.nested_template)
        nested_t['Parameters']['KeyName']['Default'] = 'Key'

        nested_stack = parser.Stack(ctx, 'test',
                                    template.Template(nested_t))
        nested_stack.store()

        stack_res._rpc_client = mock.MagicMock()
        stack_res._rpc_client.show_stack.return_value = [
            api.format_stack(nested_stack)]
        stack_res.nested_identifier = mock.Mock()
        stack_res.nested_identifier.return_value = {'foo': 'bar'}
        self.assertEqual('bar', stack_res.FnGetAtt('Outputs.Foo'))


class ResDataResource(generic_rsrc.GenericResource):
    def handle_create(self):
        self.data_set("test", 'A secret value', True)


class ResDataStackTest(common.HeatTestCase):
    tmpl = '''
HeatTemplateFormatVersion: "2012-12-12"
Parameters:
  KeyName:
    Type: String
Resources:
  res:
    Type: "res.data.resource"
Outputs:
  Foo:
    Value: bar
'''

    def setUp(self):
        super(ResDataStackTest, self).setUp()
        resource._register_class("res.data.resource", ResDataResource)

    def create_stack(self, template):
        t = template_format.parse(template)
        stack = utils.parse_stack(t)
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
        return stack

    def test_res_data_delete(self):
        stack = self.create_stack(self.tmpl)
        res = stack['res']
        stack.delete()
        self.assertEqual((stack.DELETE, stack.COMPLETE), stack.state)
        self.assertRaises(
            exception.NotFound,
            resource_data_object.ResourceData.get_val, res, 'test')


class NestedStackCrudTest(common.HeatTestCase):
    nested_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Outputs:
  Foo:
    Value: bar
'''

    def setUp(self):
        super(NestedStackCrudTest, self).setUp()

        self.ctx = utils.dummy_context('test_username', 'aaaa', 'password')
        empty_template = {"HeatTemplateFormatVersion": "2012-12-12"}
        self.stack = parser.Stack(self.ctx, 'test',
                                  template.Template(empty_template))
        self.stack.store()

        self.patchobject(urlfetch, 'get', return_value=self.nested_template)
        self.nested_parsed = yaml.safe_load(self.nested_template)
        self.nested_params = {"KeyName": "foo"}
        self.defn = rsrc_defn.ResourceDefinition(
            'test_t_res',
            'AWS::CloudFormation::Stack',
            {"TemplateURL": "https://server.test/the.template",
             "Parameters": self.nested_params})
        self.res = stack_res.NestedStack('test_t_res',
                                         self.defn, self.stack)
        self.assertIsNone(self.res.validate())
        self.res.store()

    def test_handle_create(self):
        self.res.create_with_template = mock.Mock(return_value=None)

        self.res.handle_create()

        self.res.create_with_template.assert_called_once_with(
            self.nested_parsed, self.nested_params, None, adopt_data=None)

    def test_handle_adopt(self):
        self.res.create_with_template = mock.Mock(return_value=None)

        self.res.handle_adopt(resource_data={'resource_id': 'fred'})

        self.res.create_with_template.assert_called_once_with(
            self.nested_parsed, self.nested_params, None,
            adopt_data={'resource_id': 'fred'})

    def test_handle_update(self):
        self.res.update_with_template = mock.Mock(return_value=None)

        self.res.handle_update(self.defn, None, None)

        self.res.update_with_template.assert_called_once_with(
            self.nested_parsed, self.nested_params, None)

    def test_handle_delete(self):
        self.res.rpc_client = mock.MagicMock()
        self.res.action = self.res.CREATE
        self.res.nested_identifier = mock.MagicMock()
        stack_identity = identifier.HeatIdentifier(
            self.ctx.tenant_id,
            self.res.physical_resource_name(),
            self.res.resource_id)
        self.res.nested_identifier.return_value = stack_identity
        self.res.resource_id = stack_identity.stack_id
        self.res.handle_delete()
        self.res.rpc_client.return_value.delete_stack.assert_called_once_with(
            self.ctx, stack_identity, cast=False)
