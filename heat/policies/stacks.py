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

DEPRECATED_REASON = """
The stack API now supports system scope and default roles.
"""

POLICY_ROOT = 'stacks:%s'

deprecated_abandon = policy.DeprecatedRule(
    name=POLICY_ROOT % 'abandon',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_create = policy.DeprecatedRule(
    name=POLICY_ROOT % 'create',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_delete = policy.DeprecatedRule(
    name=POLICY_ROOT % 'delete',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_detail = policy.DeprecatedRule(
    name=POLICY_ROOT % 'detail',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_export = policy.DeprecatedRule(
    name=POLICY_ROOT % 'export',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_generate_template = policy.DeprecatedRule(
    name=POLICY_ROOT % 'generate_template',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_global_index = policy.DeprecatedRule(
    name=POLICY_ROOT % 'global_index',
    check_str=base.RULE_DENY_EVERYBODY,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_index = policy.DeprecatedRule(
    name=POLICY_ROOT % 'index',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_list_resource_types = policy.DeprecatedRule(
    name=POLICY_ROOT % 'list_resource_types',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_list_template_versions = policy.DeprecatedRule(
    name=POLICY_ROOT % 'list_template_versions',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_list_template_functions = policy.DeprecatedRule(
    name=POLICY_ROOT % 'list_template_functions',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_preview = policy.DeprecatedRule(
    name=POLICY_ROOT % 'preview',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_resource_schema = policy.DeprecatedRule(
    name=POLICY_ROOT % 'resource_schema',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_show = policy.DeprecatedRule(
    name=POLICY_ROOT % 'show',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_template = policy.DeprecatedRule(
    name=POLICY_ROOT % 'template',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_environment = policy.DeprecatedRule(
    name=POLICY_ROOT % 'environment',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_files = policy.DeprecatedRule(
    name=POLICY_ROOT % 'files',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_update = policy.DeprecatedRule(
    name=POLICY_ROOT % 'update',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_update_patch = policy.DeprecatedRule(
    name=POLICY_ROOT % 'update_patch',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_preview_update = policy.DeprecatedRule(
    name=POLICY_ROOT % 'preview_update',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_preview_update_patch = policy.DeprecatedRule(
    name=POLICY_ROOT % 'preview_update_patch',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_validate_template = policy.DeprecatedRule(
    name=POLICY_ROOT % 'validate_template',
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
deprecated_show_snapshot = policy.DeprecatedRule(
    name=POLICY_ROOT % 'show_snapshot',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_delete_snapshot = policy.DeprecatedRule(
    name=POLICY_ROOT % 'delete_snapshot',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_list_snapshots = policy.DeprecatedRule(
    name=POLICY_ROOT % 'list_snapshots',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_restore_snapshot = policy.DeprecatedRule(
    name=POLICY_ROOT % 'restore_snapshot',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_list_outputs = policy.DeprecatedRule(
    name=POLICY_ROOT % 'list_outputs',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_show_output = policy.DeprecatedRule(
    name=POLICY_ROOT % 'show_output',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_lookup = policy.DeprecatedRule(
    name=POLICY_ROOT % 'lookup',
    check_str=base.RULE_ALLOW_EVERYBODY,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)


stacks_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'abandon',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Abandon stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'abandon',
                'method': 'DELETE'
            }
        ],
        deprecated_rule=deprecated_abandon
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Create stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks',
                'method': 'POST'
            }
        ],
        deprecated_rule=deprecated_create
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Delete stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}',
                'method': 'DELETE'
            }
        ],
        deprecated_rule=deprecated_delete
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'detail',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List stacks in detail.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_detail
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'export',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Export stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'export',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_export
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'generate_template',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Generate stack template.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'template',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_generate_template
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'global_index',
        check_str=base.SYSTEM_READER,
        scope_types=['system', 'project'],
        description='List stacks globally.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_global_index
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List stacks.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_index
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_resource_types',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List resource types.',
        operations=[
            {
                'path': '/v1/{tenant_id}/resource_types',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_list_resource_types
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_template_versions',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List template versions.',
        operations=[
            {
                'path': '/v1/{tenant_id}/template_versions',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_list_template_versions
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_template_functions',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List template functions.',
        operations=[
            {
                'path': '/v1/{tenant_id}/template_versions/'
                '{template_version}/functions',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_list_template_functions
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'lookup',
        check_str=base.SYSTEM_OR_PROJECT_READER_OR_STACK_USER,
        scope_types=['system', 'project'],
        description='Find stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_identity}',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_lookup
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'preview',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Preview stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/preview',
                'method': 'POST'
            }
        ],
        deprecated_rule=deprecated_preview
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'resource_schema',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Show resource type schema.',
        operations=[
            {
                'path': '/v1/{tenant_id}/resource_types/{type_name}',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_resource_schema
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Show stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_identity}',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_show
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'template',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Get stack template.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'template',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_template
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'environment',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Get stack environment.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'environment',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_environment
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'files',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Get stack files.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'files',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_files
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Update stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}',
                'method': 'PUT'
            }
        ],
        deprecated_rule=deprecated_update
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update_patch',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Update stack (PATCH).',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}',
                'method': 'PATCH'
            }
        ],
        deprecated_rule=deprecated_update_patch
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'update_no_change',
        check_str='rule:%s' % (POLICY_ROOT % 'update_patch'),
        scope_types=['system', 'project'],
        description='Update stack (PATCH) with no changes.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}',
                'method': 'PATCH'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'preview_update',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Preview update stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'preview',
                'method': 'PUT'
            }
        ],
        deprecated_rule=deprecated_preview_update
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'preview_update_patch',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Preview update stack (PATCH).',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'preview',
                'method': 'PATCH'
            }
        ],
        deprecated_rule=deprecated_preview_update_patch
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'validate_template',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Validate template.',
        operations=[
            {
                'path': '/v1/{tenant_id}/validate',
                'method': 'POST'
            }
        ],
        deprecated_rule=deprecated_validate_template
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'snapshot',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Snapshot Stack.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots',
                'method': 'POST'
            }
        ],
        deprecated_rule=deprecated_snapshot
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show_snapshot',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Show snapshot.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots/{snapshot_id}',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_show_snapshot
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete_snapshot',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Delete snapshot.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots/{snapshot_id}',
                'method': 'DELETE'
            }
        ],
        deprecated_rule=deprecated_delete_snapshot
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_snapshots',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List snapshots.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_list_snapshots
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'restore_snapshot',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Restore snapshot.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'snapshots/{snapshot_id}/restore',
                'method': 'POST'
            }
        ],
        deprecated_rule=deprecated_restore_snapshot
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'list_outputs',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List outputs.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'outputs',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_list_outputs
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show_output',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Show outputs.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'outputs/{output_key}',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_show_output
    )
]


def list_rules():
    return stacks_policies
