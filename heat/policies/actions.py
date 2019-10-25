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

from oslo_policy import policy

from heat.policies import base

POLICY_ROOT = 'actions:%s'


def _action_rule(action_name, description):
    return policy.DocumentedRuleDefault(
        name=POLICY_ROOT % action_name,
        check_str='rule:%s' % (POLICY_ROOT % 'action'),
        description=description,
        operations=[{
            'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions',
            'method': 'POST',
        }]
    )


actions_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'action',
        check_str=base.RULE_DENY_STACK_USER,
        description='Performs non-lifecycle operations on the stack '
        '(Snapshot, Resume, Cancel update, or check stack resources). '
        'This is the default for all actions but can be overridden by more '
        'specific policies for individual actions.',
        operations=[{
            'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions',
            'method': 'POST',
        }],
    ),
    _action_rule('snapshot', 'Create stack snapshot.'),
    _action_rule('suspend', 'Suspend a stack.'),
    _action_rule('resume', 'Resume a suspended stack.'),
    _action_rule('check', 'Check stack resources.'),
    _action_rule('cancel_update', 'Cancel stack operation and roll back.'),
    _action_rule('cancel_without_rollback',
                 'Cancel stack operation without rolling back.'),
]


def list_rules():
    return actions_policies
