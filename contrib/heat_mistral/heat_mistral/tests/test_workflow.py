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

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine.resources import signal_responder
from heat.engine.resources import stack_user
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils

from .. import client  # noqa
from ..resources import workflow  # noqa

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

workflow_template_full = """
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

workflow_template_update = """
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


class FakeWorkflow(object):

    def __init__(self, name):
        self.name = name


class TestWorkflow(common.HeatTestCase):

    def setUp(self):
        super(TestWorkflow, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()
        tmpl = template_format.parse(workflow_template)
        self.stack = utils.parse_stack(tmpl, stack_name='test_stack')

        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['workflow']

        self.patcher_client = mock.patch.object(workflow.Workflow, 'mistral')
        mock.patch.object(stack_user.StackUser, '_create_user').start()
        mock.patch.object(signal_responder.SignalResponder,
                          '_create_keypair').start()
        mock.patch.object(client, 'mistral_base').start()
        mock.patch.object(client.MistralClientPlugin, '_create').start()
        self.client = client.MistralClientPlugin(self.ctx)
        mock_client = self.patcher_client.start()
        self.mistral = mock_client.return_value

    def tearDown(self):
        super(TestWorkflow, self).tearDown()
        self.patcher_client.stop()

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

    def test_attributes(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)
        self.assertEqual({'name': 'test_stack-workflow-b5fiekfci3yc',
                          'input': None}, wf.FnGetAtt('data'))
        self.assertEqual([], wf.FnGetAtt('executions'))

    def test_direct_workflow_validation_error(self):
        error_msg = ("Mistral resource validation error : "
                     "workflow.properties.tasks.second_task.requires: "
                     "task second_task contains property 'requires' "
                     "in case of direct workflow. Only reverse workflows "
                     "can contain property 'requires'.")
        self._test_validation_failed(workflow_template_bad, error_msg)

    def test_wrong_params_using(self):
        error_msg = ("Mistral resource validation error : "
                     "workflow.properties.params: 'task_name' is not assigned "
                     "in 'params' in case of reverse type workflow.")
        self._test_validation_failed(workflow_template_bad_reverse, error_msg)

    def _test_validation_failed(self, templatem, error_msg):
        tmpl = template_format.parse(templatem)
        stack = utils.parse_stack(tmpl)

        rsrc_defns = stack.t.resource_definitions(stack)['workflow']

        wf = workflow.Workflow('workflow', rsrc_defns, stack)

        exc = self.assertRaises(exception.StackValidationFailed,
                                wf.validate)
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
        self.assertIn('Exception: boom!', six.text_type(exc))

    def test_update(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)

        t = template_format.parse(workflow_template_update)
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

    def test_delete(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)

        scheduler.TaskRunner(wf.delete)()
        self.assertEqual((wf.DELETE, wf.COMPLETE), wf.state)

    def test_delete_no_data(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)

        wf.data_delete('executions')
        self.assertEqual([], wf.FnGetAtt('executions'))
        scheduler.TaskRunner(wf.delete)()
        self.assertEqual((wf.DELETE, wf.COMPLETE), wf.state)

    def test_delete_not_found(self):
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)

        self.mistral.workflows.delete.side_effect = (
            self.mistral.mistral_base.APIException(error_code=404))

        scheduler.TaskRunner(wf.delete)()
        self.assertEqual((wf.DELETE, wf.COMPLETE), wf.state)

    @mock.patch.object(resource.Resource, 'client_plugin')
    def test_delete_other_errors(self, mock_plugin):
        """We mock client_plugin for returning correct mistral client."""
        mock_plugin.return_value = self.client
        client.mistral_base.APIException = exception.Error
        wf = self._create_resource('workflow', self.rsrc_defn, self.stack)

        self.mistral.workflows.delete.side_effect = (Exception('boom!'))

        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(wf.delete))
        self.assertEqual((wf.DELETE, wf.FAILED), wf.state)
        self.assertIn('boom!', six.text_type(exc))

    def test_resource_mapping(self):
        mapping = workflow.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(workflow.Workflow,
                         mapping['OS::Mistral::Workflow'])
