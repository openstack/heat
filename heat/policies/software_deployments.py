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

POLICY_ROOT = 'software_deployments:%s'

software_deployments_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.RULE_DENY_STACK_USER,
        description='List deployments.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_deployments',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.RULE_DENY_STACK_USER,
        description='Create deployment.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_deployments',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.RULE_DENY_STACK_USER,
        description='Show deployment details.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_deployments/{deployment_id}',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update',
        check_str=base.RULE_DENY_STACK_USER,
        description='Update deployment.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_deployments/{deployment_id}',
                'method': 'PUT'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.RULE_DENY_STACK_USER,
        description='Delete deployment.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_deployments/{deployment_id}',
                'method': 'DELETE'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'metadata',
        check_str=base.RULE_ALLOW_EVERYBODY,
        description='Show server configuration metadata.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_deployments/metadata/'
                '{server_id}',
                'method': 'GET'
            }
        ]
    )
]


def list_rules():
    return software_deployments_policies
