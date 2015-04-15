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

from heat.common import template_format
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils


class StackTest(common.HeatTestCase):
    def setUp(self):
        super(StackTest, self).setUp()
        self.username = 'parser_stack_test_user'
        self.ctx = utils.dummy_context()

    def _assert_can_create(self, templ):
        stack = parser.Stack(self.ctx, utils.random_name(),
                             template.Template(templ))
        stack.store()
        stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         stack.state)
        return stack

    def test_heat_empty_json(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {}, 'Parameters': {}, 'Outputs': {}}
        self._assert_can_create(tmpl)

    def test_cfn_empty_json(self):
        tmpl = {'AWSTemplateFormatVersion': '2010-09-09',
                'Resources': {}, 'Parameters': {}, 'Outputs': {}}
        self._assert_can_create(tmpl)

    def test_hot_empty_json(self):
        tmpl = {'heat_template_version': '2013-05-23',
                'resources': {}, 'parameters': {}, 'outputs': {}}
        self._assert_can_create(tmpl)

    def test_heat_empty_yaml(self):
        t = template_format.parse('''
HeatTemplateFormatVersion: 2012-12-12
Parameters:
Resources:
Outputs:
''')
        self._assert_can_create(t)

    def test_cfn_empty_yaml(self):
        t = template_format.parse('''
AWSTemplateFormatVersion: 2010-09-09
Parameters:
Resources:
Outputs:
''')
        self._assert_can_create(t)

    def test_hot_empty_yaml(self):
        t = template_format.parse('''
heat_template_version: 2013-05-23
parameters:
resources:
outputs:
''')
        self._assert_can_create(t)

    def test_update_hot_empty_yaml(self):
        t = template_format.parse('''
heat_template_version: 2013-05-23
parameters:
resources:
outputs:
''')
        ut = template_format.parse('''
heat_template_version: 2013-05-23
parameters:
resources:
  rand:
    type: OS::Heat::RandomString
outputs:
''')
        stack = self._assert_can_create(t)
        updated = parser.Stack(self.ctx, utils.random_name(),
                               template.Template(ut))
        stack.update(updated)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         stack.state)

    def test_update_cfn_empty_yaml(self):
        t = template_format.parse('''
AWSTemplateFormatVersion: 2010-09-09
Parameters:
Resources:
Outputs:
''')
        ut = template_format.parse('''
AWSTemplateFormatVersion: 2010-09-09
Parameters:
Resources:
  rand:
    Type: OS::Heat::RandomString
Outputs:
''')
        stack = self._assert_can_create(t)
        updated = parser.Stack(self.ctx, utils.random_name(),
                               template.Template(ut))
        stack.update(updated)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         stack.state)
