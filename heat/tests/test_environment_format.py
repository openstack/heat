# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from heat.common import environment_format
from heat.tests import common


class YamlEnvironmentTest(common.HeatTestCase):

    def test_minimal_yaml(self):
        yaml1 = ''
        yaml2 = '''
parameters: {}
resource_registry: {}
'''
        tpl1 = environment_format.parse(yaml1)
        environment_format.default_for_missing(tpl1)
        tpl2 = environment_format.parse(yaml2)
        self.assertEqual(tpl1, tpl2)

    def test_wrong_sections(self):
        env = '''
parameters: {}
resource_regis: {}
'''
        self.assertRaises(ValueError, environment_format.parse, env)

    def test_bad_yaml(self):
        env = '''
parameters: }
'''
        self.assertRaises(ValueError, environment_format.parse, env)
