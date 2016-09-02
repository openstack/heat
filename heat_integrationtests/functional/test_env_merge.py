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

from heat_integrationtests.functional import functional_base


TEMPLATE = '''
    heat_template_version: 2015-04-30
    parameters:
      p0:
        type: string
        default: CORRECT
      p1:
        type: string
        default: INCORRECT
      p2:
        type: string
        default: INCORRECT
    resources:
      r1:
        type: test::R1
      r2:
        type: test::R2
      r3a:
        type: test::R3
      r3b:
        type: test::R3
'''

ENV_1 = '''
    parameters:
      p1: CORRECT
      p2: INCORRECT-E1
    resource_registry:
      test::R1: OS::Heat::RandomString
      test::R2: BROKEN
      test::R3: OS::Heat::None
'''

ENV_2 = '''
    parameters:
      p2: CORRECT
    resource_registry:
      test::R2: OS::Heat::RandomString
      resources:
        r3b:
          test::R3: OS::Heat::RandomString
'''


class EnvironmentMergingTests(functional_base.FunctionalTestsBase):

    def test_server_environment_merging(self):

        # Setup
        files = {'env1.yaml': ENV_1, 'env2.yaml': ENV_2}
        environment_files = ['env1.yaml', 'env2.yaml']

        # Test
        stack_id = self.stack_create(stack_name='env_merge',
                                     template=TEMPLATE,
                                     files=files,
                                     environment_files=environment_files)

        # Verify

        # Since there is no environment show, the registry overriding
        # is partially verified by there being no error. If it wasn't
        # working, test::R2 would remain mapped to BROKEN in env1.

        # Sanity check
        resources = self.list_resources(stack_id)
        self.assertEqual(4, len(resources))

        # Verify the parameters are correctly set
        stack = self.client.stacks.get(stack_id)
        self.assertEqual('CORRECT', stack.parameters['p0'])
        self.assertEqual('CORRECT', stack.parameters['p1'])
        self.assertEqual('CORRECT', stack.parameters['p2'])

        # Verify that r3b has been overridden into a RandomString
        # by checking to see that it has a value
        r3b = self.client.resources.get(stack_id, 'r3b')
        r3b_attrs = r3b.attributes
        self.assertIn('value', r3b_attrs)
