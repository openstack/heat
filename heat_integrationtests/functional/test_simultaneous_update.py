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
import json
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


input_param = 'input'
preempt_nested_stack_type = 'preempt.yaml'
preempt_root_rsrcs = {
    'nested_stack': {
        'type': preempt_nested_stack_type,
        'properties': {
            'input': {'get_param': input_param},
        },
    }
}
preempt_root_out = {'get_attr': ['nested_stack', 'delay_stack']}
preempt_delay_stack_type = 'delay.yaml'
preempt_nested_rsrcs = {
    'delay_stack': {
        'type': preempt_delay_stack_type,
        'properties': {
            'input': {'get_param': input_param},
        },
    }
}
preempt_nested_out = {'get_resource': 'delay_stack'}
preempt_delay_rsrcs = {
    'delay_resource': {
        'type': 'OS::Heat::TestResource',
        'properties': {
            'action_wait_secs': {
                'update': 6000,
            },
            'value': {'get_param': input_param},
        },
    }
}


def _tmpl_with_rsrcs(rsrcs, output_value=None):
    tmpl = {
        'heat_template_version': 'queens',
        'parameters': {
            input_param: {
                'type': 'string',
            },
        },
        'resources': rsrcs,
    }
    if output_value is not None:
        outputs = {'delay_stack': {'value': output_value}}
        tmpl['outputs'] = outputs
    return json.dumps(tmpl)


class SimultaneousUpdateNestedStackTest(functional_base.FunctionalTestsBase):
    @test.requires_convergence
    def test_nested_preemption(self):
        root_tmpl = _tmpl_with_rsrcs(preempt_root_rsrcs,
                                     preempt_root_out)
        files = {
            preempt_nested_stack_type: _tmpl_with_rsrcs(preempt_nested_rsrcs,
                                                        preempt_nested_out),
            preempt_delay_stack_type: _tmpl_with_rsrcs(preempt_delay_rsrcs),
        }
        stack_id = self.stack_create(template=root_tmpl, files=files,
                                     parameters={input_param: 'foo'})
        delay_stack_uuid = self.get_stack_output(stack_id, 'delay_stack')

        # Start an update that includes a long delay in the second nested stack
        self.update_stack(stack_id, template=root_tmpl, files=files,
                          parameters={input_param: 'bar'},
                          expected_status='UPDATE_IN_PROGRESS')
        self._wait_for_resource_status(delay_stack_uuid, 'delay_resource',
                                       'UPDATE_IN_PROGRESS')

        # Update again to check that we preempt update of the first nested
        # stack. This will delete the second nested stack, after preempting the
        # update of that stack as well, which will cause the delay resource
        # within to be cancelled.
        empty_nest_files = {
            preempt_nested_stack_type: _tmpl_with_rsrcs({}),
        }
        self.update_stack(stack_id, template=root_tmpl, files=empty_nest_files,
                          parameters={input_param: 'baz'})
