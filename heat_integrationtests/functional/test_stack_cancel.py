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
import eventlet

from heat_integrationtests.common import test
from heat_integrationtests.functional import functional_base


template = {
    'heat_template_version': 'pike',
    'resources': {
        'test1': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'Test1',
                'action_wait_secs': {
                    'update': 30,
                }
            }
        },
        'test2': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'Test1',
                },
            'depends_on': ['test1']
        },
    }
}


def get_templates(delay_s=None):
    before = copy.deepcopy(template)
    after = copy.deepcopy(before)
    for r in after['resources'].values():
        r['properties']['value'] = 'Test2'

    if delay_s:
        before_props = before['resources']['test1']['properties']
        before_props['action_wait_secs']['create'] = delay_s
    return before, after


class StackCancelTest(functional_base.FunctionalTestsBase):

    def _test_cancel_update(self, rollback=True,
                            expected_status='ROLLBACK_COMPLETE'):
        before, after = get_templates()
        stack_id = self.stack_create(template=before)
        self.update_stack(stack_id, template=after,
                          expected_status='UPDATE_IN_PROGRESS')
        self._wait_for_resource_status(stack_id, 'test1', 'UPDATE_IN_PROGRESS')
        self.cancel_update_stack(stack_id, rollback, expected_status)
        return stack_id

    def test_cancel_update_with_rollback(self):
        self._test_cancel_update()

    def test_cancel_update_without_rollback(self):
        stack_id = self._test_cancel_update(rollback=False,
                                            expected_status='UPDATE_FAILED')
        self.assertTrue(test.call_until_true(
            60, 2, self.verify_resource_status,
            stack_id, 'test1', 'UPDATE_COMPLETE'))
        eventlet.sleep(2)
        self.assertTrue(self.verify_resource_status(stack_id, 'test2',
                                                    'CREATE_COMPLETE'))

    def test_cancel_create_without_rollback(self):
        before, after = get_templates(delay_s=30)
        stack_id = self.stack_create(template=before,
                                     expected_status='CREATE_IN_PROGRESS')
        self._wait_for_resource_status(stack_id, 'test1', 'CREATE_IN_PROGRESS')
        self.cancel_update_stack(stack_id, rollback=False,
                                 expected_status='CREATE_FAILED')
        self.assertTrue(test.call_until_true(
            60, 2, self.verify_resource_status,
            stack_id, 'test1', 'CREATE_COMPLETE'))
        eventlet.sleep(2)
        self.assertTrue(self.verify_resource_status(stack_id, 'test2',
                                                    'INIT_COMPLETE'))
