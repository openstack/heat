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

POLICY_ROOT = 'resource:%s'

resource_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.RULE_DENY_STACK_USER,
        description='List resources.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'metadata',
        check_str=base.RULE_ALLOW_EVERYBODY,
        description='Show resource metadata.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources/{resource_name}/metadata',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'signal',
        check_str=base.RULE_ALLOW_EVERYBODY,
        description='Signal resource.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources/{resource_name}/signal',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'mark_unhealthy',
        check_str=base.RULE_DENY_STACK_USER,
        description='Mark resource as unhealthy.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources/{resource_name_or_physical_id}',
                'method': 'PATCH'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.RULE_DENY_STACK_USER,
        description='Show resource.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources/{resource_name}',
                'method': 'GET'
            }
        ]
    )
]


def list_rules():
    return resource_policies
