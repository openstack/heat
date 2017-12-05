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

POLICY_ROOT = 'stacks:%s'

stacks_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'abandon',
        check_str=base.RULE_DENY_STACK_USER,
        description='Abandon stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'abandon',
                'method': 'DELETE'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.RULE_DENY_STACK_USER,
        description='Create stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.RULE_DENY_STACK_USER,
        description='Delete stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}',
                'method': 'DELETE'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'detail',
        check_str=base.RULE_DENY_STACK_USER,
        description='List stacks in detail.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'export',
        check_str=base.RULE_DENY_STACK_USER,
        description='Export stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'export',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'generate_template',
        check_str=base.RULE_DENY_STACK_USER,
        description='Generate stack template.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'template',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'global_index',
        check_str=base.RULE_DENY_EVERYBODY,
        description='List stacks globally.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.RULE_DENY_STACK_USER,
        description='List stacks.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_resource_types',
        check_str=base.RULE_DENY_STACK_USER,
        description='List resource types.',
        operations=[
            {
                'path': '/v1/{tenant_id}/resource_types',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_template_versions',
        check_str=base.RULE_DENY_STACK_USER,
        description='List template versions.',
        operations=[
            {
                'path': '/v1/{tenant_id}/template_versions',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_template_functions',
        check_str=base.RULE_DENY_STACK_USER,
        description='List template functions.',
        operations=[
            {
                'path': '/v1/{tenant_id}/template_versions/'
                '{template_version}/functions',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'lookup',
        check_str=base.RULE_ALLOW_EVERYBODY,
        description='Find stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_identity}',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'preview',
        check_str=base.RULE_DENY_STACK_USER,
        description='Preview stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/preview',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'resource_schema',
        check_str=base.RULE_DENY_STACK_USER,
        description='Show resource type schema.',
        operations=[
            {
                'path': '/v1/{tenant_id}/resource_types/{type_name}',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.RULE_DENY_STACK_USER,
        description='Show stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_identity}',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'template',
        check_str=base.RULE_DENY_STACK_USER,
        description='Get stack template.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'template',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'environment',
        check_str=base.RULE_DENY_STACK_USER,
        description='Get stack environment.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'environment',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'files',
        check_str=base.RULE_DENY_STACK_USER,
        description='Get stack files.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'files',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update',
        check_str=base.RULE_DENY_STACK_USER,
        description='Update stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}',
                'method': 'PUT'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update_patch',
        check_str=base.RULE_DENY_STACK_USER,
        description='Update stack (PATCH).',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}',
                'method': 'PATCH'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'preview_update',
        check_str=base.RULE_DENY_STACK_USER,
        description='Preview update stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'preview',
                'method': 'PUT'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'preview_update_patch',
        check_str=base.RULE_DENY_STACK_USER,
        description='Preview update stack (PATCH).',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'preview',
                'method': 'PATCH'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'validate_template',
        check_str=base.RULE_DENY_STACK_USER,
        description='Validate template.',
        operations=[
            {
                'path': '/v1/{tenant_id}/validate',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'snapshot',
        check_str=base.RULE_DENY_STACK_USER,
        description='Snapshot Stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show_snapshot',
        check_str=base.RULE_DENY_STACK_USER,
        description='Show snapshot.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots/{snapshot_id}',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete_snapshot',
        check_str=base.RULE_DENY_STACK_USER,
        description='Delete snapshot.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots/{snapshot_id}',
                'method': 'DELETE'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_snapshots',
        check_str=base.RULE_DENY_STACK_USER,
        description='List snapshots.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'restore_snapshot',
        check_str=base.RULE_DENY_STACK_USER,
        description='Restore snapshot.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots/{snapshot_id}/restore',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_outputs',
        check_str=base.RULE_DENY_STACK_USER,
        description='List outputs.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'outputs',
                'method': 'GET'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show_output',
        check_str=base.RULE_DENY_STACK_USER,
        description='Show outputs.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'outputs/{output_key}',
                'method': 'GET'
            }
        ]
    )
]


def list_rules():
    return stacks_policies
