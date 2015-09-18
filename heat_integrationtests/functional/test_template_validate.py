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

from heat_integrationtests.functional import functional_base


class StackTemplateValidateTest(functional_base.FunctionalTestsBase):

    random_template = '''
heat_template_version: 2014-10-16
description: the stack description
parameters:
  aparam:
    type: number
    default: 10
    description: the param description
resources:
  myres:
    type: OS::Heat::RandomString
    properties:
      length: {get_param: aparam}
'''

    random_template_groups = '''
heat_template_version: 2014-10-16
description: the stack description
parameters:
  aparam:
    type: number
    default: 10
    description: the param description
  bparam:
    type: string
    default: foo
  cparam:
    type: string
    default: secret
    hidden: true
parameter_groups:
- label: str_params
  description: The string params
  parameters:
  - bparam
  - cparam
resources:
  myres:
    type: OS::Heat::RandomString
    properties:
      length: {get_param: aparam}
'''

    def test_template_validate_basic(self):
        ret = self.client.stacks.validate(template=self.random_template)
        expected = {'Description': 'the stack description',
                    'Parameters': {
                        'aparam': {'Default': 10,
                                   'Description': 'the param description',
                                   'Label': 'aparam',
                                   'NoEcho': 'false',
                                   'Type': 'Number'}}}
        self.assertEqual(expected, ret)

    def test_template_validate_override_default(self):
        env = {'parameters': {'aparam': 5}}
        ret = self.client.stacks.validate(template=self.random_template,
                                          environment=env)
        expected = {'Description': 'the stack description',
                    'Parameters': {
                        'aparam': {'Default': 10,
                                   'Value': 5,
                                   'Description': 'the param description',
                                   'Label': 'aparam',
                                   'NoEcho': 'false',
                                   'Type': 'Number'}}}
        self.assertEqual(expected, ret)

    def test_template_validate_basic_required_param(self):
        tmpl = self.random_template.replace('default: 10', '')
        ret = self.client.stacks.validate(template=tmpl)
        expected = {'Description': 'the stack description',
                    'Parameters': {
                        'aparam': {'Description': 'the param description',
                                   'Label': 'aparam',
                                   'NoEcho': 'false',
                                   'Type': 'Number'}}}
        self.assertEqual(expected, ret)

    def test_template_validate_fail_version(self):
        fail_template = self.random_template.replace('2014-10-16', 'invalid')
        ex = self.assertRaises(exc.HTTPBadRequest,
                               self.client.stacks.validate,
                               template=fail_template)
        self.assertIn('The template version is invalid', six.text_type(ex))

    def test_template_validate_parameter_groups(self):
        ret = self.client.stacks.validate(template=self.random_template_groups)
        expected = {'Description': 'the stack description',
                    'ParameterGroups':
                    [{'description': 'The string params',
                      'label': 'str_params',
                      'parameters': ['bparam', 'cparam']}],
                    'Parameters':
                    {'aparam':
                     {'Default': 10,
                      'Description': 'the param description',
                      'Label': 'aparam',
                      'NoEcho': 'false',
                      'Type': 'Number'},
                     'bparam':
                     {'Default': 'foo',
                      'Description': '',
                      'Label': 'bparam',
                      'NoEcho': 'false',
                      'Type': 'String'},
                     'cparam':
                     {'Default': 'secret',
                      'Description': '',
                      'Label': 'cparam',
                      'NoEcho': 'true',
                      'Type': 'String'}}}
        self.assertEqual(expected, ret)
