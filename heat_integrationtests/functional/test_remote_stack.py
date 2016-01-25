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


from heatclient import exc
import six

from heat_integrationtests.functional import functional_base


class RemoteStackTest(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: 2013-05-23
resources:
  my_stack:
    type: OS::Heat::Stack
    properties:
      context:
        region_name: RegionOne
      template:
        get_file: remote_stack.yaml
outputs:
  key:
    value: {get_attr: [my_stack, outputs]}
'''

    remote_template = '''
heat_template_version: 2013-05-23
resources:
  random1:
    type: OS::Heat::RandomString
outputs:
  remote_key:
    value: {get_attr: [random1, value]}
'''

    def setUp(self):
        super(RemoteStackTest, self).setUp()

    def test_remote_stack_alone(self):
        stack_id = self.stack_create(template=self.remote_template)
        expected_resources = {'random1': 'OS::Heat::RandomString'}
        self.assertEqual(expected_resources, self.list_resources(stack_id))
        stack = self.client.stacks.get(stack_id)
        output_value = self._stack_output(stack, 'remote_key')
        self.assertEqual(32, len(output_value))

    def test_stack_create(self):
        files = {'remote_stack.yaml': self.remote_template}
        stack_id = self.stack_create(files=files)

        expected_resources = {'my_stack': 'OS::Heat::Stack'}
        self.assertEqual(expected_resources, self.list_resources(stack_id))

        stack = self.client.stacks.get(stack_id)
        output = self._stack_output(stack, 'key')
        parent_output_value = output['remote_key']
        self.assertEqual(32, len(parent_output_value))

        rsrc = self.client.resources.get(stack_id, 'my_stack')
        remote_id = rsrc.physical_resource_id
        rstack = self.client.stacks.get(remote_id)
        self.assertEqual(remote_id, rstack.id)
        remote_output_value = self._stack_output(rstack, 'remote_key')
        self.assertEqual(32, len(remote_output_value))
        self.assertEqual(parent_output_value, remote_output_value)

        remote_resources = {'random1': 'OS::Heat::RandomString'}
        self.assertEqual(remote_resources, self.list_resources(remote_id))

    def test_stack_create_bad_region(self):
        tmpl_bad_region = self.template.replace('RegionOne', 'DARKHOLE')
        files = {'remote_stack.yaml': self.remote_template}
        kwargs = {
            'template': tmpl_bad_region,
            'files': files
        }
        ex = self.assertRaises(exc.HTTPBadRequest, self.stack_create, **kwargs)

        error_msg = ('ERROR: Cannot establish connection to Heat endpoint '
                     'at region "DARKHOLE" due to "publicURL endpoint for '
                     'orchestration service in DARKHOLE region not found"')
        self.assertEqual(error_msg, six.text_type(ex))

    def test_stack_resource_validation_fail(self):
        tmpl_bad_format = self.remote_template.replace('resources', 'resource')
        files = {'remote_stack.yaml': tmpl_bad_format}
        kwargs = {'files': files}
        ex = self.assertRaises(exc.HTTPBadRequest, self.stack_create, **kwargs)

        error_msg = ('ERROR: Failed validating stack template using Heat '
                     'endpoint at region "RegionOne" due to '
                     '"ERROR: The template section is invalid: resource"')
        self.assertEqual(error_msg, six.text_type(ex))

    def test_stack_update(self):
        files = {'remote_stack.yaml': self.remote_template}
        stack_id = self.stack_create(files=files)

        expected_resources = {'my_stack': 'OS::Heat::Stack'}
        self.assertEqual(expected_resources, self.list_resources(stack_id))

        rsrc = self.client.resources.get(stack_id, 'my_stack')
        physical_resource_id = rsrc.physical_resource_id
        rstack = self.client.stacks.get(physical_resource_id)
        self.assertEqual(physical_resource_id, rstack.id)

        remote_resources = {'random1': 'OS::Heat::RandomString'}
        self.assertEqual(remote_resources,
                         self.list_resources(rstack.id))
        # do an update
        update_template = self.remote_template.replace('random1', 'random2')
        files = {'remote_stack.yaml': update_template}
        self.update_stack(stack_id, self.template, files=files)

        # check if the remote stack is still there with the same ID
        self.assertEqual(expected_resources, self.list_resources(stack_id))
        rsrc = self.client.resources.get(stack_id, 'my_stack')
        physical_resource_id = rsrc.physical_resource_id
        rstack = self.client.stacks.get(physical_resource_id)
        self.assertEqual(physical_resource_id, rstack.id)

        remote_resources = {'random2': 'OS::Heat::RandomString'}
        self.assertEqual(remote_resources,
                         self.list_resources(rstack.id))

    def test_stack_suspend_resume(self):
        files = {'remote_stack.yaml': self.remote_template}
        stack_id = self.stack_create(files=files)
        self.stack_suspend(stack_id)
        self.stack_resume(stack_id)
