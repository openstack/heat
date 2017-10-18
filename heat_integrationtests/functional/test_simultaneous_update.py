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


import copy
import time

from heat_integrationtests.common import test
from heat_integrationtests.functional import functional_base

_test_template = {
    'heat_template_version': 'pike',
    'description': 'Test template to create two resources.',
    'resources': {
        'test1': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'Test1',
                'fail': False,
                'update_replace': False,
                'wait_secs': 0,
            }
        },
        'test2': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'Test1',
                'fail': False,
                'update_replace': False,
                'wait_secs': 0,
                'action_wait_secs': {
                    'create': 30,
                }
            },
            'depends_on': ['test1']
        }
    }
}


def get_templates(fail=False, delay_s=None):
    before = copy.deepcopy(_test_template)

    after = copy.deepcopy(before)
    for r in after['resources'].values():
        r['properties']['value'] = 'Test2'

    before_props = before['resources']['test2']['properties']
    before_props['fail'] = fail
    if delay_s is not None:
        before_props['action_wait_secs']['create'] = delay_s

    return before, after


class SimultaneousUpdateStackTest(functional_base.FunctionalTestsBase):

    @test.requires_convergence
    def test_retrigger_success(self):
        before, after = get_templates()
        stack_id = self.stack_create(template=before,
                                     expected_status='CREATE_IN_PROGRESS')
        time.sleep(10)

        self.update_stack(stack_id, after)

    @test.requires_convergence
    def test_retrigger_failure(self):
        before, after = get_templates(fail=True)
        stack_id = self.stack_create(template=before,
                                     expected_status='CREATE_IN_PROGRESS')
        time.sleep(10)

        self.update_stack(stack_id, after)

    @test.requires_convergence
    def test_retrigger_timeout(self):
        before, after = get_templates(delay_s=70)
        stack_id = self.stack_create(template=before,
                                     expected_status='CREATE_IN_PROGRESS',
                                     timeout=1)
        time.sleep(50)

        self.update_stack(stack_id, after)
