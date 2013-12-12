# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import copy
import json

from oslo.config import cfg

cfg.CONF.import_opt('max_resources_per_stack', 'heat.common.config')

from heat.common import exception
from heat.common import template_format
from heat.common import urlfetch
from heat.db import api as db_api
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils
from heat.tests.common import HeatTestCase


class NestedStackTest(HeatTestCase):
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
        utils.setup_dummy_db()

    def create_stack(self, template):
        t = template_format.parse(template)
        stack = self.parse_stack(t)
        stack.create()
        self.assertEqual(stack.state, (stack.CREATE, stack.COMPLETE))
        return stack

    def parse_stack(self, t):
        ctx = utils.dummy_context('test_username', 'aaaa', 'password')
        stack_name = 'test_stack'
        tmpl = parser.Template(t)
        stack = parser.Stack(ctx, stack_name, tmpl)
        stack.store()
        return stack

    def test_nested_stack_create(self):
        urlfetch.get('https://server.test/the.template').MultipleTimes().\
            AndReturn(self.nested_template)
        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        rsrc = stack['the_nested']
        nested_name = utils.PhysName(stack.name, 'the_nested')
        self.assertEqual(nested_name, rsrc.physical_resource_name())
        arn_prefix = ('arn:openstack:heat::aaaa:stacks/%s/' %
                      rsrc.physical_resource_name())
        self.assertTrue(rsrc.FnGetRefId().startswith(arn_prefix))

        self.assertEqual('bar', rsrc.FnGetAtt('Outputs.Foo'))
        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Foo')
        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Outputs.Bar')
        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Bar')

        rsrc.delete()
        self.assertTrue(rsrc.FnGetRefId().startswith(arn_prefix))

        self.m.VerifyAll()

    def test_nested_stack_create_with_timeout(self):
        urlfetch.get('https://server.test/the.template').MultipleTimes().\
            AndReturn(self.nested_template)
        self.m.ReplayAll()

        timeout_template = template_format.parse(
            copy.deepcopy(self.test_template))
        props = timeout_template['Resources']['the_nested']['Properties']
        props['TimeoutInMinutes'] = '50'

        stack = self.create_stack(json.dumps(timeout_template))
        self.assertEqual(stack.state, (stack.CREATE, stack.COMPLETE))
        self.m.VerifyAll()

    def test_nested_stack_create_exceeds_resource_limit(self):
        cfg.CONF.set_override('max_resources_per_stack', 1)
        resource._register_class('GenericResource',
                                 generic_rsrc.GenericResource)
        urlfetch.get('https://server.test/the.template').MultipleTimes().\
            AndReturn('''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Resources:
  NestedResource:
    Type: GenericResource
Outputs:
  Foo:
    Value: bar
''')
        self.m.ReplayAll()

        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        stack.create()
        self.assertEqual(stack.state, (stack.CREATE, stack.FAILED))
        self.assertIn('Maximum resources per stack exceeded',
                      stack.status_reason)

        self.m.VerifyAll()

    def test_nested_stack_create_equals_resource_limit(self):
        cfg.CONF.set_override('max_resources_per_stack', 2)
        resource._register_class('GenericResource',
                                 generic_rsrc.GenericResource)
        urlfetch.get('https://server.test/the.template').MultipleTimes().\
            AndReturn('''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Resources:
  NestedResource:
    Type: GenericResource
Outputs:
  Foo:
    Value: bar
''')
        self.m.ReplayAll()

        t = template_format.parse(self.test_template)
        stack = self.parse_stack(t)
        stack.create()
        self.assertEqual(stack.state, (stack.CREATE, stack.COMPLETE))
        self.assertIn('NestedResource',
                      stack['the_nested'].nested())

        self.m.VerifyAll()

    def test_nested_stack_update(self):
        urlfetch.get('https://server.test/the.template').MultipleTimes().\
            AndReturn(self.nested_template)
        urlfetch.get('https://server.test/new.template').MultipleTimes().\
            AndReturn(self.update_template)

        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        rsrc = stack['the_nested']

        original_nested_id = rsrc.resource_id
        t = template_format.parse(self.test_template)
        new_res = copy.deepcopy(t['Resources']['the_nested'])
        new_res['Properties']['TemplateURL'] = (
            'https://server.test/new.template')
        prop_diff = {'TemplateURL': 'https://server.test/new.template'}
        updater = rsrc.handle_update(new_res, {}, prop_diff)
        updater.run_to_completion()
        self.assertIs(True, rsrc.check_update_complete(updater))

        # Expect the physical resource name staying the same after update,
        # so that the nested was actually updated instead of replaced.
        self.assertEqual(original_nested_id, rsrc.resource_id)
        db_nested = db_api.stack_get(stack.context,
                                     rsrc.resource_id)
        # Owner_id should be preserved during the update process.
        self.assertEqual(stack.id, db_nested.owner_id)

        self.assertEqual('foo', rsrc.FnGetAtt('Outputs.Bar'))
        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Foo')
        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Outputs.Foo')
        self.assertRaises(
            exception.InvalidTemplateAttribute, rsrc.FnGetAtt, 'Bar')

        rsrc.delete()

        self.m.VerifyAll()

    def test_nested_stack_update_equals_resource_limit(self):
        resource._register_class('GenericResource',
                                 generic_rsrc.GenericResource)
        urlfetch.get('https://server.test/the.template').MultipleTimes().\
            AndReturn(self.nested_template)
        urlfetch.get('https://server.test/new.template').MultipleTimes().\
            AndReturn('''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Resources:
  NestedResource:
    Type: GenericResource
Outputs:
  Bar:
    Value: foo
''')
        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)

        cfg.CONF.set_override('max_resources_per_stack', 2)

        rsrc = stack['the_nested']

        original_nested_id = rsrc.resource_id
        t = template_format.parse(self.test_template)
        new_res = copy.deepcopy(t['Resources']['the_nested'])
        new_res['Properties']['TemplateURL'] = (
            'https://server.test/new.template')
        prop_diff = {'TemplateURL': 'https://server.test/new.template'}
        updater = rsrc.handle_update(new_res, {}, prop_diff)
        updater.run_to_completion()
        self.assertIs(True, rsrc.check_update_complete(updater))

        self.assertEqual('foo', rsrc.FnGetAtt('Outputs.Bar'))

        rsrc.delete()

        self.m.VerifyAll()

    def test_nested_stack_update_exceeds_limit(self):
        resource._register_class('GenericResource',
                                 generic_rsrc.GenericResource)
        urlfetch.get('https://server.test/the.template').MultipleTimes().\
            AndReturn(self.nested_template)
        urlfetch.get('https://server.test/new.template').MultipleTimes().\
            AndReturn('''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Resources:
  NestedResource:
    Type: GenericResource
Outputs:
  Bar:
    Value: foo
''')
        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)

        cfg.CONF.set_override('max_resources_per_stack', 1)

        rsrc = stack['the_nested']

        original_nested_id = rsrc.resource_id
        t = template_format.parse(self.test_template)
        new_res = copy.deepcopy(t['Resources']['the_nested'])
        new_res['Properties']['TemplateURL'] = (
            'https://server.test/new.template')
        prop_diff = {'TemplateURL': 'https://server.test/new.template'}
        ex = self.assertRaises(exception.RequestLimitExceeded,
                               rsrc.handle_update, new_res, {}, prop_diff)
        self.assertIn(exception.StackResourceLimitExceeded.msg_fmt,
                      str(ex))
        rsrc.delete()

        self.m.VerifyAll()

    def test_nested_stack_suspend_resume(self):
        urlfetch.get('https://server.test/the.template').AndReturn(
            self.nested_template)
        self.m.ReplayAll()

        stack = self.create_stack(self.test_template)
        rsrc = stack['the_nested']

        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual(rsrc.state, (rsrc.SUSPEND, rsrc.COMPLETE))

        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual(rsrc.state, (rsrc.RESUME, rsrc.COMPLETE))

        rsrc.delete()
        self.m.VerifyAll()

    def test_nested_stack_three_deep(self):
        root_template = '''
HeatTemplateFormat: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth1.template'
'''
        depth1_template = '''
HeatTemplateFormat: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth2.template'
'''
        depth2_template = '''
HeatTemplateFormat: 2012-12-12
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
        self.create_stack(root_template)
        self.m.VerifyAll()

    def test_nested_stack_four_deep(self):
        root_template = '''
HeatTemplateFormat: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth1.template'
'''
        depth1_template = '''
HeatTemplateFormat: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth2.template'
'''
        depth2_template = '''
HeatTemplateFormat: 2012-12-12
Resources:
    Nested:
        Type: AWS::CloudFormation::Stack
        Properties:
            TemplateURL: 'https://server.test/depth3.template'
'''
        depth3_template = '''
HeatTemplateFormat: 2012-12-12
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
        stack.create()
        self.assertEqual((stack.CREATE, stack.FAILED), stack.state)
        self.assertIn('Recursion depth exceeds', stack.status_reason)
        self.m.VerifyAll()

    def test_nested_stack_four_wide(self):
        root_template = '''
HeatTemplateFormat: 2012-12-12
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
        self.create_stack(root_template)
        self.m.VerifyAll()

    def test_nested_stack_infinite_recursion(self):
        template = '''
HeatTemplateFormat: 2012-12-12
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
        stack.create()
        self.assertEqual(stack.state, (stack.CREATE, stack.FAILED))
        self.assertIn('Recursion depth exceeds', stack.status_reason)
        self.m.VerifyAll()


class ResDataResource(generic_rsrc.GenericResource):
    def handle_create(self):
        db_api.resource_data_set(self, "test", 'A secret value', True)


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

    def test_res_data_delete(self):
        urlfetch.get('https://server.test/the.template').AndReturn(
            self.nested_template)
        self.m.ReplayAll()
        stack = self.create_stack(self.test_template)
        res = stack['the_nested'].nested()['nested_res']
        stack.delete()
        self.assertEqual(stack.state, (stack.DELETE, stack.COMPLETE))
        self.assertRaises(exception.NotFound, db_api.resource_data_get, res,
                          'test')
