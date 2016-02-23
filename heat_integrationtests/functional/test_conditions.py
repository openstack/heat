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

from heat_integrationtests.functional import functional_base


cfn_template = '''
AWSTemplateFormatVersion: 2010-09-09
Parameters:
  env_type:
    Default: test
    Type: String
    AllowedValues: [prod, test]
Conditions:
  Prod: {"Fn::Equals" : [{Ref: env_type}, "prod"]}
Resources:
  test_res:
    Type: OS::Heat::TestResource
    Properties:
      value: {"Fn::If": ["Prod", "env_is_prod", "env_is_test"]}
  prod_res:
    Type: OS::Heat::TestResource
    Properties:
      value: prod_res
    Condition: Prod
Outputs:
  res_value:
    Value: {"Fn::GetAtt": [prod_res, output]}
    Condition: Prod
  test_res_value:
    Value: {"Fn::GetAtt": [test_res, output]}
  prod_resource:
    Value: {"Fn::If": [Prod, {Ref: prod_res}, 'no_prod_res']}
'''

hot_template = '''
heat_template_version: 2016-10-14
parameters:
  env_type:
    default: test
    type: string
    constraints:
      - allowed_values: [prod, test]
conditions:
  prod: {equals : [{get_param: env_type}, "prod"]}
resources:
  test_res:
    type: OS::Heat::TestResource
    properties:
      value: {if: ["prod", "env_is_prod", "env_is_test"]}
  prod_res:
    type: OS::Heat::TestResource
    properties:
      value: prod_res
    condition: prod
outputs:
  res_value:
    value: {get_attr: [prod_res, output]}
    condition: prod
  test_res_value:
    value: {get_attr: [test_res, output]}
  prod_resource:
    value: {if: [prod, {get_resource: prod_res}, 'no_prod_res']}
'''


class CreateUpdateResConditionTest(functional_base.FunctionalTestsBase):

    def setUp(self):
        super(CreateUpdateResConditionTest, self).setUp()

    def res_assert_for_prod(self, resources):
        self.assertEqual(2, len(resources))
        res_names = [res.resource_name for res in resources]
        self.assertIn('prod_res', res_names)
        self.assertIn('test_res', res_names)

    def res_assert_for_test(self, resources):
        self.assertEqual(1, len(resources))
        res_names = [res.resource_name for res in resources]
        self.assertIn('test_res', res_names)
        self.assertNotIn('prod_res', res_names)

    def output_assert_for_prod(self, stack_id):
        output = self.client.stacks.output_show(stack_id,
                                                'res_value')['output']
        self.assertEqual('prod_res', output['output_value'])

        test_res_value = self.client.stacks.output_show(
            stack_id, 'test_res_value')['output']
        self.assertEqual('env_is_prod', test_res_value['output_value'])

        prod_resource = self.client.stacks.output_show(
            stack_id, 'prod_resource')['output']
        self.assertNotEqual('no_prod_res', prod_resource['output_value'])

    def output_assert_for_test(self, stack_id):
        output = self.client.stacks.output_show(stack_id,
                                                'res_value')['output']
        self.assertIsNone(output['output_value'])

        test_res_value = self.client.stacks.output_show(
            stack_id, 'test_res_value')['output']
        self.assertEqual('env_is_test', test_res_value['output_value'])

        prod_resource = self.client.stacks.output_show(
            stack_id, 'prod_resource')['output']
        self.assertEqual('no_prod_res', prod_resource['output_value'])

    def test_stack_create_update_cfn_template_test_to_prod(self):
        stack_identifier = self.stack_create(template=cfn_template)
        resources = self.client.resources.list(stack_identifier)
        self.res_assert_for_test(resources)
        self.output_assert_for_test(stack_identifier)

        parms = {'env_type': 'prod'}
        self.update_stack(stack_identifier,
                          template=cfn_template,
                          parameters=parms)

        resources = self.client.resources.list(stack_identifier)
        self.res_assert_for_prod(resources)
        self.output_assert_for_prod(stack_identifier)

    def test_stack_create_update_cfn_template_prod_to_test(self):
        parms = {'env_type': 'prod'}
        stack_identifier = self.stack_create(template=cfn_template,
                                             parameters=parms)
        resources = self.client.resources.list(stack_identifier)
        self.res_assert_for_prod(resources)
        self.output_assert_for_prod(stack_identifier)

        parms = {'env_type': 'test'}
        self.update_stack(stack_identifier,
                          template=cfn_template,
                          parameters=parms)

        resources = self.client.resources.list(stack_identifier)
        self.res_assert_for_test(resources)
        self.output_assert_for_test(stack_identifier)

    def test_stack_create_update_hot_template_test_to_prod(self):
        stack_identifier = self.stack_create(template=hot_template)
        resources = self.client.resources.list(stack_identifier)
        self.res_assert_for_test(resources)
        self.output_assert_for_test(stack_identifier)

        parms = {'env_type': 'prod'}
        self.update_stack(stack_identifier,
                          template=hot_template,
                          parameters=parms)

        resources = self.client.resources.list(stack_identifier)
        self.res_assert_for_prod(resources)
        self.output_assert_for_prod(stack_identifier)

    def test_stack_create_update_hot_template_prod_to_test(self):
        parms = {'env_type': 'prod'}
        stack_identifier = self.stack_create(template=hot_template,
                                             parameters=parms)
        resources = self.client.resources.list(stack_identifier)
        self.res_assert_for_prod(resources)
        self.output_assert_for_prod(stack_identifier)

        parms = {'env_type': 'test'}
        self.update_stack(stack_identifier,
                          template=hot_template,
                          parameters=parms)

        resources = self.client.resources.list(stack_identifier)
        self.res_assert_for_test(resources)
        self.output_assert_for_test(stack_identifier)
