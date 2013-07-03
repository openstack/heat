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


from heat.common import template_format
from heat.common import context
from heat.common import exception
from heat.engine import parser
from heat.engine import resource
from heat.engine import stack_resource
from heat.engine import template
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
from heat.tests import generic_resource as generic_rsrc
from heat.tests.utils import setup_dummy_db
from heat.tests.utils import stack_delete_after

ws_res_snippet = {"Type": "some_magic_type",
                  "metadata": {
                      "key": "value",
                      "some": "more stuff"}}

wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "metadata": {"Fn::ResourceFacade": "Metadata"},
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''


class MyStackResource(stack_resource.StackResource,
                      generic_rsrc.GenericResource):
    def physical_resource_name(self):
        return "cb2f2b28-a663-4683-802c-4b40c916e1ff"


class StackResourceTest(HeatTestCase):

    def setUp(self):
        super(StackResourceTest, self).setUp()
        setup_dummy_db()
        resource._register_class('some_magic_type',
                                 MyStackResource)
        t = parser.Template({template.RESOURCES:
                             {"provider_resource": ws_res_snippet}})
        self.parent_stack = parser.Stack(None, 'test_stack', t,
                                         stack_id=uuidutils.generate_uuid())
        self.parent_resource = MyStackResource('test',
                                               ws_res_snippet,
                                               self.parent_stack)
        self.parent_resource.context = context.get_admin_context()
        self.templ = template_format.parse(wp_template)

    @stack_delete_after
    def test_create_with_template_ok(self):
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()

        self.assertEqual(self.parent_resource, self.stack.parent_resource)
        self.assertEqual("cb2f2b28-a663-4683-802c-4b40c916e1ff",
                         self.stack.name)
        self.assertEqual(self.templ, self.stack.t.t)
        self.assertEqual(self.stack.id, self.parent_resource.resource_id)

    @stack_delete_after
    def test_load_nested_ok(self):
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()

        self.parent_resource._nested = None
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.parent_resource.context,
                          self.parent_resource.resource_id,
                          parent_resource=self.parent_resource).AndReturn('s')
        self.m.ReplayAll()

        self.parent_resource.nested()
        self.m.VerifyAll()

    @stack_delete_after
    def test_load_nested_non_exist(self):
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()

        self.parent_resource._nested = None
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.parent_resource.context,
                          self.parent_resource.resource_id,
                          parent_resource=self.parent_resource)
        self.m.ReplayAll()

        self.assertRaises(exception.NotFound, self.parent_resource.nested)
        self.m.VerifyAll()

    def test_delete_nested_ok(self):
        nested = self.m.CreateMockAnything()
        self.m.StubOutWithMock(stack_resource.StackResource, 'nested')
        stack_resource.StackResource.nested().AndReturn(nested)
        nested.delete()
        self.m.ReplayAll()

        self.parent_resource.delete_nested()
        self.m.VerifyAll()

    def test_get_output_ok(self):
        nested = self.m.CreateMockAnything()
        self.m.StubOutWithMock(stack_resource.StackResource, 'nested')
        stack_resource.StackResource.nested().AndReturn(nested)
        nested.outputs = {"key": "value"}
        nested.output('key').AndReturn("value")
        self.m.ReplayAll()

        self.assertEqual("value", self.parent_resource.get_output("key"))

        self.m.VerifyAll()

    def test_get_output_key_not_found(self):
        nested = self.m.CreateMockAnything()
        self.m.StubOutWithMock(stack_resource.StackResource, 'nested')
        stack_resource.StackResource.nested().AndReturn(nested)
        nested.outputs = {}
        self.m.ReplayAll()

        self.assertRaises(exception.InvalidTemplateAttribute,
                          self.parent_resource.get_output,
                          "key")

        self.m.VerifyAll()
