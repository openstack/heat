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

POLICY_ROOT = 'software_configs:%s'

software_configs_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'global_index',
        check_str=base.RULE_DENY_EVERYBODY,
        description='List configs globally.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.RULE_DENY_STACK_USER,
        description='List configs.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.RULE_DENY_STACK_USER,
        description='Create config.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.RULE_DENY_STACK_USER,
        description='Show config details.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs/{config_id}',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.RULE_DENY_STACK_USER,
        description='Delete config.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs/{config_id}',
                'method': 'DELETE'
            }
        ]
    )
]


def list_rules():
    return software_configs_policies
