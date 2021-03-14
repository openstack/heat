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

from oslo_log import versionutils
from oslo_policy import policy

from heat.policies import base

POLICY_ROOT = 'actions:%s'

DEPRECATED_REASON = """
The actions API now supports system scope and default roles.
"""

deprecated_action = policy.DeprecatedRule(
    name=POLICY_ROOT % 'action',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_snapshot = policy.DeprecatedRule(
    name=POLICY_ROOT % 'snapshot',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_suspend = policy.DeprecatedRule(
    name=POLICY_ROOT % 'suspend',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_resume = policy.DeprecatedRule(
    name=POLICY_ROOT % 'resume',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_check = policy.DeprecatedRule(
    name=POLICY_ROOT % 'check',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_cancel_update = policy.DeprecatedRule(
    name=POLICY_ROOT % 'cancel_update',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_cancel_without_rollback = policy.DeprecatedRule(
    name=POLICY_ROOT % 'cancel_without_rollback',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)


actions_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'action',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        description='Performs non-lifecycle operations on the stack '
        '(Snapshot, Resume, Cancel update, or check stack resources). '
        'This is the default for all actions but can be overridden by more '
        'specific policies for individual actions.',
        operations=[{
            'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions',
            'method': 'POST',
        }],
        deprecated_rule=deprecated_action
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'snapshot',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Create stack snapshot',
        operations=[{
            'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions',
            'method': 'POST',
        }],
        deprecated_rule=deprecated_snapshot
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'suspend',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Suspend a stack.',
        operations=[{
            'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions',
            'method': 'POST',
        }],
        deprecated_rule=deprecated_suspend
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'resume',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Resume a suspended stack.',
        operations=[{
            'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions',
            'method': 'POST',
        }],
        deprecated_rule=deprecated_resume
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'check',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Check stack resources.',
        operations=[{
            'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions',
            'method': 'POST',
        }],
        deprecated_rule=deprecated_check
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'cancel_update',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Cancel stack operation and roll back.',
        operations=[{
            'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions',
            'method': 'POST',
        }],
        deprecated_rule=deprecated_cancel_update
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'cancel_without_rollback',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Cancel stack operation without rolling back.',
        operations=[{
            'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions',
            'method': 'POST',
        }],
        deprecated_rule=deprecated_cancel_without_rollback
    )
]


def list_rules():
    return actions_policies
