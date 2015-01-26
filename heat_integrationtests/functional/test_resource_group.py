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

import six

from heatclient import exc

from heat_integrationtests.common import test


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
