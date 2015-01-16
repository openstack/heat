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

import json

from heatclient import exc
import six
import yaml

from heat_integrationtests.common import test


template = '''
heat_template_version: 2013-05-23
resources:
  random_group:
    type: OS::Heat::ResourceGroup
    properties:
      count: 2
      resource_def:
        type: OS::Heat::RandomString
        properties:
          length: 30
outputs:
  random1:
    value: {get_attr: [random_group, resource.0.value]}
  random2:
    value: {get_attr: [random_group, resource.1.value]}
  all_values:
    value: {get_attr: [random_group, value]}
'''


class ResourceGroupTest(test.HeatIntegrationTest):

    def setUp(self):
        super(ResourceGroupTest, self).setUp()
        self.client = self.orchestration_client

    def _group_nested_identifier(self, stack_identifier,
                                 group_name='random_group'):
        # Get the nested stack identifier from the group
        rsrc = self.client.resources.get(stack_identifier, group_name)
        physical_resource_id = rsrc.physical_resource_id

        nested_stack = self.client.stacks.get(physical_resource_id)
        nested_identifier = '%s/%s' % (nested_stack.stack_name,
                                       nested_stack.id)
        parent_id = stack_identifier.split("/")[-1]
        self.assertEqual(parent_id, nested_stack.parent)
        return nested_identifier

    def test_resource_group_zero_novalidate(self):
        # Nested resources should be validated only when size > 0
        # This allows features to be disabled via size=0 without
        # triggering validation of nested resource custom contraints
        # e.g images etc in the nested schema.
        nested_template_fail = '''
heat_template_version: 2013-05-23
resources:
  random:
    type: OS::Heat::RandomString
    properties:
        length: BAD
'''

        template_zero_nested = '''
heat_template_version: 2013-05-23
resources:
  random_group:
    type: OS::Heat::ResourceGroup
    properties:
      count: 0
      resource_def:
        type: My::RandomString
'''

        files = {'provider.yaml': nested_template_fail}
        env = {'resource_registry':
               {'My::RandomString': 'provider.yaml'}}
        stack_identifier = self.stack_create(
            template=template_zero_nested,
            files=files,
            environment=env
        )

        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))

        # Check we created an empty nested stack
        nested_identifier = self._group_nested_identifier(stack_identifier)
        self.assertEqual({}, self.list_resources(nested_identifier))

        # Prove validation works for non-zero create/update
        template_two_nested = template_zero_nested.replace("count: 0",
                                                           "count: 2")
        expected_err = "length Value 'BAD' is not an integer"
        ex = self.assertRaises(exc.HTTPBadRequest, self.update_stack,
                               stack_identifier, template_two_nested,
                               environment=env, files=files)
        self.assertIn(expected_err, six.text_type(ex))

        ex = self.assertRaises(exc.HTTPBadRequest, self.stack_create,
                               template=template_two_nested,
                               environment=env, files=files)
        self.assertIn(expected_err, six.text_type(ex))

    def _validate_resources(self, stack_identifier, expected_count):
        nested_identifier = self._group_nested_identifier(stack_identifier)
        resources = self.list_resources(nested_identifier)
        self.assertEqual(expected_count, len(resources))
        expected_resources = dict(
            (str(idx), 'OS::Heat::RandomString')
            for idx in range(expected_count))

        self.assertEqual(expected_resources, resources)

    def test_create(self):
        def validate_output(stack, output_key, length):
            output_value = self._stack_output(stack, output_key)
            self.assertEqual(length, len(output_value))
            return output_value
        # verify that the resources in resource group are identically
        # configured, resource names and outputs are appropriate.
        stack_identifier = self.stack_create(template=template)
        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))

        # validate count, type and name of resources in a resource group.
        self._validate_resources(stack_identifier, 2)

        # validate outputs
        stack = self.client.stacks.get(stack_identifier)
        outputs = []
        outputs.append(validate_output(stack, 'random1', 30))
        outputs.append(validate_output(stack, 'random2', 30))
        self.assertEqual(outputs, self._stack_output(stack, 'all_values'))

    def test_update_increase_decrease_count(self):
        # create stack with resource group count 2
        stack_identifier = self.stack_create(template=template)
        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))
        # verify that the resource group has 2 resources
        self._validate_resources(stack_identifier, 2)

        # increase the resource group count to 5
        update_template = template.replace("count: 2", "count: 5")
        self.update_stack(stack_identifier, update_template)
        # verify that the resource group has 5 resources
        self._validate_resources(stack_identifier, 5)

        # decrease the resource group count to 3
        update_template = template.replace("count: 2", "count: 3")
        self.update_stack(stack_identifier, update_template)
        # verify that the resource group has 3 resources
        self._validate_resources(stack_identifier, 3)


class ResourceGroupAdoptTest(test.HeatIntegrationTest):
    """Prove that we can do resource group adopt."""

    main_template = '''
heat_template_version: "2013-05-23"
resources:
  group1:
    type: OS::Heat::ResourceGroup
    properties:
      count: 2
      resource_def:
        type: OS::Heat::RandomString
outputs:
  test0:
    value: {get_attr: [group1, resource.0.value]}
  test1:
    value: {get_attr: [group1, resource.1.value]}
'''

    def setUp(self):
        super(ResourceGroupAdoptTest, self).setUp()
        self.client = self.orchestration_client

    def _yaml_to_json(self, yaml_templ):
        return yaml.load(yaml_templ)

    def test_adopt(self):
        data = {
            "resources": {
                "group1": {
                    "status": "COMPLETE",
                    "name": "group1",
                    "resource_data": {},
                    "metadata": {},
                    "resource_id": "test-group1-id",
                    "action": "CREATE",
                    "type": "OS::Heat::ResourceGroup",
                    "resources": {
                        "0": {
                            "status": "COMPLETE",
                            "name": "0",
                            "resource_data": {"value": "goopie"},
                            "resource_id": "ID-0",
                            "action": "CREATE",
                            "type": "OS::Heat::RandomString",
                            "metadata": {}
                        },
                        "1": {
                            "status": "COMPLETE",
                            "name": "1",
                            "resource_data": {"value": "different"},
                            "resource_id": "ID-1",
                            "action": "CREATE",
                            "type": "OS::Heat::RandomString",
                            "metadata": {}
                        }
                    }
                }
            },
            "environment": {"parameters": {}},
            "template": yaml.load(self.main_template)
        }
        stack_identifier = self.stack_adopt(
            adopt_data=json.dumps(data))

        self.assert_resource_is_a_stack(stack_identifier, 'group1')
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('goopie', self._stack_output(stack, 'test0'))
        self.assertEqual('different', self._stack_output(stack, 'test1'))
