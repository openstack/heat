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

from heat_integrationtests.common import test
from heatclient import exc
import six


class StackPreviewTest(test.HeatIntegrationTest):
    template = '''
heat_template_version: 2015-04-30
parameters:
  incomming:
    type: string
resources:
  one:
    type: OS::Heat::TestResource
    properties:
      value: fred
  two:
    type: OS::Heat::TestResource
    properties:
      value: {get_param: incomming}
    depends_on: one
outputs:
  main_out:
    value: {get_attr: [two, output]}
    '''
    env = '''
parameters:
  incomming: abc
    '''

    def setUp(self):
        super(StackPreviewTest, self).setUp()
        self.client = self.orchestration_client
        self.project_id = self.identity_client.project_id

    def _assert_resource(self, res, stack_name):
        self.assertEqual(stack_name, res['stack_name'])
        self.assertEqual('INIT', res['resource_action'])
        self.assertEqual('COMPLETE', res['resource_status'])
        for field in ('resource_status_reason', 'physical_resource_id',
                      'description'):
            self.assertIn(field, res)
            self.assertEqual('', res[field])
        # 'creation_time' and 'updated_time' are None when preview
        for field in ('creation_time', 'updated_time'):
            self.assertIn(field, res)
            self.assertIsNone(res[field])
        self.assertIn('output', res['attributes'])

        # resource_identity
        self.assertEqual(stack_name,
                         res['resource_identity']['stack_name'])
        self.assertEqual('None', res['resource_identity']['stack_id'])
        self.assertEqual(self.project_id,
                         res['resource_identity']['tenant'])
        self.assertEqual('/resources/%s' % res['resource_name'],
                         res['resource_identity']['path'])
        # stack_identity
        self.assertEqual(stack_name,
                         res['stack_identity']['stack_name'])
        self.assertEqual('None', res['stack_identity']['stack_id'])
        self.assertEqual(self.project_id,
                         res['stack_identity']['tenant'])
        self.assertEqual('', res['stack_identity']['path'])

    def _assert_results(self, result, stack_name):
        # global stuff.
        self.assertEqual(stack_name, result['stack_name'])
        self.assertTrue(result['disable_rollback'])
        self.assertEqual('None', result['id'])
        self.assertIsNone(result['parent'])
        self.assertEqual('No description', result['template_description'])

        # parameters
        self.assertEqual('None', result['parameters']['OS::stack_id'])
        self.assertEqual(stack_name, result['parameters']['OS::stack_name'])
        self.assertEqual('abc', result['parameters']['incomming'])

    def test_basic_pass(self):
        stack_name = self._stack_rand_name()
        result = self.client.stacks.preview(
            template=self.template,
            stack_name=stack_name,
            disable_rollback=True,
            environment=self.env).to_dict()

        self._assert_results(result, stack_name)
        for res in result['resources']:
            self._assert_resource(res, stack_name)
            self.assertEqual('OS::Heat::TestResource',
                             res['resource_type'])

            # common properties
            self.assertFalse(res['properties']['fail'])
            self.assertEqual(0, res['properties']['wait_secs'])
            self.assertFalse(res['properties']['update_replace'])

            if res['resource_name'] == 'one':
                self.assertEqual('fred', res['properties']['value'])
                self.assertEqual(['two'], res['required_by'])
            if res['resource_name'] == 'two':
                self.assertEqual('abc', res['properties']['value'])
                self.assertEqual([], res['required_by'])

    def test_basic_fail(self):
        stack_name = self._stack_rand_name()

        # break the template so it fails validation.
        wont_work = self.template.replace('get_param: incomming',
                                          'get_param: missing')
        excp = self.assertRaises(exc.HTTPBadRequest,
                                 self.client.stacks.preview,
                                 template=wont_work,
                                 stack_name=stack_name,
                                 disable_rollback=True,
                                 environment=self.env)

        self.assertIn('Property error: : resources.two.properties.value: '
                      ': The Parameter (missing) was not provided.',
                      six.text_type(excp))

    def test_nested_pass(self):
        """Nested stacks need to recurse down the stacks."""
        main_template = '''
heat_template_version: 2015-04-30
parameters:
  incomming:
    type: string
resources:
  main:
    type: nested.yaml
    properties:
      value: {get_param: incomming}
outputs:
  main_out:
    value: {get_attr: [main, output]}
    '''
        nested_template = '''
heat_template_version: 2015-04-30
parameters:
  value:
    type: string
resources:
  nested:
    type: OS::Heat::TestResource
    properties:
      value: {get_param: value}
outputs:
  output:
    value: {get_attr: [nested, output]}
'''
        stack_name = self._stack_rand_name()
        result = self.client.stacks.preview(
            disable_rollback=True,
            stack_name=stack_name,
            template=main_template,
            files={'nested.yaml': nested_template},
            environment=self.env).to_dict()

        self._assert_results(result, stack_name)

        # nested resources return a list of their resources.
        res = result['resources'][0][0]
        nested_stack_name = '%s-%s' % (stack_name,
                                       res['parent_resource'])

        self._assert_resource(res, nested_stack_name)
        self.assertEqual('OS::Heat::TestResource',
                         res['resource_type'])

        self.assertFalse(res['properties']['fail'])
        self.assertEqual(0, res['properties']['wait_secs'])
        self.assertFalse(res['properties']['update_replace'])

        self.assertEqual('abc', res['properties']['value'])
        self.assertEqual([], res['required_by'])

    def test_res_group_with_nested_template(self):
        main_template = '''
heat_template_version: 2015-04-30
resources:
  fixed_network:
    type: "OS::Neutron::Net"
  rg:
    type: "OS::Heat::ResourceGroup"
    properties:
      count: 1
      resource_def:
        type: nested.yaml
        properties:
          fixed_network_id: {get_resource: fixed_network}
    '''
        nested_template = '''
heat_template_version: 2015-04-30

parameters:
  fixed_network_id:
    type: string
resources:
  port:
    type: "OS::Neutron::Port"
    properties:
      network_id:
          get_param: fixed_network_id

'''
        stack_name = self._stack_rand_name()
        result = self.client.stacks.preview(
            disable_rollback=True,
            stack_name=stack_name,
            template=main_template,
            files={'nested.yaml': nested_template}).to_dict()
        # ensure that fixed network and port here
        self.assertEqual('fixed_network',
                         result['resources'][0]['resource_name'])
        self.assertEqual('port',
                         result['resources'][1][0][0]['resource_name'])
