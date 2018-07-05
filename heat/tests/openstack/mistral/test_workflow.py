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
import yaml

from mistralclient.api.v2 import executions
from oslo_serialization import jsonutils

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import mistral as client
from heat.engine import node_data
from heat.engine import resource
from heat.engine.resources.openstack.mistral import workflow
from heat.engine.resources import signal_responder
from heat.engine.resources import stack_user
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils

workflow_template = """
heat_template_version: 2013-05-23
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      type: direct
      tasks:
        - name: hello
          action: std.echo output='Good morning!'
          publish:
            result: <% $.hello %>
"""
workflow_template_with_tags = """
heat_template_version: queens
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      type: direct
      tags:
        - tagged
      tasks:
        - name: hello
          action: std.echo output='Good morning!'
          publish:
            result: <% $.hello %>
"""
workflow_template_with_params = """
heat_template_version: 2013-05-23
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      params: {'test':'param_value'}
      type: direct
      tasks:
        - name: hello
          action: std.echo output='Good morning!'
          publish:
            result: <% $.hello %>
"""
workflow_template_with_params_override = """
heat_template_version: 2013-05-23
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      params: {'test':'param_value_override','test1':'param_value_override_1'}
      type: direct
      tasks:
        - name: hello
          action: std.echo output='Good morning!'
          publish:
            result: <% $.hello %>
"""

workflow_template_full = """
heat_template_version: 2013-05-23
parameters:
    use_request_body_as_input:
      type : boolean
      default : false
resources:
 create_vm:
   type: OS::Mistral::Workflow
   properties:
     name: create_vm
     use_request_body_as_input: { get_param: use_request_body_as_input }
     type: direct
     input:
       name: create_test_server
       image: 31d8eeaf-686e-4e95-bb27-765014b9f20b
       flavor: 2
     output:
       vm_id: <% $.vm_id %>
     task_defaults:
       on_error:
         - on_error
     tasks:
       - name: create_server
         action: |
           nova.servers_create name=<% $.name %> image=<% $.image %>
           flavor=<% $.flavor %>
         publish:
           vm_id: <% $.create_server.id %>
         on_success:
           - check_server_exists
       - name: check_server_exists
         action: nova.servers_get server=<% $.vm_id %>
         publish:
           server_exists: True
         on_success:
           - list_machines
       - name: wait_instance
         action: nova.servers_find id=<% $.vm_id_new %> status='ACTIVE'
         retry:
             delay: 5
             count: 15
         wait_before: 7
         wait_after: 8
         pause_before: true
         timeout: 11
         keep_result: false
         target: test
         with_items: vm_id_new in <% $.list_servers %>
       - name: list_machines
         action: nova.servers_list
         publish:
           -list_servers:  <% $.list_machines %>
         on_success:
           - wait_instance
       - name: on_error
         action: std.echo output="output"
       - name: external_workflow
         workflow: external_workflow_name
"""

workflow_updating_request_body_property = """
heat_template_version: 2013-05-23
resources:
 create_vm:
   type: OS::Mistral::Workflow
   properties:
     name: create_vm
     use_request_body_as_input: false
     type: direct
     input:
       name: create_test_server
       image: 31d8eeaf-686e-4e95-bb27-765014b9f20b
       flavor: 2
     output:
       vm_id: <% $.vm_id %>
     task_defaults:
       on_error:
         - on_error
     tasks:
       - name: create_server
         action: |
           nova.servers_create name=<% $.name %> image=<% $.image %>
           flavor=<% $.flavor %>
         publish:
           vm_id: <% $.create_server.id %>
         on_success:
           - check_server_exists
       - name: check_server_exists
         action: nova.servers_get server=<% $.vm_id %>
         publish:
           server_exists: True
         on_success:
           - list_machines
       - name: wait_instance
         action: nova.servers_find id=<% $.vm_id_new %> status='ACTIVE'
         retry:
             delay: 5
             count: 15
         wait_before: 7
         wait_after: 8
         pause_before: true
         timeout: 11
         keep_result: false
         target: test
         with_items: vm_id_new in <% $.list_servers %>
         join: all
       - name: list_machines
         action: nova.servers_list
         publish:
           -list_servers:  <% $.list_machines %>
         on_success:
           - wait_instance
       - name: on_error
         action: std.echo output="output"

"""

workflow_template_backward_support = """
heat_template_version: 2013-05-23
resources:
 create_vm:
   type: OS::Mistral::Workflow
   properties:
     name: create_vm
     type: direct
     input:
       name: create_test_server
       image: 31d8eeaf-686e-4e95-bb27-765014b9f20b
       flavor: 2
     output:
       vm_id: <% $.vm_id %>
     tasks:
       - name: create_server
         action: |
           nova.servers_create name=<% $.name %> image=<% $.image %>
           flavor=<% $.flavor %>
         publish:
           vm_id: <% $.create_server.id %>
         on_success:
           - check_server_exists
       - name: check_server_exists
         action: nova.servers_get server=<% $.vm_id %>
         publish:
           server_exists: True
         on_success:
           - wait_instance
       - name: wait_instance
         action: nova.servers_find id=<% $.vm_id %> status='ACTIVE'
         policies:
           retry:
             delay: 5
             count: 15
"""

workflow_template_bad = """
heat_template_version: 2013-05-23
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      type: direct
      tasks:
        - name: second_task
          action: std.noop
          requires: [first_task]
        - name: first_task
          action: std.noop
"""

workflow_template_bad_reverse = """
heat_template_version: 2013-05-23
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      type: reverse
      tasks:
        - name: second_task
          action: std.noop
          requires: [first_task]
        - name: first_task
          action: std.noop
"""

workflow_template_concurrency_no_with_items = """
heat_template_version: 2013-05-23
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      params: {'test':'param_value'}
      type: direct
      tasks:
        - name: hello
          action: std.echo output='Good morning!'
          concurrency: 9001
"""

workflow_template_update_replace = """
heat_template_version: 2013-05-23
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      name: hello_action
      type: direct
      tasks:
        - name: hello
          action: std.echo output='Good evening!'
          publish:
            result: <% $.hello %>
"""

workflow_template_update = """
heat_template_version: 2013-05-23
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      type: direct
      description: just testing workflow resource
      tasks:
        - name: hello
          action: std.echo output='Good evening!'
          publish:
            result: <% $.hello %>
"""

workflow_template_duplicate_polices = """
heat_template_version: 2013-05-23
resources:
 workflow:
   type: OS::Mistral::Workflow
   properties:
     name: list
     type: direct
     tasks:
       - name: list
         action: nova.servers_list
         policies:
           retry:
             delay: 5
             count: 15
         retry:
             delay: 6
             count: 16
"""

workflow_template_policies_translation = """
heat_template_version: 2016-10-14
resources:
  workflow:
    type: OS::Mistral::Workflow
    properties:
      name: translation_done
      type: direct
      tasks:
        - name: check_dat_thing
          action: nova.servers_list
          policies:
            retry:
              delay: 5
              count: 15
            wait_before: 5
            wait_after: 5
            pause_before: true
            timeout: 42
            concurrency: 5
"""


class FakeWorkflow(object):
    def __init__(self, name):
        self.name = name
        self._data = {'workflow': 'info'}

    def to_dict(self):
        return self._data


class TestMistralWorkflow(common.HeatTestCase):
    def setUp(self):
        super(TestMistralWorkflow, self).setUp()
        self.ctx = utils.dummy_context()
        tmpl = template_format.parse(workflow_template)
        self.stack = utils.parse_stack(tmpl, stack_name='test_stack')

        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['workflow']

        self.mistral = mock.Mock()
        self.patchobject(workflow.Workflow, 'client',
                         return_value=self.mistral)

        self.patches = []
        self.patches.append(mock.patch.object(stack_user.StackUser,
                                              '_create_user'))
        self.patches.append(mock.patch.object(signal_responder.SignalResponder,
                                              '_create_keypair'))
        self.patches.append(mock.patch.object(client.MistralClientPlugin,
                                              '_create'))
        for patch in self.patches:
            patch.start()

        self.client = client.MistralClientPlugin(self.ctx)

    def tearDown(self):
        super(TestMistralWorkflow, self).tearDown()
        for patch in self.patches:
            patch.stop()

    def _create_resource(self, name, snippet, stack):
        wf = workflow.Workflow(name, snippet, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('test_stack-workflow-b5fiekfci3yc')]
        scheduler.TaskRunner(wf.create)()
        return wf

    def test_create(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)
        expected_state = (wf.CREATE, wf.COMPLETE)
        self.assertEqual(expected_state, wf.state)
        self.assertEqual('test_stack-workflow-b5fiekfci3yc', wf.resource_id)

    def test_create_with_name(self):
        tmpl = template_format.parse(workflow_template_full)
        stack = utils.parse_stack(tmpl)

        rsrc_defns = stack.t.resource_definitions(stack)['create_vm']

        wf = workflow.Workflow('create_vm', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('create_vm')]
        scheduler.TaskRunner(wf.create)()

        expected_state = (wf.CREATE, wf.COMPLETE)
        self.assertEqual(expected_state, wf.state)
        self.assertEqual('create_vm', wf.resource_id)

    def test_create_with_task_parms(self):
        tmpl = template_format.parse(workflow_template_full)
        stack = utils.parse_stack(tmpl)

        rsrc_defns = stack.t.resource_definitions(stack)['create_vm']
        wf = workflow.Workflow('create_vm', rsrc_defns, stack)
        self.mistral.workflows.create.side_effect = (lambda args:
                                                     self.verify_create_params(
                                                         args))
        scheduler.TaskRunner(wf.create)()

    def test_backward_support(self):
        tmpl = template_format.parse(workflow_template_backward_support)
        stack = utils.parse_stack(tmpl)

        rsrc_defns = stack.t.resource_definitions(stack)['create_vm']

        wf = workflow.Workflow('create_vm', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('create_vm')]
        scheduler.TaskRunner(wf.create)()

        expected_state = (wf.CREATE, wf.COMPLETE)
        self.assertEqual(expected_state, wf.state)
        self.assertEqual('create_vm', wf.resource_id)
        for task in wf.properties['tasks']:
            if task['name'] == 'wait_instance':
                self.assertEqual(5, task['retry']['delay'])
                self.assertEqual(15, task['retry']['count'])
                break

    def test_attributes(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)
        self.mistral.workflows.get.return_value = (
            FakeWorkflow('test_stack-workflow-b5fiekfci3yc'))
        self.assertEqual({'name': 'test_stack-workflow-b5fiekfci3yc',
                          'input': None}, wf.FnGetAtt('data'))
        self.assertEqual([], wf.FnGetAtt('executions'))
        self.assertEqual({'workflow': 'info'}, wf.FnGetAtt('show'))

    def test_direct_workflow_validation_error(self):
        error_msg = ("Mistral resource validation error: "
                     "workflow.properties.tasks.second_task.requires: "
                     "task second_task contains property 'requires' "
                     "in case of direct workflow. Only reverse workflows "
                     "can contain property 'requires'.")
        self._test_validation_failed(workflow_template_bad, error_msg)

    def test_wrong_params_using(self):
        error_msg = ("Mistral resource validation error: "
                     "workflow.properties.params: 'task_name' is not assigned "
                     "in 'params' in case of reverse type workflow.")
        self._test_validation_failed(workflow_template_bad_reverse, error_msg)

    def test_with_items_concurrency_failed_validate(self):
        error_msg = "concurrency cannot be specified without with_items."
        self._test_validation_failed(
            workflow_template_concurrency_no_with_items,
            error_msg,
            error_cls=exception.ResourcePropertyDependency)

    def _test_validation_failed(self, templatem, error_msg, error_cls=None):
        tmpl = template_format.parse(templatem)
        stack = utils.parse_stack(tmpl)

        rsrc_defns = stack.t.resource_definitions(stack)['workflow']

        wf = workflow.Workflow('workflow', rsrc_defns, stack)

        if error_cls is None:
            error_cls = exception.StackValidationFailed

        exc = self.assertRaises(error_cls, wf.validate)
        self.assertEqual(error_msg, six.text_type(exc))

    def test_create_wrong_definition(self):
        tmpl = template_format.parse(workflow_template)
        stack = utils.parse_stack(tmpl)

        rsrc_defns = stack.t.resource_definitions(stack)['workflow']

        wf = workflow.Workflow('workflow', rsrc_defns, stack)

        self.mistral.workflows.create.side_effect = Exception('boom!')

        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(wf.create))
        expected_state = (wf.CREATE, wf.FAILED)
        self.assertEqual(expected_state, wf.state)
        self.assertIn('Exception: resources.workflow: boom!',
                      six.text_type(exc))

    def test_update_replace(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)

        t = template_format.parse(workflow_template_update_replace)
        rsrc_defns = template.Template(t).resource_definitions(self.stack)
        new_workflow = rsrc_defns['workflow']

        new_workflows = [FakeWorkflow('hello_action')]
        self.mistral.workflows.update.return_value = new_workflows
        self.mistral.workflows.delete.return_value = None

        err = self.assertRaises(resource.UpdateReplace,
                                scheduler.TaskRunner(wf.update,
                                                     new_workflow))
        msg = 'The Resource workflow requires replacement.'
        self.assertEqual(msg, six.text_type(err))

    def test_update(self):
        wf = self._create_resource('workflow', self.rsrc_defn,
                                   self.stack)
        t = template_format.parse(workflow_template_update)
        rsrc_defns = template.Template(t).resource_definitions(self.stack)
        new_wf = rsrc_defns['workflow']
        self.mistral.workflows.update.return_value = [
            FakeWorkflow('test_stack-workflow-b5fiekfci3yc')]
        scheduler.TaskRunner(wf.update, new_wf)()
        self.assertTrue(self.mistral.workflows.update.called)
        self.assertEqual((wf.UPDATE, wf.COMPLETE), wf.state)

    def test_update_input(self):
        wf = self._create_resource('workflow', self.rsrc_defn,
                                   self.stack)
        t = template_format.parse(workflow_template)
        t['resources']['workflow']['properties']['input'] = {'foo': 'bar'}
        rsrc_defns = template.Template(t).resource_definitions(self.stack)
        new_wf = rsrc_defns['workflow']
        self.mistral.workflows.update.return_value = [
            FakeWorkflow('test_stack-workflow-b5fiekfci3yc')]
        scheduler.TaskRunner(wf.update, new_wf)()
        self.assertTrue(self.mistral.workflows.update.called)
        self.assertEqual((wf.UPDATE, wf.COMPLETE), wf.state)

    def test_update_failed(self):
        wf = self._create_resource('workflow', self.rsrc_defn,
                                   self.stack)
        t = template_format.parse(workflow_template_update)
        rsrc_defns = template.Template(t).resource_definitions(self.stack)
        new_wf = rsrc_defns['workflow']
        self.mistral.workflows.update.side_effect = Exception('boom!')
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(wf.update, new_wf))
        self.assertEqual((wf.UPDATE, wf.FAILED), wf.state)

    def test_delete_super_call_successful(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)

        scheduler.TaskRunner(wf.delete)()
        self.assertEqual((wf.DELETE, wf.COMPLETE), wf.state)

        self.assertEqual(1, self.mistral.workflows.delete.call_count)

    def test_delete_executions_successful(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)

        self.mistral.executuions.delete.return_value = None
        wf._data = {'executions': '1234,5678'}
        data_delete = self.patchobject(resource.Resource, 'data_delete')

        wf._delete_executions()

        self.assertEqual(2, self.mistral.executions.delete.call_count)
        data_delete.assert_called_once_with('executions')

    def test_delete_executions_not_found(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)

        self.mistral.executuions.delete.side_effect = [
            self.mistral.mistral_base.APIException(error_code=404),
            None
        ]
        wf._data = {'executions': '1234,5678'}
        data_delete = self.patchobject(resource.Resource, 'data_delete')

        wf._delete_executions()

        self.assertEqual(2, self.mistral.executions.delete.call_count)
        data_delete.assert_called_once_with('executions')

    def test_signal_failed(self):
        tmpl = template_format.parse(workflow_template_full)
        stack = utils.parse_stack(tmpl)
        rsrc_defns = stack.t.resource_definitions(stack)['create_vm']
        wf = workflow.Workflow('create_vm', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('create_vm')]
        scheduler.TaskRunner(wf.create)()
        details = {'input': {'flavor': '3'}}
        self.mistral.executions.create.side_effect = Exception('boom!')
        err = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(wf.signal, details))
        self.assertEqual('Exception: resources.create_vm: boom!',
                         six.text_type(err))

    def test_signal_wrong_input_and_params_type(self):
        tmpl = template_format.parse(workflow_template_full)
        stack = utils.parse_stack(tmpl)
        rsrc_defns = stack.t.resource_definitions(stack)['create_vm']
        wf = workflow.Workflow('create_vm', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('create_vm')]
        scheduler.TaskRunner(wf.create)()
        details = {'input': '3'}
        err = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(wf.signal, details))
        if six.PY3:
            entity = 'class'
        else:
            entity = 'type'
        error_message = ("StackValidationFailed: resources.create_vm: "
                         "Signal data error: Input in"
                         " signal data must be a map, find a <%s 'str'>" %
                         entity)
        self.assertEqual(error_message, six.text_type(err))
        details = {'params': '3'}
        err = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(wf.signal, details))
        error_message = ("StackValidationFailed: resources.create_vm: "
                         "Signal data error: Params "
                         "must be a map, find a <%s 'str'>" % entity)
        self.assertEqual(error_message, six.text_type(err))

    def test_signal_wrong_input_key(self):
        tmpl = template_format.parse(workflow_template_full)
        stack = utils.parse_stack(tmpl)
        rsrc_defns = stack.t.resource_definitions(stack)['create_vm']
        wf = workflow.Workflow('create_vm', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('create_vm')]
        scheduler.TaskRunner(wf.create)()
        details = {'input': {'1': '3'}}
        err = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(wf.signal, details))
        error_message = ("StackValidationFailed: resources.create_vm: "
                         "Signal data error: Unknown input 1")
        self.assertEqual(error_message, six.text_type(err))

    def test_signal_with_body_as_input_and_delete_with_executions(self):
        tmpl = template_format.parse(workflow_template_full)
        stack = utils.parse_stack(tmpl, params={
            'parameters': {'use_request_body_as_input': 'true'}
        })
        rsrc_defns = stack.t.resource_definitions(stack)['create_vm']
        wf = workflow.Workflow('create_vm', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('create_vm')]
        scheduler.TaskRunner(wf.create)()
        details = {'flavor': '3'}
        execution = mock.Mock()
        execution.id = '12345'
        exec_manager = executions.ExecutionManager(wf.client('mistral'))
        self.mistral.executions.create.side_effect = (
            lambda *args, **kw: exec_manager.create(*args, **kw))
        self.patchobject(exec_manager, '_create', return_value=execution)
        scheduler.TaskRunner(wf.signal, details)()
        call_args = self.mistral.executions.create.call_args
        args, kwargs = call_args
        expected_args = (
            '{"image": "31d8eeaf-686e-4e95-bb27-765014b9f20b", '
            '"name": "create_test_server", "flavor": "3"}')
        self.validate_json_inputs(kwargs['workflow_input'], expected_args)
        self.assertEqual({'executions': '12345'}, wf.data())
        # Updating the workflow changing "use_request_body_as_input" to
        # false and signaling again with the expected request body format.
        t = template_format.parse(workflow_updating_request_body_property)
        new_stack = utils.parse_stack(t)
        rsrc_defns = new_stack.t.resource_definitions(new_stack)
        self.mistral.workflows.update.return_value = [
            FakeWorkflow('test_stack-workflow-b5fiekdsa355')]
        scheduler.TaskRunner(wf.update, rsrc_defns['create_vm'])()
        self.assertTrue(self.mistral.workflows.update.called)
        self.assertEqual((wf.UPDATE, wf.COMPLETE), wf.state)
        details = {'input': {'flavor': '4'}}
        execution = mock.Mock()
        execution.id = '54321'
        exec_manager = executions.ExecutionManager(wf.client('mistral'))
        self.mistral.executions.create.side_effect = (
            lambda *args, **kw: exec_manager.create(*args, **kw))
        self.patchobject(exec_manager, '_create', return_value=execution)
        scheduler.TaskRunner(wf.signal, details)()
        call_args = self.mistral.executions.create.call_args
        args, kwargs = call_args
        expected_args = (
            '{"image": "31d8eeaf-686e-4e95-bb27-765014b9f20b", '
            '"name": "create_test_server", "flavor": "4"}')
        self.validate_json_inputs(kwargs['workflow_input'], expected_args)
        self.assertEqual({'executions': '54321,12345', 'name':
                         'test_stack-workflow-b5fiekdsa355'}, wf.data())
        scheduler.TaskRunner(wf.delete)()
        self.assertEqual(2, self.mistral.executions.delete.call_count)
        self.assertEqual((wf.DELETE, wf.COMPLETE), wf.state)

    def test_signal_and_delete_with_executions(self):
        tmpl = template_format.parse(workflow_template_full)
        stack = utils.parse_stack(tmpl)
        rsrc_defns = stack.t.resource_definitions(stack)['create_vm']
        wf = workflow.Workflow('create_vm', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('create_vm')]
        scheduler.TaskRunner(wf.create)()
        details = {'input': {'flavor': '3'}}
        execution = mock.Mock()
        execution.id = '12345'
        # Invoke the real create method (bug 1453539)
        exec_manager = executions.ExecutionManager(wf.client('mistral'))
        self.mistral.executions.create.side_effect = (
            lambda *args, **kw: exec_manager.create(*args, **kw))
        self.patchobject(exec_manager, '_create', return_value=execution)
        scheduler.TaskRunner(wf.signal, details)()
        self.assertEqual({'executions': '12345'}, wf.data())
        scheduler.TaskRunner(wf.delete)()
        self.assertEqual(1, self.mistral.executions.delete.call_count)
        self.assertEqual((wf.DELETE, wf.COMPLETE), wf.state)

    def test_workflow_params(self):
        tmpl = template_format.parse(workflow_template_full)
        stack = utils.parse_stack(tmpl)
        rsrc_defns = stack.t.resource_definitions(stack)['create_vm']
        wf = workflow.Workflow('create_vm', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('create_vm')]
        scheduler.TaskRunner(wf.create)()
        details = {'input': {'flavor': '3'},
                   'params': {'test': 'param_value', 'test1': 'param_value_1'}}
        execution = mock.Mock()
        execution.id = '12345'
        self.mistral.executions.create.side_effect = (
            lambda *args, **kw: self.verify_params(*args, **kw))
        scheduler.TaskRunner(wf.signal, details)()

    def test_workflow_tags(self):
        tmpl = template_format.parse(workflow_template_with_tags)
        stack = utils.parse_stack(tmpl)
        rsrc_defns = stack.t.resource_definitions(stack)['workflow']
        wf = workflow.Workflow('workflow', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('workflow')]
        scheduler.TaskRunner(wf.create)()
        details = {'tags': ['mytag'],
                   'params': {'test': 'param_value', 'test1': 'param_value_1'}}
        execution = mock.Mock()
        execution.id = '12345'
        self.mistral.executions.create.side_effect = (
            lambda *args, **kw: self.verify_params(*args, **kw))
        scheduler.TaskRunner(wf.signal, details)()

    def test_workflow_params_merge(self):
        tmpl = template_format.parse(workflow_template_with_params)
        stack = utils.parse_stack(tmpl)
        rsrc_defns = stack.t.resource_definitions(stack)['workflow']
        wf = workflow.Workflow('workflow', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('workflow')]
        scheduler.TaskRunner(wf.create)()
        details = {'params': {'test1': 'param_value_1'}}
        execution = mock.Mock()
        execution.id = '12345'
        self.mistral.executions.create.side_effect = (
            lambda *args, **kw: self.verify_params(*args, **kw))
        scheduler.TaskRunner(wf.signal, details)()

    def test_workflow_params_override(self):
        tmpl = template_format.parse(workflow_template_with_params_override)
        stack = utils.parse_stack(tmpl)
        rsrc_defns = stack.t.resource_definitions(stack)['workflow']
        wf = workflow.Workflow('workflow', rsrc_defns, stack)
        self.mistral.workflows.create.return_value = [
            FakeWorkflow('workflow')]
        scheduler.TaskRunner(wf.create)()
        details = {'params': {'test': 'param_value', 'test1': 'param_value_1'}}
        execution = mock.Mock()
        execution.id = '12345'
        self.mistral.executions.create.side_effect = (
            lambda *args, **kw: self.verify_params(*args, **kw))
        scheduler.TaskRunner(wf.signal, details)()

    def test_duplicate_attribute_translation_error(self):
        tmpl = template_format.parse(workflow_template_duplicate_polices)
        stack = utils.parse_stack(tmpl)

        rsrc_defns = stack.t.resource_definitions(stack)['workflow']

        workflow_rsrc = workflow.Workflow('workflow', rsrc_defns, stack)
        ex = self.assertRaises(exception.StackValidationFailed,
                               workflow_rsrc.validate)
        error_msg = ("Cannot define the following properties at "
                     "the same time: tasks.retry, tasks.policies.retry")
        self.assertIn(error_msg, six.text_type(ex))

    def validate_json_inputs(self, actual_input, expected_input):
        actual_json_input = jsonutils.loads(actual_input)
        expected_json_input = jsonutils.loads(expected_input)
        self.assertEqual(expected_json_input, actual_json_input)

    def verify_params(self, workflow_name, workflow_input=None, **params):
        self.assertEqual({'test': 'param_value', 'test1': 'param_value_1'},
                         params)
        execution = mock.Mock()
        execution.id = '12345'
        return execution

    def verify_create_params(self, wf_yaml):
        wf = yaml.safe_load(wf_yaml)["create_vm"]
        self.assertEqual(['on_error'], wf["task-defaults"]["on-error"])

        tasks = wf['tasks']
        task = tasks['wait_instance']
        self.assertEqual('vm_id_new in <% $.list_servers %>',
                         task['with-items'])
        self.assertEqual(5, task['retry']['delay'])
        self.assertEqual(15, task['retry']['count'])
        self.assertEqual(8, task['wait-after'])
        self.assertTrue(task['pause-before'])
        self.assertEqual(11, task['timeout'])
        self.assertEqual('test', task['target'])
        self.assertEqual(7, task['wait-before'])
        self.assertFalse(task['keep-result'])

        return [FakeWorkflow('create_vm')]

    def test_mistral_workflow_refid(self):
        tmpl = template_format.parse(workflow_template)
        stack = utils.parse_stack(tmpl, stack_name='test')
        rsrc = stack['workflow']
        rsrc.uuid = '4c885bde-957e-4758-907b-c188a487e908'
        rsrc.id = 'mockid'
        rsrc.action = 'CREATE'
        self.assertEqual('test-workflow-owevpzgiqw66', rsrc.FnGetRefId())

    def test_mistral_workflow_refid_convergence_cache_data(self):
        tmpl = template_format.parse(workflow_template)
        cache_data = {'workflow': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        })}
        stack = utils.parse_stack(tmpl, stack_name='test',
                                  cache_data=cache_data)
        rsrc = stack.defn['workflow']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())

    def test_policies_translation_successful(self):
        tmpl = template_format.parse(workflow_template_policies_translation)
        stack = utils.parse_stack(tmpl)
        rsrc_defns = stack.t.resource_definitions(stack)['workflow']
        wf = workflow.Workflow('workflow', rsrc_defns, stack)

        result = {k: v for k, v in wf.properties['tasks'][0].items() if v}
        self.assertEqual({'name': 'check_dat_thing',
                          'action': 'nova.servers_list',
                          'retry': {'delay': 5, 'count': 15},
                          'wait_before': 5,
                          'wait_after': 5,
                          'pause_before': True,
                          'timeout': 42,
                          'concurrency': 5}, result)
