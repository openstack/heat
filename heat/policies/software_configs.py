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
The software configuration API now support system scope and default roles.
"""

POLICY_ROOT = 'software_configs:%s'

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
deprecated_create = policy.DeprecatedRule(
    name=POLICY_ROOT % 'create',
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
deprecated_delete = policy.DeprecatedRule(
    name=POLICY_ROOT % 'delete',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)

software_configs_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'global_index',
        check_str=base.SYSTEM_READER,
        scope_types=['system', 'project'],
        description='List configs globally.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_global_index
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List configs.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_index
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'create',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Create config.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs',
                'method': 'POST'
            }
        ],
        deprecated_rule=deprecated_create
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Show config details.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs/{config_id}',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_show
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'delete',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        description='Delete config.',
        operations=[
            {
                'path': '/v1/{tenant_id}/software_configs/{config_id}',
                'method': 'DELETE'
            }
        ],
        deprecated_rule=deprecated_delete
    )
]


def list_rules():
    return software_configs_policies
