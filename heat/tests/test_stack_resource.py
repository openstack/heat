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
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
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

    def set_template(self, nested_tempalte, params):
        self.nested_tempalte = nested_tempalte
        self.nested_params = params

    def handle_create(self):
        return self.create_with_template(self.nested_tempalte,
                                         self.nested_params)

    def handle_delete(self):
        self.delete_nested()


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

    @stack_delete_after
    def test_create_complete_state_err(self):
        """
        check_create_complete should raise error when create task is
        done but the nested stack is not in (CREATE,COMPLETE) state
        """
        del self.templ['Resources']['WebServer']
        self.parent_resource.set_template(self.templ, {"KeyName": "test"})

        ctx = self.parent_resource.context
        phy_id = "cb2f2b28-a663-4683-802c-4b40c916e1ff"
        templ = parser.Template(self.templ)
        env = environment.Environment({"KeyName": "test"})
        self.stack = parser.Stack(ctx, phy_id, templ, env, timeout_mins=None,
                                  disable_rollback=True,
                                  parent_resource=self.parent_resource)

        self.m.StubOutWithMock(parser, 'Template')
        parser.Template(self.templ).AndReturn(templ)

        self.m.StubOutWithMock(environment, 'Environment')
        environment.Environment({"KeyName": "test"}).AndReturn(env)

        self.m.StubOutWithMock(parser, 'Stack')
        parser.Stack(ctx, phy_id, templ, env, timeout_mins=None,
                     disable_rollback=True,
                     parent_resource=self.parent_resource)\
            .AndReturn(self.stack)

        st_set = self.stack.state_set
        self.m.StubOutWithMock(self.stack, 'state_set')
        self.stack.state_set(parser.Stack.CREATE, parser.Stack.IN_PROGRESS,
                             "Stack CREATE started").WithSideEffects(st_set)

        self.stack.state_set(parser.Stack.CREATE, parser.Stack.COMPLETE,
                             "Stack create completed successfully")
        self.m.ReplayAll()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(self.parent_resource.create))
        self.assertEqual(('CREATE', 'FAILED'), self.parent_resource.state)
        self.assertEqual(('Error: Stack CREATE started'),
                         self.parent_resource.status_reason)

        self.m.VerifyAll()
        # Restore state_set to let clean up proceed
        self.stack.state_set = st_set

    @stack_delete_after
    def test_suspend_complete_state_err(self):
        """
        check_suspend_complete should raise error when suspend task is
        done but the nested stack is not in (SUSPEND,COMPLETE) state
        """
        del self.templ['Resources']['WebServer']
        self.parent_resource.set_template(self.templ, {"KeyName": "test"})
        scheduler.TaskRunner(self.parent_resource.create)()
        self.stack = self.parent_resource.nested()

        st_set = self.stack.state_set
        self.m.StubOutWithMock(self.stack, 'state_set')
        self.stack.state_set(parser.Stack.SUSPEND, parser.Stack.IN_PROGRESS,
                             "Stack SUSPEND started").WithSideEffects(st_set)

        self.stack.state_set(parser.Stack.SUSPEND, parser.Stack.COMPLETE,
                             "Stack suspend completed successfully")
        self.m.ReplayAll()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(self.parent_resource.suspend))
        self.assertEqual(('SUSPEND', 'FAILED'), self.parent_resource.state)
        self.assertEqual(('Error: Stack SUSPEND started'),
                         self.parent_resource.status_reason)

        self.m.VerifyAll()
        # Restore state_set to let clean up proceed
        self.stack.state_set = st_set

    @stack_delete_after
    def test_resume_complete_state_err(self):
        """
        check_resume_complete should raise error when resume task is
        done but the nested stack is not in (RESUME,COMPLETE) state
        """
        del self.templ['Resources']['WebServer']
        self.parent_resource.set_template(self.templ, {"KeyName": "test"})
        scheduler.TaskRunner(self.parent_resource.create)()
        self.stack = self.parent_resource.nested()

        scheduler.TaskRunner(self.parent_resource.suspend)()

        st_set = self.stack.state_set
        self.m.StubOutWithMock(self.stack, 'state_set')
        self.stack.state_set(parser.Stack.RESUME, parser.Stack.IN_PROGRESS,
                             "Stack RESUME started").WithSideEffects(st_set)

        self.stack.state_set(parser.Stack.RESUME, parser.Stack.COMPLETE,
                             "Stack resume completed successfully")
        self.m.ReplayAll()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(self.parent_resource.resume))
        self.assertEqual(('RESUME', 'FAILED'), self.parent_resource.state)
        self.assertEqual(('Error: Stack RESUME started'),
                         self.parent_resource.status_reason)

        self.m.VerifyAll()
        # Restore state_set to let clean up proceed
        self.stack.state_set = st_set
