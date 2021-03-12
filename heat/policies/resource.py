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

POLICY_ROOT = 'resource:%s'

DEPRECATED_REASON = """
The resources API now supports system scope and default roles.
"""

deprecated_list_resources = policy.DeprecatedRule(
    name=POLICY_ROOT % 'index',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_mark_unhealthy = policy.DeprecatedRule(
    name=POLICY_ROOT % 'mark_unhealthy',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_show_resource = policy.DeprecatedRule(
    name=POLICY_ROOT % 'show',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY,
)
deprecated_metadata = policy.DeprecatedRule(
    name=POLICY_ROOT % 'metadata',
    check_str=base.RULE_ALLOW_EVERYBODY,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY,
)
deprecated_signal = policy.DeprecatedRule(
    name=POLICY_ROOT % 'signal',
    check_str=base.RULE_ALLOW_EVERYBODY,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY,
)

resource_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List resources.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_list_resources
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'metadata',
        check_str=base.SYSTEM_OR_PROJECT_READER_OR_STACK_USER,
        scope_types=['system', 'project'],
        description='Show resource metadata.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources/{resource_name}/metadata',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_metadata
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'signal',
        check_str=base.SYSTEM_OR_PROJECT_READER_OR_STACK_USER,
        scope_types=['system', 'project'],
        description='Signal resource.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources/{resource_name}/signal',
                'method': 'POST'
            }
        ],
        deprecated_rule=deprecated_signal
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'mark_unhealthy',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Mark resource as unhealthy.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources/{resource_name_or_physical_id}',
                'method': 'PATCH'
            }
        ],
        deprecated_rule=deprecated_mark_unhealthy
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Show resource.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources/{resource_name}',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_show_resource
    )
]


def list_rules():
    return resource_policies
