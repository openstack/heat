
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

import uuid

import mock
import mox

from heat.common import exception
from heat.common import template_format
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import stack_resource
from heat.tests.common import HeatTestCase
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils


ws_res_snippet = {"Type": "some_magic_type",
                  "metadata": {
                      "key": "value",
                      "some": "more stuff"}}

param_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "GenericResource",
      "Properties": {}
    }
  }
}
'''


simple_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Parameters" : {},
  "Resources" : {
    "WebServer": {
      "Type": "GenericResource",
      "Properties": {}
    }
  }
}
'''


class MyStackResource(stack_resource.StackResource,
                      generic_rsrc.GenericResource):
    def physical_resource_name(self):
        return "cb2f2b28-a663-4683-802c-4b40c916e1ff"

    def set_template(self, nested_template, params):
        self.nested_template = nested_template
        self.nested_params = params

    def handle_create(self):
        return self.create_with_template(self.nested_template,
                                         self.nested_params)

    def handle_adopt(self, resource_data):
        return self.create_with_template(self.nested_template,
                                         self.nested_params,
                                         adopt_data=resource_data)

    def handle_delete(self):
        self.delete_nested()


class MyImplementedStackResource(MyStackResource):
    def child_template(self):
        return self.nested_template

    def child_params(self):
        return self.nested_params


class StackResourceTest(HeatTestCase):

    def setUp(self):
        super(StackResourceTest, self).setUp()
        utils.setup_dummy_db()
        resource._register_class('some_magic_type',
                                 MyStackResource)
        resource._register_class('GenericResource',
                                 generic_rsrc.GenericResource)
        t = parser.Template({'Resources':
                             {"provider_resource": ws_res_snippet}})
        self.parent_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                         t, stack_id=str(uuid.uuid4()))
        self.parent_resource = MyStackResource('test',
                                               ws_res_snippet,
                                               self.parent_stack)
        self.templ = template_format.parse(param_template)
        self.simple_template = template_format.parse(simple_template)

    def test_child_template_defaults_to_not_implemented(self):
        self.assertRaises(NotImplementedError,
                          self.parent_resource.child_template)

    def test_child_params_defaults_to_not_implemented(self):
        self.assertRaises(NotImplementedError,
                          self.parent_resource.child_params)

    def test_preview_defaults_to_stack_resource_itself(self):
        preview = self.parent_resource.preview()
        self.assertIsInstance(preview, stack_resource.StackResource)

    def test_propagated_files(self):
        self.parent_stack.t.files["foo"] = "bar"
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()
        self.assertEqual({"foo": "bar"}, self.stack.t.files)

    @mock.patch.object(stack_resource.StackResource, '_nested_environment')
    @mock.patch.object(stack_resource.parser, 'Template')
    @mock.patch.object(stack_resource.parser, 'Stack')
    def test_preview_with_implemented_child_resource(self, mock_stack_class,
                                                     mock_template_class,
                                                     mock_env_class):
        nested_stack = mock.Mock()
        mock_stack_class.return_value = nested_stack
        nested_stack.preview_resources.return_value = 'preview_nested_stack'
        mock_template_class.return_value = 'parsed_template'
        mock_env_class.return_value = 'environment'
        template = template_format.parse(param_template)
        parent_resource = MyImplementedStackResource('test',
                                                     ws_res_snippet,
                                                     self.parent_stack)
        params = {'KeyName': 'test'}
        parent_resource.set_template(template, params)
        validation_mock = mock.Mock(return_value=None)
        parent_resource._validate_nested_resources = validation_mock

        result = parent_resource.preview()
        mock_env_class.assert_called_once_with(params)
        mock_template_class.assert_called_once_with(template)
        self.assertEqual('preview_nested_stack', result)
        mock_stack_class.assert_called_once_with(
            mock.ANY,
            'test_stack-test',
            'parsed_template',
            'environment',
            disable_rollback=mock.ANY,
            parent_resource=parent_resource,
            owner_id=mock.ANY
        )

    def test_preview_validates_nested_resources(self):
        stack_resource = MyImplementedStackResource('test',
                                                    ws_res_snippet,
                                                    self.parent_stack)
        stack_resource.child_template = mock.Mock(return_value={})
        stack_resource.child_params = mock.Mock()
        exc = exception.RequestLimitExceeded(message='Validation Failed')
        validation_mock = mock.Mock(side_effect=exc)
        stack_resource._validate_nested_resources = validation_mock

        self.assertRaises(exception.RequestLimitExceeded,
                          stack_resource.preview)

    def test__validate_nested_resources_checks_num_of_resources(self):
        stack_resource.cfg.CONF.set_override('max_resources_per_stack', 2)
        tmpl = {'Resources': [1]}
        template = stack_resource.parser.Template(tmpl)
        root_resources = mock.Mock(return_value=2)
        self.parent_resource.stack.root_stack.total_resources = root_resources

        self.assertRaises(exception.RequestLimitExceeded,
                          self.parent_resource._validate_nested_resources,
                          template)

    @utils.stack_delete_after
    def test_create_with_template_ok(self):
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()

        self.assertEqual(self.parent_resource, self.stack.parent_resource)
        self.assertEqual("cb2f2b28-a663-4683-802c-4b40c916e1ff",
                         self.stack.name)
        self.assertEqual(self.templ, self.stack.t.t)
        self.assertEqual(self.stack.id, self.parent_resource.resource_id)
        self.assertIsNone(self.stack.timeout_mins)

    @utils.stack_delete_after
    def test_create_with_template_timeout_mins(self):
        self.assertIsNone(self.parent_stack.timeout_mins)
        self.m.StubOutWithMock(self.parent_stack, 'timeout_mins')
        self.parent_stack.timeout_mins = 100
        self.m.ReplayAll()
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()
        self.assertEqual(100, self.stack.timeout_mins)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_adopt_with_template_ok(self):
        adopt_data = {
            "resources": {
                "WebServer": {
                    "resource_id": "test-res-id"
                }
            }
        }
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"},
                                                  adopt_data=adopt_data)
        self.stack = self.parent_resource.nested()

        self.assertEqual(self.stack.ADOPT, self.stack.action)
        self.assertEqual('test-res-id',
                         self.stack.resources['WebServer'].resource_id)
        self.assertEqual(self.parent_resource, self.stack.parent_resource)
        self.assertEqual("cb2f2b28-a663-4683-802c-4b40c916e1ff",
                         self.stack.name)
        self.assertEqual(self.templ, self.stack.t.t)
        self.assertEqual(self.stack.id, self.parent_resource.resource_id)

    @utils.stack_delete_after
    def test_set_deletion_policy(self):
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()
        self.parent_resource.set_deletion_policy(resource.RETAIN)
        for res in self.stack.resources.values():
            self.assertEqual(resource.RETAIN, res.t['DeletionPolicy'])

    @utils.stack_delete_after
    def test_get_abandon_data(self):
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        ret = self.parent_resource.get_abandon_data()
        # check abandoned data contains all the necessary information.
        # (no need to check stack/resource IDs, because they are
        # randomly generated uuids)
        self.assertEqual(6, len(ret))
        self.assertEqual('CREATE', ret['action'])
        self.assertIn('name', ret)
        self.assertIn('id', ret)
        self.assertIn('resources', ret)
        self.assertEqual(template_format.parse(param_template),
                         ret['template'])

    @utils.stack_delete_after
    def test_create_with_template_validates(self):
        """
        Creating a stack with a template validates the created stack, so that
        an invalid template will cause an error to be raised.
        """
        # Make a parameter key with the same name as the resource to cause a
        # simple validation error
        template = self.simple_template.copy()
        template['Parameters']['WebServer'] = {'Type': 'String'}
        self.assertRaises(
            exception.StackValidationFailed,
            self.parent_resource.create_with_template,
            template, {'WebServer': 'foo'})

    @utils.stack_delete_after
    def test_update_with_template_validates(self):
        """Updating a stack with a template validates the created stack."""
        create_result = self.parent_resource.create_with_template(
            self.simple_template, {})
        while not create_result.step():
            pass

        template = self.simple_template.copy()
        template['Parameters']['WebServer'] = {'Type': 'String'}
        self.assertRaises(
            exception.StackValidationFailed,
            self.parent_resource.update_with_template,
            template, {'WebServer': 'foo'})

    @utils.stack_delete_after
    def test_update_with_template_ok(self):
        """
        The update_with_template method updates the nested stack with the
        given template and user parameters.
        """
        create_result = self.parent_resource.create_with_template(
            self.simple_template, {})
        while not create_result.step():
            pass
        self.stack = self.parent_resource.nested()

        new_templ = self.simple_template.copy()
        inst_snippet = new_templ["Resources"]["WebServer"].copy()
        new_templ["Resources"]["WebServer2"] = inst_snippet
        updater = self.parent_resource.update_with_template(
            new_templ, {})
        updater.run_to_completion()
        self.assertIs(True,
                      self.parent_resource.check_update_complete(updater))
        self.assertEqual(('UPDATE', 'COMPLETE'), self.stack.state)
        self.assertEqual(set(["WebServer", "WebServer2"]),
                         set(self.stack.keys()))
        self.assertIsNone(self.stack.timeout_mins)

        # The stack's owner_id is maintained.
        saved_stack = parser.Stack.load(
            self.parent_stack.context, self.stack.id)
        self.assertEqual(self.parent_stack.id, saved_stack.owner_id)

    @utils.stack_delete_after
    def test_update_with_template_timeout_mins(self):
        self.assertIsNone(self.parent_stack.timeout_mins)
        self.m.StubOutWithMock(self.parent_stack, 'timeout_mins')
        self.parent_stack.timeout_mins = 100
        self.m.ReplayAll()

        create_result = self.parent_resource.create_with_template(
            self.simple_template, {})
        while not create_result.step():
            pass
        self.stack = self.parent_resource.nested()
        self.assertEqual(100, self.stack.timeout_mins)

        self.parent_stack.timeout_mins = 200
        self.m.ReplayAll()

        updater = self.parent_resource.update_with_template(
            self.simple_template, {})
        updater.run_to_completion()
        self.assertEqual(200, self.stack.timeout_mins)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_with_template_files(self):
        create_result = self.parent_resource.create_with_template(
            self.simple_template, {})
        while not create_result.step():
            pass
        self.stack = self.parent_resource.nested()

        new_templ = self.simple_template.copy()
        inst_snippet = new_templ["Resources"]["WebServer"].copy()
        new_templ["Resources"]["WebServer2"] = inst_snippet
        self.parent_stack.t.files["foo"] = "bar"
        updater = self.parent_resource.update_with_template(
            new_templ, {})
        updater.run_to_completion()

        self.assertEqual({"foo": "bar"}, self.stack.t.files)

    @utils.stack_delete_after
    def test_update_with_template_state_err(self):
        """
        update_with_template_state_err method should raise error when update
        task is done but the nested stack is in (UPDATE, FAILED) state.
        """
        create_creator = self.parent_resource.create_with_template(
            self.simple_template, {})
        create_creator.run_to_completion()
        self.stack = self.parent_resource.nested()

        new_templ = self.simple_template.copy()
        inst_snippet = new_templ["Resources"]["WebServer"].copy()
        new_templ["Resources"]["WebServer2"] = inst_snippet

        def update_task():
            yield
            self.stack.state_set(parser.Stack.UPDATE, parser.Stack.FAILED, '')

        self.m.StubOutWithMock(self.stack, 'update_task')
        self.stack.update_task(mox.IgnoreArg()).AndReturn(update_task())
        self.m.ReplayAll()

        updater = self.parent_resource.update_with_template(new_templ, {})
        updater.run_to_completion()
        self.assertEqual((self.stack.UPDATE, self.stack.FAILED),
                         self.stack.state)
        ex = self.assertRaises(exception.Error,
                               self.parent_resource.check_update_complete,
                               updater)
        self.assertEqual('Nested stack UPDATE failed: ', str(ex))

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_load_nested_ok(self):
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()

        self.parent_resource._nested = None
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.parent_resource.context,
                          self.parent_resource.resource_id,
                          parent_resource=self.parent_resource,
                          show_deleted=False).AndReturn('s')
        self.m.ReplayAll()

        self.parent_resource.nested()
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_load_nested_non_exist(self):
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()

        self.parent_resource._nested = None
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.parent_resource.context,
                          self.parent_resource.resource_id,
                          parent_resource=self.parent_resource,
                          show_deleted=False)
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

    def test_delete_nested_not_found_nested_stack(self):
        self.parent_resource.create_with_template(self.templ,
                                                  {"KeyName": "key"})
        self.stack = self.parent_resource.nested()

        self.parent_resource._nested = None
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(
            self.parent_resource.context,
            self.parent_resource.resource_id,
            parent_resource=self.parent_resource,
            show_deleted=False).AndRaise(exception.NotFound(''))
        self.m.ReplayAll()

        self.assertIsNone(self.parent_resource.delete_nested())

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

    @utils.stack_delete_after
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
        parser.Template(self.templ, files={}).AndReturn(templ)

        self.m.StubOutWithMock(environment, 'Environment')
        environment.Environment().AndReturn(env)

        self.m.StubOutWithMock(parser, 'Stack')
        parser.Stack(ctx, phy_id, templ, env, timeout_mins=None,
                     disable_rollback=True,
                     parent_resource=self.parent_resource,
                     owner_id=self.parent_stack.id,
                     adopt_stack_data=None).AndReturn(self.stack)

        st_set = self.stack.state_set
        self.m.StubOutWithMock(self.stack, 'state_set')
        self.stack.state_set(self.stack.CREATE, self.stack.IN_PROGRESS,
                             "Stack CREATE started").WithSideEffects(st_set)

        self.stack.state_set(self.stack.CREATE, self.stack.COMPLETE,
                             "Stack CREATE completed successfully")
        self.m.ReplayAll()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(self.parent_resource.create))
        self.assertEqual(('CREATE', 'FAILED'), self.parent_resource.state)
        self.assertEqual(('Error: Stack CREATE started'),
                         self.parent_resource.status_reason)

        self.m.VerifyAll()
        # Restore state_set to let clean up proceed
        self.stack.state_set = st_set

    @utils.stack_delete_after
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
                             "Stack SUSPEND completed successfully")
        self.m.ReplayAll()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(self.parent_resource.suspend))
        self.assertEqual(('SUSPEND', 'FAILED'), self.parent_resource.state)
        self.assertEqual(('Error: Stack SUSPEND started'),
                         self.parent_resource.status_reason)

        self.m.VerifyAll()
        # Restore state_set to let clean up proceed
        self.stack.state_set = st_set

    @utils.stack_delete_after
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
                             "Stack RESUME completed successfully")
        self.m.ReplayAll()

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(self.parent_resource.resume))
        self.assertEqual(('RESUME', 'FAILED'), self.parent_resource.state)
        self.assertEqual(('Error: Stack RESUME started'),
                         self.parent_resource.status_reason)

        self.m.VerifyAll()
        # Restore state_set to let clean up proceed
        self.stack.state_set = st_set
