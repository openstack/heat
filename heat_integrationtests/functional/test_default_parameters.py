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

import yaml

from heat_integrationtests.functional import functional_base


class DefaultParametersTest(functional_base.FunctionalTestsBase):

    template = '''
heat_template_version: 2013-05-23
parameters:
  length:
    type: string
    default: 40
resources:
  random1:
    type: nested_random.yaml
  random2:
    type: OS::Heat::RandomString
    properties:
      length: {get_param: length}
outputs:
  random1:
    value: {get_attr: [random1, random1_value]}
  random2:
    value: {get_resource: random2}
'''
    nested_template = '''
heat_template_version: 2013-05-23
parameters:
  length:
    type: string
    default: 50
resources:
  random1:
    type: OS::Heat::RandomString
    properties:
      length: {get_param: length}
outputs:
  random1_value:
    value: {get_resource: random1}
'''

    scenarios = [
        ('none', dict(param=None, default=None, temp_def=True,
                      expect1=50, expect2=40)),
        ('default', dict(param=None, default=12, temp_def=True,
                         expect1=12, expect2=12)),
        ('both', dict(param=15, default=12, temp_def=True,
                      expect1=12, expect2=15)),
        ('no_temp_default', dict(param=None, default=12, temp_def=False,
                                 expect1=12, expect2=12)),
    ]

    def test_defaults(self):
        env = {'parameters': {}, 'parameter_defaults': {}}
        if self.param:
            env['parameters'] = {'length': self.param}
        if self.default:
            env['parameter_defaults'] = {'length': self.default}

        if not self.temp_def:
            # remove the default from the parameter in the nested template.
            ntempl = yaml.safe_load(self.nested_template)
            del ntempl['parameters']['length']['default']
            nested_template = yaml.safe_dump(ntempl)
        else:
            nested_template = self.nested_template

        stack_identifier = self.stack_create(
            template=self.template,
            files={'nested_random.yaml': nested_template},
            environment=env
        )

        stack = self.client.stacks.get(stack_identifier)
        for out in stack.outputs:
            if out['output_key'] == 'random1':
                self.assertEqual(self.expect1, len(out['output_value']))
            if out['output_key'] == 'random2':
                self.assertEqual(self.expect2, len(out['output_value']))
