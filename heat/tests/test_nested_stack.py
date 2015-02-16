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
from requests import exceptions
import six
import yaml

from heat.common import exception
from heat.common import template_format
from heat.common import urlfetch
from heat.db import api as db_api
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources import stack as stack_res
from heat.engine import rsrc_defn
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
        self.m.StubOutWithMock(urlfetch, 'get')

    def validate_stack(self, template):
        t = template_format.parse(template)
        stack = self.parse_stack(t)
        res = stack.validate()
        self.assertIsNone(res)
        return stack

    def parse_stack(self, t, data=None):
        ctx = utils.dummy_context('test_username', 'aaaa', 'password')
        stack_name = 'test_stack'
        tmpl = parser.Template(t)
        stack = parser.Stack(ctx, stack_name, tmpl, adopt_stack_data=data)
        stack.store()
        return stack

    def test_nested_stack_three_deep(self):
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
        urlfetch.get(
            'https://server.test/depth1.template').AndReturn(
                depth1_template)
        urlfetch.get(
            'https://server.test/depth2.template').AndReturn(
                depth2_template)
        urlfetch.get(
            'https://server.test/depth3.template').AndReturn(
                self.nested_template)
        self.m.ReplayAll()
        self.validate_stack(root_template)
        self.m.VerifyAll()

    def test_nested_stack_four_deep(self):
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
'''
        depth3_template = '''
HeatTemplateFormatVersion: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth4.template'
            Parameters:
                KeyName: foo
'''
        urlfetch.get(
            'https://server.test/depth1.template').AndReturn(
                depth1_template)
        urlfetch.get(
            'https://server.test/depth2.template').AndReturn(
                depth2_template)
        urlfetch.get(
            'https://server.test/depth3.template').AndReturn(
                depth3_template)
        urlfetch.get(
            'https://server.test/depth4.template').AndReturn(
                self.nested_template)
        self.m.ReplayAll()
        t = template_format.parse(root_template)
        stack = self.parse_stack(t)
        res = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('Recursion depth exceeds', six.text_type(res))
        self.m.VerifyAll()

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
        urlfetch.get(
            'https://server.test/depth1.template').InAnyOrder().AndReturn(
                self.nested_template)
        urlfetch.get(
            'https://server.test/depth2.template').InAnyOrder().AndReturn(
                self.nested_template)
        urlfetch.get(
            'https://server.test/depth3.template').InAnyOrder().AndReturn(
                self.nested_template)
        urlfetch.get(
            'https://server.test/depth4.template').InAnyOrder().AndReturn(
                self.nested_template)
        self.m.ReplayAll()
        self.validate_stack(root_template)
        self.m.VerifyAll()

    def test_nested_stack_infinite_recursion(self):
        template = '''
HeatTemplateFormatVersion: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/the.template'
'''
        urlfetch.get(
            'https://server.test/the.template').MultipleTimes().AndReturn(
                template)
        self.m.ReplayAll()
        t = template_format.parse(template)
        stack = self.parse_stack(t)
        res = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('Recursion depth exceeds', six.text_type(res))

    def test_child_params(self):
        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        nested_stack = stack['the_nested']
        nested_stack.properties.data[nested_stack.PARAMETERS] = {'foo': 'bar'}

        self.assertEqual({'foo': 'bar'}, nested_stack.child_params())

    @mock.patch.object(urlfetch, 'get')
    def test_child_template_when_file_is_fetched(self, mock_get):
        mock_get.return_value = 'template_file'
        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        nested_stack = stack['the_nested']

        with mock.patch('heat.common.template_format.parse') as mock_parse:
            mock_parse.return_value = 'child_template'
            self.assertEqual('child_template', nested_stack.child_template())
            mock_parse.assert_called_once_with('template_file')

    @mock.patch.object(urlfetch, 'get')
    def test_child_template_when_fetching_file_fails(self, mock_get):
        mock_get.side_effect = exceptions.RequestException()
        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        nested_stack = stack['the_nested']
        self.assertRaises(ValueError, nested_stack.child_template)

    @mock.patch.object(urlfetch, 'get')
    def test_child_template_when_io_error(self, mock_get):
        msg = 'Failed to retrieve template'
        mock_get.side_effect = urlfetch.URLFetchError(msg)
        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        nested_stack = stack['the_nested']
        self.assertRaises(ValueError, nested_stack.child_template)


class ResDataResource(generic_rsrc.GenericResource):
    def handle_create(self):
        self.data_set("test", 'A secret value', True)


class ResDataNestedStackTest(NestedStackTest):

    nested_template = '''
HeatTemplateFormatVersion: "2012-12-12"
Parameters:
  KeyName:
    Type: String
Resources:
  nested_res:
    Type: "res.data.resource"
Outputs:
  Foo:
    Value: bar
'''

    def setUp(self):
        super(ResDataNestedStackTest, self).setUp()
        resource._register_class("res.data.resource", ResDataResource)

    def create_stack(self, template):
        t = template_format.parse(template)
        stack = self.parse_stack(t)
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
        return stack

    def test_res_data_delete(self):
        urlfetch.get('https://server.test/the.template').AndReturn(
            self.nested_template)
        self.m.ReplayAll()
        stack = self.create_stack(self.test_template)
        res = stack['the_nested'].nested()['nested_res']
        stack.delete()
        self.assertEqual((stack.DELETE, stack.COMPLETE), stack.state)
        self.assertRaises(exception.NotFound, db_api.resource_data_get, res,
                          'test')


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

        ctx = utils.dummy_context('test_username', 'aaaa', 'password')
        empty_template = {"HeatTemplateFormatVersion": "2012-12-12"}
        stack = parser.Stack(ctx, 'test', parser.Template(empty_template))
        stack.store()

        self.patchobject(urlfetch, 'get', return_value=self.nested_template)
        self.nested_parsed = yaml.load(self.nested_template)
        self.nested_params = {"KeyName": "foo"}
        self.defn = rsrc_defn.ResourceDefinition(
            'test_t_res',
            'AWS::CloudFormation::Stack',
            {"TemplateURL": "https://server.test/the.template",
             "Parameters": self.nested_params})
        self.res = stack_res.NestedStack('test_t_res',
                                         self.defn, stack)
        self.assertIsNone(self.res.validate())

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
        self.res.nested = mock.MagicMock()
        self.res.nested.return_value.delete.return_value = None
        self.res.handle_delete()
        self.res.nested.return_value.delete.assert_called_once_with()
